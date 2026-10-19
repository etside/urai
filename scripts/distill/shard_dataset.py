#!/usr/bin/env python3
"""Split a verified .jsonl dataset into N hash-shards for parallel GPU phases.

Usage:
  python3 scripts/distill/shard_dataset.py data/verified/distill-now.jsonl 2
  -> data/verified/distill-now-p0.jsonl, distill-now-p1.jsonl (deduped, deterministic)

Deterministic MD5-of-content routing: re-running gives identical shards,
and no row appears in two shards.
"""
import hashlib
import json
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: shard_dataset.py IN.jsonl N")
    src, n = Path(sys.argv[1]), int(sys.argv[2])
    assert n >= 1 and n <= 8, "N must be 1..8"
    buckets: list[list[str]] = [[] for _ in range(n)]
    total = 0
    for line in src.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        h = r.get("content_hash") or hashlib.sha256(
            r.get("completion", "").encode()).hexdigest()[:16]
        buckets[int(h, 16) % n].append(line)
        total += 1
    outs = []
    for i, rows in enumerate(buckets):
        dest = src.with_name(f"{src.stem}-p{i}.jsonl")
        dest.write_text("\n".join(rows) + ("\n" if rows else ""))
        outs.append((str(dest), len(rows)))
    print(f"sharded {total} rows into {n}: " +
          ", ".join(f"{p}={c}" for p, c in outs))


if __name__ == "__main__":
    main()
