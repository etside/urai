#!/usr/bin/env python3
"""Urai self-improvement pipeline — end-to-end wiring (stdlib only).

Runs the full loop in one call:
  1. selfimprove  probe live API → mine failures → data/raw_tasks/selfimprove/<tag>.jsonl
  2. distill      raw tasks → verified dataset → data/verified/<tag>.jsonl
  3. (optional)   LoRA train — skipped if no GPU; logs skip clearly
  4. bench        run benchmark on live API → eval/reports/bench-<tag>.json
  5. promote      compare to prev bench → update registry if no regression
  6. s3_backup    sync data/ + eval/ to S3 (always, even if earlier steps fail)

Each step is guarded: failure of one step is logged and skipped, pipeline
continues. No step modifies serving code or restarts services.

Usage (GitHub Actions / cron / manual):
    python3 scripts/train_pipeline.py \\
        --base http://127.0.0.1:8777 \\
        --tag weekly-2026-10-27 \\
        --key $URAI_MASTER_KEY

Env vars (all optional):
    URAI_MASTER_KEY      required for selfimprove + bench
    TEACHER_BASE_URL     teacher API for distill (default: mock)
    TEACHER_API_KEY      teacher API key
    TEACHER_MODEL        teacher model id
    URAI_ALLOW_CPU_TRAIN train on CPU (demo-grade, slow)
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "eval" / "reports"


def log(step: str, msg: str, ok: bool = True):
    icon = "✓" if ok else "✗"
    print(f"{icon} [{step}] {msg}", flush=True)


def run_step(name: str, cmd: list[str], env: dict | None = None) -> tuple[bool, str]:
    """Run a subprocess step. Returns (ok, output)."""
    print(f"\n── {name} ──", flush=True)
    e = dict(os.environ)
    if env:
        e.update(env)
    try:
        r = subprocess.run(cmd, capture_output=False, text=True,
                           env=e, cwd=str(ROOT), timeout=1800)
        ok = r.returncode == 0
        log(name, "done" if ok else f"exit {r.returncode}", ok)
        return ok, ""
    except subprocess.TimeoutExpired:
        log(name, "TIMEOUT (1800s)", False)
        return False, "timeout"
    except Exception as e:
        log(name, f"ERROR: {e}", False)
        return False, str(e)


def gpu_available() -> bool:
    try:
        r = subprocess.run(["nvidia-smi"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def s3_backup():
    try:
        sys.path.insert(0, str(ROOT))
        from jev.aws import s3_backup_data, available as aws_ok
        if aws_ok():
            r = s3_backup_data()
            log("s3_backup", "ok" if r["ok"] else r.get("detail", "failed"), r["ok"])
            # Also sync eval reports
            subprocess.run(["aws", "s3", "sync",
                            str(REPORTS),
                            "s3://urai-data-089737991855-ap-south-1/eval/",
                            "--region", "ap-south-1"],
                           capture_output=True, timeout=120)
        else:
            log("s3_backup", "AWS not configured — skipped", False)
    except Exception as e:
        log("s3_backup", f"skipped: {e}", False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8777")
    ap.add_argument("--tag", default=time.strftime("auto-%Y-%m-%d"))
    ap.add_argument("--key", default="")
    ap.add_argument("--skip-train", action="store_true",
                    help="Skip LoRA training (distill+bench+promote only)")
    ap.add_argument("--model-id", default="qwen3-4b",
                    help="Registry model id to promote to if bench passes")
    args = ap.parse_args()

    key = args.key or os.environ.get("URAI_MASTER_KEY", "")
    tag = args.tag
    summary = {"tag": tag, "started": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
               "steps": {}}

    print(f"\n{'='*60}")
    print(f"  Urai train pipeline  tag={tag}")
    print(f"  base={args.base}  gpu={gpu_available()}")
    print(f"{'='*60}\n")

    # ── 1. Selfimprove ─────────────────────────────────────────────────────────
    if key:
        ok, _ = run_step("selfimprove", [
            "python3", "jev/selfimprove.py",
            "--base", args.base, "--tag", tag, "--key", key])
    else:
        log("selfimprove", "skipped (no URAI_MASTER_KEY)", False)
        ok = False
    summary["steps"]["selfimprove"] = ok

    # ── 2. Distill ─────────────────────────────────────────────────────────────
    raw = ROOT / "data" / "raw_tasks" / "selfimprove" / f"{tag}.jsonl"
    fallback = ROOT / "data" / "raw_tasks" / "sample_tasks.jsonl"
    task_file = str(raw) if raw.exists() else str(fallback)
    out_file = str(ROOT / "data" / "verified" / f"{tag}.jsonl")

    ok, _ = run_step("distill", [
        "python3", "scripts/distill/run_distill.py",
        "--tasks", task_file,
        "--out", out_file,
        "--threshold", "0.75",
        "--exec",
    ])
    summary["steps"]["distill"] = ok
    if not ok:
        log("distill", "distill failed — using existing verified set if any", False)
        # Fall back to last existing verified set
        verified_files = sorted((ROOT / "data" / "verified").glob("*.jsonl"),
                                  key=lambda p: p.stat().st_mtime)
        if verified_files:
            out_file = str(verified_files[-1])
            log("distill", f"using existing: {out_file}")

    # ── 3. LoRA train (GPU only unless --skip-train) ───────────────────────────
    train_ok = False
    if args.skip_train:
        log("train", "skipped by --skip-train flag")
        summary["steps"]["train"] = "skipped"
    elif not gpu_available():
        log("train", "no GPU detected — skipped (use Kaggle T4 for training)", False)
        summary["steps"]["train"] = "skipped-no-gpu"
    elif not Path(out_file).exists():
        log("train", "no verified dataset — skipped", False)
        summary["steps"]["train"] = "skipped-no-data"
    else:
        ok, _ = run_step("train", [
            "python3", "scripts/train/lora_urai.py",
            "--data", out_file,
            "--tag", tag,
        ])
        summary["steps"]["train"] = ok
        train_ok = ok

    # ── 4. Bench ───────────────────────────────────────────────────────────────
    bench_ok = False
    if key:
        ok, _ = run_step("bench", [
            "python3", "jev/bench.py",
            "--base", args.base,
            "--tag", tag,
            "--key", key,
        ])
        summary["steps"]["bench"] = ok
        bench_ok = ok
    else:
        log("bench", "skipped (no URAI_MASTER_KEY)", False)
        summary["steps"]["bench"] = "skipped"

    # ── 5. Promote ─────────────────────────────────────────────────────────────
    bench_report = REPORTS / f"bench-{tag}.json"
    if bench_ok and bench_report.exists():
        ok, _ = run_step("promote", [
            "python3", "scripts/promote.py",
            "--tag", tag,
            "--model-id", args.model_id,
        ])
        summary["steps"]["promote"] = ok
    else:
        log("promote", "skipped (no bench report)", False)
        summary["steps"]["promote"] = "skipped"

    # ── 6. S3 backup ───────────────────────────────────────────────────────────
    s3_backup()
    summary["steps"]["s3_backup"] = True

    # ── Summary ────────────────────────────────────────────────────────────────
    summary["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    summary["elapsed_s"] = int(time.time()) - int(
        time.mktime(time.strptime(summary["started"], "%Y-%m-%dT%H:%M:%SZ")))

    print(f"\n{'='*60}")
    print(f"  Pipeline complete  tag={tag}")
    for k, v in summary["steps"].items():
        icon = "✓" if v is True else ("~" if v in ("skipped", "skipped-no-gpu",
                                                     "skipped-no-data") else "✗")
        print(f"  {icon} {k}: {v}")
    print(f"{'='*60}\n")

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"pipeline-{tag}.json").write_text(
        json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
