#!/usr/bin/env python3
"""Kaggle: quantize the saved 4B merged model to GGUF Q4_K_M (no merge needed)."""
import glob, os, subprocess, sys

MERGED = sorted(glob.glob("/kaggle/input/**/model.safetensors", recursive=True))
print("found:", MERGED)
if not MERGED:
    raise SystemExit(10)

kern = os.path.dirname(MERGED[0])
print("merged dir:", kern)

conv = "/kaggle/working/convert_hf_to_gguf.py"
import urllib.request
urllib.request.urlretrieve(
    "https://raw.githubusercontent.com/ggerganov/llama.cpp/master/"
    "convert_hf_to_gguf.py", conv)
gguf_f16 = "/kaggle/working/model-f16.gguf"
r = subprocess.run([sys.executable, conv, kern, "--outfile", gguf_f16,
                    "--outtype", "f16"], capture_output=True, text=True)
print(r.stdout[-400:], r.stderr[-400:])

qlib = "/kaggle/working/llama-b12192.zip"
subprocess.run(["curl", "-fsSL", "-o", qlib,
                "https://github.com/ggerganov/llama.cpp/releases/download/"
                "b12192/llama-b12192-bin-ubuntu-x64.zip"], check=False)
subprocess.run(["unzip", "-q", "-o", qlib, "-d", "/kaggle/working/llama"], check=False)
q = "/kaggle/working/llama/llama-quantize"
if not os.path.exists(q):
    q = "llama-quantize"
OUT = "/kaggle/working/urai-4b-q4_k_m.zip"
r = subprocess.run([q, gguf_f16, "/kaggle/working/urai-4b-q4_k_m.gguf", "Q4_K_M"],
                   capture_output=True, text=True)
print(r.stdout[-400:], r.stderr[-400:])
import zipfile
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    z.write("/kaggle/working/urai-4b-q4_k_m.gguf", "urai-4b-q4_k_m.gguf")
print("zipped ->", OUT)
