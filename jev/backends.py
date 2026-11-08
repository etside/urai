#!/usr/bin/env python3
"""Backends: Urai first-party only (stdlib only).

  UraiBackend          Urai weights runtime (primary, backend="urai")
  LlamaServerBackend   local llama.cpp runtime serving Urai weights
                       (alias, backend="urai")

External teacher APIs are NOT available at request time (offline distill only,
see scripts/distill/). MockBackend exists only for unit tests and is never
selected at request time.
"""

import json
import os
import urllib.request


class Backend:
    name = "base"

    def complete(self, messages, max_tokens=256, temperature=0.2) -> dict:
        raise NotImplementedError

    def healthy(self) -> bool:
        return True

    def stream(self, messages, max_tokens=256, temperature=0.2):
        """Yield answer deltas. Default: chunk a single completion (fallback).
        Subclasses with a native streaming endpoint override this."""
        text = self.complete(messages, max_tokens=max_tokens,
                             temperature=temperature).get("content", "")
        for tok in _chunk_tokens(text):
            yield tok


def _chunk_tokens(text: str) -> list:
    import re as _re
    return _re.findall(r"\s*\S+|\s+", text or "") or ([text] if text else [])


class MockBackend(Backend):
    """Unit-test only. Never selected at request time (see router.py)."""
    name = "mock"

    def complete(self, messages, max_tokens=256, temperature=0.2):
        last = messages[-1]["content"] if messages else ""
        return {"content": f"[mock] received {len(last)} chars; "
                           "configure a real backend for output.",
                "backend": self.name, "mock": True}

    def stream(self, messages, max_tokens=256, temperature=0.2):
        for tok in _chunk_tokens(self.complete(messages, max_tokens,
                                               temperature)["content"]):
            yield tok


def _post_json(url, payload, key=None, timeout=900):
    import urllib.error as _ue
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, json.dumps(payload).encode(), headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except _ue.HTTPError as e:
        try:
            detail = e.read().decode()[:300]
        except Exception:
            detail = ""
        raise RuntimeError(f"HTTP {e.code}: {detail}")


