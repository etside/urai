#!/usr/bin/env python3
"""Merge the Urai LoRA adapter into its base and export GGUF Q4_K_M.

Input dataset: sherikhtj/urai-adapter-1.7b (adapter_model.safetensors +
tokenizer files at the root). Output: urai-1.7b-q4_k_m.gguf in /kaggle/working.
CPU-able; runs fine on Kaggle's T4.
"""
import glob
import os
import subprocess
import sys

run = lambda cmd: subprocess.run(cmd, shell=True, check=False)

print("installing deps", flush=True)
subprocess.run(
    [sys.executable, "-m", "pip", "install", "-q", "peft", "transformers",
     "safetensors", "gguf", "torch", "--index-url",
     "https://download.pytorch.org/whl/cpu"],
    capture_output=True)
try:
    import torch
except Exception as e:
    print("torch import failed:", e)
    raise SystemExit(0)

ADAPTER = sorted(glob.glob("/kaggle/input/**/adapter_config.json", recursive=True))
ADAPTER = os.path.dirname(ADAPTER[0]) if ADAPTER else ""
BASE = os.environ.get("URAI_BASE", "unsloth/Qwen3-1.7B")
OUT = "/kaggle/working/urai-1.7b-q4_k_m.gguf"
print("adapter:", ADAPTER, "base:", BASE)

from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

model = AutoModelForCausalLM.from_pretrained(
    BASE, torch_dtype=torch.bfloat16, trust_remote_code=True)
tok = AutoTokenizer.from_pretrained(BASE, trust_remote_code=True)
model = PeftModel.from_pretrained(model, ADAPTER)
model = model.merge_and_unload()

merged = "/kaggle/working/merged"
model.save_pretrained(merged)
tok.save_pretrained(merged)
print("merged ->", merged)

# convert to GGUF
conv = "/kaggle/working/convert_hf_to_gguf.py"
import urllib.request
urllib.request.urlretrieve(
    "https://raw.githubusercontent.com/ggerganov/llama.cpp/master/"
    "convert_hf_to_gguf.py", conv)
gguf_f16 = "/kaggle/working/model-f16.gguf"
r = subprocess.run([sys.executable, conv, merged, "--outfile", gguf_f16,
                    "--outtype", "f16"], capture_output=True, text=True)
print(r.stdout[-500:], r.stderr[-500:])

# quantize
qbin = "/kaggle/working/llama-b12192-bin-ubuntu-x64.zip"
subprocess.run(["curl", "-fsSL", "-o", qbin,
                "https://github.com/ggerganov/llama.cpp/releases/download/"
                "b12192/llama-b12192-bin-ubuntu-x64.zip"], check=False)
subprocess.run(["unzip", "-q", "-o", qbin, "-d", "/kaggle/working/llama"],
               check=False)
q = "/kaggle/working/llama/llama-quantize"
if not os.path.exists(q):
    q = "llama-quantize"
r = subprocess.run([q, gguf_f16, OUT, "Q4_K_M"], capture_output=True, text=True)
print(r.stdout[-500:], r.stderr[-500:])
print("exported ->", OUT, os.path.getsize(OUT) if os.path.exists(OUT) else "missing")
