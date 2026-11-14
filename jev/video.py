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
    CHATCUT_API_KEY — ChatCut MCP server (Seedance 2.5, Kling 4, MiniMax H3, Gemini Omni)
    HIGGSFIELD_API_KEY / HIGGSFIELD_BASE_URL (default https://api.higgsfield.ai/v1)
    RUNWAY_API_KEY / RUNWAY_BASE_URL
  Generic: pass provider_url + provider_key in the request; Urai POSTs an
  OpenAI-style {prompt, duration, width, height} body and returns the result.

  ChatCut models: seedance-2-5 (default), seedance2, seedance2fast, seedance2mini,
                  kling, kling-4, minimax-h3, minimax-h3-max, omni

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

# Load .env so provider keys are available
try:
    from .envfile import load as _load_env
    _load_env()
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]

# ChatCut MCP server
CHATCUT_MCP_URL = "https://api.chatcut.io/api/external-mcp/mcp"
CHATCUT_MODELS = {
    "seedance-2-5": {"duration": (4, 30), "resolution": ["480p", "720p", "1080p"], "default_res": "720p"},
    "seedance2": {"duration": (4, 15), "resolution": ["480p", "720p", "1080p"], "default_res": "720p"},
    "seedance2fast": {"duration": (4, 15), "resolution": ["480p", "720p"], "default_res": "720p"},
    "seedance2mini": {"duration": (4, 15), "resolution": ["480p", "720p"], "default_res": "720p"},
    "kling": {"duration": (1, 10), "resolution": ["720p", "1080p"], "default_res": "720p"},
    "kling-4": {"duration": (3, 30), "resolution": ["720p", "1080p"], "default_res": "720p"},
    "minimax-h3": {"duration": (4, 15), "resolution": ["768p", "2k"], "default_res": "768p"},
    "minimax-h3-max": {"duration": (5, 15), "resolution": ["480p", "768p"], "default_res": "768p"},
    "omni": {"duration": (3, 10), "resolution": ["360p", "720p", "1080p", "4k"], "default_res": "720p"},
}