class LlamaServerBackend(Backend):
    """Local llama.cpp runtime serving Urai weights (first-party)."""

    name = "urai"

    def __init__(self, base=None, model=None):
        self.base = (base or os.environ.get("JEV_LLAMA_URL",
                                            "http://127.0.0.1:8080")).rstrip("/")
        if model is None:
            model = os.environ.get("JEV_LLAMA_MODEL")
        if model is None:
            # fall back to the registry's active model id so model-specific
            # behavior (e.g. Qwen3 /no_think) follows `urai model use`
            try:
                from . import models_registry as _reg
                model = _reg.load().get("active")
            except Exception:
                model = None
        self.model = model or "local-student"

    def healthy(self):
        try:
            urllib.request.urlopen(self.base + "/health", timeout=10).read()
            return True
        except Exception:
            return False

    def _prep(self, messages):
        msgs = [dict(m) for m in messages]
        # Qwen3 thinks by default (reasoning_content, empty answer, wasted
        # tokens). Our pipeline wants answers — disable thinking unless
        # explicitly asked (URAI_THINKING=1). Verified on llama-server b11559.
        if "qwen3" in self.model.lower() and \
                os.environ.get("URAI_THINKING") != "1":
            for m in reversed(msgs):
                if m.get("role") == "user" and isinstance(m.get("content"), str):
                    m["content"] = m["content"].rstrip() + "\n/no_think"
                    break
        return msgs

    def complete(self, messages, max_tokens=256, temperature=0.2,
                tools=None, tool_choice=None):
        msgs = self._prep(messages)
        payload = {
            "model": self.model, "messages": msgs,
            "max_tokens": max_tokens, "temperature": temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        data = _post_json(self.base + "/v1/chat/completions", payload)
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

    def stream(self, messages, max_tokens=256, temperature=0.2,
              tools=None, tool_choice=None):
        """True token streaming: pass llama-server's SSE through as it arrives.
        Yields content deltas; first delta arrives before generation finishes
        (TTFT < full-generation time)."""
        msgs = self._prep(messages)
        body = {
            "model": self.model, "messages": msgs,
            "max_tokens": max_tokens, "temperature": temperature,
            "stream": True,
        }
        if tools:
            body["tools"] = tools
        if tool_choice is not None:
            body["tool_choice"] = tool_choice
        payload = json.dumps(body).encode()
        req = urllib.request.Request(
            self.base + "/v1/chat/completions", payload,
            {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=900) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except Exception:
                    continue
                try:
                    delta = obj["choices"][0].get("delta") or {}
                except Exception:
                    continue
                piece = delta.get("content")
                if not piece and delta.get("reasoning_content"):
                    piece = delta["reasoning_content"]
                if piece:
                    yield piece


class EmbeddingBackend(Backend):
    """Local embedding server (llama-server --embedding, :8081)."""

    name = "embed-local"

    def __init__(self, base=None, model=None):
        self.base = (base or os.environ.get("URAI_EMBED_URL",
                                            "http://127.0.0.1:8081")).rstrip("/")
        self.model = model or os.environ.get("URAI_EMBED_MODEL", "local-embed")

    def healthy(self):
        try:
            urllib.request.urlopen(self.base + "/health", timeout=5).read()
            return True
        except Exception:
            return False

    def embed(self, inputs):
        if isinstance(inputs, str):
            inputs = [inputs]
        data = _post_json(self.base + "/v1/embeddings",
                          {"model": self.model, "input": inputs})
        return [d["embedding"] for d in data["data"]]

    def complete(self, messages, max_tokens=256, temperature=0.2):
        raise NotImplementedError("embedding backend has no chat; use .embed()")


class UraiBackend(Backend):
    """First-party Urai runtime (n-gram student / llama.cpp wrapper).

    backend is always "urai". Raises 503-style RuntimeError when weights
    are unavailable — never falls back to mock or a vendor model.
    """

    name = "urai"

    def __init__(self, runtime=None):
        self._rt = runtime

    def _get_rt(self):
        if self._rt is not None:
            return self._rt
        from .urai_runtime import load_runtime as _lr
        self._rt = _lr()
        return self._rt

    def healthy(self) -> bool:
        try:
            return bool(self._get_rt().healthy())
        except Exception:
            return False

    def complete(self, messages, max_tokens=256, temperature=0.2,
                 tools=None, tool_choice=None) -> dict:
        rt = self._get_rt()
        if not rt.healthy():
            # Prefer local llama.cpp if runtime weights absent but server up
            ll = LlamaServerBackend()
            if ll.healthy():
                out = ll.complete(messages, max_tokens=max_tokens,
                                  temperature=temperature,
                                  tools=tools, tool_choice=tool_choice)
                out["backend"] = "urai"
                return out
            raise RuntimeError("Urai runtime not loaded (503)")
        # If llama-server healthy, prefer it (faster GGUF) but keep backend urai
        ll = LlamaServerBackend()
        if ll.healthy():
            out = ll.complete(messages, max_tokens=max_tokens,
                              temperature=temperature,
                              tools=tools, tool_choice=tool_choice)
            out["backend"] = "urai"
            return out
        return rt.complete(messages, max_tokens=max_tokens, temperature=temperature,
                           tools=tools, tool_choice=tool_choice)

    def stream(self, messages, max_tokens=256, temperature=0.2,
               tools=None, tool_choice=None):
        rt = self._get_rt()
        if rt.healthy():
            yield from rt.stream(messages, max_tokens=max_tokens,
                                 temperature=temperature,
                                 tools=tools, tool_choice=tool_choice)
            return
        ll = LlamaServerBackend()
        if ll.healthy():
            yield from ll.stream(messages, max_tokens=max_tokens,
                                 temperature=temperature,
                                 tools=tools, tool_choice=tool_choice)
            return
        raise RuntimeError("Urai runtime not loaded (503)")
