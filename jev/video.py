#!/usr/bin/env python3
"""Video: open-source text-to-video for Urai.

All backends are free, open-weight, and self-hostable. No paid API keys required.

Local backends (ranked by quality, auto-selected):
  1. WAN 2.1       — ByteDance open-weight T2V (Apache 2.0, 17B params, best quality)
                     https://github.com/Wan-Video/Wan2.1
                     Install: urai model download wan2.1
                     GPU: 8GB+ VRAM recommended; CPU: very slow
  2. LTX-Video     — Lightricks open-weight T2V (Apache 2.0, fast, good quality)
                     https://github.com/Lightricks/LTX-Video
                     Install: urai model download ltx-video
                     GPU: 8GB+ VRAM; CPU: slow
  3. AnimateDiff   — SD-based animation (Apache 2.0, motion LoRA patterns)
                     Install: urai model download animatediff
                     GPU: 6GB+ VRAM; CPU: very slow
  4. Animatic      — sd-turbo frames + ffmpeg slideshow (always available, CPU-ok)
                     Not true video gen, but works on any hardware with sd-turbo downloaded

Video gen patterns inspired by (all open-source):
  Seedance (ByteDance): 8-element prompt structure, multi-shot storyboards
  Kling (Kuaishou): camera-control language, firstFrame/lastFrame transitions
  LTX-Video: fast generation, style consistency
  WAN 2.1: image-to-video, reference-guided generation

Env vars (all optional):
  URAI_VIDEO_BACKEND  — force a backend: wan21 | ltx | animatediff | animatic | auto
  URAI_VIDEO_TIMEOUT  — generation timeout in seconds (default 1200)
  URAI_VIDEO_MAX_FRAMES — max frames for animatic fallback (default 16)
  URAI_WAN_PATH       — path to wan2.1 inference script (default: third_party/wan2.1/)
  URAI_LTX_PATH       — path to ltx-video inference script (default: third_party/ltx-video/)

Stdlib only for the core module; heavy imports (torch, diffusers) are lazy.
"""

import base64
import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

try:
    from .envfile import load as _load_env
    _load_env()
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "out" / "videos"
TIMEOUT_S = int(os.environ.get("URAI_VIDEO_TIMEOUT", "1200"))
MAX_FRAMES = int(os.environ.get("URAI_VIDEO_MAX_FRAMES", "16"))

# Backend paths
WAN_DIR = Path(os.environ.get("URAI_WAN_PATH", str(ROOT / "third_party" / "wan2.1")))
LTX_DIR = Path(os.environ.get("URAI_LTX_PATH", str(ROOT / "third_party" / "LTX-Video")))
ANIM_DIR = ROOT / "third_party" / "AnimateDiff"


# ── Prompt engineering (learned from Seedance/Kling open references) ──────────

def build_prompt(prompt: str, style: str = "cinematic", motion: str = None,
                 camera: str = None, audio: str = None) -> str:
    """Structure a video prompt using the 8-element pattern from open research.

    Seedance open research identified 8 elements for best T2V results:
    [Subject] [Action] [Environment] [Camera] [Lighting] [Mood] [Style] [Audio]
    """
    parts = [prompt.strip()]
    if camera:
        parts.append(camera)
    if motion:
        parts.append(motion)
    if style and style not in prompt.lower():
        parts.append(f"{style} style")
    if audio:
        parts.append(f"({audio})")
    return ". ".join(p.rstrip(".") for p in parts if p)


# ── Backend detection ─────────────────────────────────────────────────────────

def _detect_backend() -> str:
    """Return the best available video backend."""
    forced = os.environ.get("URAI_VIDEO_BACKEND", "auto").lower()
    if forced != "auto":
        return forced

    # WAN 2.1 (best quality, needs GPU ideally)
    wan_script = WAN_DIR / "generate.py"
    wan_model = ROOT / "model" / "video" / "wan2.1"
    if wan_script.exists() and wan_model.exists():
        return "wan21"

    # LTX-Video (fast, good quality)
    ltx_script = LTX_DIR / "inference.py"
    ltx_model = ROOT / "model" / "video" / "ltx-video"
    if ltx_script.exists() and ltx_model.exists():
        return "ltx"

    # AnimateDiff (SD-based, motion LoRA)
    anim_script = ANIM_DIR / "animate.py"
    if anim_script.exists():
        return "animatediff"

    # Animatic fallback (always available if sd-turbo downloaded)
    return "animatic"


