"""Urai unified-student QLoRA on Modal (the default GPU path).

T4 by default (~$1/run, ~$1.50 per 300 steps); set URAI_MODAL_GPU=A100|L40S
for more headroom. No local compute: the dataset is baked from
data/verified/ at image build and only ever runs in the container.

Usage (CI dispatch; secrets MODAL_TOKEN_ID / MODAL_TOKEN_SECRET):
    URAI_TRAIN_TAG=unified modal run modal/modal_train.py --tag unified --max-steps 300
    modal volume get urai-adapters <tag>-modal ./adapters/<tag>-modal

tag == "unified" merges + dedups every verified row (the single student set);
any other tag trains on data/verified/<tag>.jsonl. Mirrors
scripts/train/sft_unsloth.py (Unsloth QLoRA r=16, 4-bit, adamw_8bit).
"""
import hashlib
import json
import os
from pathlib import Path

import modal

TAG = os.environ.get("URAI_TRAIN_TAG", "unified")
GPU = os.environ.get("URAI_MODAL_GPU", "T4")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("unsloth", "trl", "peft", "accelerate",
                 "bitsandbytes", "datasets", "transformers")
    .add_local_dir("data/verified", "/data/verified")
)

app = modal.App("urai-qlora")
out_vol = modal.Volume.from_name("urai-adapters", create_if_missing=True)

ALPACA = ("Below is an instruction. Write a response.\n\n"
          "### Instruction:\n{instruction}\n\n### Response:\n{output}")


def _prompt_of(r):
    task = r.get("task", r.get("prompt", ""))
    if isinstance(task, dict):
        return task.get("prompt", "")
    return str(task or "")


def load_rows(tag):
    """tag == 'unified' merges + dedups all verified rows; else a single file."""
    if tag == "unified":
        files = sorted(Path("/data/verified").rglob("*.jsonl"))
    else:
        files = [Path(f"/data/verified/{tag}.jsonl")]
    seen, rows = set(), []
    for f in files:
        if not f.is_file() or f.name == "unified.jsonl":
            continue
        for line in f.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            prompt = _prompt_of(r).strip()
            completion = r.get("completion", "") or ""
            if not prompt or not completion:
                continue
            h = hashlib.sha1(prompt.encode()).hexdigest()
            if h in seen:
                continue
            seen.add(h)
            rows.append({"instruction": prompt[:1500],
                         "output": completion[:3000]})
    return rows


@app.function(image=image, gpu=GPU, timeout=7200,
              volumes={"/out": out_vol})
def train(tag: str = TAG, max_steps: int = 300,
          base: str = "unsloth/Qwen3-4B-bnb-4bit"):
    rows = load_rows(tag)
    print(f"training rows: {len(rows)} (tag={tag}, gpu={GPU})")
    if len(rows) < 5:
        raise SystemExit("need >= 5 rows")

    try:
        from unsloth import FastModel as Fast
    except ImportError:
        from unsloth import FastLanguageModel as Fast

    model, tok = Fast.from_pretrained(
        model_name=base, max_seq_length=2048, dtype=None, load_in_4bit=True)
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
        [{"text": ALPACA.format(instruction=r["instruction"],
                               output=r["output"])} for r in rows])
    out = f"/out/{tag}-modal"
    targs = dict(output_dir=out, per_device_train_batch_size=2,
                 gradient_accumulation_steps=4, learning_rate=2e-4,
                 logging_steps=5, save_steps=200, optim="adamw_8bit",
                 seed=3407, report_to="none", max_steps=max_steps)
    SFTTrainer(model=model, tokenizer=tok, train_dataset=ds,
               args=TrainingArguments(**targs)).train()
    model.save_pretrained(out)
    tok.save_pretrained(out)
    out_vol.commit()
    print(f"adapter saved -> volume:urai-adapters/{tag}-modal")


@app.local_entrypoint()
def main(tag: str = TAG, max_steps: int = 300):
    train.remote(tag, max_steps)
