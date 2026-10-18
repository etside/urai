"""Urai QLoRA on Modal (A100-40GB, ~$2.10/hr, ~$1.50 per 300-step run).

Usage (CI dispatch, secrets MODAL_TOKEN_ID / MODAL_TOKEN_SECRET):
    modal run modal/modal_train.py --tag distill-now --max-steps 300
    modal volume get urai-adapters <tag>-modal ./adapters/<tag>-modal

Dataset is baked into the image at build time from data/verified/<tag>.jsonl,
so every dispatch trains on the latest committed rows. Mirrors
scripts/train/sft_unsloth.py (Unsloth QLoRA r=16, 4-bit, adamw_8bit).
"""
import json
import os

import modal

TAG = os.environ.get("URAI_TRAIN_TAG", "distill-now")
DATA_PATH = f"data/verified/{TAG}.jsonl"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("unsloth", "trl", "peft", "accelerate",
                 "bitsandbytes", "datasets", "transformers")
    .add_local_file(DATA_PATH, "/data/train.jsonl")
)

app = modal.App("urai-qlora")
out_vol = modal.Volume.from_name("urai-adapters", create_if_missing=True)

ALPACA = ("Below is an instruction. Write a response.\n\n"
          "### Instruction:\n{instruction}\n\n### Response:\n{output}")


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
            rows.append({"instruction": prompt[:1500],
                         "output": completion[:3000]})
    return rows


@app.function(image=image, gpu="T4", timeout=7200,
              volumes={"/out": out_vol})
def train(tag: str = TAG, max_steps: int = 300,
          base: str = "unsloth/Qwen3-4B-bnb-4bit"):
    rows = load_rows("/data/train.jsonl")
    print(f"training rows: {len(rows)}")
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
