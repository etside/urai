#!/usr/bin/env python3
"""Urai Phase-3 training: QLoRA fine-tune on the distilled dataset with Unsloth.

Needs a CUDA GPU (free Colab T4 works for 0.6B/1.7B; see docs/TRAINING.md).
Does NOT run on CPU-only boxes — train there, bring the adapter back here,
merge + quantize to GGUF, register it.

    pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git" \
        trl peft accelerate bitsandbytes datasets
    python3 scripts/train/sft_unsloth.py \
        --model unsloth/Qwen3-0.6B-bnb-4bit \
        --train data/verified/distill-v0.2.jsonl \
        --out model/adapters/urai-qwen3-06b-v1

Refs:
  https://github.com/unslothai/unsloth (2x faster, 70% less VRAM)
  https://docs.unsloth.ai (canonical QLoRA recipe: r=16, all linear layers)
"""

import argparse
import json
from pathlib import Path


def load_distill(path: Path) -> list:
    """verified .jsonl records -> [{instruction, output}] chat pairs."""
    rows = []
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        task, completion = r.get("task", r.get("prompt", "")), r.get("completion", "")
        prompt = task.get("prompt", "") if isinstance(task, dict) else str(task or "")
        if prompt and completion:
            rows.append({"instruction": prompt, "output": completion})
    return rows


ALPACA = ("Below is an instruction. Write a response.\n\n"
          "### Instruction:\n{instruction}\n\n### Response:\n{output}")


def to_text(rows: list) -> list:
    return [{"text": ALPACA.format(instruction=r["instruction"],
                                   output=r["output"])} for r in rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="unsloth/Qwen3-0.6B-bnb-4bit")
    ap.add_argument("--train", default="data/verified/distill-v0.2.jsonl")
    ap.add_argument("--out", default="model/adapters/urai-qwen3-06b-v1")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--max-steps", type=int, default=0,
                    help=">0 overrides epochs (quick smoke runs)")
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--seq-len", type=int, default=2048)
    args = ap.parse_args()

    rows = load_distill(Path(args.train))
    print(f"training rows: {len(rows)} from {args.train}")
    if not rows:
        raise SystemExit("no training rows — run the distill pipeline first")

    try:
        from unsloth import FastModel as Fast
    except ImportError:
        from unsloth import FastLanguageModel as Fast

    model, tok = Fast.from_pretrained(
        model_name=args.model, max_seq_length=args.seq_len,
        dtype=None, load_in_4bit=True)
    model = Fast.get_peft_model(
        model, r=args.rank, lora_alpha=args.rank, lora_dropout=0, bias="none",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth", random_state=3407)
    model.print_trainable_parameters()

    from datasets import Dataset
    from trl import SFTTrainer
    from transformers import TrainingArguments
    ds = Dataset.from_list(to_text(rows))
    targs = dict(output_dir=args.out, per_device_train_batch_size=2,
                 gradient_accumulation_steps=4, learning_rate=2e-4,
                 logging_steps=5, save_steps=200, optim="adamw_8bit",
                 seed=3407, report_to="none")
    if args.max_steps > 0:
        targs["max_steps"] = args.max_steps
    else:
        targs["num_train_epochs"] = args.epochs
    SFTTrainer(model=model, tokenizer=tok, train_dataset=ds,
               args=TrainingArguments(**targs)).train()

    model.save_pretrained(args.out)
    tok.save_pretrained(args.out)
    print(f"adapter saved -> {args.out}")
    print("next: merge + GGUF export, e.g.")
    print(f"  model.save_pretrained_merged('{args.out}-merged', tok, "
          f"save_method='merged_16bit')")
    print(f"  model.save_pretrained_gguf('{args.out}-gguf', tok, "
          f"quantization_method='q4_k_m')")
    print("then: urai model bench + register in model/registry.json")


if __name__ == "__main__":
    main()
