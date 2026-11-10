#!/usr/bin/env python3
"""Imagine: text-to-image generation via stable-diffusion.cpp (local, CPU-ok).

Backend: `third_party/stable-diffusion.cpp` `sd` CLI (open source, MIT) —
https://github.com/leejet/stable-diffusion.cpp
Default checkpoint: SD-Turbo (open weights, CreativeML Open RAIL++-M) —
https://huggingface.co/stabilityai/sd-turbo — 1-4 steps, 512px, CPU-feasible.

Build the runner once:
    git clone --depth 1 https://github.com/leejet/stable-diffusion.cpp.git \
        third_party/stable-diffusion.cpp
    cmake -S third_party/stable-diffusion.cpp -B third_party/stable-diffusion.cpp/build \
        -DCMAKE_BUILD_TYPE=Release
    cmake --build third_party/stable-diffusion.cpp/build -j$(nproc) --target sd-cli
Then:
    ./bin/urai model download sd-turbo
    ./bin/urai imagine "a robot reading a book" -o out.png

Stdlib only. Generation runs synchronously in-process timeout-guarded.
"""

import base64
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

# Load .env so OPENROUTER_API_KEY is available when called from CLI or scripts
try:
    from .envfile import load as _load_env
    _load_env()
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
SD_BIN = ROOT / "third_party" / "stable-diffusion.cpp" / "build" / "bin" / "sd-cli"
OUT_DIR = ROOT / "out" / "images"
TIMEOUT_S = int(os.environ.get("URAI_IMAGINE_TIMEOUT", "900"))

# Cloud image gen via OpenRouter (google/gemini-2.5-flash-image or gemini-3.1-flash-image)
OPENROUTER_IMAGE_MODEL = os.environ.get(
    "URAI_IMAGE_MODEL", "google/gemini-2.5-flash-image"
)