# ── WAN 2.1 backend ───────────────────────────────────────────────────────────

def _wan21_generate(prompt: str, out: str, duration: int = 4, width: int = 480,
                     height: int = 832, fps: int = 16, seed: int = 42,
                     first_frame: str = None) -> dict:
    """Generate video using WAN 2.1 (open-weight, Apache 2.0).

    WAN 2.1: https://github.com/Wan-Video/Wan2.1
    Supports text-to-video and image-to-video (firstFrame).
    Best quality; requires 8GB+ VRAM for GPU or runs (slowly) on CPU.
    """
    wan_script = WAN_DIR / "generate.py"
    if not wan_script.exists():
        return {"ok": False, "error": (
            f"WAN 2.1 script not found at {wan_script}. "
            "Run: urai model download wan2.1"
        )}
    wan_model_dir = ROOT / "model" / "video" / "wan2.1"
    if not wan_model_dir.exists():
        return {"ok": False, "error": (
            f"WAN 2.1 model not found at {wan_model_dir}. "
            "Run: urai model download wan2.1"
        )}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        "python3", str(wan_script),
        "--task", "i2v-14B" if first_frame else "t2v-14B",
        "--size", f"{width}*{height}",
        "--ckpt_dir", str(wan_model_dir),
        "--sample_steps", "50",
        "--sample_guide_scale", "5",
        "--sample_shift", "8",
        "--frame_num", str(max(16, duration * fps // 4 * 4)),  # must be divisible by 4
        "--prompt", prompt,
        "--save_file", str(out),
    ]
    if first_frame and Path(first_frame).exists():
        cmd.extend(["--image", str(first_frame)])

    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=TIMEOUT_S, cwd=str(WAN_DIR))
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"WAN 2.1 timed out after {TIMEOUT_S}s"}
    if p.returncode != 0 or not Path(out).exists():
        return {"ok": False, "error": f"WAN 2.1 failed: {(p.stderr or p.stdout)[-500:]}"}
    return {"ok": True, "path": str(out), "backend": "wan21", "prompt": prompt,
            "elapsed_s": round(time.time() - t0, 1)}


# ── LTX-Video backend ─────────────────────────────────────────────────────────

def _ltx_generate(prompt: str, out: str, duration: int = 4, width: int = 704,
                   height: int = 480, fps: int = 24, seed: int = 42,
                   first_frame: str = None, last_frame: str = None) -> dict:
    """Generate video using LTX-Video (open-weight, Apache 2.0).

    LTX-Video: https://github.com/Lightricks/LTX-Video
    Fast generation, good quality, supports firstFrame/lastFrame.
    8B+ VRAM recommended.
    """
    ltx_script = LTX_DIR / "inference.py"
    if not ltx_script.exists():
        return {"ok": False, "error": (
            f"LTX-Video script not found at {ltx_script}. "
            "Run: urai model download ltx-video"
        )}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n_frames = max(8, min(257, duration * fps))
    cmd = [
        "python3", str(ltx_script),
        "--ckpt_dir", str(ROOT / "model" / "video" / "ltx-video"),
        "--prompt", prompt,
        "--height", str(height),
        "--width", str(width),
        "--num_frames", str(n_frames),
        "--frame_rate", str(fps),
        "--seed", str(seed),
        "--output_path", str(out),
    ]
    if first_frame and Path(first_frame).exists():
        cmd.extend(["--conditioning_media_paths", str(first_frame),
                    "--conditioning_start_frames", "0"])
    if last_frame and Path(last_frame).exists():
        cmd.extend(["--conditioning_media_paths", str(last_frame),
                    "--conditioning_start_frames", str(n_frames - 1)])

    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=TIMEOUT_S, cwd=str(LTX_DIR))
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"LTX-Video timed out after {TIMEOUT_S}s"}
    # LTX may output to a directory; find the mp4
    out_path = Path(out)
    if not out_path.exists():
        # Try finding generated file
        candidates = list(OUT_DIR.glob("*.mp4")) + list(Path(str(out)).parent.glob("*.mp4"))
        if candidates:
            out_path = max(candidates, key=lambda f: f.stat().st_mtime)
        else:
            return {"ok": False, "error": f"LTX-Video failed: {(p.stderr or p.stdout)[-500:]}"}
    return {"ok": True, "path": str(out_path), "backend": "ltx", "prompt": prompt,
            "elapsed_s": round(time.time() - t0, 1)}


