#!/usr/bin/env python3
"""Merge verified distill outputs with global dedup.

Usage:
  python3 scripts/distill/merge_parallel.py data/verified/distill-now.jsonl \
      data/verified/distill-now-a.jsonl data/verified/distill-now-b.jsonl
"""
import hashlib
import json
import re
import sys
from pathlib import Path


def normalize(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def content_hash(text):
    return hashlib.sha256(normalize(text).encode()).hexdigest()[:16]


def main():
    if len(sys.argv) < 3:
        raise SystemExit("usage: merge_parallel.py OUT IN [IN ...]")
    out = Path(sys.argv[1])
    seen, kept = set(), []
    for src in sys.argv[2:]:
        p = Path(src)
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            h = r.get("content_hash") or content_hash(r.get("completion", ""))
            if h in seen:
                continue
            seen.add(h)
            kept.append(line)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(kept) + ("\n" if kept else ""))
    print(f"merged {len(kept)} unique rows -> {out}")


if __name__ == "__main__":
    main()
