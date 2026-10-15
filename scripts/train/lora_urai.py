#!/usr/bin/env python3
"""LoRA fine-tune for Urai independence Stage 2 — GPU-first, CPU-capped fallback.

Contract:
  input   data/verified/<TAG>.jsonl rows {task, completion, score}
  base    Qwen3-4B (configurable via --base)
  method  LoRA (r=16/alpha=32 GPU; r=8/alpha=16 CPU-capped)
  gate    bench AFTER merge must not regress knowledge/math/code, else DISCARD
  output  adapters/<tag>/

Paths (honest trade-offs):
  GPU (default --device auto + CUDA present): full run via unsloth if
      installed, else transformers+peft+trl. This is the only path that can
      produce a competitive student in reasonable time.
  CPU (--allow-cpu): transformers+peft+trl on CPU, HARD CAPPED (<=300
      examples, 1 epoch, r=8, batch 1). Expect ~1-3 hours on 4 vCPU for 200
      examples and only a demonstration-grade adapter. It proves the
      pipeline; it does not replace GPU training.
  FREE GPU TIERS (recommended if you own no GPU): Kaggle gives ~30h/week of
      free T4 GPUs — enough for the real thing. See docs/INDEPENDENCE.md
      "Stage 2 without your own GPU" for the click-by-click flow, then run
      THIS script there (it auto-uses CUDA when present).

Examples:
  python3 scripts/train/lora_urai.py --data data/verified/distill-now.jsonl --tag now
  python3 scripts/train/lora_urai.py --data data/verified/distill-now.jsonl --tag cpu-demo --allow-cpu --max-examples 200
"""

import argparse
import json
import shutil
import sys
from pathlib import Path


def load_rows(data_path, max_examples):
    rows = []
    with open(data_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            task = r.get("task") or r.get("prompt") or ""
            completion = r.get("completion") or ""
            if not task or not completion:
                continue
            rows.append({"task": task[:1500], "completion": completion[:3000]})
            if len(rows) >= max_examples:
                break
    return rows


def to_texts(rows):
    return [("Below is a task and a verified solution. Learn the pattern.\n\n"
             f"### Task:\n{r['task']}\n\n### Solution:\n{r['completion']}")
            for r in rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--base", default="Qwen/Qwen3-4B")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--allow-cpu", action="store_true",
                    help="permit the capped CPU fallback (demo-grade only)")
    ap.add_argument("--max-examples", type=int, default=2000)
    ap.add_argument("--epochs", type=int, default=1)
    args = ap.parse_args()

    has_cuda = bool(shutil.which("nvidia-smi"))
    if args.device == "cuda" and not has_cuda:
        sys.exit("REFUSE: --device cuda but no NVIDIA GPU here.")
    use_cuda = has_cuda and args.device in ("auto", "cuda")

    if use_cuda:
        max_examples, lora_r, lora_alpha, batch = args.max_examples, 16, 32, 2
        mode = "GPU full run"
    elif args.allow_cpu:
        small = any(k in args.base for k in ("0.5B", "0.6B", "1B", "1.5B", "1.7B"))
        if not small:
            sys.exit(
                "REFUSE: CPU path needs a SMALL base (fp32 4B needs ~16 GB RAM; "
                "this droplet has 8 GB). Use e.g. --base Qwen/Qwen2.5-0.5B-Instruct "
                "or Qwen/Qwen2.5-Coder-0.5B-Instruct, or take the Kaggle T4 route.")
        max_examples = min(args.max_examples, 300)
        lora_r, lora_alpha, batch = 8, 16, 1
        mode = ("CPU CAPPED demo run (<=300 examples, r=8, 1 epoch, small base) — "
                "proves the pipeline only; expect hours and small effect")
    else:
        sys.exit(
            "REFUSE: no CUDA here and --allow-cpu not given.\n"
            "Options:\n"
            "  1) re-run with --allow-cpu for the capped CPU demo "
            "(slow, demonstration-grade),\n"
            "  2) run this same script on a free Kaggle T4 "
            "(30h/week free — see docs/INDEPENDENCE.md),\n"
            "  3) dispatch urai-train.yml on a GPU runner.")

    rows = load_rows(args.data, max_examples)
    if len(rows) < 10:
        sys.exit(f"REFUSE: only {len(rows)} usable rows in {args.data}; need >= 10.")
    print(f"train [{mode}]: {len(rows)} rows, base={args.base}, tag={args.tag}",
          flush=True)

    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig
        from transformers import (AutoModelForCausalLM, AutoTokenizer,
                                  TrainingArguments)
        from trl import SFTTrainer
    except ImportError as e:
        sys.exit(f"REFUSE: missing training stack ({e}).\n"
                 "  GPU box: pip install unsloth trl datasets   (unsloth path)\n"
                 "  or: pip install torch transformers peft trl datasets accelerate")

    ds = Dataset.from_list([{"text": t} for t in to_texts(rows)])
    dtype = torch.bfloat16 if (use_cuda and torch.cuda.is_bf16_supported()) else torch.float32
    tok = AutoTokenizer.from_pretrained(args.base, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        args.base, torch_dtype=dtype, trust_remote_code=True,
        **({"device_map": "auto"} if use_cuda else {}))
    peft_cfg = LoraConfig(r=lora_r, lora_alpha=lora_alpha,
                          target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                                          "gate_proj", "up_proj", "down_proj"],
                          lora_dropout=0.05, task_type="CAUSAL_LM")
    targs = TrainingArguments(
        output_dir=f"adapters/{args.tag}", num_train_epochs=args.epochs,
        per_device_train_batch_size=batch, gradient_accumulation_steps=8,
        learning_rate=2e-4, logging_steps=10, save_steps=100,
        save_total_limit=2, fp16=False, bf16=False,
        report_to="none", seed=7)
    SFTTrainer(model=model, train_dataset=ds, peft_config=peft_cfg,
               processing_class=tok, args=targs).train()
    model.save_pretrained(f"adapters/{args.tag}")
    tok.save_pretrained(f"adapters/{args.tag}")
    print(f"DONE adapters/{args.tag} — next (mandatory): merge -> GGUF export "
          f"-> bench gate (knowledge/math/code must not regress) -> promote. "
          f"See docs/INDEPENDENCE.md Stage 3.")


if __name__ == "__main__":
    main()
