#!/usr/bin/env python3
"""Brand map: the public Urai model surface (stdlib only).

There are exactly TWO public models:

  urai       — one unified assistant. Internally it picks the right local /
               teacher backend and mode (fast · balanced · ultra) per request.
  cyberurai  — separate cybersecurity specialist (latest threat knowledge,
               threat-analysis + Android privacy guard).

Everything else (qwen*, coder*, laya, jev-local-student, ...) is an internal
backend id that must never leak as a primary model id — it only ever appears
in traces/metadata. Legacy public ids (urai-fast / urai-ultra / urai-cyber /
cyberurai-v1) are accepted as aliases and folded into the two.
"""

PUBLIC = ("urai", "cyberurai")

BRANDS = {
    "urai": {
        "tier": "urai",
        "desc": "Urai — one unified assistant (fast · balanced · ultra modes)",
        "modes": [
            {"id": "fast", "desc": "short, quick answers"},
            {"id": "balanced", "desc": "everyday default"},
            {"id": "ultra", "desc": "verified depth, multi-step reasoning"},
        ],
        "internal": [
            "jev-local-student", "local-student", "llama-local", "local",
            "qwen3-4b", "qwen3-17b", "qwen3-4B-Q4_K_M", "qwen25vl-3b",
            "coder05-fast", "coder15-primary", "qwen2.5-coder",
            "laya", "urai-fast", "urai-ultra", "auto",
        ],
    },
    "cyberurai": {
        "tier": "cyberurai",
        "desc": "CyberUrai — cybersecurity specialist + Android privacy guard",
        "modes": [
            {"id": "audit", "desc": "code/dependency security review"},
            {"id": "threat", "desc": "threat modeling + latest advisories"},
            {"id": "guard", "desc": "device/app privacy monitoring"},
        ],
        "internal": ["urai-cyber", "cyberurai-v1", "cyberurai", "cyber"],
    },
}


def brand_id(internal: str) -> str:
    """Map any internal/legacy id to one of the two public brands."""
    name = (internal or "").lower()
    if name in BRANDS:
        return name
    for bid, b in BRANDS.items():
        if name in [i.lower() for i in b.get("internal", [])]:
            return bid
    if "cyber" in name:
        return "cyberurai"
    if any(k in name for k in ("qwen", "llama", "local", "student",
                               "coder", "laya", "vl", "auto", "urai")):
        return "urai"
    return "urai"


def tier_of_brand(model: str) -> str:
    m = (model or "").lower()
    # legacy tier ids stay valid so fast/ultra/cyber strategies still resolve
    if m in ("urai-fast", "urai-ultra", "urai-cyber"):
        return m
    return brand_id(m)


def brand_list(available: bool = True) -> list:
    return [{"id": bid, "owned_by": "Urai", "available": available,
             "tier": b["tier"], "description": b["desc"],
             "modes": [m["id"] for m in b.get("modes", [])]}
            for bid, b in BRANDS.items()]
