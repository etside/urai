#!/usr/bin/env python3
"""Model registry: which local models exist, which is active.

 registry file: model/registry.json
   {"active": "<model-id>",
    "models": {"<id>": {"path": ..., "params": ..., "quant": ...,
                        "role": "fast|primary|reasoning", "hf": <url>}}}
 stdlib only. `jev model add` downloads from HF; `jev model use` switches.
"""

import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "model" / "registry.json"

DEFAULTS = {
    "active": "qwen05-fast",
    "models": {
        "qwen05-fast": {
            "path": "model/base/qwen2.5-0.5b-instruct-q4_k_m.gguf",
            "params": "0.5B", "quant": "Q4_K_M", "role": "fast",
            "hf": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf",
            "pp_toks": 28.6, "tg_toks": 6.9, "ram_mb": 592,
        },
        "coder05-fast": {
            "path": "model/base/qwen2.5-coder-0.5b-instruct-q4_k_m.gguf",
            "params": "0.5B", "quant": "Q4_K_M", "role": "fast-coding",
            "hf": "https://huggingface.co/Qwen/Qwen2.5-Coder-0.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-0.5b-instruct-q4_k_m.gguf",
        },
        "coder15-primary": {
            "path": "model/base/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
            "params": "1.5B", "quant": "Q4_K_M", "role": "primary",
            "hf": "https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
        },
    },
}


def load():
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text())
    save(DEFAULTS)
    return json.loads(json.dumps(DEFAULTS))


def save(reg):
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(reg, indent=2) + "\n")


def active_model(reg=None):
    reg = reg or load()
    m = reg["models"][reg["active"]]
    return reg["active"], m


def active_path():
    mid, m = active_model()
    p = ROOT / m["path"]
    return mid, str(p) if p.exists() else None


def download(mid, progress=True):
    reg = load()
    if mid not in reg["models"]:
        raise KeyError(f"unknown model id: {mid}")
    url = reg["models"][mid]["hf"]
    dest = ROOT / reg["models"][mid]["path"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "ownai-jeV/0.1"})
    total = 0
    with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
            if progress and total % (20 << 20) < (1 << 20):
                print(f"  ... {total >> 20} MB", flush=True)
    print(f"downloaded {mid}: {total >> 20} MB -> {dest}")
    return str(dest)
