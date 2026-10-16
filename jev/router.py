#!/usr/bin/env python3
"""Router: complexity classification -> backend choice (mission §11).

LEVEL 0: simple question            -> fastest available (local)
LEVEL 1: simple coding               -> fast local student
LEVEL 2: multi-file coding           -> primary local model
LEVEL 3: architecture / debugging    -> stronger reasoning (teacher API if configured)
LEVEL 4: very difficult / explicit   -> strongest available, with verification

Rules: never use an expensive backend when a local one suffices; every
LEVEL>=2 answer passes through the verifier; fallback on failure.
Heuristics now, learned classifier later (routing outcomes are logged).
"""

import json
import re
import time

from .backends import LlamaServerBackend, TeacherAPIBackend

DIFFICULT = re.compile(
    r"architect|design system|debug|root cause|race condition|deadlock|"
    r"security|vulnerab|migrat|refactor.*multi|monorepo|distributed|"
    r"consensus|split-brain|threat model", re.I)
MULTIFILE = re.compile(
    r"multi-?file|across files|repo|repository|codebase|project-wide|"
    r"files?:\s*\S+\.(ts|py|tsx|js)", re.I)
CODE = re.compile(r"```|def |function |class |import |SELECT|fn\(|=>", re.I)


def classify(prompt: str) -> dict:
    n = len(prompt)
    if len(prompt.split()) < 12 and not CODE.search(prompt):
        return {"level": 0, "reason": "short non-code question"}
    if CODE.search(prompt) and not MULTIFILE.search(prompt) and n < 1500:
        return {"level": 1, "reason": "single-snippet coding"}
    if MULTIFILE.search(prompt) or (CODE.search(prompt) and n >= 1500):
        return {"level": 2, "reason": "multi-file or large coding context"}
    if DIFFICULT.search(prompt):
        return {"level": 3, "reason": "architecture/debugging/security"}
    if n > 6000 or "think hard" in prompt.lower() or "very difficult" in prompt.lower():
        return {"level": 4, "reason": "explicit hard task"}
    if CODE.search(prompt):
        return {"level": 1, "reason": "code present, default fast"}
    return {"level": 0, "reason": "general question"}


def pick_backend(level: int, local: bool = True):
    """Returns (backend, needs_verification, allow_fallback)."""
    if level <= 2:
        ll = LlamaServerBackend()
        if ll.healthy():
            return ll, level >= 2, True
        raise RuntimeError("local backend unavailable (llama-server down or overloaded)")
    try:
        api = TeacherAPIBackend()
        if api.healthy():
            return api, True, True
    except KeyError:
        pass
    ll = LlamaServerBackend()
    if ll.healthy():
        return ll, True, False
    raise RuntimeError("local backend unavailable (llama-server down or overloaded)")


# Fugu-style tiers, one pool, no keys. Tier = strategy over local models:
# fast = short answers, no verify loop; balanced = default agent;
# ultra = consistency sampling + verify (+teacher backend when TEACHER_* set);
# cyber = security skill forced + verify + consistency.
TIERS = {
    "urai-fast": {"consistency": 1, "max_tokens": 128, "verify": False,
                  "skills_extra": [], "level_cap": 1},
    "urai": {"consistency": 1, "max_tokens": 512, "verify": None,
             "skills_extra": [], "level_cap": 4},
    "urai-ultra": {"consistency": 3, "max_tokens": 512, "verify": True,
                   "skills_extra": [], "level_cap": 4},
    # unified CyberUrai brand (urn: legacy urai-cyber folded here)
    "cyberurai": {"consistency": 3, "max_tokens": 512, "verify": True,
                  "skills_extra": ["cyber-security", "threat-analysis"],
                  "level_cap": 4},
    "urai-cyber": {"consistency": 3, "max_tokens": 512, "verify": True,
                   "skills_extra": ["cyber-security", "threat-analysis"],
                   "level_cap": 4},
}

SCORES_FILE = "data/routing_scores.json"


def apply_tier(tier: str) -> dict:
    return dict(TIERS.get(tier or "urai", TIERS["urai"]))


def record_outcome(level: int, backend: str, ok: bool):
    """Append-only routing outcome log (learning loop, stage 1: measure)."""
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
        return json.loads((_P(__file__).resolve().parents[1] / SCORES_FILE).read_text())
    except Exception:
        return {}


def route(prompt: str, tier: str = "urai") -> dict:
    cls = classify(prompt)
    t = apply_tier(tier)
    level = min(cls["level"], t["level_cap"])
    backend, verify, fallback = pick_backend(level)
    try:
        from .pool import allowed as _allowed
        if not _allowed(getattr(backend, "model", backend.name)):
            ll = LlamaServerBackend()
            if ll.healthy():
                backend, fallback = ll, False
    except Exception:
        pass
    if t["verify"] is not None:
        verify = t["verify"]
    return {"level": level, "reason": cls["reason"], "tier": tier,
            "backend": backend, "verify": verify, "fallback": fallback,
            "tier_cfg": t}
