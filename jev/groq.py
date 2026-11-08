#!/usr/bin/env python3
"""Groq free inference (OpenAI-compatible, no credit card required).

https://console.groq.com — create a free account and paste an API key into
GROQ_API_KEY. Rate limits are per-model but free and card-free.

Models (Groq-hosted, OpenAI-compatible):
    llama-3.3-70b-versatile   — strong, fast, 128K ctx
    qwen-qwq-32b              — reasoning, 128K ctx
    deepseek-r1-distill-llama-70b  — Distill-R1 70B reasoning
    gemma3-27b               — multimodal
    meta-llama/llama-4-scout-17b-16e-instruct
    meta/muse-spark-open     — NOT on Groq; Muse stays OpenRouter-only

Env:
    GROQ_API_KEY          (https://console.groq.com/keys)
    GROQ_BASE_URL         (default https://api.groq.com/openai/v1)
    GROQ_MODEL            (default llama-3.3-70b-versatile)

Stdlib only. Same interface as jev.muse / jev.vercelai.
"""
from __future__ import annotations
import json
import os
import urllib.error
import urllib.request

BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
MODEL_ID = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

def api_key() -> str:
    return os.environ.get("GROQ_API_KEY", "").strip()

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
        raise RuntimeError(f"Groq HTTP {e.code}: {detail}")

def complete(messages, max_tokens=2048, temperature=0.2, model=None):
    if not available():
        raise RuntimeError("GROQ_API_KEY not set")
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
        "backend": "groq",
    }

def stream(messages, max_tokens=2048, temperature=0.2, model=None):
    if not available():
        raise RuntimeError("GROQ_API_KEY not set")
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
        raise RuntimeError(f"Groq stream HTTP {e.code}: {detail}")
