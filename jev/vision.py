#!/usr/bin/env python3
"""Vision: first-party Urai multimodal path (no external model).

image_url parts (data: and http) -> jev.urai_runtime.vision -> Urai text head.
Stdlib only. If the runtime is not loaded, reports not-loaded (503 class).
"""

import base64
from pathlib import Path


def _data_url(image_path) -> str:
    """Normalize to data: URL text (kept for compat; decode happens downstream)."""
    ref = str(image_path)
    if ref.startswith("data:image/") or ref.startswith(("http://", "https://")):
        return ref
    p = Path(ref)
    raw = p.read_bytes()
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


def see(image_path, question="Describe this image in detail.",
        max_tokens=512, temperature=0.2, timeout=600) -> dict:
    """Ask `question` about `image_path` via Urai runtime. {"ok",...}."""
    try:
        url = _data_url(image_path)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    try:
        from .urai_runtime import complete_with_image
        res = complete_with_image(url, question, max_tokens=max_tokens,
                                  temperature=temperature)
        return {"ok": True, "answer": res["answer"],
                "model": res.get("model", ""), "backend": "urai",
                "image": res.get("image", {})}
    except Exception as e:
        return {"ok": False,
                "error": f"{str(e)[:200]} — Urai runtime not loaded"}
