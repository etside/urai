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


def match(task: str, limit: int = MAX_SKILLS) -> list:
    """Score skills by keyword overlap with the task. Returns top matches."""
    words = set(re.findall(r"[a-z]{3,}", task.lower()))
    scored = []
    for s in all_skills():
        hay = (s["name"] + " " + s["description"]).lower()
        score = sum(1 for w in words if w in hay)
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
