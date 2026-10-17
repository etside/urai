#!/usr/bin/env python3
"""Skills: markdown capability packs loaded into agent context.

Format (Anthropic Agent Skills compatible):
    skills/<name>/SKILL.md      # frontmatter: name:, description:, then body
    skills/<name>/LICENSE.txt   # keep upstream attribution

Matching: task keywords vs skill name+description (stdlib scoring).
Agent includes top matches (char-capped) in context. `urai skill list`
shows all. Urai can write its own skills too (see skill-creator).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills"
MAX_SKILL_CHARS = 6000
MAX_SKILLS = 2


def _parse(path: Path) -> dict:
    text = path.read_text()
    meta, body = {}, text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            front = text[3:end]
            body = text[end + 4:].strip()
            for line in front.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip()
    return {"name": meta.get("name") or path.parent.name,
            "description": meta.get("description", ""),
            "body": body, "path": str(path)}


def all_skills() -> list:
    out = []
    if not SKILL_DIR.is_dir():
        return out
    for p in sorted(SKILL_DIR.glob("*/SKILL.md")):
        try:
            out.append(_parse(p))
        except Exception:
            continue
    return out


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").strip().lower()).strip("-")
    return s


def add_skill(name: str, description: str = "", body: str = "") -> dict:
    """Scaffold a new skill at skills/<slug>/SKILL.md. Raises ValueError on a
    bad or already-existing name."""
    slug = _slug(name)
    if not slug:
        raise ValueError("invalid skill name; use letters, digits, dashes")
    path = SKILL_DIR / slug / "SKILL.md"
    if path.exists():
        raise ValueError(f"skill already exists: {slug}")
    desc = description.strip() or f"{slug} capability pack"
    text = (f"---\nname: {slug}\ndescription: {desc}\n---\n\n"
            + (body.strip() or
               f"# {slug}\n\nDescribe when to use this skill and the exact "
               "steps Urai should follow.\n"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return {"name": slug, "description": desc, "path": str(path)}


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) - len(suf) >= 3 and w.endswith(suf):
            return w[:-len(suf)]
    return w


def _related(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4:
        n = 0
        for x, y in zip(a, b):
            if x != y:
                break
            n += 1
        if n >= 5:  # secur-ity/secure, cod-e/coding
            return True
    return False


def match(task: str, limit: int = MAX_SKILLS) -> list:
    """Score skills by keyword overlap: substring hit (1pt) or stem/prefix
    relation (1pt). Keeps old substring behavior, adds word-variant recall."""
    words = set(re.findall(r"[a-z]{3,}", task.lower()))
    scored = []
    for s in all_skills():
        hay = (s["name"] + " " + s["description"]).lower()
        hay_words = set(re.findall(r"[a-z]{3,}", hay))
        hay_stems = {_stem(w) for w in hay_words}
        score = 0
        name = s["name"].lower()
        for w in words:
            if w in name:
                score += 2  # name hit = strong signal
            elif w in hay:
                score += 1
            elif _stem(w) in hay_stems:
                score += 1
            elif any(_related(w, h) for h in hay_words):
                score += 1
        if score > 0:
            scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:limit]]


def context_block(task: str) -> str:
    """Rendered block for the agent prompt (empty when nothing matches)."""
    parts = []
    for s in match(task):
        parts.append(f"## Skill: {s['name']}\n{s['body'][:MAX_SKILL_CHARS]}")
    return "\n\n".join(parts)
