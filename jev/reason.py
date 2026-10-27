#!/usr/bin/env python3
"""jev/reason.py — Urai reasoning engine.

Exposes Qwen3's native thinking traces properly:
  - URAI_THINKING=1  → full <think>...</think> visible in response
  - URAI_THINKING=0  → thinking runs but stripped (default, faster answers)
  - URAI_THINKING=budget:<N> → thinking tokens capped at N (quality/speed trade)

Also provides:
  reason(messages, budget)   → {answer, thinking, steps, backend}
  chain_of_thought(prompt)   → step-by-step breakdown, structured
  verify_answer(q, a)        → re-check answer, return {ok, issues, fixed}

The thinking trace is stored in the session and available via
GET /v1/sessions/<id>/trace — clients can show "Urai's reasoning" like
Claude's extended thinking or o1's chain of thought.
"""
from __future__ import annotations
import json
import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THINKING_MODE = os.environ.get("URAI_THINKING", "0")  # 0 | 1 | budget:<N>


def _thinking_enabled() -> bool:
    return THINKING_MODE != "0"


def _thinking_budget() -> int | None:
    """Return token budget for thinking, or None for unlimited."""
    if THINKING_MODE.startswith("budget:"):
        try:
            return int(THINKING_MODE.split(":")[1])
        except Exception:
            return 512
    return None


def _extract_thinking(text: str) -> tuple[str, str]:
    """Split <think>...</think> from answer. Returns (thinking, answer)."""
    m = re.search(r"<think>(.*?)</think>\s*", text, re.DOTALL)
    if m:
        thinking = m.group(1).strip()
        answer = text[m.end():].strip()
        return thinking, answer
    # Qwen3 sometimes uses reasoning_content field (handled in backends.py)
    # Fall back: no thinking found
    return "", text.strip()


def _inject_thinking_prompt(messages: list, budget: int | None) -> list:
    """Inject thinking instruction into the last user message."""
    msgs = [dict(m) for m in messages]
    # Remove any previous /no_think injected by backends.py
    for m in msgs:
        if isinstance(m.get("content"), str):
            m["content"] = m["content"].replace("\n/no_think", "").rstrip()

    # Add thinking trigger for Qwen3
    budget_hint = f" Use at most {budget} tokens of thinking." if budget else ""
    for m in reversed(msgs):
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            m["content"] = m["content"].rstrip() + f"\n/think{budget_hint}"
            break
    return msgs


def reason(messages: list, max_tokens: int = 1024,
           temperature: float = 0.6) -> dict:
    """Run Urai with thinking enabled. Returns structured result.

    temperature=0.6 is Qwen3's recommended value for thinking mode.
    """
    from .backends import LlamaServerBackend
    backend = LlamaServerBackend()
    if not backend.healthy():
        raise RuntimeError("Urai local model not available")

    budget = _thinking_budget()
    msgs = _inject_thinking_prompt(messages, budget)

    # Temporarily override URAI_THINKING so backends.py doesn't strip it
    old = os.environ.get("URAI_THINKING", "0")
    os.environ["URAI_THINKING"] = "1"
    try:
        res = backend.complete(msgs, max_tokens=max_tokens,
                               temperature=temperature)
    finally:
        os.environ["URAI_THINKING"] = old

    raw = res.get("content", "")
    thinking_raw = res.get("reasoning_content", "")  # llama-server field

    if thinking_raw:
        thinking, answer = thinking_raw.strip(), raw.strip()
    else:
        thinking, answer = _extract_thinking(raw)

    # Parse thinking into steps if present
    steps = _parse_steps(thinking)

    return {
        "answer": answer,
        "thinking": thinking,
        "steps": steps,
        "backend": res.get("backend", "llama-local"),
        "model": res.get("model", ""),
        "usage": res.get("usage", {}),
        "thinking_mode": THINKING_MODE,
    }


def _parse_steps(thinking: str) -> list[str]:
    """Extract numbered steps or paragraph breaks from thinking trace."""
    if not thinking:
        return []
    # Numbered steps: "1. ...", "Step 1:", etc.
    numbered = re.findall(
        r"(?:^|\n)(?:Step\s*)?\d+[.)]\s*(.+?)(?=\n(?:Step\s*)?\d+[.)]|\Z)",
        thinking, re.DOTALL)
    if len(numbered) >= 2:
        return [s.strip()[:300] for s in numbered]
    # Paragraph breaks
    paras = [p.strip() for p in thinking.split("\n\n") if p.strip()]
    return paras[:8]


def chain_of_thought(prompt: str, max_tokens: int = 1024) -> dict:
    """Step-by-step reasoning for a single prompt.
    Returns {answer, steps, thinking}.
    """
    msgs = [
        {"role": "system",
         "content": ("You are Urai. Think step by step. "
                     "Show your reasoning clearly before giving the final answer.")},
        {"role": "user", "content": prompt},
    ]
    return reason(msgs, max_tokens=max_tokens, temperature=0.6)


def verify_answer(question: str, answer: str,
                  max_tokens: int = 512) -> dict:
    """Re-examine an answer for correctness. Returns {ok, issues, fixed}.
    Used by agent.py verify loop and urai-ultra tier.
    """
    msgs = [
        {"role": "system",
         "content": ("You are a careful verifier. Check if the answer is correct, "
                     "complete, and consistent. If there are issues, provide a "
                     "fixed version. Reply as JSON: "
                     '{"ok": true/false, "issues": [...], "fixed": "...or empty"}')},
        {"role": "user",
         "content": f"Question: {question}\n\nAnswer to verify:\n{answer}"},
    ]
    from .backends import LlamaServerBackend
    backend = LlamaServerBackend()
    res = backend.complete(msgs, max_tokens=max_tokens, temperature=0.1)
    raw = res.get("content", "")
    # Parse JSON response
    try:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except Exception:
        pass
    ok = "correct" in raw.lower() and "issue" not in raw.lower()
    return {"ok": ok, "issues": [], "fixed": "", "raw": raw[:300]}


def consistency_vote(messages: list, n: int = 3,
                     max_tokens: int = 512) -> dict:
    """Run Urai n times and pick the most common answer (majority vote).
    Used by urai-ultra tier for hard/math questions.
    Returns {answer, votes, agreement, candidates}.
    """
    from .backends import LlamaServerBackend
    backend = LlamaServerBackend()
    if not backend.healthy():
        raise RuntimeError("Urai local model not available")

    answers = []
    for i in range(n):
        # Slightly varied temperature for diversity
        temp = 0.3 + i * 0.15
        res = backend.complete(messages, max_tokens=max_tokens,
                               temperature=temp)
        _, ans = _extract_thinking(res.get("content", ""))
        answers.append(ans.strip())

    # Find most common answer (exact then fuzzy)
    from collections import Counter
    counts = Counter(answers)
    best, votes = counts.most_common(1)[0]
    agreement = round(votes / n, 2)

    return {
        "answer": best,
        "votes": votes,
        "total": n,
        "agreement": agreement,
        "candidates": answers,
    }
