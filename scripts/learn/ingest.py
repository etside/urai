#!/usr/bin/env python3
"""Learn from the internet: URLs -> distill-ready tasks.

Fetches pages (keyless), splits them into study chunks, and writes
tasks shaped for the distill pipeline (prompt + reference), e.g.:

    python3 scripts/learn/ingest.py --topic qwen3-lora \\
        --urls urls.txt --out data/raw_tasks/learned/qwen3-lora.jsonl
    python3 scripts/distill/run_distill.py --tasks data/raw_tasks/learned/qwen3-lora.jsonl \\
        --out data/verified/learn-qwen3-lora.jsonl

URLs can come from `urai agent` (web_search), OpenClaw research runs, or
hand-picked lists. Dedupes by content hash against previous ingests.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "jev"))
from tools import web_fetch

CHUNK = 1500


def chunks(text: str):
    parts, cur = [], ""
    for para in re.split(r"\n+", text):
        para = para.strip()
        if not para:
            continue
        if len(cur) + len(para) > CHUNK and cur:
            parts.append(cur)
            cur = para
        else:
            cur = (cur + "\n" + para).strip()
    if cur.strip():
        parts.append(cur)
    return [p for p in parts if len(p) > 200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--urls", required=True,
                    help="file with one URL per line (# comments ok)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-pages", type=int, default=20)
    args = ap.parse_args()

    urls = [ln.strip() for ln in open(args.urls)
            if ln.strip() and not ln.startswith("#")][:args.max_pages]
    seen_hashes = set()
    for old in Path("data/raw_tasks/learned").glob("*.jsonl"):
        for line in open(old):
            try:
                seen_hashes.add(json.loads(line).get("content_hash", ""))
            except Exception:
                pass

    made, skipped = 0, 0
    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    with open(outp, "w") as f:
        for i, url in enumerate(urls):
            r = web_fetch(url)
            if not r["ok"]:
                print(f"SKIP {url}: {r['error'][:80]}")
                continue
            for j, ch in enumerate(chunks(r["output"])):
                h = hashlib.sha256(ch.encode()).hexdigest()[:16]
                if h in seen_hashes:
                    skipped += 1
                    continue
                seen_hashes.add(h)
                f.write(json.dumps({
                    "id": f"learn-{args.topic}-{i:03d}-{j:02d}",
                    "category": f"learn-{args.topic}",
                    "prompt": ("Study note — read, remember, and be ready "
                               "to answer questions:\n" + ch),
                    "reference_good": ch,
                    "content_hash": h,
                    "source": url,
                }, ensure_ascii=False) + "\n")
                made += 1
    print(f"ingested {made} chunks ({skipped} dupes) -> {outp}")


if __name__ == "__main__":
    main()
