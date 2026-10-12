#!/usr/bin/env python3
"""Hardware baseline probe for ownai-distill-jev (Phase 1).

Collects reproducible machine facts: CPU, RAM, swap, disk, GPU presence,
Python/numpy versions, and a small CPU matmul throughput proxy so we can
compare machines/runs later. Prints JSON to stdout.

Usage:
    python3 scripts/hw_baseline.py [--matmul-n 512] [--matmul-iters 5]
"""

import argparse
import json
import platform
import shutil
import subprocess
import sys
import time


def run(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except Exception:
        return ""


def meminfo():
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                info[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matmul-n", type=int, default=512)
    ap.add_argument("--matmul-iters", type=int, default=5)
    args = ap.parse_args()

    mi = meminfo()
    nvidia = run(["nvidia-smi", "-L"])
    has_cuda = bool(nvidia)

    bench = {"ran": False}
    try:
        import numpy as np

        rng = np.random.default_rng(0)
        a = rng.standard_normal((args.matmul_n, args.matmul_n), dtype=np.float32)
        b = rng.standard_normal((args.matmul_n, args.matmul_n), dtype=np.float32)
        # warmup
        a @ b
        t0 = time.perf_counter()
        for _ in range(args.matmul_iters):
            a @ b
        dt = (time.perf_counter() - t0) / args.matmul_iters
        gflops = (2 * args.matmul_n**3 / 1e9) / dt
        bench = {
            "ran": True,
            "numpy": np.__version__,
            "matmul_n": args.matmul_n,
            "iters": args.matmul_iters,
            "sec_per_iter": round(dt, 4),
            "gflops_fp32": round(gflops, 2),
        }
    except ImportError:
        bench = {"ran": False, "reason": "numpy not installed"}

    report = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_model": run(["bash", "-c", "lscpu | grep 'Model name' | cut -d: -f2"]),
        "cpu_count_logical": run(["nproc"]),
        "mem_total": mi.get("MemTotal", ""),
        "mem_available": mi.get("MemAvailable", ""),
        "swap_total": run(["bash", "-c", "grep SwapTotal /proc/meminfo | awk '{print $2$3}'"]),
        "gpu": nvidia if has_cuda else "none detected",
        "disk_root_free": run(["bash", "-c", "df -h / | tail -1 | awk '{print $4}'"]),
        "disk_cwd_free": run(["bash", "-c", "df -h . | tail -1 | awk '{print $4}'"]),
        "huggingface_reachable": bool(
            run(["curl", "-sI", "--max-time", "10", "https://huggingface.co"])
        ),
        "cpu_matmul_proxy": bench,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    sys.exit(main())
