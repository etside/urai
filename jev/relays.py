#!/usr/bin/env python3
"""Media relays: Seedream 4.0 (image) + Wan 3.0 (video) via managed APIs.

Honest capability model (PRODUCTION_SPEC §4):
  - Provider URLs expire (~24h), so every output is downloaded to
    out/{images,videos}/ immediately and a stable Urai path is returned.
  - Missing keys -> a clear, typed error; the caller may fall back to local
    SD-Turbo. We never fake a provider result.

Stdlib only. HTTP calls go through ``urllib.request.urlopen`` (patchable in
tests).
"""

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import platform as _platform

ROOT = Path(__file__).resolve().parents[1]
POLL_INTERVAL_S = float(os.environ.get("URAI_RELAY_POLL", "5"))
WAN_TIMEOUT_S = int(os.environ.get("URAI_WAN_TIMEOUT", "600"))


class RelayError(Exception):
    """Typed relay failure with an optional HTTP status."""
    def __init__(self, message, status=0, payload=None):
        super().__init__(message)
        self.status = status
        self.payload = payload or {}


def _post_json(url, payload, key=None, timeout=120, extra_headers=None):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, json.dumps(payload).encode(), headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:  # noqa: F821 (urllib.error imported below)
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        raise RelayError(f"HTTP {e.code}: {body[:300]}", status=e.code)
    except Exception as e:
        raise RelayError(str(e)[:300])
    try:
        return json.loads(raw or b"{}")
    except Exception:
        raise RelayError("provider returned non-JSON response")


def _get_json(url, key=None, timeout=120):
    headers = {}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read() or b"{}")





def _persist(url, dest_dir: str, stem: str, ext: str = ".png") -> str:
    """Download a (soon-expiring) provider URL to a stable local path."""
    dest = ROOT / dest_dir
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"{stem}{ext}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=300) as resp:
        out.write_bytes(resp.read())
    return str(out)


def seedream_images(prompt: str, size=None, refs=None, response_format="url",
                    watermark=False, sequential=False, out=None) -> dict:
    """Seedream 4.0 text/image-to-image. Returns a Urai-normalised dict."""
    cfg = _platform.image_cfg()
    if not cfg.get("api_key"):
        return {"ok": False, "provider": "seedream4", "configured": False,
                "error": "ARK_API_KEY not set (see docs/DEPLOYMENT_PLAN.md)"}
    refs = [r for r in (refs or []) if r][: int(cfg.get("max_refs", 14))]
    payload = {
        "model": cfg.get("model"),
        "prompt": prompt,
        "size": size or cfg.get("default_size", "2K"),
        "response_format": response_format,
        "watermark": bool(watermark),
    }
    if refs:
        payload["image"] = refs if len(refs) > 1 else refs[0]
    if sequential:
        payload["sequential_image_generation"] = "auto"
    url = _platform.images_endpoint(cfg.get("ark_base", ""))
    data = _post_json(url, payload, key=cfg.get("api_key"), timeout=180)
    item = (data.get("data") or [{}])[0]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    stem = f"seedream-{stamp}"
    path = None
    if response_format == "b64_json" or item.get("b64_json"):
        b64 = item.get("b64_json") or ""
        if b64:
            dest = ROOT / cfg.get("persist_dir", "out/images")
            dest.mkdir(parents=True, exist_ok=True)
            fd = dest / f"{stem}.png"
            fd.write_bytes(base64.b64decode(b64))
            path = str(fd)
    elif item.get("url"):
        path = _persist(item["url"], cfg.get("persist_dir", "out/images"), stem)
    if out and path:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(Path(path).read_bytes())
        path = str(out)
    return {"ok": bool(path), "provider": "seedream4", "model": cfg.get("model"),
            "path": path, "url": item.get("url"),
            "revised_prompt": item.get("revised_prompt", prompt),
            "cost": cfg.get("cost_usd_per_image", 0.03),
            "error": None if path else "provider returned no image"}


def wan_video(prompt: str, duration: int = 5, resolution: str = "720P",
              ratio: str = "16:9", seed: int = None, audio: bool = False,
              media=None, prime: bool = None, out=None) -> dict:
    """Wan 3.0 async text/image-to-video. Submits, polls, persists the MP4."""
    cfg = _platform.video_cfg()
    if not cfg.get("api_key"):
        return {"ok": False, "provider": "wan3", "configured": False,
                "error": "DASHSCOPE_API_KEY not set (see docs/DEPLOYMENT_PLAN.md)"}
    use_prime = cfg.get("fast") if prime is None else bool(prime)
    model = cfg.get("prime_model") if use_prime else cfg.get("model")
    inp = {"prompt": prompt}
    for k, v in (media or {}).items():
        if v:
            inp[k] = v
    params = {"resolution": resolution, "ratio": ratio,
              "duration": int(duration), "prompt_extend": True}
    if seed is not None:
        params["seed"] = int(seed)
    if audio:
        params["audio"] = True
    url = _platform.wan_endpoint(cfg.get("dashscope_base", ""))
    submit = _post_json(url, {"model": model, "input": inp, "parameters": params},
                        key=cfg.get("api_key"), timeout=120,
                        extra_headers={"X-DashScope-Async": "enable"})
    task_id = ((submit.get("output") or {}).get("task_id")
               or submit.get("task_id"))
    if not task_id:
        return {"ok": False, "provider": "wan3", "model": model,
                "error": f"provider returned no task id: {str(submit)[:200]}"}
    base = cfg.get("dashscope_base", "")
    deadline = time.time() + WAN_TIMEOUT_S
    while time.time() < deadline:
        info = _get_json(_platform.wan_task_endpoint(base, task_id),
                         key=cfg.get("api_key"))
        out_obj = info.get("output") or {}
        status = (out_obj.get("task_status") or info.get("task_status") or "")
        if status in ("SUCCEEDED", "SUCCESS"):
            video_url = (out_obj.get("video_url")
                         or (out_obj.get("results") or [{}])[0].get("url"))
            if not video_url:
                return {"ok": False, "provider": "wan3", "model": model,
                        "id": task_id, "error": "task succeeded without a URL"}
            stamp = time.strftime("%Y%m%d-%H%M%S")
            path = _persist(video_url, cfg.get("persist_dir", "out/videos"),
                            f"wan3-{stamp}", ".mp4")
            if out:
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                Path(out).write_bytes(Path(path).read_bytes())
                path = str(out)
            return {"ok": True, "provider": "wan3", "model": model,
                    "id": task_id, "path": path, "url": video_url,
                    "duration": duration, "resolution": resolution,
                    "prime": use_prime}
        if status in ("FAILED", "CANCELED", "UNKNOWN"):
            return {"ok": False, "provider": "wan3", "model": model,
                    "id": task_id,
                    "error": f"task {status}: {out_obj.get('message', '')}"[:300]}
        time.sleep(POLL_INTERVAL_S)
    return {"ok": False, "provider": "wan3", "model": model, "id": task_id,
            "error": f"timed out after {WAN_TIMEOUT_S}s"}


def status() -> dict:
    img, vid = _platform.image_cfg(), _platform.video_cfg()
    return {
        "seedream4": {"configured": bool(img.get("api_key")),
                      "model": img.get("model"),
                      "base": img.get("ark_base")},
        "wan3": {"configured": bool(vid.get("api_key")),
                 "model": vid.get("model"), "prime_model": vid.get("prime_model"),
                 "fast": bool(vid.get("fast")), "base": vid.get("dashscope_base")},
    }
