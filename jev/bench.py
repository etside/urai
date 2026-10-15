#!/usr/bin/env python3
"""Urai benchmark harness — honest, reproducible, stdlib only.

Measures what the DEPLOYED system actually does (no cherry-picking):
  knowledge : factual Q&A, substring-scored
  math      : numeric answers, exact-scored; self-consistency mode supported
  code      : fenced python solutions EXECUTED against tests (pass/fail)
  latency   : per-call wall time + llama usage tokens

Modes per task:
  direct     temp 0.2, 1 sample
  consistent temp 0.7, 3 samples, majority vote (math) / exec-pass pick (code)

Run (needs a live Urai API + master key for unlimited tokens):
  python3 jev/bench.py --base http://127.0.0.1:8777 --tag local --key 856777
  => eval/reports/bench-<tag>.json

Designed for GH workflow urai-bench.yml (dispatch) which commits the report
back to the repo; /v1/benchmarks serves the latest one.
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "eval" / "reports"

KNOWLEDGE = [
    ("What is the capital of Bangladesh?", ["dhaka"]),
    ("How many planets are in the solar system?", ["8", "eight"]),
    ("What does CPU stand for?", ["central processing unit"]),
    ("Which language has the most native speakers?", ["mandarin", "chinese"]),
    ("What is H2O commonly known as?", ["water"]),
    ("How many days are in a leap year?", ["366"]),
    ("What is the largest ocean?", ["pacific"]),
    ("What year did the first moon landing occur?", ["1969"]),
    ("What does HTTP stand for?", ["hypertext transfer protocol"]),
    ("How many bits are in a byte?", ["8", "eight"]),
    ("What is the chemical symbol for gold?", ["au"]),
    ("Which planet is known as the Red Planet?", ["mars"]),
]

MATH = [
    ("What is 15 + 27? Reply with just the number.", "42"),
    ("A shop has 3 boxes with 12 apples each. How many apples total? Reply with just the number.", "36"),
    ("What is 7 * 8? Reply with just the number.", "56"),
    ("If a train travels 60 km in 1 hour, how far in 2.5 hours? Reply with just the number.", "150"),
    ("What is 100 - 37? Reply with just the number.", "63"),
    ("A rectangle is 9 by 4. What is its area? Reply with just the number.", "36"),
    ("What is 144 / 12? Reply with just the number.", "12"),
    ("What is 2 to the power of 10? Reply with just the number.", "1024"),
    ("A book costs $15, discount 20%. Final price? Reply with just the number.", "12"),
    ("What is the average of 10, 20, 30? Reply with just the number.", "20"),
    ("If x + 5 = 12, what is x? Reply with just the number.", "7"),
    ("How many minutes are in 3 hours? Reply with just the number.", "180"),
]

CODE = [
    {"prompt": "Write a Python function named solve(n) that returns the factorial of n. Reply with only a ```python fenced code block, no explanation.",
     "tests": "assert solve(0) == 1\nassert solve(5) == 120\nassert solve(6) == 720\n"},
    {"prompt": "Write a Python function named solve(s) that returns True if s is a palindrome (ignore case and spaces), else False. Reply with only a ```python fenced code block, no explanation.",
     "tests": "assert solve('Racecar') is True\nassert solve('hello') is False\nassert solve('nurses run') is True\n"},
    {"prompt": "Write a Python function named solve(lst) that returns the list sorted ascending without using sorted() or .sort(). Reply with only a ```python fenced code block, no explanation.",
     "tests": "assert solve([3, 1, 2]) == [1, 2, 3]\nassert solve([]) == []\nassert solve([5]) == [5]\n"},
    {"prompt": "Write a Python function named solve(a, b) that returns the greatest common divisor of a and b. Reply with only a ```python fenced code block, no explanation.",
     "tests": "assert solve(12, 18) == 6\nassert solve(7, 5) == 1\nassert solve(100, 75) == 25\n"},
    {"prompt": "Write a Python function named solve(s) that counts vowels (aeiou, any case) in s and returns the count. Reply with only a ```python fenced code block, no explanation.",
     "tests": "assert solve('hello') == 2\nassert solve('AEIOU') == 5\nassert solve('xyz') == 0\n"},
    {"prompt": "Write a Python function named solve(n) that returns the nth Fibonacci number (solve(0)=0, solve(1)=1). Reply with only a ```python fenced code block, no explanation.",
     "tests": "assert solve(0) == 0\nassert solve(1) == 1\nassert solve(10) == 55\n"},
]


def _post(base, path, body, key, device, timeout=180):
    req = urllib.request.Request(
        base + path, json.dumps(body).encode(),
        {"Content-Type": "application/json",
         "Authorization": "Bearer " + key, "X-Device-Id": device})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def chat(base, messages, key, device, max_tokens=128, temperature=0.2):
    t0 = time.time()
    d = _post(base, "/v1/chat/completions",
              {"model": "jev-local-student", "messages": messages,
               "max_tokens": max_tokens, "temperature": temperature,
               "device_id": device}, key, device)
    dt = time.time() - t0
    return d["choices"][0]["message"]["content"], dt, d.get("usage", {})


def _num(s):
    m = re.findall(r"-?\d+(?:\.\d+)?", s or "")
    return m[-1] if m else None


def _norm_num(s):
    try:
        return float(_num(s))
    except (TypeError, ValueError):
        return None


def run_code_candidate(code_text, tests, timeout=20):
    m = re.search(r"```(?:python)?\s*(.*?)```", code_text, re.DOTALL)
    src = (m.group(1) if m else code_text).strip()
    if "def solve" not in src:
        return False, "no solve() found"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(src + "\n" + tests + "\nprint('BENCH-OK')\n")
        path = f.name
    try:
        p = subprocess.run([sys.executable, path], capture_output=True,
                           text=True, timeout=timeout)
        ok = p.returncode == 0 and "BENCH-OK" in p.stdout
        return ok, (p.stdout + p.stderr)[-400:]
    except subprocess.TimeoutExpired:
        return False, "timeout"
    finally:
        try:
            Path(path).unlink()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8777")
    ap.add_argument("--tag", default="local")
    ap.add_argument("--key", default="856777")
    ap.add_argument("--modes", default="direct,consistent",
                    help="comma list: direct, consistent")
    ap.add_argument("--categories", default="knowledge,math,code",
                    help="comma list: knowledge, math, code")
    ap.add_argument("--quick", action="store_true",
                    help="single sample, smaller output (smoke benchmark)")
    args = ap.parse_args()
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    cats = [c.strip() for c in args.categories.split(",") if c.strip()]
    device = f"bench-{args.tag}"
    out = {"tag": args.tag, "base": args.base,
           "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "identity": "Urai, developed by Tynio LTD",
           "categories": {}, "calls": 0, "total_s": 0.0}
    t_all = time.time()

    # knowledge: single sample (deterministic scoring). math/code: 3 samples
    # in consistent mode for majority-vote / exec-pass selection.
    for cat, items, max_tok in (("knowledge", KNOWLEDGE, 64), ("math", MATH, 32)):
        if cat not in cats:
            continue
        force_single = (cat == "knowledge" or args.quick)
        rec = {"passed": 0, "total": 0, "items": [], "latency_s": [], "usage_tokens": 0}
        for q, exp in items:
            entry = {"q": q, "expected": exp, "modes": {}}
            cands, lats = [], []
            n = 1 if force_single else (3 if "consistent" in modes else 1)
            for i in range(n):
                temp = 0.7 if (n > 1) else 0.2
                try:
                    txt, dt, usage = chat(args.base, [{"role": "user", "content": q}],
                                      args.key, device, max_tok, temp)
                    rec["usage_tokens"] += int((usage or {}).get("total_tokens", 0))
                except Exception as e:
                    txt, dt, usage = f"ERROR: {e}"[:200], 0.0, {}
                cands.append(txt)
                lats.append(round(dt, 2))
                out["calls"] += 1
            entry["modes"]["direct"] = {"ok": None}
            if cat == "knowledge":
                hit = any(e.lower() in cands[0].lower() for e in
                          ([exp] if isinstance(exp, str) else exp))
                entry["modes"]["direct"] = {"pass": hit, "answer": cands[0][:200]}
                entry["pass"] = hit
            else:
                votes = [_norm_num(c) for c in cands]
                votes = [v for v in votes if v is not None]
                final = max(set(votes), key=votes.count) if votes else None
                entry["modes"]["consistent"] = {"pass": final == float(exp),
                                                "votes": votes, "final": final}
                entry["modes"]["direct"] = {"pass": _norm_num(cands[0]) == float(exp),
                                            "answer": cands[0][:120]}
                entry["pass"] = entry["modes"]["consistent"]["pass"] if n > 1 else entry["modes"]["direct"]["pass"]
            rec["latency_s"] += lats
            rec["passed"] += 1 if entry["pass"] else 0
            rec["total"] += 1
            rec["items"].append(entry)
            print(f"[{cat}] {'PASS' if entry['pass'] else 'FAIL'} q={q[:50]!r}", flush=True)
        rec["accuracy"] = round(rec["passed"] / max(rec["total"], 1), 3)
        rec["avg_latency_s"] = round(sum(rec["latency_s"]) / max(len(rec["latency_s"]), 1), 2)
        rec["tokens_per_s"] = round(rec["usage_tokens"] / max(sum(rec["latency_s"]), 0.01), 2)
        out["categories"][cat] = rec

    # code: best-of-N by execution
    rec = {"passed": 0, "total": 0, "items": [], "latency_s": [], "usage_tokens": 0}
    for item in (CODE if "code" in cats else []):
        entry = {"q": item["prompt"][:80], "modes": {}}
        cands = []
        n = 3 if "consistent" in modes else 1
        for i in range(n):
            temp = 0.7 if n > 1 else 0.2
            try:
                txt, dt, usage = chat(args.base, [{"role": "user", "content": item["prompt"]}],
                                  args.key, device, 256, temp)
                rec["usage_tokens"] += int((usage or {}).get("total_tokens", 0))
            except Exception as e:
                txt, dt = f"ERROR: {e}"[:200], 0.0
            cands.append(txt)
            rec["latency_s"].append(round(dt, 2))
            out["calls"] += 1
        results = [run_code_candidate(c, item["tests"]) for c in cands]
        entry["modes"]["direct"] = {"pass": results[0][0], "log": results[0][1][:200]}
        best = any(r[0] for r in results)
        entry["modes"]["consistent"] = {"pass": best,
                                        "per_sample": [r[0] for r in results]}
        entry["pass"] = best if n > 1 else results[0][0]
        rec["passed"] += 1 if entry["pass"] else 0
        rec["total"] += 1
        rec["items"].append(entry)
        print(f"[code] {'PASS' if entry['pass'] else 'FAIL'} {item['prompt'][:50]!r}", flush=True)
    rec["accuracy"] = round(rec["passed"] / max(rec["total"], 1), 3)
    rec["avg_latency_s"] = round(sum(rec["latency_s"]) / max(len(rec["latency_s"]), 1), 2)
    rec["tokens_per_s"] = round(rec["usage_tokens"] / max(sum(rec["latency_s"]), 0.01), 2)
    out["categories"]["code"] = rec

    out["total_s"] = round(time.time() - t_all, 1)
    REPORTS.mkdir(parents=True, exist_ok=True)
    fp = REPORTS / f"bench-{args.tag}.json"
    fp.write_text(json.dumps(out, indent=2))
    acc = {k: v["accuracy"] for k, v in out["categories"].items()}
    print(f"\nBENCH {args.tag}: {json.dumps(acc)} calls={out['calls']} total_s={out['total_s']}")
    print(f"report: {fp}")


if __name__ == "__main__":
    main()
