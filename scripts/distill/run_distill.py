#!/usr/bin/env python3
"""Distillation pipeline prototype (Phase 2, offline-capable):

  RAW TASKS (.jsonl) -> teacher.generate -> verifier.verify
      -> filter (threshold + dedup) -> structured dataset (.jsonl)

Runs with MockTeacher by default (no keys). Set TEACHER_* env vars to use a
real OpenAI-compatible teacher. Every kept record carries score, failures,
content hash and pipeline version for reproducibility.

Usage:
    python3 scripts/distill/run_distill.py \
        --tasks data/raw_tasks/sample_tasks.jsonl \
        --out data/verified/distill-v0.1.jsonl
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from teacher_client import get_teacher, SYSTEMS
from verifier import verify
from filter import build_record, filter_batch
from judge import judge


def score_completion(task, out, exec_python=False, use_judge=False, teacher=None):
    verdict = verify(out.content, exec_python=exec_python)
    # Judge is a SECOND signal only for text-only (neutral 0.5) completions.
    if use_judge and verdict["checks"] == 0 and verdict["score"] == 0.5:
        j = judge(task, out.content, teacher)
        verdict["judge"] = j
        verdict["score"] = j["score"]
    return verdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threshold", type=float, default=0.8)
    ap.add_argument("--report", default=None)
    ap.add_argument("--exec", dest="exec_python", action="store_true",
                    help="execute python blocks (timeout-guarded), not just compile")
    ap.add_argument("--judge", action="store_true",
                    help="LLM-judge second signal for text-only tasks")
    ap.add_argument("--system", default="default",
                    choices=sorted(SYSTEMS),
                    help="teacher system prompt (reasoning = R1-style think traces)")
    args = ap.parse_args()

    teacher = get_teacher()
    print(f"teacher: {teacher.name} (system: {args.system})")

    scored = []
    import glob as _glob
    task_files = sorted(_glob.glob(str(Path(args.tasks) / "*.jsonl"))) \
        if Path(args.tasks).is_dir() else [args.tasks]
    for tf in task_files:
        with open(tf) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                task = json.loads(line)
                if args.system != "default":
                    task["system"] = SYSTEMS[args.system]
                out = teacher.generate(task)
                verdict = score_completion(task, out, exec_python=args.exec_python,
                                           use_judge=args.judge, teacher=teacher)
                scored.append({"record": build_record(task, out, verdict),
                               "verdict": verdict})

    result = filter_batch(scored, args.threshold)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        for item in result["kept"]:
            f.write(json.dumps(item["record"], ensure_ascii=False) + "\n")

    summary = {
        "teacher": teacher.name,
        "total": len(scored),
        "kept": len(result["kept"]),
        "rejected": len(result["rejected"]),
        "dupes": len(result["dupes"]),
        "reject_reasons": {},
    }
    for item in result["rejected"]:
        for tag in item["verdict"]["failures"] or ["score-below-threshold"]:
            summary["reject_reasons"][tag] = summary["reject_reasons"].get(tag, 0) + 1
    print(json.dumps(summary, indent=2))
    if args.report:
        Path(args.report).write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    sys.exit(main())
