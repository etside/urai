#!/usr/bin/env python3
"""Router: complexity classification → backend choice.

LEVEL 0: simple question            → fastest available (local 0.6B/fast)
LEVEL 1: simple coding              → fast local student
LEVEL 2: multi-file coding          → primary local model
LEVEL 3: architecture / debugging   → cloud reasoning (Kimi K2 / DeepSeek) or local
LEVEL 4: very difficult / explicit  → strongest available + verification

Routing priority (GPU-aware):
  1. Local GPU model  (llama-server healthy + GPU detected)
  2. Local CPU model  (llama-server healthy, no GPU)
  3. Cloud reasoning  (MOONSHOT/DEEPSEEK/ANTHROPIC/OPENAI key set, level ≥ 3)
  4. MockBackend      (nothing available — never hard-errors)

Cloud backends skip VPS if env key is absent.
Streaming flag propagated: caller passes stream=True to backend.stream_complete().
Routing outcomes logged to data/routing_scores.json for future learned routing.
"""

from __future__ import annotations
import json
import os
import re
import time

from .backends import (LlamaServerBackend, CloudAPIBackend, BedrockBackend,
                       MockBackend, TeacherAPIBackend, _gpu_available)

# ── Classifiers ────────────────────────────────────────────────────────────────

DIFFICULT = re.compile(
    r"architect|design system|debug|root cause|race condition|deadlock|"
    r"security|vulnerab|migrat|refactor.*multi|monorepo|distributed|"
    r"consensus|split-brain|threat model", re.I)
MULTIFILE = re.compile(
    r"multi-?file|across files|repo|repository|codebase|project-wide|"
    r"files?:\s*\S+\.(ts|py|tsx|js)", re.I)
CODE = re.compile(r"```|def |function |class |import |SELECT|fn\(|=>", re.I)
REASONING = re.compile(
    r"think (hard|step|carefully)|reason through|very difficult|"
    r"solve exactly|proof|math problem|competition|olympiad", re.I)


def classify(prompt: str) -> dict:
    n = len(prompt)
    if REASONING.search(prompt) or n > 8000:
        return {"level": 4, "reason": "explicit hard / reasoning task"}
    if DIFFICULT.search(prompt):
        return {"level": 3, "reason": "architecture/debugging/security"}
    if MULTIFILE.search(prompt) or (CODE.search(prompt) and n >= 1500):
        return {"level": 2, "reason": "multi-file or large coding context"}
    if CODE.search(prompt) and n < 1500:
        return {"level": 1, "reason": "single-snippet coding"}
    if len(prompt.split()) < 12:
        return {"level": 0, "reason": "short question"}
    return {"level": 0, "reason": "general question"}


# ── Backend selection ──────────────────────────────────────────────────────────

def _best_local() -> LlamaServerBackend | None:
    """Return local backend if healthy, else None."""
    ll = LlamaServerBackend()
    return ll if ll.healthy() else None


def _best_cloud(min_level: int = 3) -> CloudAPIBackend | None:
    """Return best available cloud backend, or None if none configured/healthy."""
    c = CloudAPIBackend()  # auto-select
    if c.available and c.healthy():
        return c
    return None


def pick_backend(level: int, stream: bool = False):
    """Returns (backend, needs_verification, allow_fallback).

    Never raises — falls back to MockBackend in worst case.
    GPU presence influences which local model tier llama-server uses
    (configured via URAI_LLAMA_MODEL or model registry active).
    """
    gpu = _gpu_available()  # cached, never raises

    local = _best_local()

    # Fast path: levels 0-2 → local only
    if level <= 2:
        if local:
            return local, level >= 2, True
        # Local down — for low-level queries, try cheap cloud
        cloud = _best_cloud(min_level=0)
        if cloud:
            return cloud, False, True
        return MockBackend(), False, False

    # Levels 3-4 → prefer cloud reasoning backend
    cloud = _best_cloud(min_level=3)
    if cloud:
        return cloud, True, True

    # Cloud not configured — fall back to local (best we have)
    if local:
        return local, True, False

    # Legacy teacher API
    try:
        api = TeacherAPIBackend()
        if api.healthy():
            return api, True, True
    except (KeyError, Exception):
        pass

    # AWS Bedrock fallback (Nova Micro, cheapest)
    try:
        bedrock = BedrockBackend()
        if bedrock.healthy():
            return bedrock, level >= 2, True
    except Exception:
        pass

    # Nothing available
    return MockBackend(), False, False


# ── Tiers ─────────────────────────────────────────────────────────────────────

TIERS = {
    "urai-fast": {
        "consistency": 1, "max_tokens": 128, "verify": False,
        "skills_extra": [], "level_cap": 1, "stream": False,
    },
    "urai": {
        "consistency": 1, "max_tokens": 512, "verify": None,
        "skills_extra": [], "level_cap": 4, "stream": False,
    },
    "urai-ultra": {
        "consistency": 3, "max_tokens": 1024, "verify": True,
        "skills_extra": [], "level_cap": 4, "stream": True,
    },
    "urai-cyber": {
        "consistency": 3, "max_tokens": 512, "verify": True,
        "skills_extra": ["cyber-security", "threat-analysis"],
        "level_cap": 4, "stream": False,
    },
}

SCORES_FILE = "data/routing_scores.json"


def apply_tier(tier: str) -> dict:
    return dict(TIERS.get(tier or "urai", TIERS["urai"]))


def record_outcome(level: int, backend: str, ok: bool):
    """Append-only routing outcome log (learning loop stage 1: measure)."""
    try:
        from pathlib import Path as _P
        fp = _P(__file__).resolve().parents[1] / SCORES_FILE
        try:
            d = json.loads(fp.read_text())
        except Exception:
            d = {}
        k = f"L{level}/{backend}"
        e = d.get(k, {"n": 0, "ok": 0})
        e["n"] += 1
        e["ok"] += 1 if ok else 0
        e["rate"] = round(e["ok"] / e["n"], 3)
        e["ts"] = int(time.time())
        d[k] = e
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps(d, indent=2) + "\n")
    except Exception:
        pass


def routing_scores() -> dict:
    try:
        from pathlib import Path as _P
        return json.loads(
            (_P(__file__).resolve().parents[1] / SCORES_FILE).read_text())
    except Exception:
        return {}


def route(prompt: str, tier: str = "urai", stream: bool = False) -> dict:
    cls = classify(prompt)
    t = apply_tier(tier)
    level = min(cls["level"], t["level_cap"])

    # stream flag: body.stream overrides tier default
    want_stream = stream or t.get("stream", False)

    backend, verify, fallback = pick_backend(level, stream=want_stream)

    try:
        from .pool import allowed as _allowed
        if not _allowed(getattr(backend, "model", backend.name)):
            local = _best_local()
            if local:
                backend, fallback = local, False
    except Exception:
        pass

    if t["verify"] is not None:
        verify = t["verify"]

    return {
        "level": level,
        "reason": cls["reason"],
        "tier": tier,
        "backend": backend,
        "verify": verify,
        "fallback": fallback,
        "stream": want_stream,
        "gpu": _gpu_available(),
        "tier_cfg": t,
    }
