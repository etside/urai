#!/usr/bin/env python3
"""Verify the H3 Ref2VA VSA installation and checkpoints. Exit 1 if incomplete.

    python3 scripts/video/verify_ref2va_models.py
    python3 scripts/video/verify_ref2va_models.py --json

Reports per-checkpoint presence + safetensors integrity + the ComfyUI server and
the bundled API workflow. Missing weights are shown as "not installed" — never
substituted with a fake success.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from jev import ref2va  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    st = ref2va.verify_install()
    if a.json:
        print(json.dumps(st, indent=2))
        return 0 if st["installed"] else 1

    print("H3 Ref2VA VSA — installation check")
    print(f"  ComfyUI dir : {ref2va.COMFY_DIR}")
    print(f"  node dir    : {st['node_dir']}  {'OK' if st['node_present'] else 'MISSING'}")
    print(f"  workflow    : {st['workflow']}  {'OK' if st['workflow_present'] else 'MISSING'}")
    print(f"  comfy url   : {st['comfy_url']}  {'up' if st['comfy_up'] else 'down'}")
    print(f"  VRAM total  : {round(st['vram_bytes'] / 1e9, 1)} GB")
    print("  checkpoints:")
    for m in st["models"]:
        tag = "OK       " if m["valid"] else ("not installed" if not m["present"] else "INVALID  ")
        print(f"    [{tag}] {m['dir']}/{m['name']}  ({round(m['size'] / 1e6, 1)} MB)")
    print()
    if st["installed"]:
        print("  RESULT: installed")
        return 0
    print(f"  RESULT: not installed — missing: {', '.join(st['missing']) or 'node/workflow'}")
    print("  fix: scripts/video/install_ref2va_vsa.sh --download")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
