#!/usr/bin/env python3
"""Merge a LoRA adapter into a base model with numpy only, then write GGUF.

No torch/peft required — works on any Python 3.10+. LoRA merge is plain
linear algebra: W += scaling * B @ A per targeted linear layer.

Usage:
    python3 kaggle/merge_numpy.py --adapter /opt/urai-adapter/urai-adapter \
        --base Qwen/Qwen3-1.7B --out /tmp/merged  [--safetensors-out]
    python3 /opt/llama/convert_hf_to_gguf.py /tmp/merged \
        --outfile /tmp/model-f16.gguf --outtype f16
    llama-quantize /tmp/model-f16.gguf /tmp/out.gguf Q4_K_M
"""
import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import ml_dtypes  # registers bfloat16 with numpy
np.dtype(np.float32)
from safetensors import safe_open
from safetensors.numpy import save_file

ap = argparse.ArgumentParser()
ap.add_argument("--adapter", required=True)
ap.add_argument("--base", required=True, help="HF repo id or local path")
ap.add_argument("--out", required=True)
a = ap.parse_args()

adapter_dir = Path(a.adapter)
cfg = json.loads((adapter_dir / "adapter_config.json").read_text())
r = int(cfg["r"])
alpha = float(cfg.get("lora_alpha", r))
scaling = alpha / r
targets = cfg.get("target_modules", [])
if isinstance(targets, str):
    targets = [targets]
print(f"lora r={r} alpha={alpha} scaling={scaling} targets={targets}")

# ---- base safetensors (HF) ----
from huggingface_hub import snapshot_download

base_path = Path(a.base)
if not (base_path / "config.json").exists():
    base_path = Path(snapshot_download(a.base))
print("base:", base_path)

files = sorted(base_path.glob("*.safetensors"))
if not files:
    print("no safetensors in base clone")
    raise SystemExit(1)

state = {}
for f in files:
    with safe_open(str(f), framework="numpy") as sf:
        for k in sf.keys():
            state[k] = sf.get_tensor(k)

# ---- adapter ----
ad = {}
with safe_open(str(adapter_dir / "adapter_model.safetensors"),
               framework="numpy") as sf:
    for k in sf.keys():
        ad[k] = sf.get_tensor(k)
# keys like base_model.model.model.layers.0.self_attn.q_proj.lora_A.weight
# map to base names: model.layers.0.self_attn.q_proj.weight
kinds = []
for key in sorted(ad):
    if "lora_A.weight" in key:
        base = key.split("base_model.model.")[1].split("lora_A")[0].rstrip(".")
        kinds.append((base, "A"))
    if "lora_embedding_A" in key:
        kinds.append((None, "emb"))
pairs = {}
for base, tag in kinds:
    A = ad.get(f"base_model.model.{base}lora_A.weight"
               f"base_model.model.{base}lora_B.weight")
    # handled below generically
for key in list(ad):
    if key.endswith("lora_A.weight"):
        prefix = key[: -len("lora_A.weight")]
        bkey = f"{prefix}lora_B.weight"
        wkey = prefix.rstrip(".") + ".weight"
        wkey = wkey.replace("base_model.model.", "")
        if wkey not in state:
            # try without prefix adjustment
            wkey2 = key.replace("base_model.model.", "").replace(".lora_A.weight", ".weight")
            wkey = wkey2
        if wkey in state and bkey in ad:
            A = ad[key].astype(np.float32)
            B = ad[bkey].astype(np.float32)
            delta = scaling * (B @ A)
            if delta.shape != state[wkey].shape:
                print(f"shape mismatch {wkey}: {delta.shape} vs {state[wkey].shape}")
                continue
            state[wkey] = (state[wkey].astype(np.float32) + delta).astype(
                state[wkey].dtype)
            print("merged", wkey)

out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)
save_file(state, str(out / "model.safetensors"), metadata={"format": "pt"})
for f in ["config.json", "generation_config.json", "tokenizer.json",
          "tokenizer_config.json", "chat_template.jinja",
          "special_tokens_map.json", "added_tokens.json", "vocab.json",
          "merges.txt"]:
    src = base_path / f
    if src.exists():
        (out / f).write_bytes(src.read_bytes())
print("merged ->", out)
