#!/usr/bin/env python3
"""Merge a Kaggle LoRA adapter into its base model and export GGUF Q4_K_M.

Usage (on a host with the adapter files + internet):
    python3 kaggle/export_gguf.py --adapter /path/urai-adapter \
        --base unsloth/Qwen3-1.7B --out /tmp/urai-qwen3-1.7b-q4_k_m.gguf

Installs peft/transformers/llama-cpp-python (GGUF writer via llama.cpp's
convert_hf_to_gguf.py, which ships with the llama-cpp-python source tree
or as a standalone script). CPU only; ~6GB RAM free required for 1.7B bf16.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

def ensure(pkg):
    try:
        __import__(pkg)
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", pkg],
                       check=True, capture_output=True)

for pkg in ["peft", "transformers", "safetensors"]:
    ensure(pkg)

ap = argparse.ArgumentParser()
ap.add_argument("--adapter", required=True)
ap.add_argument("--base", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--work", default="/tmp/urai-export")
a = ap.parse_args()

from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

adapter = Path(a.adapter)
# Kaggles output nests the adapter; find adapter_config.json
cfg = next(adapter.rglob("adapter_config.json"), None)
if not cfg:
    print("no adapter_config.json under", adapter)
    raise SystemExit(1)
adapter_dir = cfg.parent
print("adapter:", adapter_dir)

base = AutoModelForCausalLM.from_pretrained(
    a.base, torch_dtype=torch.bfloat16, trust_remote_code=True)
tok = AutoTokenizer.from_pretrained(a.base, trust_remote_code=True)
model = PeftModel.from_pretrained(base, str(adapter_dir))
merged = model.merge_and_unload()
work = Path(a.work)
work.mkdir(parents=True, exist_ok=True)
merged.save_pretrained(work / "merged")
tok.save_pretrained(work / "merged")
print("merged ->", work / "merged")

# GGUF via llama.cpp converter
conv = next(HERE.glob("**/convert_hf_to_gguf.py"), None)
if not conv:
    # clone the converter into the work dir
    import urllib.request
    url = ("https://raw.githubusercontent.com/ggerganov/llama.cpp/master/"
           "convert_hf_to_gguf.py")
    dest = work / "convert_hf_to_gguf.py"
    urllib.request.urlretrieve(url, dest)
    conv = dest
print("converter:", conv)
gguf_dir = work / "gguf"
input: str
# llama-cpp-python's bundled converter writes a .gguf in its own dir
subprocess.run([sys.executable, str(conv), str(work / "merged"),
                "--outfile", str(gguf_dir / "model.gguf"),
                "--outtype", "f16"],
               check=False, capture_output=True)
print("f16 ->", gguf_dir / "model.gguf")

print("done. Quantize with:",
      "llama-quantize", str(gguf_dir / "model.gguf"),
      str(a.out), "Q4_K_M")
