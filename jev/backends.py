#!/usr/bin/env python3
"""Backends: anything that can complete a prompt. Stdlib only.

  MockBackend          offline deterministic (tests, no-model dev)
  LlamaServerBackend   local llama-server OpenAI endpoint (fast/primary local)
  TeacherAPIBackend    external OpenAI-compatible API (legacy alias kept)
  CloudAPIBackend      registry-driven cloud (Kimi K2, DeepSeek, Claude, GPT-4o-mini, …)
  EmbeddingBackend     local embedding server (llama-server --embedding, :8081)

Backend selection lives in router.py; this file only executes.

Streaming:
  All backends that support it implement stream_complete() which yields
  raw SSE chunk strings (the part after "data: ").  The server calls
  stream_complete() directly when body.stream=true.

Probe cache:
  Each remote backend probes its health endpoint once per process and
  caches the result.  Failed backends are retried after PROBE_TTL_S.
  GPU availability is probed via torch once and cached.
"""

from __future__ import annotations
import json
import os
import threading
import time
import urllib.error
import urllib.request

# ── Probe cache ────────────────────────────────────────────────────────────────

PROBE_TTL_S = int(os.environ.get("URAI_PROBE_TTL", "120"))  # re-probe interval

_probe_cache: dict[str, tuple[bool, float]] = {}  # key -> (ok, expires_at)
_probe_lock = threading.Lock()


def _probe_cached(key: str, fn, ttl: int = PROBE_TTL_S) -> bool:
    """Run fn() at most once per ttl seconds; cache ok/fail."""
    now = time.monotonic()
    with _probe_lock:
        entry = _probe_cache.get(key)
        if entry and now < entry[1]:
            return entry[0]
    try:
        fn()
        ok = True
    except Exception:
        ok = False
    with _probe_lock:
        _probe_cache[key] = (ok, now + ttl)
    return ok


def _gpu_available() -> bool:
    """True if CUDA is reachable (probed once per process lifetime)."""
    def check():
        import torch  # type: ignore
        if not torch.cuda.is_available():
            raise RuntimeError("no cuda")
    return _probe_cached("cuda", check, ttl=3600)


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _post_json(url: str, payload: dict, key: str | None = None,
               timeout: int = 900) -> dict:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, json.dumps(payload).encode(), headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode()[:400]
        except Exception:
            detail = ""
        raise RuntimeError(f"HTTP {e.code}: {detail}")