# ── Animatic fallback (sd-turbo + ffmpeg) ────────────────────────────────────

def _animatic_generate(prompt: str, out: str, duration: int = 4, width: int = 512,
                        height: int = 512, fps: int = 4, seed: int = 7) -> dict:
    """Ken-Burns-style animatic: sd-turbo frames + ffmpeg slideshow.

    Not true video gen — good for quick previews on CPU-only hardware.
    Requires sd-turbo model downloaded and ffmpeg installed.
    """
    if not shutil.which("ffmpeg"):
        return {"ok": False, "error": (
            "ffmpeg not found. Install ffmpeg or download WAN 2.1 for real video gen: "
            "urai model download wan2.1"
        )}
    from . import imagine as _imagine
    st = _imagine.status()
    if not st.get("runner_built") or not st.get("checkpoint_ready"):
        return {"ok": False, "error": (
            "Animatic needs sd-turbo. Run: urai model download sd-turbo\n"
            "Or for real video: urai model download wan2.1"
        )}

    n_frames = min(duration * fps, MAX_FRAMES)
    ts = time.strftime("%Y%m%d-%H%M%S")
    job = f"vid-{ts}-{seed}"
    fdir = OUT_DIR / job
    fdir.mkdir(parents=True, exist_ok=True)

    for i in range(n_frames):
        fp = fdir / f"frame{i:03d}.png"
        r = _imagine.generate(
            f"{prompt} (frame {i + 1}/{n_frames}, slight motion variation)",
            str(fp), steps=1, width=width, height=height, seed=seed + i
        )
        if not r.get("ok"):
            return {"ok": False, "error": f"frame {i + 1} failed: {r.get('error')}", "id": job}

    mp4 = Path(out) if out else (OUT_DIR / f"{job}.mp4")
    mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-framerate", str(fps),
           "-i", str(fdir / "frame%03d.png"),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", str(mp4)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "ffmpeg timed out", "id": job}
    if p.returncode != 0 or not mp4.exists():
        return {"ok": False, "error": (p.stderr or "")[-500:], "id": job}

    meta = {"ok": True, "id": job, "path": str(mp4), "frames": n_frames,
            "duration": duration, "fps": fps, "width": width, "height": height,
            "backend": "animatic",
            "note": "Ken-Burns animatic (sd-turbo frames). For real video: urai model download wan2.1",
            "cost": 0}
    try:
        (OUT_DIR / f"{job}.json").write_text(json.dumps(meta, indent=2))
    except Exception:
        pass
    return meta


# ── Status ────────────────────────────────────────────────────────────────────

