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

import re

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


def route(prompt: str) -> dict:
    cls = classify(prompt)
    backend, verify, fallback = pick_backend(cls["level"])
    return {"level": cls["level"], "reason": cls["reason"],
            "backend": backend, "verify": verify, "fallback": fallback}
