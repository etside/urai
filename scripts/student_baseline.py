#!/usr/bin/env python3
"""Student baseline: generate with a local GGUF + verify, record the 'before'.

This is the scoreboard every future student must beat. Runs fully offline.

    python3 scripts/student_baseline.py --model coder05-fast --n 10
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "distill"))
sys.path.insert(0, str(ROOT / "jev"))
from verifier import verify


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="coder05-fast")
    ap.add_argument("--tasks", default="data/raw_tasks/sample_tasks.jsonl")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--out", default=None)
    ap.add_argument("--temp", type=float, default=0.1)
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT))
    from jev import models_registry as reg
    m = reg.load()["models"][args.model]
    gguf = str(ROOT / m["path"])
    lib = ROOT / "third_party" / "llama.cpp" / "build" / "bin"
    cli = lib / "llama-cli"
    if not cli.exists():
        raise SystemExit(f"runner missing: {cli}")
    import os
    env = dict(os.environ, LD_LIBRARY_PATH=str(lib))

    tasks = [json.loads(l) for l in open(args.tasks) if l.strip()][:args.n]
    print(f"probing {len(tasks)} tasks with {args.model}", flush=True)
    res = []
    for t in tasks:
        p = subprocess.run(
            [str(cli), "-m", gguf, "-t", "2", "-c", "1024", "-n", "120",
             "--temp", str(args.temp),
             "-p", t["prompt"] + " Output only code."],
            capture_output=True, text=True, timeout=600, env=env)
        mobj = re.search(r"```python\n(.*)", p.stdout, re.DOTALL)
        code = ("```python\n" + mobj.group(1).split("```")[0] + "```"
                if mobj else p.stdout[-1500:])
        v = verify(code, exec_python=True)
        res.append({"id": t.get("id"), "score": v["score"],
                    "passed": v["passed"], "checks": v["checks"],
                    "failures": [str(x)[:100] for x in v["failures"]]})
        print(f"{t.get('id')} -> {v['score']} ({v['passed']}/{v['checks']})",
              flush=True)
    out = args.out or f"eval/reports/student-baseline-{args.model}.json"
    json.dump({"model": args.model, "n": len(res),
               "mean_score": sum(r["score"] for r in res) / max(1, len(res)),
               "results": res}, open(out, "w"), indent=1)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
