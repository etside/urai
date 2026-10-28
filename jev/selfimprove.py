#!/usr/bin/env python3
"""Urai self-improvement loop — Overmind-style traces→datasets→evals, safely.

What it borrows from overmind-core/overmind (ideas, own stdlib code):
  traces in  -> probe runs + failure records (PII-scrubbed, no secrets)
  datasets   -> failures become new distill/bench tasks (data-only output)
  eval gate  -> regression check vs previous bench reports (advisory, never blocks)

What it deliberately does NOT do (safety):
  * never modifies serving code (jev/*.py) — output is data + reports only
  * never auto-deploys, never restarts services, never touches credentials
  * never persists PII (previews scrubbed) or secret values

Run:
  python3 jev/selfimprove.py --base http://127.0.0.1:8777 --tag weekly
  => data/raw_tasks/selfimprove/<tag>.jsonl  (new training tasks)
     eval/reports/selfimprove-<tag>.json     (summary + regression note)

Scheduled via .github/workflows/urai-selfimprove.yml (weekly + dispatch).
"""

import argparse
import hashlib
import json
import re
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK_DIR = ROOT / "data" / "raw_tasks" / "selfimprove"
REPORTS = ROOT / "eval" / "reports"

PROBES = [
    ("knowledge", "What is the capital of Nepal?", ["kathmandu"]),
    ("knowledge", "How many sides does a hexagon have?", ["6", "six"]),
    ("knowledge", "What planet is closest to the sun?", ["mercury"]),
    ("knowledge", "What does RAM stand for?", ["random access memory"]),
    ("math", "What is 25 * 4? Reply with just the number.", "100"),
    ("math", "A box holds 24 eggs. How many in 5 boxes? Reply with just the number.", "120"),
    ("math", "What is 81 / 9? Reply with just the number.", "9"),
    ("math", "What is 13 squared? Reply with just the number.", "169"),
    ("code", "Write a Python function named solve(s) that returns s reversed. Reply with only a ```python fenced code block, no explanation.",
     "assert solve('abc') == 'cba'\nassert solve('') == ''\n"),
    ("code", "Write a Python function named solve(lst) that returns the largest number in lst. Reply with only a ```python fenced code block, no explanation.",
     "assert solve([1, 9, 3]) == 9\nassert solve([-5, -1]) == -1\n"),
]

PII_RES = [r"\d{3}-\d{2}-\d{4}", r"[\w\.-]+@[\w\.-]+\.\w+", r"\+?1?\d{9,15}"]


def scrub(s):
    s = str(s or "")
    for p in PII_RES:
        s = re.sub(p, "[REDACTED]", s)
    return s[:300]


def chat(base, text, key, device, max_tokens=96, temperature=0.2):
    t0 = time.time()
    req = urllib.request.Request(
        base + "/v1/chat/completions", json.dumps(
            {"model": "jev-local-student",
             "messages": [{"role": "user", "content": text}],
             "max_tokens": max_tokens, "temperature": temperature,
             "device_id": device}).encode(),
        {"Content-Type": "application/json",
         "Authorization": "Bearer " + key, "X-Device-Id": device})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.load(r)
    return d["choices"][0]["message"]["content"], round(time.time() - t0, 2)


def classify(kind, expected, answer, code_ok=None):
    a = (answer or "").lower()
    if kind == "knowledge":
        exp = [expected] if isinstance(expected, str) else expected
        if any(e.lower() in a for e in exp):
            return None
        if "error" in a[:20] or len(a.strip()) < 2:
            return "tool"
        return "knowledge"
    if kind == "math":
        m = re.findall(r"-?\d+(?:\.\d+)?", answer or "")
        try:
            if m and float(m[-1]) == float(expected):
                return None
        except (TypeError, ValueError):
            pass
        return "reasoning"
    if code_ok:
        return None
    if "def solve" not in (answer or ""):
        return "instruction"
    return "coding"


def run_code_candidate(code_text, tests, timeout=20):
    import subprocess
    import sys
    import tempfile
    m = re.search(r"```(?:python)?\s*(.*?)```", code_text or "", re.DOTALL)
    src = (m.group(1) if m else code_text or "").strip()
    if "def solve" not in src:
        return False
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(src + "\n" + tests + "\nprint('SI-OK')\n")
        path = f.name
    try:
        p = subprocess.run([sys.executable, path], capture_output=True,
                           text=True, timeout=timeout)
        return p.returncode == 0 and "SI-OK" in p.stdout
    except Exception:
        return False
    finally:
        try:
            Path(path).unlink()
        except Exception:
            pass


