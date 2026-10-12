#!/usr/bin/env python3
"""Imagine: text-to-image generation via stable-diffusion.cpp (local, CPU-ok).

Backend: `third_party/stable-diffusion.cpp` `sd` CLI (open source, MIT) —
https://github.com/leejet/stable-diffusion.cpp
Default checkpoint: SD-Turbo (open weights, CreativeML Open RAIL++-M) —
https://huggingface.co/stabilityai/sd-turbo — 1-4 steps, 512px, CPU-feasible.

Build the runner once:
    git clone --depth 1 https://github.com/leejet/stable-diffusion.cpp.git \\
        third_party/stable-diffusion.cpp
    cmake -S third_party/stable-diffusion.cpp -B third_party/stable-diffusion.cpp/build \\
        -DCMAKE_BUILD_TYPE=Release -DSD_CUBLAS=OFF
    cmake --build third_party/stable-diffusion.cpp/build -j$(nproc) --target sd
Then:
    ./bin/urai model download sd-turbo
    ./bin/urai imagine "a robot reading a book" -o out.png

Stdlib only. Generation runs synchronously in-process timeout-guarded.
"""

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SD_BIN = ROOT / "third_party" / "stable-diffusion.cpp" / "build" / "bin" / "sd"
OUT_DIR = ROOT / "out" / "images"
TIMEOUT_S = int(os.environ.get("URAI_IMAGINE_TIMEOUT", "900"))


def status() -> dict:
    from . import models_registry as reg
    m = reg.load()["models"]["sd-turbo"]
    ckpt = ROOT / m["path"]
    return {"runner": str(SD_BIN), "runner_built": SD_BIN.exists(),
            "checkpoint": str(ckpt),
            "checkpoint_ready": ckpt.exists() and ckpt.stat().st_size > 0,
            "defaults": {"steps": m.get("steps", 2),
                         "size": m.get("size", [512, 512])}}


def generate(prompt: str, out: str = None, steps: int = None,
             width: int = None, height: int = None,
             seed: int = 7) -> dict:
    """Render `prompt` to a PNG. Returns {"ok", "path"|"error", ...}."""
    from . import models_registry as reg
    st = status()
    if not st["runner_built"]:
        return {"ok": False,
                "error": f"sd runner not built: {SD_BIN} — see jev/imagine.py header"}
    m = reg.load()["models"]["sd-turbo"]
    ckpt = ROOT / m["path"]
    if not (ckpt.exists() and ckpt.stat().st_size > 0):
        return {"ok": False,
                "error": f"checkpoint missing: {ckpt} — run: urai model download sd-turbo"}
    steps = steps or m.get("steps", 2)
    w, h = width or 512, height or 512
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = Path(out) if out else OUT_DIR / f"urai-{stamp}-s{seed}.png"
    cmd = [str(SD_BIN), "-m", str(ckpt), "-p", prompt, "-o", str(dest),
           "-W", str(w), "-H", str(h), "--steps", str(steps),
           "--seed", str(seed), "-t", str(max(1, (os.cpu_count() or 4) - 1))]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=TIMEOUT_S, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"generation timed out after {TIMEOUT_S}s"}
    if not dest.exists():
        tail = (p.stdout + p.stderr)[-800:]
        return {"ok": False, "error": f"sd-cli failed: {tail}"}
    return {"ok": True, "path": str(dest), "prompt": prompt,
            "steps": steps, "size": [w, h], "seed": seed,
            "elapsed_s": round(time.time() - t0, 1)}
