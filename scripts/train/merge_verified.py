#!/usr/bin/env python3
"""Merge every verified distill row into one deduped unified dataset.

Gathers data/verified/**/*.jsonl (chunk lands, shards, merged tags),
normalises the prompt text, drops exact duplicate prompts, and writes
data/verified/unified.jsonl — the single training set for the unified Urai
student. Stdlib only; safe to run in CI (writes are small and deterministic).
"""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VDIR = ROOT / "data" / "verified"
OUT = VDIR / "unified.jsonl"


def prompt_of(r: dict) -> str:
    task = r.get("task", r.get("prompt", ""))
    if isinstance(task, dict):
        return task.get("prompt", "") or ""
    return str(task or "")


def merge(out: Path = OUT) -> int:
    seen, kept = set(), []
    files = sorted(VDIR.rglob("*.jsonl"))
    for f in files:
        if f.name == "unified.jsonl":
            continue
        try:
            lines = f.read_text().splitlines()
        except Exception:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            p = prompt_of(r).strip()
            if not p or not r.get("completion"):
                continue
            h = hashlib.sha1(p.encode()).hexdigest()
            if h in seen:
                continue
            seen.add(h)
            kept.append(r)
    out.write_text("".join(json.dumps(r) + "\n" for r in kept))
    print(f"unified: {len(kept)} rows from {len(files)} files -> {out}")
    return len(kept)


if __name__ == "__main__":
    merge()
