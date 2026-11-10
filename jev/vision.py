#!/usr/bin/env python3
"""Vision: ask questions about pictures via a local multimodal model.

Pipeline: image file -> base64 data URL -> llama-server OpenAI endpoint
(/v1/chat/completions with image_url parts) -> answer text.

Requires the vision model served, e.g.:
    ./bin/urai model download qwen25vl-3b
    ./bin/urai model use qwen25vl-3b
    ./bin/urai serve start          # auto-passes --mmproj for kind=vision

Model: Qwen2.5-VL-3B-Instruct Q4_K_M + Q8_0 mmproj (open weights,
Apache-2.0) — https://huggingface.co/ggml-org/Qwen2.5-VL-3B-Instruct-GGUF
Runner: llama.cpp llama-server multimodal (mtmd) —
https://github.com/ggml-org/llama.cpp

Stdlib only.
"""

import base64
import json
import os
import urllib.request
from pathlib import Path

LLAMA_URL = os.environ.get("JEV_LLAMA_URL", "http://127.0.0.1:8080").rstrip("/")
MAX_IMAGE_MB = 12
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def _data_url(image_path) -> str:
    ref = str(image_path)
    if ref.startswith("data:image/"):
        return ref  # already a data URL (API passthrough)
    if ref.startswith(("http://", "https://")):
        raw = urllib.request.urlopen(ref, timeout=60).read(
            (MAX_IMAGE_MB << 20) + 1)
        if len(raw) > MAX_IMAGE_MB << 20:
            raise ValueError(f"remote image too large (max {MAX_IMAGE_MB} MB)")
        return "data:image/jpeg;base64," + base64.b64encode(raw).decode()
    p = Path(ref)
    if p.suffix.lower() not in IMAGE_EXTS:
        raise ValueError(f"unsupported image type: {p.suffix} "
                         f"(allowed: {sorted(IMAGE_EXTS)})")
    raw = p.read_bytes()
    if len(raw) > MAX_IMAGE_MB << 20:
        raise ValueError(f"image too large: {len(raw) >> 20} MB "
                         f"(max {MAX_IMAGE_MB} MB)")
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


def see(image_path, question="Describe this image in detail.",
        max_tokens=512, temperature=0.2, timeout=600) -> dict:
    """Ask `question` about `image_path`. Returns {"ok", "answer"|"error"}."""
    try:
        url = _data_url(image_path)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    payload = {
        "model": os.environ.get("JEV_LLAMA_MODEL", "local-vision"),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": url}},
                {"type": "text", "text": question},
            ],
        }],
    }
    req = urllib.request.Request(
        LLAMA_URL + "/v1/chat/completions", json.dumps(payload).encode(),
        {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
        return {"ok": True,
                "answer": data["choices"][0]["message"]["content"],
                "model": data.get("model", "")}
    except Exception as e:
        return {"ok": False,
                "error": f"{str(e)[:200]} — is the vision model up? "
                         f"run: urai model use qwen25vl-3b && urai serve start"}
