#!/usr/bin/env python3
"""Portkey AI Gateway client (OpenAI-compatible) + local LiteLLM.

Portkey (https://portkey.ai) is an AI gateway with a free tier and no credit
card required:  https://api.portkey.ai/v1/chat/completions
It fronts the whole catalog (OpenAI, Anthropic, Cohere, Together, Groq,
Mistral, Meta, ...) behind one OpenAI-compatible API. Auth: `PORTKEY_API_KEY`
(https://app.portkey.ai/settings/api-keys). Free tier daily limits apply.

LiteLLM (pypi `litellm`, Apache-2.0 OSS) is a local proxy/router. If it is
installed on the host (`pip install litellm`), Urai routes through
`litellm.completion` for the local student path so one interface master the
whole catalog.

Env:
    PORTKEY_API_KEY        (https://app.portkey.ai/settings/api-keys)
    PORTKEY_BASE_URL       (default https://api.portkey.ai/v1)
    PORTKEY_MODEL          (default openai/gpt-4.1-mini)
    LITELLM_MODEL          (default huggingface/meta-llama/Meta-Llama-3-70B-Instruct)
    LITELLM_API_KEY        (optional — provider key passthrough like OPENAI_API_KEY)

Stdlib for Portkey; LiteLLM path is lazy-imported.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

BASE_URL = os.environ.get("PORTKEY_BASE_URL", "https://api.portkey.ai/v1").rstrip("/")
PORTKEY_MODEL = os.environ.get("PORTKEY_MODEL", "openai/gpt-4.1-mini")
LITELLM_MODEL = os.environ.get("LITELLM_MODEL",
                               "huggingface/meta-llama/Meta-Llama-3-70B-Instruct")

def api_key() -> str:
    return os.environ.get("PORTKEY_API_KEY", "").strip()

def available() -> bool:
    return bool(api_key())

def _headers() -> dict:
    return {
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
        "x-portkey-api-key": api_key(),
    }

def _post(payload: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(
        BASE_URL + "/chat/completions",
        json.dumps(payload).encode(),
        _headers(),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode()[:600]
        except Exception:
            detail = ""
        raise RuntimeError(f"Portkey HTTP {e.code}: {detail}")

def complete(messages, max_tokens=2048, temperature=0.2, model=None):
    if not available():
        raise RuntimeError("PORTKEY_API_KEY not set")
    payload = {
        "model": model or PORTKEY_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    data = _post(payload)
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message", {})
    return {
        "content": msg.get("content") or "",
        "reasoning_content": msg.get("reasoning_content") or msg.get("reasoning") or "",
        "usage": data.get("usage", {}),
        "model": data.get("model") or (model or PORTKEY_MODEL),
        "backend": "portkey",
    }

def stream(messages, max_tokens=2048, temperature=0.2, model=None):
    if not available():
        raise RuntimeError("PORTKEY_API_KEY not set")
    model_id = model or PORTKEY_MODEL
    payload = {
        "model": model_id,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    req = urllib.request.Request(
        BASE_URL + "/chat/completions",
        json.dumps(payload).encode(),
        _headers(),
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").rstrip("\n")
                if not line.startswith("data: "):
                    continue
                chunk = line[6:]
                if chunk == "[DONE]":
                    break
                try:
                    ev = json.loads(chunk)
                except Exception:
                    continue
                choice = (ev.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    out_delta = {"content": delta["content"]}
                elif delta.get("reasoning"):
                    out_delta = {"reasoning_content": delta["reasoning"]}
                else:
                    continue
                yield json.dumps({
                    "id": ev.get("id", "chatcmpl-urai"),
                    "object": "chat.completion.chunk",
                    "model": ev.get("model", model_id),
                    "choices": [{"index": 0, "delta": out_delta,
                                 "finish_reason": choice.get("finish_reason")}],
                })
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode()[:400]
        except Exception:
            detail = ""
        raise RuntimeError(f"Portkey stream HTTP {e.code}: {detail}")

# ── LiteLLM (local proxy option) ────────────────────────────────────────────

def litellm_available() -> bool:
    try:
        import litellm  # noqa: F401
        return True
    except Exception:
        return False

def litellm_complete(messages, max_tokens=2048, temperature=0.2, model=None):
    """Route through a locally-installed LiteLLM proxy.

    Only used when `litellm` is pip-installed on the host and LITELLM_MODEL
    is set. Provider API keys are passed through from the environment
    (OPENAI_API_KEY, ANTHROPIC_API_KEY, GROQ_API_KEY, ...).
    """
    import litellm  # lazy; importing here keeps Urai dependency-light

    resp = litellm.completion(
        model=model or LITELLM_MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        stream=False,
    )
    msg = resp["choices"][0]["message"]
    usage = getattr(resp, "usage", None)
    try:
        usage = usage.model_dump() if usage is not None and hasattr(usage, "model_dump") else (dict(usage) if usage else {})
    except Exception:
        usage = {}
    return {
        "content": msg.get("content") or "",
        "reasoning_content": msg.get("reasoning_content") or "",
        "usage": usage,
        "model": getattr(resp, "model", model or LITELLM_MODEL),
        "backend": "litellm",
    }