def status() -> dict:
    from . import models_registry as reg
    backend = _detect_backend()
    st = {
        "backend": backend,
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "out_dir": str(OUT_DIR),
        "backends": {
            "wan21": {
                "available": (WAN_DIR / "generate.py").exists() and
                             (ROOT / "model" / "video" / "wan2.1").exists(),
                "note": "Best quality open-source T2V (Apache 2.0). urai model download wan2.1",
                "source": "https://github.com/Wan-Video/Wan2.1",
            },
            "ltx": {
                "available": (LTX_DIR / "inference.py").exists() and
                             (ROOT / "model" / "video" / "ltx-video").exists(),
                "note": "Fast open-source T2V (Apache 2.0). urai model download ltx-video",
                "source": "https://github.com/Lightricks/LTX-Video",
            },
            "animatediff": {
                "available": (ANIM_DIR / "animate.py").exists(),
                "note": "SD-based animation. urai model download animatediff",
                "source": "https://github.com/guoyww/AnimateDiff",
            },
            "animatic": {
                "available": bool(shutil.which("ffmpeg")),
                "note": "sd-turbo frames + ffmpeg. CPU-ok preview. urai model download sd-turbo",
            },
        },
    }
    # Check sd-turbo for animatic
    try:
        m = reg.load()["models"]["sd-turbo"]
        ckpt = ROOT / m["path"]
        st["backends"]["animatic"]["checkpoint_ready"] = (
            ckpt.exists() and ckpt.stat().st_size > 0
        )
    except Exception:
        st["backends"]["animatic"]["checkpoint_ready"] = False
    return st


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
    for ext in (".mp4", ".mov"):
        f = OUT_DIR / f"{job_id}{ext}"
        if f.is_file():
            return {"ok": True, "id": job_id, "path": str(f)}
    return {"ok": False, "error": "unknown job id"}


# ── Main generate ─────────────────────────────────────────────────────────────

def generate(prompt: str, out: str = None, duration: int = 4, width: int = 480,
             height: int = 832, fps: int = 16, seed: int = 7,
             backend: str = "auto", ratio: str = "16:9", resolution: str = "720p",
             first_frame: str = None, last_frame: str = None,
             style: str = "cinematic", camera: str = None,
             # Legacy compat params (ignored, kept for API compat)
             provider: str = None, provider_url: str = None,
             provider_key: str = None, model: str = None,
             ref_images: list = None, ref_audios: list = None) -> dict:
    """Generate a video. Returns {"ok", "path"|"error", "backend", ...}.

    All backends are open-source and free — no API keys needed.

    Backend priority (auto):
      1. wan21     — WAN 2.1 (best quality, needs model downloaded)
      2. ltx       — LTX-Video (fast, needs model downloaded)
      3. animatic  — sd-turbo frames + ffmpeg (CPU-ok preview)

    Setup:
      urai model download wan2.1    # recommended
      urai model download ltx-video # alternative
      urai model download sd-turbo  # for animatic preview
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "error": "prompt required"}

    # Apply ratio to dimensions if not explicitly set
    ratio_map = {
        "16:9": (854, 480), "9:16": (480, 854), "1:1": (512, 512),
        "4:3": (640, 480), "3:4": (480, 640), "21:9": (854, 368),
    }
    if ratio in ratio_map and (width, height) == (480, 832):
        width, height = ratio_map[ratio]

    # Resolution override
    res_map = {"480p": 480, "720p": 720, "1080p": 1080, "768p": 768}
    if resolution in res_map:
        target_h = res_map[resolution]
        if height != target_h:
            scale = target_h / height
            height = target_h
            width = int(width * scale // 2 * 2)  # keep even

    duration = max(1, min(int(duration or 4), 30))

    # Build structured prompt using open research patterns
    structured_prompt = build_prompt(prompt, style=style, camera=camera)

    ts = time.strftime("%Y%m%d-%H%M%S")
    dest = Path(out) if out else (OUT_DIR / f"urai-{ts}-s{seed}.mp4")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Choose backend
    chosen = (backend or "auto").lower()
    if chosen == "auto":
        chosen = _detect_backend()

    if chosen == "wan21":
        return _wan21_generate(structured_prompt, str(dest), duration,
                                width, height, fps, seed, first_frame)
    if chosen == "ltx":
        return _ltx_generate(structured_prompt, str(dest), duration,
                              width, height, fps, seed, first_frame, last_frame)
    if chosen == "animatic":
        return _animatic_generate(structured_prompt, str(dest), duration,
                                   width, height, min(fps, 8), seed)

    # Fallback: try animatic
    return _animatic_generate(structured_prompt, str(dest), duration,
                               width, height, min(fps, 8), seed)
