#!/usr/bin/env python3
"""Kaggle: merge the 4B LoRA adapter into Qwen3-4B and export GGUF Q4_K_M."""
import glob, os, subprocess, sys

subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                "peft", "transformers", "safetensors", "gguf",
                "torchao>=0.16", "bitsandbytes"], capture_output=True)

ADAPTER = sorted(glob.glob("/kaggle/input/**/adapter_config.json", recursive=True))
ADAPTER = os.path.dirname(ADAPTER[0]) if ADAPTER else ""
BASE = "Qwen/Qwen3-4B"
OUT = "/kaggle/working/urai-4b-q4_k_m.gguf"
print("adapter:", ADAPTER, "base:", BASE)

from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

# load base in full bf16 (4-bit bnb models can't save_pretrained after merge)
model = AutoModelForCausalLM.from_pretrained(
    BASE, dtype=torch.bfloat16, trust_remote_code=True, device_map="cuda")
tok = AutoTokenizer.from_pretrained(BASE, trust_remote_code=True)
model = PeftModel.from_pretrained(model, ADAPTER)
model = model.merge_and_unload()

merged = "/kaggle/working/merged"
model.save_pretrained(merged)
tok.save_pretrained(merged)

conv = "/kaggle/working/convert_hf_to_gguf.py"
import urllib.request
urllib.request.urlretrieve(
    "https://raw.githubusercontent.com/ggerganov/llama.cpp/master/"
    "convert_hf_to_gguf.py", conv)
gguf_f16 = "/kaggle/working/model-f16.gguf"
r = subprocess.run([sys.executable, conv, merged, "--outfile", gguf_f16,
                    "--outtype", "f16"], capture_output=True, text=True)
print(r.stdout[-300:], r.stderr[-300:])

import zipfile
qlib = "/kaggle/working/llama-b12192.zip"
subprocess.run(["curl", "-fsSL", "-o", qlib,
                "https://github.com/ggerganov/llama.cpp/releases/download/"
                "b12192/llama-b12192-bin-ubuntu-x64.zip"], check=False)
subprocess.run(["unzip", "-q", "-o", qlib, "-d", "/kaggle/working/llama"], check=False)
q = "/kaggle/working/llama/llama-quantize"
if not os.path.exists(q):
    q = "llama-quantize"
r = subprocess.run([q, gguf_f16, OUT, "Q4_K_M"], capture_output=True, text=True)
print(r.stdout[-300:], r.stderr[-300:])
print("exported ->", OUT)
