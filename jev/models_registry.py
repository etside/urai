#!/usr/bin/env python3
"""Model registry: which local models exist, which is active.

 registry file: model/registry.json
   {"active": "<model-id>",
    "models": {"<id>": {"path": ..., "params": ..., "quant": ...,
                        "role": "fast|primary|reasoning", "hf": <url>,
                        "kind": "chat|vision|generate",
                        "files": [{"path": ..., "hf": <url>}, ...]}}}
 kinds: chat    = text LLM via llama-server (default)
        vision  = multimodal LLM via llama-server --mmproj (see jev/vision.py)
        generate= image checkpoint via stable-diffusion.cpp (see jev/imagine.py)
 stdlib only. `urai model download` fetches every listed file from HF;
 `urai model use` switches the active chat/vision model.
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
            "kind": "chat",
            "hf": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf",
            "pp_toks": 28.6, "tg_toks": 6.9, "ram_mb": 592,
        },
        "coder05-fast": {
            "path": "model/base/qwen2.5-coder-0.5b-instruct-q4_k_m.gguf",
            "params": "0.5B", "quant": "Q4_K_M", "role": "fast-coding",
            "kind": "chat",
            "hf": "https://huggingface.co/Qwen/Qwen2.5-Coder-0.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-0.5b-instruct-q4_k_m.gguf",
        },
        "coder15-primary": {
            "path": "model/base/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
            "params": "1.5B", "quant": "Q4_K_M", "role": "primary",
            "kind": "chat",
            "hf": "https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
        },
        # Vision: Qwen2.5-VL-3B-Instruct (open weights, Apache-2.0).
        # Served by llama.cpp llama-server --mmproj (mtmd). Refs:
        #   https://github.com/ggml-org/llama.cpp (multimodal docs)
        #   https://huggingface.co/ggml-org/Qwen2.5-VL-3B-Instruct-GGUF
        "qwen25vl-3b": {
            "path": "model/base/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf",
            "params": "3B", "quant": "Q4_K_M", "role": "vision",
            "kind": "vision",
            "hf": "https://huggingface.co/ggml-org/Qwen2.5-VL-3B-Instruct-GGUF/resolve/main/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf",
            "files": [
                {"path": "model/base/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf",
                 "hf": "https://huggingface.co/ggml-org/Qwen2.5-VL-3B-Instruct-GGUF/resolve/main/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"},
                {"path": "model/base/mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf",
                 "hf": "https://huggingface.co/ggml-org/Qwen2.5-VL-3B-Instruct-GGUF/resolve/main/mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf"},
            ],
        },
        # Generation: SD-Turbo (open weights, CreativeML Open RAIL++-M).
        # Run by stable-diffusion.cpp on CPU. Refs:
        #   https://github.com/leejet/stable-diffusion.cpp
        #   https://huggingface.co/stabilityai/sd-turbo (sd_turbo.safetensors)
        "sd-turbo": {
            "path": "model/generate/sd_turbo.safetensors",
            "params": "0.86B-unet", "quant": "fp16", "role": "generate",
            "kind": "generate",
            "hf": "https://huggingface.co/stabilityai/sd-turbo/resolve/main/sd_turbo.safetensors",
            "steps": 2, "size": [512, 512],
            "note": "~3.4GB fp16; 1-4 steps; CPU-runnable via stable-diffusion.cpp",
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


def _fetch(url, dest, progress=True):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"exists, skipping: {dest} ({dest.stat().st_size >> 20} MB)")
        return str(dest)
    req = urllib.request.Request(url, headers={"User-Agent": "urai/1.0"})
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
    print(f"downloaded: {total >> 20} MB -> {dest}")
    return str(dest)


def download(mid, progress=True):
    reg = load()
    if mid not in reg["models"]:
        raise KeyError(f"unknown model id: {mid}")
    m = reg["models"][mid]
    jobs = m.get("files") or [{"path": m["path"], "hf": m["hf"]}]
    outs = [_fetch(j["hf"], ROOT / j["path"], progress) for j in jobs]
    print(f"ready {mid}: kind={m.get('kind', 'chat')}")
    return outs[-1]