def known_tasks():
    seen = set()
    for base in (ROOT / "data" / "raw_tasks", ROOT / "data" / "verified"):
        if not base.is_dir():
            continue
        for f in base.rglob("*.jsonl"):
            try:
                for line in f.read_text().splitlines():
                    try:
                        t = json.loads(line).get("task") or json.loads(line).get("prompt", "")
                    except Exception:
                        t = ""
                    if t:
                        seen.add(hashlib.md5(t.encode()).hexdigest())
            except Exception:
                continue
    return seen


def latest_bench():
    reps = sorted(REPORTS.glob("bench-*.json"))
    out = []
    for fp in reps[-2:]:
        try:
            d = json.loads(fp.read_text())
            out.append({"file": fp.name,
                        "acc": {k: v.get("accuracy") for k, v in d.get("categories", {}).items()}})
        except Exception:
            continue
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8777")
    ap.add_argument("--tag", default="weekly")
    ap.add_argument("--key", default="")
    args = ap.parse_args()
    import os
    key = args.key or os.environ.get("URAI_MASTER_KEY", "")
    if not key:
        raise SystemExit("URAI_MASTER_KEY (or --key) required")
    device = f"selfimprove-{args.tag}"
    seen = known_tasks()
    summary = {"tag": args.tag, "probes": len(PROBES), "passed": 0,
               "failed": 0, "by_kind": {}, "tasks_written": 0, "calls": 0}
    new_tasks = []
    for kind, prompt, expected in PROBES:
        try:
            txt, dt = chat(args.base, prompt, key, device,
                           256 if kind == "code" else 64)
            summary["calls"] += 1
        except Exception as e:
            txt = f"ERROR: {e}"[:200]
        code_ok = run_code_candidate(txt, expected) if kind == "code" else None
        fail = classify(kind, expected, txt, code_ok)
        if fail is None:
            summary["passed"] += 1
            print(f"PASS {kind}: {prompt[:50]!r}", flush=True)
            continue
        summary["failed"] += 1
        summary["by_kind"][fail] = summary["by_kind"].get(fail, 0) + 1
        h = hashlib.md5(prompt.encode()).hexdigest()
        if h not in seen and len(new_tasks) < 25:
            seen.add(h)
            new_tasks.append({"task": prompt,
                              "expected": expected if kind != "code" else None,
                              "tests": expected if kind == "code" else None,
                              "kind": f"selfimprove-{kind}",
                              "failure_kind": fail,
                              "answer_preview": scrub(txt)[:200],
                              "source": f"probe:{args.tag}"})
        print(f"FAIL({fail}) {kind}: {prompt[:50]!r}", flush=True)

    TASK_DIR.mkdir(parents=True, exist_ok=True)
    if new_tasks:
        with open(TASK_DIR / f"{args.tag}.jsonl", "w") as f:
            for t in new_tasks:
                f.write(json.dumps(t) + "\n")
    summary["tasks_written"] = len(new_tasks)

    # advisory regression gate: compare last two bench reports, never fails
    benches = latest_bench()
    summary["bench_window"] = benches
    summary["regression"] = None
    if len(benches) == 2:
        notes = []
        for cat in ("knowledge", "math", "code"):
            a, b = benches[0]["acc"].get(cat), benches[1]["acc"].get(cat)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b < a:
                notes.append(f"{cat}: {a} -> {b} (REGRESSED)")
        summary["regression"] = notes or ["no regression detected"]
    summary["safety"] = ("data-only output; no serving-code changes, no deploys, "
                         "no credential storage, previews PII-scrubbed")

    REPORTS.mkdir(parents=True, exist_ok=True)
    fp = REPORTS / f"selfimprove-{args.tag}.json"
    fp.write_text(json.dumps(summary, indent=2))
    print(f"\nSELFIMPROVE {args.tag}: passed={summary['passed']} failed={summary['failed']} "
          f"tasks={summary['tasks_written']} regression={summary['regression']}")
    print(f"report: {fp}")


if __name__ == "__main__":
    main()
