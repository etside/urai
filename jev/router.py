#!/usr/bin/env python3
"""Router: complexity classification → Urai's own local model, always.

Architecture:
  Urai IS the LLM. The local student (Qwen3 via llama-server) is Urai's
  brain — not a backend option. Cloud APIs are TOOLS Urai can call through
  the agent/tools layer (like web_search), not replacements for Urai itself.

  Muse Spark Open (816B MoE, 1M ctx, multimodal, via OpenRouter) is Urai's
  hosted teacher/consult: it supplies long-context reasoning, image/video/
  audio/PDF understanding, and distill data. It never claims to BE Urai.
  See jev/muse.py + docs/MUSE_SPARK_OPEN.md.

  When llama-server is temporarily down, the watchdog (sched.py) restarts
  it within seconds. The right response to "local is down" is:
    → return a clear service-unavailable error (503)
    → NOT silently answer as Claude/DeepSeek pretending to be Urai

  Cloud keys (OPENROUTER_API_KEY etc.) power Urai's TOOLS:
    - research tool: fetch info from a smarter model mid-task
    - distill teacher: generate training data (Muse Spark → Qwen3 student)
    - verify tool: second-opinion check on Urai's own answer
  They do NOT replace Urai's identity.

  Public mode (URAI_PUBLIC=1 / URAI_FREE_MODE=1):
    - API exposed publicly behind Caddy + HTTPS (see deploy/deploy-public.sh)
    - Local-model bad requests still 503; cloud teacher available to any
      authenticated caller. Keep URAI_MASTER_KEY set when public.

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

Multimodal routing:
  If messages contain image/video/audio parts or a PDF (URAI_CLOUD_1M=1),
  route understanding to Muse Spark Open (1M ctx) and return the summary
  as context for the local model. Local llama-server Cedaruri keeps text-only.
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
    """Urai's own local model, else hosted Muse Spark when fallback is on.

    Returns (backend, needs_verification, allow_fallback).
    Raises RuntimeError with 503 hint when no brain is available —
    the caller surfaces this to the client rather than silently
    substituting an unrelated LLM.
    """
    local = _urai_local()
    if local and not cloud_primary():
        verify = level >= 2
        return local, verify, False   # allow_fallback=False: local brain

    # Hosted Muse Spark (public deployments, or when no local model is up)
    if cloud_primary() or cloud_fallback():
        from .backends import MuseBackend
        mb = MuseBackend()
        if mb.healthy():
            return mb, level >= 2, True

    if local:
        return local, level >= 2, False

    # llama-server is temporarily down (watchdog is restarting it)
    raise RuntimeError(
        "Urai's local model is starting up — please retry in a few seconds. "
        "(watchdog is restarting llama-server)")


def cloud_fallback() -> bool:
    """True when hosted Muse Spark may stand in for a missing local model."""
    if os.environ.get("URAI_CLOUD_FALLBACK") in ("0", "false", "no"):
        return False
    if os.environ.get("URAI_CLOUD_FALLBACK") == "1":
        return True
    return free_mode()   # public/free deployments default to on


def cloud_primary() -> bool:
    """True when hosted Muse Spark should answer first (public deployments).

    Urai keeps the local student for offline use; on hosts with no capable
    local GPU the hosted teacher gives the quality users expect. Set
    URAI_CLOUD_PRIMARY=1 to prefer it, 0 to prefer the local model.
    """
    return os.environ.get("URAI_CLOUD_PRIMARY", "0") == "1"


def pick_backend_safe(level: int, stream: bool = False):
    """Like pick_backend but returns (None, False, False) instead of raising.
    Use when you want to check availability without error handling.
    """
    try:
        return pick_backend(level, stream)
    except RuntimeError:
        return None, False, False


# ── Cloud consult tool (opt-in only, URAI_CLOUD_CONSULT=1) ───────────────────

# ── 1M-context cloud path (L4, URAI_CLOUD_1M=1, tier='urai-ultra') ───────────
# When URAI_CLOUD_1M=1 is set in the environment AND the tier is 'urai-ultra',
# cloud_consult() can route to a 1M-context provider as a research tool:
#
#   Provider priority (Muse Spark Open first):
#     1. Muse Spark Open  (1M tokens, OPENROUTER_API_KEY → meta/muse-spark-open)
#     2. Gemini 1.5 Pro  (1M token window, GEMINI_API_KEY)
#     3. Claude 3.5      (200K window,     ANTHROPIC_API_KEY — fallback)
#
#   This path is a TOOL call inside Urai's reasoning, not a replacement:
#     - Urai stays the identity (voice, personality, answer author)
#     - The cloud result is marked [cloud-consult:<model-id>] so Urai
#       can incorporate or cross-check it before responding
#     - Activate:  URAI_CLOUD_1M=1 URAI_CLOUD_CONSULT=1 urai chat
#     - Tier gate: only 'urai-ultra' enables cloud consult by default;
#       'urai' / 'urai-fast' ignore cloud even when URAI_CLOUD_1M=1
#
# URAI_CTX env sets the local context window hint (default 32768).
# Public free mode: URAI_FREE_MODE=1 — Muse Spark consult allowed for
# any authenticated caller until official release (no billing gate).
# ─────────────────────────────────────────────────────────────────────────────

def is_multimodal(messages: list) -> bool:
    """True if any user message carries non-text content (image/video/audio)."""
    for m in messages or []:
        c = m.get("content")
        if isinstance(c, list):
            for part in c:
                if isinstance(part, dict) and part.get("type") in (
                    "image_url", "video_url", "audio_url", "input_audio",
                ):
                    return True
    return False

def reasoning_effort_for(level: int, override: str | None = None) -> str:
    """Muse Spark reasoning effort by Urai level (low/med/high/xhigh)."""
    if override in ("low", "medium", "high", "xhigh"):
        return override
    env = os.environ.get("URAI_REASONING_EFFORT", "")
    if env in ("low", "medium", "high", "xhigh"):
        return env
    return {0: "low", 1: "medium", 2: "high", 3: "high", 4: "xhigh"}.get(level, "medium")

def free_mode() -> bool:
    return os.environ.get("URAI_FREE_MODE", "0") == "1" or os.environ.get("URAI_PUBLIC", "0") == "1"

def cloud_consult(prompt: str, context: str = "") -> str | None:
    """Call a cloud model as a RESEARCH TOOL for Urai to incorporate.
    Returns a string Urai can include in its reasoning, or None if unavailable.
    Only fires when URAI_CLOUD_CONSULT=1 AND a cloud key is configured.
    The result is clearly marked [cloud-consult] so Urai knows it's external.
    When URAI_CLOUD_1M=1 the context hint and URAI_CTX window size are passed.
    """
    if os.environ.get("URAI_CLOUD_CONSULT") != "1":
        return None
    try:
        from .backends import CloudAPIBackend
        c = CloudAPIBackend()
        if not c.available or not c.healthy():
            return None
        # Build context hint — include local ctx window when 1M path is active
        ctx_hint = ""
        if os.environ.get("URAI_CLOUD_1M") == "1":
            ctx_window = int(os.environ.get("URAI_CTX", "32768"))
            ctx_hint = (f"[context-window-hint: local={ctx_window} tokens, "
                        f"cloud=1M path active]\n")
        msgs = []
        if context or ctx_hint:
            msgs.append({"role": "system",
                         "content": "You are a research assistant. Be concise."})
        msgs.append({"role": "user",
                     "content": (ctx_hint
                                 + (f"Research context:\n{context}\n\n" if context else "")
                                 + prompt)})
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
        "backend": backend,       # local llama-server, or Muse Spark fallback
        "verify": verify,
        "fallback": getattr(backend, "name", "") == "muse-spark-open",
        "stream": want_stream,
        "gpu": _gpu_available(),
        "tier_cfg": t,
        "cloud_consult": t.get("cloud_consult", False),
    }
