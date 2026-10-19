#!/usr/bin/env python3
"""Few-shot memory: verified completions promoted from landed distill chunks.

`data/prompts/fewshots.jsonl` rows: {h, kind, task, answer, score}.
`best_for(task, kinds, limit)` returns top matches by keyword overlap so the
agent can show 1-3 solved examples before answering — the mechanism by which
each landed chunk immediately improves Urai without retraining.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEW = ROOT / "data" / "prompts" / "fewshots.jsonl"
MAX_CHARS = 1500


def _load():
    if not FEW.is_file():
        return []
    out = []
    for line in FEW.read_text().splitlines():
        try:
            d = json.loads(line)
            if d.get("task") and d.get("answer"):
                out.append(d)
        except Exception:
            continue
    return out


def best_for(task: str, kinds=None, limit: int = 2) -> list:
    rows = _load()
    if not rows:
        return []
    if kinds:
        kinds = set(kinds)
        rows = [r for r in rows if not r.get("kind") or r["kind"] in kinds
                or True]
    words = set(re.findall(r"[a-z]{3,}", (task or "").lower()))
    scored = []
    for r in rows:
        hay = ((r.get("task") or "") + " " + (r.get("kind") or "")).lower()
        s = sum(1 for w in words if w in hay) + float(r.get("score", 0))
        if s > 0:
            scored.append((s, r))
    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:limit]]


def context_block(task: str, limit: int = 2) -> str:
    rows = best_for(task, limit=limit)
    if not rows:
        return ""
    parts = []
    for r in rows:
        parts.append(f"Example (solved, score {r.get('score', '?')}):\n"
                     f"Q: {r['task'][:300]}\nA: {r['answer'][:800]}")
    block = "Solved examples to follow:\n\n" + "\n\n".join(parts)
    return block[:MAX_CHARS]
