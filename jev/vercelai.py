#!/usr/bin/env python3
"""Vercel AI Gateway client (OpenAI-compatible).

https://ai-gateway.vercel.sh/v1 — free tier carries a subset of models at
zero markup; paid credits unlock the full catalog. When the OpenRouter free
quota is exhausted, this gives Urai a second cloud teacher without credits.

Configured via env:
    VERCEL_AI_GATEWAY_API_KEY   (https://vercel.com/d/.../ai-gateway/api-keys)
    VERCEL_AI_GATEWAY_BASE_URL  (default https://ai-gateway.vercel.sh/v1)
    VERCEL_AI_GATEWAY_MODEL     (default openai/gpt-4.1-mini; pick a free-tier
                                 model from /ai-gateway/models?freeTier=true)

Stdlib only. Mirrors the jev.muse interface so backends can swap providers.
"""
from __future__ import annotations
import json
import os
import urllib.error
import urllib.request

BASE_URL = os.environ.get("VERCEL_AI_GATEWAY_BASE_URL",
                          "https://ai-gateway.vercel.sh/v1").rstrip("/")
MODEL_ID = os.environ.get("VERCEL_AI_GATEWAY_MODEL", "humansand/ampersand-v0.1")

def api_key() -> str:
    return os.environ.get("VERCEL_AI_GATEWAY_API_KEY", "").strip()

def available() -> bool:
    return bool(api_key())

def _headers() -> dict:
    return {
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
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
        raise RuntimeError(f"Vercel AI Gateway HTTP {e.code}: {detail}")

def complete(messages, max_tokens=2048, temperature=0.2, model=None):
    if not available():
        raise RuntimeError("VERCEL_AI_GATEWAY_API_KEY not set")
    payload = {
        "model": model or MODEL_ID,
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
        "model": data.get("model") or (model or MODEL_ID),
        "backend": "vercel-ai-gateway",
    }

def stream(messages, max_tokens=2048, temperature=0.2, model=None):
    if not available():
        raise RuntimeError("VERCEL_AI_GATEWAY_API_KEY not set")
    model_id = model or MODEL_ID
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
        raise RuntimeError(f"Vercel AI Gateway stream HTTP {e.code}: {detail}")
