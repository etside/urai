#!/usr/bin/env python3
"""Video: honest text-to-video for Urai (local CPU fallback + provider proxy).

Capability statement (read before promising SOTA):
  Urai's LOCAL path renders N still frames with the on-disk image checkpoint
  (sd-turbo via stable-diffusion.cpp) and stitches them into an MP4 slideshow
  with ffmpeg. That is a Ken-Burns-style animatic — it is NOT in the same
  league as Veo3 / Wan / Seedance for motion realism, and we do not claim it
  is. To compete with those models, point Urai at them: set one of the
  provider env keys below (or pass provider_url + provider_key per request)
  and Urai proxies the job and returns the provider result transparently.

  Providers (env):
    HIGGSFIELD_API_KEY / HIGGSFIELD_BASE_URL (default https://api.higgsfield.ai/v1)
    RUNWAY_API_KEY / RUNWAY_BASE_URL
  Generic: pass provider_url + provider_key in the request; Urai POSTs an
  OpenAI-style {prompt, duration, width, height} body and returns the result.

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
                    "(animatic-grade, not Veo3-class). For SOTA motion, "
                    "configure a provider key; see docs/video-studios.md.")}
    try:
        m = reg.load()["models"]["sd-turbo"]
        ckpt = ROOT / m["path"]
        st["local_frames"] = ckpt.exists() and ckpt.stat().st_size > 0
    except Exception:
        st["local_frames"] = False
    for name in ("HIGGSFIELD", "RUNWAY"):
        st["providers"][name.lower()] = bool(os.environ.get(name + "_API_KEY"))
    return st


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
             provider_key: str = None) -> dict:
    """Render prompt to MP4. Returns {"ok", "id", "path"|"error", ...}."""
    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "error": "prompt required"}
    duration = max(1, min(int(duration or 4), 12))
    fps = max(1, min(int(fps or 4), 12))
    n_frames = min(duration * fps, MAX_FRAMES)

    # 1. External SOTA provider path (honest Veo3-class route).
    use_provider = (provider or "auto").lower() not in ("", "auto", "local", "none")
    env_provider = os.environ.get("HIGGSFIELD_API_KEY") or os.environ.get("RUNWAY_API_KEY")
    if use_provider or (provider == "auto" and env_provider and not _ffmpeg()):
        res = _provider_call(provider if use_provider else "", prompt, duration,
                             width, height, provider_url, provider_key)
        if res["ok"] or use_provider:
            return res
        # else fall through to local

    # 2. Local fallback: frames + ffmpeg slideshow.
    if not _ffmpeg():
        return {"ok": False, "error": "ffmpeg not found on server; install ffmpeg for local video, or set HIGGSFIELD_API_KEY / RUNWAY_API_KEY for SOTA providers (see docs/video-studios.md)"}
    from . import imagine as _imagine
    st = _imagine.status()
    if not st.get("runner_built") or not st.get("checkpoint_ready"):
        return {"ok": False, "error": "local image checkpoint/runner missing; run: urai model download sd-turbo (or configure a provider key)"}

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
            "grade": "animatic (local CPU slideshow — not Veo3-class; use a provider key for SOTA)",
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
