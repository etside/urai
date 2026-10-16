#!/usr/bin/env python3
"""Six-section Ref2VA prompt compiler for MiniMax H3 Reference-to-Video.

MiniMax H3 Ref2VA wants a structured English prompt with exactly six sections,
in this order:

    subject_definitions
    summary
    retention_analysis
    detailed_description
    overall_soundscape
    non_diegetic_music

References are addressed with 1-based tags per media type:
    <Picture N>  <Video N>  <Audio N>  <Subject N>

Retention vocabulary:
    visual  : fully_preserved | partially_preserved | attribute_transfer | weak_reference
    audio   : fully_copy | partially_copy | reference | weak_reference

Camera movements follow the documented formula:
    "The camera [movement] with [amplitude] at [speed] toward/revealing [target]."

Stdlib only. `compile_prompt()` returns the exact string; `validate()` checks all
six sections are present and English (ASCII/Latin script).
"""

import re

SECTIONS = ("subject_definitions", "summary", "retention_analysis",
            "detailed_description", "overall_soundscape", "non_diegetic_music")

VISUAL_RETENTION = ("fully_preserved", "partially_preserved",
                    "attribute_transfer", "weak_reference")
AUDIO_RETENTION = ("fully_copy", "partially_copy", "reference", "weak_reference")

CAMERA_MOVEMENTS = (
    "Zoom In", "Zoom Out", "Push In", "Pull Out", "Pan Left", "Pan Right",
    "Truck Left", "Truck Right", "Tilt Up", "Tilt Down", "Arc Shot",
    "Tracking Shot", "Static Shot", "Shake Slightly", "Shake Strongly",
    "POV", "Roll Clockwise", "Roll Counterclockwise",
)


def pic(n: int) -> str:
    return f"<Picture {int(n)}>"


def vid(n: int) -> str:
    return f"<Video {int(n)}>"


def aud(n: int) -> str:
    return f"<Audio {int(n)}>"


def subj(n: int) -> str:
    return f"<Subject {int(n)}>"


def camera_phrase(movement: str, amplitude: str = "moderate",
                  speed: str = "steady", target: str = "the subject") -> str:
    """Build a validated camera sentence. Raises ValueError on bad movement."""
    m = (movement or "").strip()
    if m.lower() not in [x.lower() for x in CAMERA_MOVEMENTS]:
        raise ValueError(f"unknown camera movement {movement!r}; "
                         f"allowed: {', '.join(CAMERA_MOVEMENTS)}")
    return (f"The camera {m.lower()} with {amplitude} amplitude at {speed} "
            f"speed toward {target}.")


def retention_line(tag: str, context: str, word: str, note: str,
                   audio: bool = False) -> str:
    """One retention_analysis line, e.g.
    '<Subject 1> (appears in [Shot 1]): fully_preserved - preserve facial identity.'
    """
    allowed = AUDIO_RETENTION if audio else VISUAL_RETENTION
    if word not in allowed:
        raise ValueError(f"retention word {word!r} not in {allowed}")
    ctx = f" {context}" if context else ""
    return f"{tag}{ctx}: {word} - {note}"


class Ref2VAFields:
    """Structured holder; render with `compile_prompt`."""

    def __init__(self):
        self.subject_definitions = ""
        self.summary = ""
        self.retention_analysis = ""
        self.detailed_description = ""
        self.overall_soundscape = ""
        self.non_diegetic_music = ""


def compile_prompt(subject_definitions="", summary="", retention_analysis="",
                   detailed_description="", overall_soundscape="",
                   non_diegetic_music="") -> str:
    """Assemble the six-section prompt in the required order."""
    body = {
        "subject_definitions": subject_definitions,
        "summary": summary,
        "retention_analysis": retention_analysis,
        "detailed_description": detailed_description,
        "overall_soundscape": overall_soundscape,
        "non_diegetic_music": non_diegetic_music,
    }
    parts = []
    for s in SECTIONS:
        parts.append(f"{s}:\n{(body.get(s) or '').strip()}")
    return "\n\n".join(parts).strip() + "\n"


def parse_sections(prompt: str) -> dict:
    """Split a compiled prompt back into its six sections (tolerant)."""
    out = {s: "" for s in SECTIONS}
    cur = None
    for line in (prompt or "").splitlines():
        m = re.match(r"^\s*([a-z_]+)\s*:\s*$", line)
        if m and m.group(1) in SECTIONS:
            cur = m.group(1)
            continue
        if cur:
            out[cur] += line + "\n"
    return {k: v.strip() for k, v in out.items()}


def validate(prompt: str) -> dict:
    """All six sections present and non-empty, English (Latin/ASCII), tags sane."""
    secs = parse_sections(prompt)
    missing = [s for s in SECTIONS if not secs.get(s)]
    bad_lang = []
    for s in SECTIONS:
        txt = secs.get(s, "")
        if txt and not _is_english(txt):
            bad_lang.append(s)
    tags = re.findall(r"<(?:Picture|Video|Audio|Subject)\s+\d+>", prompt or "")
    bad_ret = []
    for line in (secs.get("retention_analysis", "") or "").splitlines():
        if ":" in line and "-" in line:
            word = line.split(":", 1)[1].split("-", 1)[0].strip()
            if word and word not in VISUAL_RETENTION + AUDIO_RETENTION:
                bad_ret.append(word)
    return {
        "ok": not missing and not bad_lang,
        "missing": missing,
        "non_english_sections": bad_lang,
        "reference_tags": tags,
        "unknown_retention_words": bad_ret,
    }


def _is_english(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return True
    latin = sum(1 for c in letters if ord(c) < 0x250)
    return (latin / len(letters)) >= 0.9


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "validate":
        print(json.dumps(validate(sys.stdin.read()), indent=2))
    else:
        p = compile_prompt(
            subject_definitions="<Subject 1>: a woman in a blue coat and a silver necklace.",
            summary="<Subject 1> walks through a rainy neon street.",
            retention_analysis="\n".join([
                retention_line(subj(1), "(appears in [Shot 1])", "fully_preserved",
                               "preserve facial identity, blue coat, and silver necklace."),
                retention_line(vid(1), "(camera and pacing)", "weak_reference",
                               "follow the broad tracking direction and beat timing."),
                retention_line(aud(1), "", "reference",
                               "follow the voice timbre without copying the source.", audio=True),
            ]),
            detailed_description="Shot 1: " + camera_phrase("Tracking Shot", "moderate", "slow"),
            overall_soundscape="Rain on pavement; distant traffic.",
            non_diegetic_music="Low ambient synth pad.",
        )
        print(p)
        print(json.dumps(validate(p), indent=2))
