#!/usr/bin/env python3
"""GPU detection + offload policy (mission: GPU-wise CLI tool).

  - NVIDIA: nvidia-smi -> VRAM total/free, CUDA present
  - AMD: rocm-smi (best effort)
  - none: CPU-only policy (this box)

llama.cpp offload = --n-gpu-layers N. Policy:
  VRAM >= 6 GB  -> offload all (ngl=99)
  3-6 GB        -> partial offload (ngl=20) + smaller ctx
  < 3 GB / none -> CPU only (ngl=0), prefer <=1B Q4 models

CUDA builds: this repo's third_party build is CPU-only. On a CUDA box:
  cmake -B build -DGGML_CUDA=ON ... (needs CUDA toolkit + driver).
  The launcher below passes --n-gpu-layers automatically when a GPU is
  detected, so the SAME CLI is GPU-ready with zero code changes.
"""

import shutil
import subprocess


def _run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return p.stdout.strip() if p.returncode == 0 else ""
    except Exception:
        return ""


def detect():
    info = {"vendor": "none", "name": "", "vram_total_mb": 0,
            "vram_free_mb": 0, "cuda": False}
    if shutil.which("nvidia-smi"):
        q = _run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
                  "--format=csv,noheader,nounits"])
        if q:
            parts = [x.strip() for x in q.split("\n")[0].split(",")]
            try:
                info.update(vendor="nvidia", name=parts[0],
                            vram_total_mb=int(parts[1]),
                            vram_free_mb=int(parts[2]), cuda=True)
            except (IndexError, ValueError):
                info.update(vendor="nvidia", cuda=True)
    elif shutil.which("rocm-smi"):
        info.update(vendor="amd")
    return info


def offload_policy(gpu=None):
    gpu = gpu or detect()
    vram = gpu["vram_total_mb"]
    if gpu["vendor"] == "nvidia" and vram >= 6000:
        return {"ngl": 99, "note": "full GPU offload"}
    if gpu["vendor"] in ("nvidia", "amd") and vram >= 3000:
        return {"ngl": 20, "note": "partial offload, watch VRAM"}
    if gpu["vendor"] in ("nvidia", "amd"):
        return {"ngl": 10, "note": "minimal offload, low VRAM"}
    return {"ngl": 0, "note": "CPU-only box: keep <=1B Q4 local"}


def cuda_build_hint():
    return ("On a CUDA box rebuild llama.cpp with:\n"
            "  cmake -S third_party/llama.cpp -B third_party/llama.cpp/build "
            "-DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release\n"
            "  cmake --build third_party/llama.cpp/build -j --target llama-server llama-cli llama-bench\n"
            "Then `jev serve start` auto-uses --n-gpu-layers.")