def _chatcut_generate(prompt: str, model: str = "seedance-2-5", duration: int = 5,
                       ratio: str = "16:9", resolution: str = None,
                       first_frame: str = None, last_frame: str = None,
                       ref_images: list = None, ref_audios: list = None) -> dict:
    """Generate video via ChatCut MCP server.

    Requires CHATCUT_API_KEY environment variable.
    Returns {"ok", "job_id", "provider", "model"} or {"ok": False, "error"}.
    """
    key = os.environ.get("CHATCUT_API_KEY", "")
    if not key:
        return {"ok": False, "error": "CHATCUT_API_KEY not set"}

    model_info = CHATCUT_MODELS.get(model, CHATCUT_MODELS["seedance-2-5"])
    min_dur, max_dur = model_info["duration"]
    duration = max(min_dur, min(max_dur, duration))
    res = resolution or model_info["default_res"]

    args = {
        "model": model,
        "prompt": prompt,
        "durationSeconds": duration,
        "ratio": ratio,
        "resolution": res,
    }
    if first_frame:
        args["firstFrame"] = first_frame
    if last_frame:
        args["lastFrame"] = last_frame
    if ref_images:
        args["refImages"] = ref_images if isinstance(ref_images, list) else [ref_images]
    if ref_audios:
        args["refAudios"] = ref_audios if isinstance(ref_audios, list) else [ref_audios]

    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "submit_video", "arguments": args},
        "id": 1,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "x-chatcut-mcp-client": "urai",
        "x-chatcut-mcp-surface": "embedded-preview",
        "x-chatcut-plugin-version": "1.3.0",
        "x-chatcut-install-source": "urai_marketplace",
    }

    try:
        req = urllib.request.Request(
            CHATCUT_MCP_URL,
            json.dumps(payload).encode(),
            headers,
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.load(resp)
    except Exception as e:
        return {"ok": False, "error": f"ChatCut MCP request failed: {e}"}

    if "error" in data:
        return {"ok": False, "error": f"ChatCut error: {data['error']}"}

    result = data.get("result", {})
    if isinstance(result, dict) and result.get("content"):
        # MCP tool result
        content = result["content"]
        if isinstance(content, list):
            for item in content:
                if item.get("type") == "text":
                    try:
                        job_data = json.loads(item["text"])
                        job_id = job_data.get("jobId") or job_data.get("id")
                        if job_id:
                            return {"ok": True, "job_id": job_id, "provider": "chatcut",
                                    "model": model, "status": "pending",
                                    "note": f"ChatCut job submitted. Poll GET /v1/videos/{job_id} for status."}
                    except Exception:
                        pass
        # Return raw result
        return {"ok": True, "provider": "chatcut", "model": model,
                "result": str(result)[:500], "status": "submitted"}

    return {"ok": False, "error": f"Unexpected ChatCut response: {str(data)[:300]}"}
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
             provider_key: str = None, model: str = None,
             ratio: str = "16:9", resolution: str = None,
             first_frame: str = None, last_frame: str = None,
             ref_images: list = None, ref_audios: list = None) -> dict:
    """Render prompt to MP4. Returns {"ok", "id", "path"|"error", ...}.

    Provider priority (auto):
      1. ChatCut (CHATCUT_API_KEY) — Seedance 2.5 / Kling 4 / MiniMax / Omni
      2. Higgsfield (HIGGSFIELD_API_KEY)
      3. Runway (RUNWAY_API_KEY)
      4. Generic provider_url
      5. Local sd-turbo + ffmpeg slideshow
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "error": "prompt required"}
    duration = max(1, min(int(duration or 4), 30))
    fps = max(1, min(int(fps or 4), 12))

    # Normalize provider
    prov = (provider or "auto").lower().strip()

    # 1. ChatCut provider
    chatcut_models = {
        "chatcut": model or "seedance-2-5",
        "chatcut-seedance": "seedance-2-5",
        "chatcut-kling": "kling",
        "chatcut-kling4": "kling-4",
        "chatcut-minimax": "minimax-h3",
        "chatcut-minimax-max": "minimax-h3-max",
        "chatcut-omni": "omni",
    }
    if prov in chatcut_models or (prov == "auto" and os.environ.get("CHATCUT_API_KEY")):
        cc_model = chatcut_models.get(prov, model or "seedance-2-5")
        res = _chatcut_generate(prompt, cc_model, duration, ratio, resolution,
                                first_frame, last_frame, ref_images, ref_audios)
        if res["ok"] or prov != "auto":
            return res
        # else fall through

    # 2. External SOTA provider path (Higgsfield / Runway / generic)
    n_frames = min(duration * fps, MAX_FRAMES)
    use_provider = prov not in ("", "auto", "local", "none")
    env_provider = os.environ.get("HIGGSFIELD_API_KEY") or os.environ.get("RUNWAY_API_KEY")
    if use_provider or (prov == "auto" and env_provider and not _ffmpeg()):
        res = _provider_call(provider if use_provider else "", prompt, duration,
                             width, height, provider_url, provider_key)
        if res["ok"] or use_provider:
            return res

    # 3. Local fallback: frames + ffmpeg slideshow
    if not _ffmpeg():
        return {"ok": False, "error": (
            "No video provider configured. Set CHATCUT_API_KEY for Seedance/Kling/MiniMax/Omni, "
            "HIGGSFIELD_API_KEY, RUNWAY_API_KEY, or install ffmpeg for local animatic."
        )}
    from . import imagine as _imagine
    st = _imagine.status()
    if not st.get("runner_built") or not st.get("checkpoint_ready"):
        return {"ok": False, "error": (
            "Local video requires sd-turbo. Set CHATCUT_API_KEY for cloud video "
            "(Seedance 2.5, Kling 4, MiniMax H3), or run: urai model download sd-turbo"
        )}

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
            "grade": "animatic (local CPU slideshow — set CHATCUT_API_KEY for Seedance/Kling/MiniMax)",
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
