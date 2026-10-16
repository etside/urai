#!/usr/bin/env python3
"""Urai QLoRA on Kaggle T4 (free) — self-contained kernel script.

Setup (5 min, see docs/KAGGLE_NOW.md):
  1. Kaggle Notebook, accelerator GPU T4 x2, internet ON.
  2. Upload data/verified/distill-now.jsonl as input dataset.
  3. Paste this file into the notebook (or !pip install + run).
  4. Run all → adapter lands in /kaggle/working/urai-adapter.
  5. Download it, send back for GGUF export + bench gate.

Mirrors scripts/train/sft_unsloth.py (Unsloth QLoRA r=16, 4-bit,
adamw_8bit, grad checkpointing) with the prompt/completion loader fix.
"""
import glob
import json
import os

DATA = sorted(glob.glob("/kaggle/input/**/*.jsonl", recursive=True))
DATA = DATA[0] if DATA else "distill-now.jsonl"
OUT = "/kaggle/working/urai-adapter"
MODEL = os.environ.get("URAI_BASE", "unsloth/Qwen3-4B-bnb-4bit")
MAX_STEPS = int(os.environ.get("MAX_TRAIN_STEPS", "300"))


def load_rows(path):
    rows = []
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        task = r.get("task", r.get("prompt", ""))
        prompt = task.get("prompt", "") if isinstance(task, dict) else str(task or "")
        completion = r.get("completion", "") or ""
        if prompt and completion:
            rows.append({"instruction": prompt[:1500], "output": completion[:3000]})
    return rows


ALPACA = ("Below is an instruction. Write a response.\n\n"
          "### Instruction:\n{instruction}\n\n### Response:\n{output}")


def main():
    rows = load_rows(DATA)
    print(f"training rows: {len(rows)} from {DATA}")
    if len(rows) < 5:
        raise SystemExit("need >= 5 rows — upload distill-now.jsonl as input dataset")

    try:
        from unsloth import FastModel as Fast
    except ImportError:
        from unsloth import FastLanguageModel as Fast

    model, tok = Fast.from_pretrained(
        model_name=MODEL, max_seq_length=2048, dtype=None, load_in_4bit=True)
    model = Fast.get_peft_model(
        model, r=16, lora_alpha=16, lora_dropout=0, bias="none",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth", random_state=3407)
    model.print_trainable_parameters()

    from datasets import Dataset
    from trl import SFTTrainer
    from transformers import TrainingArguments
    ds = Dataset.from_list(
        [{"text": ALPACA.format(instruction=r["instruction"], output=r["output"])}
         for r in rows])
    targs = dict(output_dir=OUT, per_device_train_batch_size=2,
                 gradient_accumulation_steps=4, learning_rate=2e-4,
                 logging_steps=5, save_steps=200, optim="adamw_8bit",
                 seed=3407, report_to="none", max_steps=MAX_STEPS)
    SFTTrainer(model=model, tokenizer=tok, train_dataset=ds,
               args=TrainingArguments(**targs)).train()
    model.save_pretrained(OUT)
    tok.save_pretrained(OUT)
    print(f"adapter saved -> {OUT} — download it and send back for GGUF export")


if __name__ == "__main__":
    main()
