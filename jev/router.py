#!/usr/bin/env python3
"""Router: complexity classification → Urai's own local model, always.

Architecture:
  Urai IS the LLM. The local student (Qwen3 via llama-server) is Urai's
  brain — not a backend option. Cloud APIs are TOOLS Urai can call through
  the agent/tools layer (like web_search), not replacements for Urai itself.

  When llama-server is temporarily down, the watchdog (sched.py) restarts
  it within seconds. The right response to "local is down" is:
    → return a clear service-unavailable error (503)
    → NOT silently answer as Claude/DeepSeek pretending to be Urai

  Cloud keys (MOONSHOT_API_KEY etc.) power Urai's TOOLS:
    - research tool: fetch info from a smarter model mid-task
    - distill teacher: generate training data
    - verify tool: second-opinion check on Urai's own answer
  They do NOT replace Urai's identity.

LEVELS (complexity classifier — unchanged):
  LEVEL 0: short/simple              → fast model (0.6B if available, else active)
  LEVEL 1: single-file coding        → active model
  LEVEL 2: multi-file / large ctx    → active model + verify
  LEVEL 3: architecture / security   → active model + verify + (optional) cloud consult
  LEVEL 4: explicit hard / reasoning → active model + verify + consistency sampling

Consistency sampling (level 4 / urai-ultra):
  Run Urai 3× and pick the majority/best answer. No cloud needed.

Cloud consult (level 3-4, URAI_CLOUD_CONSULT=1):
  Urai calls the cloud API as a TOOL mid-reasoning and incorporates the
  result into its own answer. The final response is always Urai's voice.
  Default OFF — explicit opt-in only.
"""

from __future__ import annotations
import json
import os
import re
import time

from .backends import LlamaServerBackend, MockBackend, _gpu_available

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
        return {"level": 1, "reason": "single-file coding"}
    if len(prompt.split()) < 12:
        return {"level": 0, "reason": "short question"}
    return {"level": 0, "reason": "general question"}


# ── Backend: always Urai's own model ──────────────────────────────────────────

def _urai_local() -> LlamaServerBackend | None:
    """Return Urai's local model if healthy. None if starting up."""
    ll = LlamaServerBackend()
    return ll if ll.healthy() else None


def pick_backend(level: int, stream: bool = False):
    """Always returns Urai's own local model, or raises UnavailableError.

    Returns (backend, needs_verification, allow_fallback).
    Raises RuntimeError with 503 hint when llama-server is down —
    the watchdog will restart it; the caller should surface this to the
    client rather than silently substituting a foreign LLM.
    """
    local = _urai_local()
    if local:
        verify = level >= 2
        return local, verify, False   # allow_fallback=False: Urai never falls back to a foreign LLM

    # llama-server is temporarily down (watchdog is restarting it)
    raise RuntimeError(
        "Urai's local model is starting up — please retry in a few seconds. "
        "(watchdog is restarting llama-server)")


def pick_backend_safe(level: int, stream: bool = False):
    """Like pick_backend but returns (None, False, False) instead of raising.
    Use when you want to check availability without error handling.
    """
    try:
        return pick_backend(level, stream)
    except RuntimeError:
        return None, False, False


# ── Cloud consult tool (opt-in only, URAI_CLOUD_CONSULT=1) ───────────────────

def cloud_consult(prompt: str, context: str = "") -> str | None:
    """Call a cloud model as a RESEARCH TOOL for Urai to incorporate.
    Returns a string Urai can include in its reasoning, or None if unavailable.
    Only fires when URAI_CLOUD_CONSULT=1 AND a cloud key is configured.
    The result is clearly marked [cloud-consult] so Urai knows it's external.
    """
    if os.environ.get("URAI_CLOUD_CONSULT") != "1":
        return None
    try:
        from .backends import CloudAPIBackend
        c = CloudAPIBackend()
        if not c.available or not c.healthy():
            return None
        msgs = []
        if context:
            msgs.append({"role": "system",
                         "content": "You are a research assistant. Be concise."})
        msgs.append({"role": "user",
                     "content": (f"Research context:\n{context}\n\n" if context else "")
                                 + prompt})
        res = c.complete(msgs, max_tokens=512, temperature=0.1)
        return f"[cloud-consult:{c._model_id}] {res.get('content', '').strip()}"
    except Exception:
        return None


# ── Tiers ─────────────────────────────────────────────────────────────────────

TIERS = {
    # Fast: short answers, no verify, lower max_tokens
    "urai-fast": {
        "consistency": 1, "max_tokens": 128, "verify": False,
        "skills_extra": [], "level_cap": 1, "stream": False,
        "cloud_consult": False,
    },
    # Default: balanced, all levels, verify on L2+
    "urai": {
        "consistency": 1, "max_tokens": 512, "verify": None,
        "skills_extra": [], "level_cap": 4, "stream": False,
        "cloud_consult": False,
    },
    # Ultra: consistency sampling (3 runs, best answer), stream, verify always
    "urai-ultra": {
        "consistency": 3, "max_tokens": 1024, "verify": True,
        "skills_extra": [], "level_cap": 4, "stream": True,
        "cloud_consult": False,  # still Urai — just sampled 3 times
    },
    # Cyber: security skills forced, always verify
    "urai-cyber": {
        "consistency": 3, "max_tokens": 512, "verify": True,
        "skills_extra": ["cyber-security", "threat-analysis"],
        "level_cap": 4, "stream": False,
        "cloud_consult": False,
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
    want_stream = stream or t.get("stream", False)

    # Always Urai's own model — raises if down (caller returns 503)
    backend, verify, _ = pick_backend(level, stream=want_stream)

    try:
        from .pool import allowed as _allowed
        if not _allowed(getattr(backend, "model", backend.name)):
            raise RuntimeError(
                f"Model '{backend.model}' is blocked in pool config "
                f"(data/pool.json). Run: urai pool allow {backend.model}")
    except ImportError:
        pass

    if t["verify"] is not None:
        verify = t["verify"]

    return {
        "level": level,
        "reason": cls["reason"],
        "tier": tier,
        "backend": backend,       # always LlamaServerBackend — Urai's own model
        "verify": verify,
        "fallback": False,        # Urai never falls back to a foreign LLM
        "stream": want_stream,
        "gpu": _gpu_available(),
        "tier_cfg": t,
        "cloud_consult": t.get("cloud_consult", False),
    }