def _stream_post(url: str, payload: dict, key: str | None = None,
                 timeout: int = 120):
    """POST with stream=True; yields raw SSE lines from the response."""
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    payload = dict(payload)
    payload["stream"] = True
    req = urllib.request.Request(url, json.dumps(payload).encode(), headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").rstrip("\n")
                if line.startswith("data: "):
                    yield line[6:]
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode()[:400]
        except Exception:
            detail = ""
        raise RuntimeError(f"HTTP {e.code}: {detail}")


# ── Base ───────────────────────────────────────────────────────────────────────

class Backend:
    name = "base"

    def complete(self, messages: list, max_tokens: int = 256,
                 temperature: float = 0.2) -> dict:
        raise NotImplementedError

    def healthy(self) -> bool:
        return True

    def stream_complete(self, messages: list, max_tokens: int = 256,
                        temperature: float = 0.2):
        """Yield SSE data payloads (str).  Default: buffer complete() then chunk."""
        res = self.complete(messages, max_tokens, temperature)
        content = res.get("content", "")
        model = res.get("model", self.name)
        for i in range(0, max(len(content), 1), 64):
            piece = content[i:i + 64]
            yield json.dumps({
                "id": "chatcmpl-urai", "object": "chat.completion.chunk",
                "model": model,
                "choices": [{"index": 0,
                              "delta": {"content": piece},
                              "finish_reason": None}]})
        yield json.dumps({
            "id": "chatcmpl-urai", "object": "chat.completion.chunk",
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})


# ── Mock ───────────────────────────────────────────────────────────────────────

class MockBackend(Backend):
    name = "mock"

    def complete(self, messages, max_tokens=256, temperature=0.2):
        last = messages[-1]["content"] if messages else ""
        return {"content": f"[mock] received {len(last)} chars; "
                           "configure a real backend for output.",
                "backend": self.name, "mock": True}


# ── Local llama-server ─────────────────────────────────────────────────────────

class LlamaServerBackend(Backend):
    """Local llama-server (llama.cpp) — fast/primary student host.

    GPU path: llama-server itself handles GPU via n_gpu_layers.
    We just check CUDA availability to pick the best local model tier.
    """

    name = "llama-local"

    def __init__(self, base: str | None = None, model: str | None = None):
        self.base = (base or os.environ.get("JEV_LLAMA_URL",
                                            "http://127.0.0.1:8080")).rstrip("/")
        if model is None:
            model = os.environ.get("JEV_LLAMA_MODEL")
        if model is None:
            try:
                from . import models_registry as _reg
                model = _reg.load().get("active")
            except Exception:
                model = None
        self.model = model or "local-student"

    def healthy(self) -> bool:
        return _probe_cached(
            f"llama:{self.base}",
            lambda: urllib.request.urlopen(self.base + "/health", timeout=5).read())

    def complete(self, messages, max_tokens=256, temperature=0.2):
        msgs = [dict(m) for m in messages]
        if "qwen3" in self.model.lower() and \
                os.environ.get("URAI_THINKING") != "1":
            for m in reversed(msgs):
                if m.get("role") == "user" and isinstance(m.get("content"), str):
                    m["content"] = m["content"].rstrip() + "\n/no_think"
                    break
        data = _post_json(self.base + "/v1/chat/completions", {
            "model": self.model, "messages": msgs,
            "max_tokens": max_tokens, "temperature": temperature,
            "stream": False,
        })
        _msg = data["choices"][0]["message"]
        _content = _msg.get("content") or ""
        if not _content.strip() and _msg.get("reasoning_content"):
            _content = _msg["reasoning_content"]
        out = {"content": _content, "backend": self.name, "model": self.model}
        if isinstance(data.get("usage"), dict):
            out["usage"] = data["usage"]
        if isinstance(data.get("timings"), dict):
            out["timings"] = data["timings"]
        return out

    def stream_complete(self, messages, max_tokens=256, temperature=0.2):
        """True streaming via llama-server SSE."""
        msgs = [dict(m) for m in messages]
        if "qwen3" in self.model.lower() and \
                os.environ.get("URAI_THINKING") != "1":
            for m in reversed(msgs):
                if m.get("role") == "user" and isinstance(m.get("content"), str):
                    m["content"] = m["content"].rstrip() + "\n/no_think"
                    break
        yield from _stream_post(self.base + "/v1/chat/completions", {
            "model": self.model, "messages": msgs,
            "max_tokens": max_tokens, "temperature": temperature,
        })


# ── Embedding backend ──────────────────────────────────────────────────────────

class EmbeddingBackend(Backend):
    """Local embedding server (llama-server --embedding, :8081)."""

    name = "embed-local"

    def __init__(self, base: str | None = None, model: str | None = None):
        self.base = (base or os.environ.get("URAI_EMBED_URL",
                                            "http://127.0.0.1:8081")).rstrip("/")
        self.model = model or os.environ.get("URAI_EMBED_MODEL", "local-embed")

    def healthy(self) -> bool:
        return _probe_cached(
            f"embed:{self.base}",
            lambda: urllib.request.urlopen(self.base + "/health", timeout=5).read())

    def embed(self, inputs):
        if isinstance(inputs, str):
            inputs = [inputs]
        data = _post_json(self.base + "/v1/embeddings",
                          {"model": self.model, "input": inputs})
        return [d["embedding"] for d in data["data"]]

    def complete(self, messages, max_tokens=256, temperature=0.2):
        raise NotImplementedError("embedding backend has no chat; use .embed()")


# ── Cloud API backend ──────────────────────────────────────────────────────────

class CloudAPIBackend(Backend):
    """Registry-driven cloud backend.

    Reads model/registry.json entries with api_only=true.  Selects the
    best available backend in priority order:
        kimi-k2 (MOONSHOT_API_KEY) → deepseek-r2 (DEEPSEEK_API_KEY)
        → claude-haiku (ANTHROPIC_API_KEY) → gpt-4o-mini (OPENAI_API_KEY)

    Health is probed once and cached (PROBE_TTL_S seconds).
    Skips VPS/remote if key absent or probe fails — never hard-errors.
    Supports true streaming via _stream_post.
    """

    # Provider → (env_var, endpoint_key, chat_path, auth_header_style)
    # auth_header_style: "bearer" | "x-api-key" (Anthropic)
    _PROVIDERS = {
        "moonshot":   ("MOONSHOT_API_KEY",   "endpoint", "/chat/completions", "bearer"),
        "deepseek":   ("DEEPSEEK_API_KEY",   "endpoint", "/chat/completions", "bearer"),
        "openai":     ("OPENAI_API_KEY",     "endpoint", "/chat/completions", "bearer"),
        "anthropic":  ("ANTHROPIC_API_KEY",  "endpoint", "/messages",         "x-api-key"),
    }

    # Preferred order (best reasoning → cheapest)
    _PRIORITY = ["kimi-k2", "deepseek-r2", "claude-haiku", "gpt-4o-mini", "muse-wonder"]

    def __init__(self, model_id: str | None = None):
        """model_id: registry key like 'kimi-k2'.  None = auto-select best available."""
        self._reg_entry: dict | None = None
        self._model_id: str | None = None
        self._key: str | None = None
        self._base: str | None = None
        self._chat_path: str = "/chat/completions"
        self._auth_style: str = "bearer"

        if model_id:
            entry = self._load_entry(model_id)
            if entry:
                self._configure(model_id, entry)
        else:
            self._auto_select()

    def _load_entry(self, mid: str) -> dict | None:
        try:
            from pathlib import Path as _P
            reg_path = _P(__file__).resolve().parents[1] / "model" / "registry.json"
            reg = json.loads(reg_path.read_text())
            return reg["models"].get(mid)
        except Exception:
            return None

    def _configure(self, mid: str, entry: dict):
        provider = entry.get("provider", "")
        pconf = self._PROVIDERS.get(provider)
        if not pconf:
            return
        env_var, endpoint_key, chat_path, auth_style = pconf
        key = os.environ.get(env_var, "")
        if not key:
            return
        self._model_id = mid
        self._reg_entry = entry
        self._key = key
        self._base = entry.get(endpoint_key, "").rstrip("/")
        self._chat_path = chat_path
        self._auth_style = auth_style
        self.name = f"cloud:{provider}/{mid}"

    def _auto_select(self):
        for mid in self._PRIORITY:
            entry = self._load_entry(mid)
            if not entry:
                continue
            self._configure(mid, entry)
            if self._key:
                # quick check: at least key is set; probe() does network check
                return
        # nothing configured
        self._model_id = None

    @property
    def available(self) -> bool:
        return bool(self._model_id and self._key and self._base)

    def healthy(self) -> bool:
        if not self.available:
            return False
        # Anthropic has no /health; just verify key is non-empty
        if self._auth_style == "x-api-key":
            return bool(self._key)
        return _probe_cached(
            f"cloud:{self._model_id}",
            lambda: urllib.request.urlopen(
                self._base + "/models", timeout=8).read())

    def _build_payload(self, messages, max_tokens, temperature, stream=False):
        entry = self._reg_entry or {}
        model_api_id = entry.get("model_id", self._model_id or "")
        if self._auth_style == "x-api-key":
            # Anthropic messages API format
            system_msgs = [m["content"] for m in messages if m.get("role") == "system"]
            user_msgs = [m for m in messages if m.get("role") != "system"]
            payload: dict = {
                "model": model_api_id,
                "max_tokens": max_tokens,
                "messages": user_msgs,
                "stream": stream,
            }
            if system_msgs:
                payload["system"] = "\n".join(system_msgs)
            return payload
        return {
            "model": model_api_id,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self._auth_style == "x-api-key":
            h["x-api-key"] = self._key or ""
            h["anthropic-version"] = "2023-06-01"
        else:
            h["Authorization"] = f"Bearer {self._key}"
        return h

    def complete(self, messages, max_tokens=256, temperature=0.2) -> dict:
        if not self.available:
            raise RuntimeError("No cloud backend configured "
                               "(set MOONSHOT_API_KEY / DEEPSEEK_API_KEY / "
                               "ANTHROPIC_API_KEY / OPENAI_API_KEY)")
        # Budget guard — raises BudgetExceeded if daily limit hit
        try:
            from .cloud_budget import check_budget as _cb
            _provider = (self._reg_entry or {}).get('provider', '')
            _cb(_provider)
        except ImportError:
            pass
        url = self._base + self._chat_path
        payload = self._build_payload(messages, max_tokens, temperature, stream=False)
        req = urllib.request.Request(url, json.dumps(payload).encode(), self._headers())
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode()[:400]
            except Exception:
                detail = ""
            raise RuntimeError(f"Cloud {self.name} HTTP {e.code}: {detail}")

        provider = (self._reg_entry or {}).get('provider', '')
        if self._auth_style == "x-api-key":
            # Anthropic response shape
            content_blocks = data.get("content", [])
            text = " ".join(b.get("text", "") for b in content_blocks
                            if b.get("type") == "text")
            usage = data.get("usage", {})
            pt = usage.get("input_tokens", 0)
            ct = usage.get("output_tokens", 0)
            try:
                from .cloud_budget import record_usage as _ru
                _ru(provider, pt, ct, self._model_id or '')
            except Exception:
                pass
            return {"content": text, "backend": self.name,
                    "model": self._model_id,
                    "usage": {"prompt_tokens": pt,
                              "completion_tokens": ct,
                              "total_tokens": pt + ct}}
        _msg = data["choices"][0]["message"]
        content = _msg.get("content") or ""
        if not content.strip() and _msg.get("reasoning_content"):
            content = _msg["reasoning_content"]
        out = {"content": content, "backend": self.name, "model": self._model_id}
        if isinstance(data.get("usage"), dict):
            out["usage"] = data["usage"]
            try:
                from .cloud_budget import record_usage as _ru
                _ru(provider,
                    data['usage'].get('prompt_tokens', 0),
                    data['usage'].get('completion_tokens', 0),
                    self._model_id or '')
            except Exception:
                pass
        return out

    def stream_complete(self, messages, max_tokens=256, temperature=0.2):
        """True SSE streaming from cloud provider."""
        if not self.available:
            raise RuntimeError("No cloud backend configured")
        url = self._base + self._chat_path
        payload = self._build_payload(messages, max_tokens, temperature, stream=True)
        headers = self._headers()
        req = urllib.request.Request(url, json.dumps(payload).encode(), headers)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", errors="replace").rstrip("\n")
                    if line.startswith("data: "):
                        chunk = line[6:]
                        if chunk == "[DONE]":
                            break
                        if self._auth_style == "x-api-key":
                            # Re-encode Anthropic delta → OpenAI chunk shape
                            try:
                                ev = json.loads(chunk)
                                delta_text = ""
                                if ev.get("type") == "content_block_delta":
                                    delta_text = ev.get("delta", {}).get("text", "")
                                elif ev.get("type") == "message_delta":
                                    pass  # finish event, skip
                                else:
                                    continue
                                yield json.dumps({
                                    "id": "chatcmpl-urai",
                                    "object": "chat.completion.chunk",
                                    "model": self._model_id,
                                    "choices": [{"index": 0,
                                                 "delta": {"content": delta_text},
                                                 "finish_reason": None}]})
                            except Exception:
                                continue
                        else:
                            yield chunk  # already OpenAI SSE format
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode()[:400]
            except Exception:
                detail = ""
            raise RuntimeError(f"Cloud stream {self.name} HTTP {e.code}: {detail}")


# ── TeacherAPIBackend — legacy alias ───────────────────────────────────────────

class TeacherAPIBackend(Backend):
    """External fallback (OpenRouter / Gemini-OAI / any OpenAI endpoint).
    Kept for backward compatibility.  New code should use CloudAPIBackend.
    """

    name = "teacher-api"

    def __init__(self):
        self.base = os.environ["TEACHER_BASE_URL"].rstrip("/")
        self.key = os.environ["TEACHER_API_KEY"]
        self.model = os.environ.get("TEACHER_MODEL", "")

    def healthy(self) -> bool:
        return bool(self.base and self.key and self.model)

    def complete(self, messages, max_tokens=512, temperature=0.2):
        data = _post_json(self.base + "/chat/completions", {
            "model": self.model, "messages": messages,
            "max_tokens": max_tokens, "temperature": temperature,
        }, key=self.key)
        _msg = data["choices"][0]["message"]
        _content = _msg.get("content") or ""
        if not _content.strip() and _msg.get("reasoning_content"):
            _content = _msg["reasoning_content"]
        out = {"content": _content,
               "backend": self.name, "model": self.model}
        if isinstance(data.get("usage"), dict):
            out["usage"] = data["usage"]
        if isinstance(data.get("timings"), dict):
            out["timings"] = data["timings"]
        return out

    def stream_complete(self, messages, max_tokens=512, temperature=0.2):
        yield from _stream_post(self.base + "/chat/completions", {
            "model": self.model, "messages": messages,
            "max_tokens": max_tokens, "temperature": temperature,
        }, key=self.key)
