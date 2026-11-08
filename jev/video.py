#!/usr/bin/env python3
"""Video: local-only text-to-video for Urai (frames + ffmpeg animatic).

The LOCAL path renders N still frames with the on-disk image checkpoint
(sd-turbo via stable-diffusion.cpp) and stitches them into an MP4 slideshow
with ffmpeg. No external provider or relay is ever contacted.

Stdlib only.
"""

import base64
import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "out" / "videos"
TIMEOUT_S = int(os.environ.get("URAI_VIDEO_TIMEOUT", "1200"))
MAX_FRAMES = int(os.environ.get("URAI_VIDEO_MAX_FRAMES", "16"))


def _ffmpeg():
    return shutil.which("ffmpeg")


def status() -> dict:
    from . import models_registry as reg
    st = {"runner": "ffmpeg", "ffmpeg": bool(_ffmpeg()),
          "local_frames": False, "providers": {}, "out_dir": str(OUT_DIR),
          "note": ("Local path = sd-turbo frames + ffmpeg slideshow "
                    "(animatic-grade). Generation runs on Urai's local "
                    "checkpoint only; no external relay is used.")}
    try:
        m = reg.load()["models"]["sd-turbo"]
        ckpt = ROOT / m["path"]
        st["local_frames"] = ckpt.exists() and ckpt.stat().st_size > 0
    except Exception:
        st["local_frames"] = False
    st["profiles"] = profiles()
    return st


def profiles() -> list:
    """Media profiles surfaced to the UI/API.

    Only the local path is advertised: sd-turbo frames (via
    stable-diffusion.cpp) stitched into an MP4 slideshow with ffmpeg.
    External relays (Wan / Seedream / H3) are not listed — per the
    no-external-AI rule they are not part of this deployment.
    """
    try:
        from . import imagine as _imagine
        st = _imagine.status()
        local_image = bool(st.get("runner_built") and st.get("checkpoint_ready"))
    except Exception:
        local_image = False
    local_video = bool(_ffmpeg() and local_image)
    return [
        {"id": "local_animatic", "label": "Urai local animatic",
         "kind": "video", "grade": "Local (CPU, frames + ffmpeg)",
         "available": local_video,
         "detail": "Local sd-turbo frames stitched with ffmpeg. "
                   "Needs sd-turbo checkpoint + ffmpeg on the server."},
        {"id": "local_image", "label": "Urai local image",
         "kind": "image", "grade": "Local (CPU, sd-turbo)",
         "available": local_image,
         "detail": "Local image generation via stable-diffusion.cpp (CPU). "
                   "Needs sd-turbo checkpoint on the server."},
    ]


def _post_json(url, payload, key=None, timeout=300):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, json.dumps(payload).encode(), headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _provider_call(provider, prompt, duration, width, height, provider_url=None,
                   provider_key=None):
    """Proxy to an external SOTA video provider. Returns provider JSON."""
    provider = (provider or "").lower()
    if provider in ("higgsfield", "higgs") or (not provider and os.environ.get("HIGGSFIELD_API_KEY") and not provider_url):
        base = (provider_url or os.environ.get("HIGGSFIELD_BASE_URL",
                                               "https://api.higgsfield.ai/v1")).rstrip("/")
        key = provider_key or os.environ.get("HIGGSFIELD_API_KEY", "")
        data = _post_json(base + "/videos/generations",
                          {"prompt": prompt, "duration": duration,
                           "width": width, "height": height}, key=key or None)
        return {"ok": True, "provider": "higgsfield", "result": data}
    if provider in ("runway",) or (not provider and os.environ.get("RUNWAY_API_KEY") and not provider_url):
        base = (provider_url or os.environ.get("RUNWAY_BASE_URL", "")).rstrip("/")
        key = provider_key or os.environ.get("RUNWAY_API_KEY", "")
        if not base:
            return {"ok": False, "error": "RUNWAY_BASE_URL not set"}
        data = _post_json(base + "/videos/generations",
                          {"prompt": prompt, "duration": duration,
                           "width": width, "height": height}, key=key or None)
        return {"ok": True, "provider": "runway", "result": data}
    if provider_url:
        data = _post_json(provider_url,
                          {"prompt": prompt, "duration": duration,
                           "width": width, "height": height},
                          key=provider_key)
        return {"ok": True, "provider": "custom", "result": data}
    return {"ok": False, "error": "no provider configured"}


