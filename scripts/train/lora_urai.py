#!/usr/bin/env python3
"""LoRA fine-tune stub for Urai independence Stage 2 (GPU REQUIRED).

This script documents the exact training contract and FAILS FAST on
machines without CUDA — it will not silently fake-train on CPU.

Contract:
  input   data/verified/<TAG>.jsonl rows {task, completion, score}
  base    Qwen3-4B (configurable via --base)
  method  LoRA (r=16, alpha=32, targets: q,k,v,o,gate,up,down)
  gate    eval/reports/bench-<tag>.json AFTER merge must not regress
          knowledge/math/code vs the pre-run report, else DISCARD
  output  adapters/<tag>/ + merged weights dir (see export_gguf.sh)

Run (GPU box with unsloth + trl + datasets):
  pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git" trl datasets
  python3 scripts/train/lora_urai.py --data data/verified/distill-now.jsonl --tag now

Dispatched by .github/workflows/urai-train.yml on a GPU runner label.
"""

import argparse
import shutil
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--base", default="Qwen/Qwen3-4B")
    args = ap.parse_args()

    if not shutil.which("nvidia-smi"):
        sys.exit("REFUSE: no NVIDIA GPU on this machine. Stage 2 needs CUDA — "
                 "see docs/INDEPENDENCE.md. Run via urai-train.yml on a GPU runner.")
    try:
        import torch
        assert torch.cuda.is_available(), "torch has no CUDA"
    except ImportError:
        sys.exit("REFUSE: torch/unsloth not installed (see module docstring).")

    print(f"train: data={args.data} tag={args.tag} base={args.base}")
    # Full LoRA loop lives here once a GPU runner is commissioned.
    # It MUST end with: merge -> GGUF export -> bench gate -> adapters/<tag>/.
    raise NotImplementedError(
        "Stage-2 trainer body pending GPU runner commissioning. "
        "Stages 0-1 (few-shot promotion + dataset scale) run today.")


if __name__ == "__main__":
    main()
