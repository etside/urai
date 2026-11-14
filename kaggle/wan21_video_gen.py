#!/usr/bin/env python3
"""WAN 2.1 Video Generation on Kaggle T4 (free GPU) — Urai video gen kernel.

Usage on Kaggle:
  1. Create notebook, GPU T4 x2, Internet ON.
  2. Paste this file or upload as input.
  3. Set PROMPT env var or edit prompt below.
  4. Run all → video lands in /kaggle/working/output.mp4
  5. Download and use, or push to Urai via API.

WAN 2.1 is Apache 2.0, open-weight by ByteDance.
Source: https://github.com/Wan-Video/Wan2.1
"""

import os
import subprocess
import sys
import json
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
PROMPT = os.environ.get("URAI_VIDEO_PROMPT",
    "A red paper boat drifts slowly across a sunlit pond. "
    "Locked camera. Soft water sounds. Cinematic, 4K.")
DURATION = int(os.environ.get("URAI_VIDEO_DURATION", "5"))  # seconds
WIDTH = int(os.environ.get("URAI_VIDEO_WIDTH", "832"))
HEIGHT = int(os.environ.get("URAI_VIDEO_HEIGHT", "480"))
RATIO = os.environ.get("URAI_VIDEO_RATIO", "16:9")
SEED = int(os.environ.get("URAI_VIDEO_SEED", "42"))
MODEL_SIZE = os.environ.get("URAI_WAN_MODEL", "1.3B")  # 1.3B fits T4; 14B needs A100
OUTPUT = "/kaggle/working/output.mp4"
URAI_PUSH_URL = os.environ.get("URAI_API_URL", "")  # optional: push result back to Urai
URAI_API_KEY = os.environ.get("URAI_API_KEY", "")

# ── Install dependencies ──────────────────────────────────────────────────────
def install():
    pkgs = ["torch", "torchvision", "diffusers>=0.31", "transformers",
            "accelerate", "imageio[ffmpeg]", "einops", "timm", "sentencepiece"]
    for pkg in pkgs:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", pkg],
                       check=False)
    # Install WAN 2.1 from GitHub
    wan_dir = Path("/kaggle/working/Wan2.1")
    if not wan_dir.exists():
        subprocess.run(["git", "clone", "--depth", "1",
                        "https://github.com/Wan-Video/Wan2.1.git",
                        str(wan_dir)], check=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", str(wan_dir)],
                       check=False)

# ── Download model ────────────────────────────────────────────────────────────
def download_model():
    from huggingface_hub import snapshot_download
    model_id = {
        "1.3B": "Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
        "14B": "Wan-AI/Wan2.1-T2V-14B-Diffusers",
    }.get(MODEL_SIZE, "Wan-AI/Wan2.1-T2V-1.3B-Diffusers")
    print(f"Downloading {model_id}...")
    model_dir = snapshot_download(model_id, cache_dir="/kaggle/working/models",
                                   ignore_patterns=["*.bin"])  # prefer safetensors
    return model_dir

# ── Generate video ────────────────────────────────────────────────────────────
def generate(model_dir: str):
    import torch
    from diffusers import AutoencoderKLWan, WanPipeline
    from diffusers.schedulers.scheduling_unipc_multistep import UniPCMultistepScheduler

    print(f"GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
    print(f"Prompt: {PROMPT}")
    print(f"Duration: {DURATION}s | Size: {WIDTH}x{HEIGHT} | Model: {MODEL_SIZE}")

    # 1.3B runs fine on T4 (16GB); 14B needs A100
    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32

    # Load VAE separately for memory efficiency
    vae = AutoencoderKLWan.from_pretrained(model_dir, subfolder="vae", torch_dtype=dtype)
    pipe = WanPipeline.from_pretrained(model_dir, vae=vae, torch_dtype=dtype)
    pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config,
                                                          flow_shift=8.0)
    if torch.cuda.is_available():
        pipe.to("cuda")
    else:
        pipe.enable_sequential_cpu_offload()

    # Frame count: WAN uses ~16fps, so duration * 16 frames
    num_frames = max(16, DURATION * 16)

    output = pipe(
        prompt=PROMPT,
        negative_prompt="blurry, low quality, artifacts, watermark",
        height=HEIGHT,
        width=WIDTH,
        num_frames=num_frames,
        guidance_scale=5.0,
        num_inference_steps=50,
        generator=torch.Generator().manual_seed(SEED),
    )

    # Export to MP4
    import imageio
    frames = output.frames[0]  # list of PIL images
    writer = imageio.get_writer(OUTPUT, fps=16, quality=8)
    for frame in frames:
        import numpy as np
        writer.append_data(np.array(frame))
    writer.close()

    print(f"Video saved to {OUTPUT}")
    return OUTPUT


# ── Push result back to Urai (optional) ──────────────────────────────────────
def push_to_urai(video_path: str):
    if not URAI_PUSH_URL or not URAI_API_KEY:
        print("URAI_API_URL or URAI_API_KEY not set — skipping push")
        return
    import urllib.request
    with open(video_path, "rb") as f:
        video_data = f.read()
    import base64
    b64 = base64.b64encode(video_data).decode()
    payload = json.dumps({
        "video_b64": b64,
        "prompt": PROMPT,
        "backend": "wan21",
        "model": MODEL_SIZE,
        "duration": DURATION,
        "width": WIDTH,
        "height": HEIGHT,
    }).encode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {URAI_API_KEY}",
    }
    req = urllib.request.Request(URAI_PUSH_URL.rstrip("/") + "/v1/videos/ingest",
                                  payload, headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.load(r)
            print("Pushed to Urai:", resp)
    except Exception as e:
        print(f"Push failed (video still at {video_path}): {e}")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Urai WAN 2.1 Video Generation ===")
    print("Apache 2.0 open-weight model by ByteDance")
    print("Source: https://github.com/Wan-Video/Wan2.1\n")

    install()
    model_dir = download_model()
    video_path = generate(model_dir)
    push_to_urai(video_path)

    print(f"\nDone! Download {video_path} from Kaggle output.")
    print("To run again with different prompt:")
    print("  URAI_VIDEO_PROMPT='your prompt' python3 wan21_video_gen.py")
