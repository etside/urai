#!/usr/bin/env python3
"""Benchmark H3 Ref2VA VSA against the documented 72s warm / 13.5GB baseline.

    python3 scripts/video/bench_ref2va.py [--runs 3]

Writes eval/reports/bench-ref2va-vsa.json and prints PASS/FAIL for the two
acceptance gates: warm inference < 90s @1344x768 and peak VRAM < 14GB.
Must run on the GPU box with ComfyUI + the node installed.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from jev import ref2va  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--height", type=int, default=ref2va.PROFILE["height"])
    ap.add_argument("--width", type=int, default=ref2va.PROFILE["width"])
    a = ap.parse_args()
    res = ref2va.bench(runs=a.runs)
    if not res.get("ok"):
        print(f"bench failed: {res.get('error')}")
        return 1
    print(f"runs          : {res['runs']}  times(s): {res['all_times_s']}")
    print(f"first run     : {res['first_run_s']}s")
    print(f"warm avg      : {res['warm_avg_s']}s   (baseline 72s, gate < 90s)")
    print(f"peak VRAM     : {res['peak_vram_gb']} GB  (baseline 13.5GB, gate < 14GB)")
    print(f"GATE warm<90s : {'PASS' if res['gate_warm_lt_90'] else 'FAIL'}")
    print(f"GATE vram<14GB: {'PASS' if res['gate_vram_lt_14'] else 'FAIL'}")
    print("report        : eval/reports/bench-ref2va-vsa.json")
    return 0 if (res["gate_warm_lt_90"] and res["gate_vram_lt_14"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
