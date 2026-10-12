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


class MockBackend(Backend):
    name = "mock"

    def complete(self, messages, max_tokens=256, temperature=0.2):
        last = messages[-1]["content"] if messages else ""
        return {"content": f"[mock] received {len(last)} chars; "
                           "configure a real backend for output.",
                "backend": self.name, "mock": True}


def _post_json(url, payload, key=None, timeout=300):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, json.dumps(payload).encode(), headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


class LlamaServerBackend(Backend):
    """Local llama-server (llama.cpp) — our fast/primary student host."""

    name = "llama-local"

    def __init__(self, base=None, model=None):
        self.base = (base or os.environ.get("JEV_LLAMA_URL",
                                            "http://127.0.0.1:8080")).rstrip("/")
        self.model = model or os.environ.get("JEV_LLAMA_MODEL", "local-student")

    def healthy(self):
        try:
            urllib.request.urlopen(self.base + "/health", timeout=5).read()
            return True
        except Exception:
            return False

    def complete(self, messages, max_tokens=256, temperature=0.2):
        data = _post_json(self.base + "/v1/chat/completions", {
            "model": self.model, "messages": messages,
            "max_tokens": max_tokens, "temperature": temperature,
            "stream": False,
        })
        return {"content": data["choices"][0]["message"]["content"],
                "backend": self.name, "model": self.model}


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
        return {"content": data["choices"][0]["message"]["content"],
                "backend": self.name, "model": self.model}