def _openrouter_generate(prompt: str, width: int = 512, height: int = 512) -> dict:
    """Generate image via OpenRouter image model. Returns {"ok", "path"|"error"}."""
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        return {"ok": False, "error": "OPENROUTER_API_KEY not set"}
    base = os.environ.get("OPENROUTER_BASE_URL",
                          "https://openrouter.ai/api/v1").rstrip("/")
    payload = {
        "model": OPENROUTER_IMAGE_MODEL,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "HTTP-Referer": "https://urai.ai",
        "X-Title": "Urai",
    }
    try:
        req = urllib.request.Request(
            base + "/chat/completions",
            json.dumps(payload).encode(),
            headers,
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.load(resp)
    except Exception as e:
        return {"ok": False, "error": f"OpenRouter request failed: {e}"}

    # Extract image from response (OpenRouter returns image as base64 or URL)
    try:
        content = data["choices"][0]["message"]["content"]
        # content may be a list of parts or a string with a URL/base64
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    img_url = part["image_url"].get("url", "")
                    if img_url.startswith("data:image"):
                        # base64 data URI
                        b64 = img_url.split(",", 1)[1]
                        OUT_DIR.mkdir(parents=True, exist_ok=True)
                        stamp = time.strftime("%Y%m%d-%H%M%S")
                        dest = OUT_DIR / f"urai-{stamp}-cloud.png"
                        dest.write_bytes(base64.b64decode(b64))
                        return {"ok": True, "path": str(dest), "prompt": prompt,
                                "provider": "openrouter", "model": OPENROUTER_IMAGE_MODEL}
                    elif img_url.startswith("http"):
                        # Download the image
                        OUT_DIR.mkdir(parents=True, exist_ok=True)
                        stamp = time.strftime("%Y%m%d-%H%M%S")
                        dest = OUT_DIR / f"urai-{stamp}-cloud.png"
                        with urllib.request.urlopen(img_url, timeout=60) as r:
                            dest.write_bytes(r.read())
                        return {"ok": True, "path": str(dest), "prompt": prompt,
                                "provider": "openrouter", "model": OPENROUTER_IMAGE_MODEL}
        elif isinstance(content, str):
            # May contain a URL or markdown image
            import re
            m = re.search(r'https?://\S+\.(?:png|jpg|jpeg|webp)', content)
            if m:
                img_url = m.group(0)
                OUT_DIR.mkdir(parents=True, exist_ok=True)
                stamp = time.strftime("%Y%m%d-%H%M%S")
                dest = OUT_DIR / f"urai-{stamp}-cloud.png"
                with urllib.request.urlopen(img_url, timeout=60) as r:
                    dest.write_bytes(r.read())
                return {"ok": True, "path": str(dest), "prompt": prompt,
                        "provider": "openrouter", "model": OPENROUTER_IMAGE_MODEL}
        return {"ok": False, "error": f"Could not extract image from response: {str(data)[:300]}"}
    except Exception as e:
        return {"ok": False, "error": f"Image extraction failed: {e}"}


def _pollinations_generate(prompt: str, width: int = 512, height: int = 512,
                            seed: int = 7) -> dict:
    """Generate image via Pollinations.ai (free, no API key needed).

    Returns {"ok", "path"|"error", "provider"}.
    """
    import urllib.parse
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = OUT_DIR / f"urai-{stamp}-poll-s{seed}.png"
    url = (f"https://image.pollinations.ai/prompt/"
           f"{urllib.parse.quote(prompt)}?width={width}&height={height}"
           f"&seed={seed}&nologo=true")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Urai/1.3"})
        with urllib.request.urlopen(req, timeout=120) as r:
            dest.write_bytes(r.read())
        if dest.exists() and dest.stat().st_size > 1000:
            return {"ok": True, "path": str(dest), "prompt": prompt,
                    "provider": "pollinations", "model": "pollinations-free",
                    "size": [width, height], "seed": seed}
        return {"ok": False, "error": "Pollinations returned empty/invalid image"}
    except Exception as e:
        return {"ok": False, "error": f"Pollinations request failed: {e}"}


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
    """Render `prompt` to a PNG. Returns {"ok", "path"|"error", ...}.

    Falls back to OpenRouter cloud image gen (OPENROUTER_API_KEY) when the
    local stable-diffusion.cpp runner or checkpoint is not available.
    """
    from . import models_registry as reg
    st = status()
    w, h = width or 512, height or 512

    # --- Local path (stable-diffusion.cpp) ---
    if st["runner_built"] and st["checkpoint_ready"]:
        m = reg.load()["models"]["sd-turbo"]
        ckpt = ROOT / m["path"]
        steps = steps or m.get("steps", 2)
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
        if dest.exists():
            return {"ok": True, "path": str(dest), "prompt": prompt,
                    "steps": steps, "size": [w, h], "seed": seed,
                    "elapsed_s": round(time.time() - t0, 1)}
        tail = (p.stdout + p.stderr)[-800:]
        # local failed — fall through to cloud
        local_err = f"sd-cli failed: {tail}"
    else:
        local_err = (
            f"Local image runner not ready (runner_built={st['runner_built']}, "
            f"checkpoint_ready={st['checkpoint_ready']}). "
            f"Run: urai model download sd-turbo (or set OPENROUTER_API_KEY for cloud)."
        )

    # --- Cloud fallback: Pollinations (free, no key) → OpenRouter (paid) ---
    cloud_err = ""
    if not os.environ.get("URAI_DISABLE_POLLINATIONS"):
        res = _pollinations_generate(prompt, w, h, seed)
        if res["ok"]:
            if out:
                import shutil
                shutil.copy(res["path"], out)
                res["path"] = out
            return res
        cloud_err = res["error"]

    if os.environ.get("OPENROUTER_API_KEY"):
        res = _openrouter_generate(prompt, w, h)
        if res["ok"]:
            if out:
                import shutil
                shutil.copy(res["path"], out)
                res["path"] = out
            return res
        cloud_err = f"{cloud_err} | OpenRouter: {res['error']}"

    return {"ok": False,
            "error": f"Local: {local_err} | Cloud: {cloud_err or 'no cloud provider available'}"}
