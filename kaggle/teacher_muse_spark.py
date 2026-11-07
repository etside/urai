#!/usr/bin/env python3
"""Kaggle teacher-generation: Muse Spark Open (OpenRouter) → Urai SFT JSONL.

Run on YOUR machine first (needs OPENROUTER_API_KEY), then push the
output JSONL to Kaggle for QLoRA training (kaggle/train_qlora.py).

Usage:
    export OPENROUTER_API_KEY=...
    python3 kaggle/teacher_muse_spark.py \
        --tasks data/raw_tasks/sample_tasks.jsonl \
        --out data/finetune/muse-spark-open/train.jsonl \
        --reasoning high --limit 200

Cost (OpenRouter): $1.25/M in, $4.25/M out. 200 tasks ≈ $0.50.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jev import muse  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="data/raw_tasks/sample_tasks.jsonl")
    ap.add_argument("--out", default="data/finetune/muse-spark-open/train.jsonl")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reasoning", default="high", choices=["low", "medium", "high", "xhigh"])
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--resume", action="store_true",
                    help="append to --out and skip prompts already present")
    ap.add_argument("--models", default=(
        "meta/muse-spark-open,"
        "nvidia/nemotron-3-ultra-550b-a55b:free,"
        "nvidia/nemotron-3.5-super-vl:free"),
        help="comma-separated teacher chain; first that answers wins")
    ap.add_argument("--shard", default="",
                    help="i/n — run only tasks where index %% n == i")
    ap.add_argument("--s3-uri", default="",
                    help="upload the shard here every --sync-every rows")
    ap.add_argument("--sync-every", type=int, default=10)
    a = ap.parse_args()

    if not muse.available():
        print("Set OPENROUTER_API_KEY (https://openrouter.ai/settings/keys)")
        return 1

    tasks = [json.loads(l) for l in Path(a.tasks).read_text().splitlines() if l.strip()]
    if a.shard:
        i, n = (int(x) for x in a.shard.split("/"))
        tasks = tasks[i::n]
    if a.limit:
        tasks = tasks[: a.limit]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    done = set()
    if a.resume and out.exists():
        for line in out.read_text().splitlines():
            try:
                done.add(json.loads(line).get("prompt", ""))
            except Exception:
                pass

    n = 0
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    with out.open("a" if a.resume else "w") as f:
        for t in tasks:
            prompt = t.get("prompt") or t.get("input") or t.get("text") or ""
            if not prompt or prompt in done:
                continue
            res = None
            teacher = models[0]
            for model in models:
                teacher = model
                max_tokens = a.max_tokens
                # reasoning_effort is a Muse/paid-model knob; free routers
                # reject unknown fields on some providers.
                effort = a.reasoning if model.startswith("meta/") else None
                for attempt in range(1, a.retries + 1):
                    try:
                        res = muse.complete(
                            [
                                {"role": "system", "content": muse.SYSTEM_PROMPT},
                                {"role": "user", "content": prompt},
                            ],
                            max_tokens=max_tokens,
                            reasoning_effort=effort,
                            model=model,
                        )
                        break
                    except Exception as e:
                        msg = str(e)
                        print(f"  {model} attempt {attempt} failed: {msg[:160]}",
                              flush=True)
                        if attempt == a.retries:
                            break
                        # Free-tier budget is per-request: ask for less next time.
                        if "402" in msg:
                            max_tokens = max(512, max_tokens // 2)
                            time.sleep(10)
                        elif "429" in msg:
                            time.sleep(20 * attempt)
                        else:
                            time.sleep(5 * attempt)
                if res and (res.get("content") or "").strip():
                    break
                res = None
            if not res:
                print(f"  skipped (no content): {prompt[:60]}", flush=True)
                continue
            f.write(json.dumps({
                "prompt": prompt,
                "completion": res["content"],
                "messages": [
                    {"role": "system", "content": muse.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": res["content"]},
                ],
                "teacher": res.get("model") or teacher,
                "reasoning_effort": a.reasoning,
                "usage": res.get("usage", {}),
            }) + "\n")
            f.flush()
            n += 1
            print(f"[{n}/{len(tasks)}] {res.get('usage', {})}", flush=True)
            if a.s3_uri and n % a.sync_every == 0:
                subprocess.run(["aws", "s3", "cp", str(out), a.s3_uri],
                               capture_output=True, check=False)
    print(f"wrote {n} → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
