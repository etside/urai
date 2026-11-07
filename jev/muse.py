#!/usr/bin/env python3
"""Muse Spark Open — hosted client (OpenRouter gateway).

Muse Spark Open is Meta's 816B MoE open-weight model (42B active/token,
1M context, text/image/video/audio in). It cannot run on Urai's small
local hardware, so Urai accesses it through OpenRouter (pay-per-token,
$1.25/M in / $4.25/M out across Fireworks/Makora/Modal/Together/Nebius/Baseten).

Ref: https://dev.meta.ai/resources/blog/build-with-muse-spark-open
Model: https://openrouter.ai/meta/muse-spark-open  (model id: meta/muse-spark-open)

Stdlib only.
"""
from __future__ import annotations
import json
import os
import urllib.error
import urllib.request

BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
MODEL_ID = os.environ.get("OPENROUTER_MODEL", "meta/muse-spark-open")

def api_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "").strip()

def available() -> bool:
    return bool(api_key())

def _headers() -> dict:
    return {
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("URAI_PUBLIC_URL", "https://etside.github.io/urai/"),
        "X-Title": "Urai",
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
        raise RuntimeError(f"OpenRouter HTTP {e.code}: {detail}")

SYSTEM_PROMPT = (
    "You are Urai, an AI assistant developed by Tynio LTD. "
    "When asked who you are, say you are Urai.\n"
    "## Objective\n"
    "Produce a precise, user-visible outcome.\n"
    "## Priority rules\n"
    "1. Correctness over style.\n"
    "2. Cite evidence when reasoning; do not fabricate tool results.\n"
    "## Scope check\n"
    "If the request is out of scope, say so briefly and offer the closest useful help.\n"
    "## Tools\n"
    "Use native tool calls. Do not invent results.\n"
    "## Output\n"
    "Answer directly and compactly. Put reasoning before the answer only when it helps.\n"
    "## Reasoning\n"
    "Reasoning strength is controlled by the request. Keep reasoning compact unless asked for depth."
)

def complete(
    messages: list,
    max_tokens: int = 1024,
    temperature: float = 1.0,
    reasoning_effort: str | None = None,
    tools: list | None = None,
    tool_choice: str | None = None,
    model: str | None = None,
) -> dict:
    if not available():
        raise RuntimeError("OPENROUTER_API_KEY not set")
    model_id = model or MODEL_ID
    payload: dict = {
        "model": model_id,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    if reasoning_effort in ("low", "medium", "high", "xhigh"):
        payload["reasoning_effort"] = reasoning_effort
    if tools:
        payload["tools"] = tools
    if tool_choice:
        payload["tool_choice"] = tool_choice
    data = _post(payload)
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message", {})
    content = msg.get("content") or ""
    # Muse Spark always reasons first; a small max_tokens can be spent
    # entirely on reasoning and return empty content with finish=length.
    if not content.strip() and choice.get("finish_reason") == "length" \
            and max_tokens < 32768:
        return complete(messages, min(max_tokens * 4, 32768), temperature,
                        reasoning_effort, tools, tool_choice, model=model_id)
    return {
        "content": content,
        "reasoning_content": msg.get("reasoning_content") or msg.get("reasoning") or "",
        "tool_calls": msg.get("tool_calls") or [],
        "finish_reason": choice.get("finish_reason"),
        "usage": data.get("usage", {}),
        "model": data.get("model") or model_id,
        "backend": f"{model_id}/openrouter",
    }

def stream(
    messages: list,
    max_tokens: int = 2048,
    temperature: float = 1.0,
    reasoning_effort: str | None = None,
    model: str | None = None,
):
    """Yield OpenAI-shaped SSE chunk JSON strings from OpenRouter."""
    if not available():
        raise RuntimeError("OPENROUTER_API_KEY not set")
    model_id = model or MODEL_ID
    payload: dict = {
        "model": model_id,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    if reasoning_effort in ("low", "medium", "high", "xhigh"):
        payload["reasoning_effort"] = reasoning_effort
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
                out_delta = {}
                if delta.get("content"):
                    out_delta["content"] = delta["content"]
                if delta.get("reasoning"):
                    out_delta["reasoning_content"] = delta["reasoning"]
                if delta.get("tool_calls"):
                    out_delta["tool_calls"] = delta["tool_calls"]
                if not out_delta and not choice.get("finish_reason"):
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
        raise RuntimeError(f"OpenRouter stream HTTP {e.code}: {detail}")


def estimate_cost(usage: dict) -> float:
    try:
        pt = int(usage.get("prompt_tokens", 0))
        ct = int(usage.get("completion_tokens", 0))
        return (pt * 1.25 + ct * 4.25) / 1_000_000
    except Exception:
        return 0.0
