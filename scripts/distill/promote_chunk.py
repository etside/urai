#!/usr/bin/env python3
"""Promote a landed distill chunk into live behavior (no training needed).

Called automatically after each grind chunk (see run_free_grind.sh hook).
What it does:
  1. reads the chunk JSONL (verified completions with scores)
  2. keeps items with score >= threshold (default 0.8) + exec-passed code
  3. appends them as few-shot examples to data/prompts/fewshots.jsonl (deduped)
  4. writes a promotion report to eval/reports/promote-<tag>-<chunk>.json

The agent loads these few-shots at runtime (jev/fewshots.py), so every landed
chunk IMMEDIATELY improves answers — step 1 of independence from Qwen:
behavior first distills into prompts, later into weights (see docs/INDEPENDENCE.md).

Safe: data-only, never touches serving code, never fails the grind (|| true).
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FEW = ROOT / "data" / "prompts" / "fewshots.jsonl"
REPORTS = ROOT / "eval" / "reports"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunk", required=True, help="chunk .jsonl path")
    ap.add_argument("--tag", default="now")
    ap.add_argument("--threshold", type=float, default=0.8)
    args = ap.parse_args()

    FEW.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    if FEW.is_file():
        for line in FEW.read_text().splitlines():
            try:
                seen.add(json.loads(line).get("h", ""))
            except Exception:
                continue
    kept, scanned = 0, 0
    try:
        lines = Path(args.chunk).read_text().splitlines()
    except Exception as e:
        print(f"PROMOTE-SKIP: cannot read chunk: {e}")
        return 0
    with open(FEW, "a") as out:
        for line in lines:
            line = line.strip()
            if not line:
                continue
            scanned += 1
            try:
                r = json.loads(line)
            except Exception:
                continue
            score = float(r.get("score", 0) or 0)
            completion = r.get("completion", "") or ""
            task = r.get("task", "") or r.get("prompt", "")
            if score < args.threshold or not task or not completion:
                continue
            h = hashlib.md5((task + completion[:200]).encode()).hexdigest()
            if h in seen:
                continue
            seen.add(h)
            out.write(json.dumps({"h": h, "kind": r.get("kind", ""),
                                  "task": task[:500],
                                  "answer": completion[:1500],
                                  "score": score}) + "\n")
            kept += 1
    name = Path(args.chunk).stem
    REPORTS.mkdir(parents=True, exist_ok=True)
    rep = {"tag": args.tag, "chunk": name, "scanned": scanned,
           "promoted": kept, "threshold": args.threshold,
           "fewshots_total": len(seen)}
    (REPORTS / f"promote-{args.tag}-{name}.json").write_text(json.dumps(rep, indent=2))
    print(f"PROMOTED {kept}/{scanned} from {name} (fewshots now {len(seen)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
