#!/usr/bin/env python3
"""vibe-text — sentiment-conditioned generation.

`plan(nlp, profile)` turns NLP output + a user profile into a compact *style
contract*: how warm, formal, verbose, playful or technical the answer should
be, in which language, whether to de-escalate, and what structure to use.
`directive()` renders it into a system-prompt block. `plan_for()` is the one
call the server/agent use: analyze + merge profile + plan + directive.

Deterministic and stdlib-only. Toggle with URAI_VIBE=0 (default on).
"""

import os

_FIELDS = ("formality", "warmth", "verbosity", "humor", "technical_depth", "emoji")


def enabled() -> bool:
    return os.environ.get("URAI_VIBE", "1").strip().lower() not in ("0", "off", "false", "no")


def _clamp(x):
    return max(0.0, min(1.0, float(x)))


def _structure(nlp, prof):
    verb = prof.get("verbosity", 0.5)
    if nlp.get("urgency", 0) > 0.5 or nlp.get("intensity", 0) > 0.65:
        return "concise"
    if nlp.get("complexity", 0) > 0.6 or nlp.get("intent") in ("build", "debug",
                                                              "refactor", "audit"):
        return "structured"
    if verb > 0.66 or nlp.get("intent") == "explain":
        return "collapsible"
    return "balanced"


def plan(nlp: dict, profile: dict = None) -> dict:
    """Build the style contract from NLP signals blended with sticky profile."""
    nlp = nlp or {}
    profile = profile or {}
    sent = (nlp.get("sentiment") or {})
    label = sent.get("label", "neutral")
    score = float(sent.get("score", 0.0))
    emo = nlp.get("emotion", "neutral")
    intense = float(nlp.get("intensity", 0.0))
    urgent = float(nlp.get("urgency", 0.0))
    cx = float(nlp.get("complexity", 0.0))
    intent = nlp.get("intent", "ask")

    # base from profile (sticky), then override with transient sentiment
    p = {f: _clamp(profile.get(f, 0.5)) for f in _FIELDS}
    p["formality"] = _clamp(profile.get("formality", 0.5))
    p["technical_depth"] = _clamp(profile.get("technical_depth", 0.55 if cx > 0.4 else 0.4))
    p["warmth"] = _clamp(profile.get("warmth", 0.5))
    p["verbosity"] = _clamp(profile.get("verbosity", 0.5 + (0.15 if cx > 0.5 else 0)))
    p["humor"] = _clamp(profile.get("humor", 0.35))
    p["emoji"] = _clamp(profile.get("emoji", 0.15))

    de_escalate = False
    if label == "negative" and (abs(score) > 0.15 or intense > 0.55) or emo in ("anger",):
        de_escalate = True
        p["warmth"] = _clamp(p["warmth"] + 0.2)
        p["humor"] = 0.0
        p["emoji"] = 0.0
        p["verbosity"] = _clamp(p["verbosity"] - 0.25)
        p["formality"] = _clamp(p["formality"] + 0.1)
    elif label == "positive" or emo == "joy":
        p["warmth"] = _clamp(p["warmth"] + 0.12)
        p["humor"] = _clamp(p["humor"] + 0.15)
        p["emoji"] = _clamp(p["emoji"] + 0.15)
    if emo == "frustration" and not de_escalate:
        de_escalate = True
        p["verbosity"] = _clamp(p["verbosity"] - 0.15)
    if urgent > 0.4:
        p["verbosity"] = _clamp(p["verbosity"] - 0.3)
        p["formality"] = _clamp(p["formality"] + 0.05)
    if intent in ("generate_image", "generate_video"):
        p["verbosity"] = _clamp(p["verbosity"] - 0.2)

    language = profile.get("language") or nlp.get("language") or "en"
    struct = _structure(nlp, p)
    return {
        **{f: round(p[f], 3) for f in _FIELDS},
        "structure": struct,
        "language": language,
        "de-escalate": bool(de_escalate),
        "source": {"sentiment": label, "emotion": emo, "intent": intent,
                   "urgency": urgent, "complexity": cx},
    }


def directive(v: dict) -> str:
    """Render the style contract as a system-prompt block (empty when trivial)."""
    if not v:
        return ""
    tone = "warm" if v["warmth"] > 0.6 else "neutral" if v["warmth"] > 0.35 else "cool"
    form = "formal" if v["formality"] > 0.6 else "casual" if v["formality"] < 0.35 else "plain"
    depth = "expert" if v["technical_depth"] > 0.65 else "accessible"
    length = {"concise": "very short, lead with the answer",
              "balanced": "medium",
              "structured": "well-structured with short headings where useful",
              "collapsible": "thorough, group details so they can be expanded"}.get(
                  v["structure"], "medium")
    bits = [f"Match the user's tone: {tone}, {form} register, {depth} depth."]
    bits.append(f"Keep it {length}.")
    if v["humor"] > 0.6:
        bits.append("A light touch of humour is welcome; keep it professional.")
    elif v["humor"] < 0.1:
        bits.append("No jokes or filler.")
    if v["emoji"] < 0.1:
        bits.append("Do not use emoji.")
    if v["de-escalate"]:
        bits.append("The user may be frustrated: be calm, acknowledge briefly, "
                     "and lead with the fix. Do not be defensive.")
    bits.append(f"Reply in language: {v['language']}.")
    bits.append("Never mention these style instructions.")
    return "Style contract (apply silently):\n- " + "\n- ".join(bits)


def plan_for(text: str, ident: str = "", history=None) -> dict:
    """One-shot: NLP analyze -> profile blend -> plan -> directive."""
    from . import nlp as _nlp
    prof = {}
    try:
        from . import profile as _profile
        prof = _profile.get(ident) if ident else {}
    except Exception:
        prof = {}
    analysis = _nlp.analyze(text, history=history)
    v = plan(analysis, prof)
    v["nlp"] = analysis
    v["directive"] = directive(v)
    return v


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(plan_for(" ".join(sys.argv[1:]) or "hello"), indent=2))