def generate(prompt: str, out: str = None, duration: int = 4, width: int = 512,
             height: int = 512, fps: int = 4, seed: int = 7,
             provider: str = "auto", provider_url: str = None,
             provider_key: str = None, ref_images=None, profile=None,
             settings=None) -> dict:
    """Render prompt to MP4 via the LOCAL path only (no external relay).

    Local path = sd-turbo frames + ffmpeg animatic. External provider
    parameters are ignored (no-external-AI rule).
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "error": "prompt required"}
    # External / SOTA ids are rejected honestly instead of faking presence.
    prov = (provider or "auto").lower()
    if prov in ("ref2va", "ref2va-vsa", "ref2va_vsa", "h3", "h3-vsa", "vsa",
                "wan3", "wan3.0", "wan", "dashscope",
                "higgsfield", "higgs", "runway", "custom"):
        return {"ok": False, "installed": False, "provider": prov,
                "error": "external / SOTA video is not part of this deployment; "
                         "use the local animatic profile (local_animatic)"}
    duration = max(1, min(int(duration or 4), 12))
    fps = max(1, min(int(fps or 4), 12))
    n_frames = min(duration * fps, MAX_FRAMES)

    # Local path: frames + ffmpeg slideshow.
    if not _ffmpeg():
        return {"ok": False, "error": "ffmpeg not found on server; install ffmpeg for the local animatic"}
    from . import imagine as _imagine
    st = _imagine.status()
    if not st.get("runner_built") or not st.get("checkpoint_ready"):
        return {"ok": False, "error": "local image checkpoint/runner missing; run: urai model download sd-turbo"}

    ts = time.strftime("%Y%m%d-%H%M%S")
    job = f"vid-{ts}-{seed}"
    fdir = OUT_DIR / job
    fdir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i in range(n_frames):
        fp = fdir / f"frame{i:03d}.png"
        r = _imagine.generate(f"{prompt} (frame {i + 1}/{n_frames}, slight variation)",
                              str(fp), steps=1, width=width, height=height,
                              seed=seed + i)
        if not r.get("ok"):
            return {"ok": False, "error": f"frame {i + 1} failed: {r.get('error')}",
                    "id": job}
        frames.append(str(fp))
    mp4 = Path(out) if out else (OUT_DIR / f"{job}.mp4")
    mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i", str(fdir / "frame%03d.png"),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", str(mp4)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "ffmpeg timed out", "id": job}
    if p.returncode != 0 or not mp4.exists():
        return {"ok": False, "error": (p.stderr or "")[-500:], "id": job}
    meta = {"ok": True, "id": job, "path": str(mp4), "frames": n_frames,
            "duration": duration, "fps": fps, "width": width, "height": height,
            "grade": "local animatic (CPU frames + ffmpeg)",
            "cost": 0}
    try:
        (OUT_DIR / f"{job}.json").write_text(json.dumps(meta, indent=2))
    except Exception:
        pass
    return meta


def job_info(job_id: str) -> dict:
    job_id = (job_id or "").strip().replace("/", "")
    if not job_id:
        return {"ok": False, "error": "job id required"}
    mf = OUT_DIR / f"{job_id}.json"
    if mf.is_file():
        try:
            d = json.loads(mf.read_text())
            d["ok"] = True
            return d
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}
    # maybe an mp4 with that stem exists
    for ext in (".mp4",):
        f = OUT_DIR / f"{job_id}{ext}"
        if f.is_file():
            return {"ok": True, "id": job_id, "path": str(f)}
    return {"ok": False, "error": "unknown job id"}
