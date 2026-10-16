#!/usr/bin/env python3
"""Backends: anything that can complete a prompt. Stdlib only.

  MockBackend          offline deterministic (tests, no-model dev)
  LlamaServerBackend   local llama-server OpenAI endpoint (fast/primary local)
  TeacherAPIBackend    external OpenAI-compatible API (fallback, metered)

Backend selection lives in router.py; this file only executes.
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
    """Local llama-server (llama.cpp) — our fast/primary student host."""

    name = "llama-local"

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

    def complete(self, messages, max_tokens=256, temperature=0.2):
        msgs = self._prep(messages)
        data = _post_json(self.base + "/v1/chat/completions", {
            "model": self.model, "messages": msgs,
            "max_tokens": max_tokens, "temperature": temperature,
            "stream": False,
        })
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

    def stream(self, messages, max_tokens=256, temperature=0.2):
        """True token streaming: pass llama-server's SSE through as it arrives.
        Yields content deltas; first delta arrives before generation finishes
        (TTFT < full-generation time)."""
        msgs = self._prep(messages)
        payload = json.dumps({
            "model": self.model, "messages": msgs,
            "max_tokens": max_tokens, "temperature": temperature,
            "stream": True,
        }).encode()
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


class TeacherAPIBackend(Backend):
    """External fallback (OpenRouter / Gemini-OAI / any OpenAI endpoint)."""

    name = "teacher-api"

    def __init__(self):
        self.base = os.environ["TEACHER_BASE_URL"].rstrip("/")
        self.key = os.environ["TEACHER_API_KEY"]
        self.model = os.environ.get("TEACHER_MODEL", "")

    def healthy(self):
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
