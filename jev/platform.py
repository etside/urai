#!/usr/bin/env python3
"""Platform config: model ids + endpoints read from config/platform.json, with
environment overrides. Keeps provider/model ids out of code (PRODUCTION_SPEC §4).

    ARK_BASE / ARK_API_KEY / ARK_IMAGE_MODEL      Seedream 4.0 (image)
    DASHSCOPE_BASE / DASHSCOPE_API_KEY            Wan 3.0 (video)
    WAN_MODEL / WAN_PRIME_MODEL / URAI_VIDEO_FAST

Stdlib only.
"""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(os.environ.get("URAI_PLATFORM_CONFIG",
                                  ROOT / "config" / "platform.json"))

_DEFAULT = {
    "media": {
        "image": {"provider": "seedream",
                  "ark_base": "https://ark.ap-southeast.bytepluses.com",
                  "model": "seedream-4-0-250828", "default_size": "2K",
                  "max_refs": 14, "persist_dir": "out/images",
                  "cost_usd_per_image": 0.03},
        "video": {"provider": "wan3",
                  "dashscope_base": "https://dashscope.aliyuncs.com",
                  "model": "wan3.0-video", "prime_model": "wan3.0-video-prime",
                  "persist_dir": "out/videos"},
    }
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    data = dict(_DEFAULT)
    try:
        if CONFIG_PATH.is_file():
            data = _deep_merge(_DEFAULT, json.loads(CONFIG_PATH.read_text()))
    except Exception:
        data = dict(_DEFAULT)
    return data


def image_cfg() -> dict:
    cfg = dict(load().get("media", {}).get("image", {}))
    cfg["ark_base"] = os.environ.get("ARK_BASE", cfg.get("ark_base", "")).rstrip("/")
    cfg["api_key"] = os.environ.get("ARK_API_KEY", "")
    cfg["model"] = os.environ.get("ARK_IMAGE_MODEL", cfg.get("model", ""))
    return cfg


def video_cfg() -> dict:
    cfg = dict(load().get("media", {}).get("video", {}))
    cfg["dashscope_base"] = os.environ.get(
        "DASHSCOPE_BASE", cfg.get("dashscope_base", "")).rstrip("/")
    cfg["api_key"] = os.environ.get("DASHSCOPE_API_KEY", "")
    cfg["model"] = os.environ.get("WAN_MODEL", cfg.get("model", ""))
    cfg["prime_model"] = os.environ.get("WAN_PRIME_MODEL",
                                        cfg.get("prime_model", ""))
    cfg["fast"] = str(os.environ.get("URAI_VIDEO_FAST", "")).strip().lower() \
        in ("1", "true", "yes", "on")
    return cfg


def images_endpoint(base: str) -> str:
    """ARK accepts base with or without the /api/v3 suffix."""
    base = (base or "").rstrip("/")
    if base.endswith("/api/v3"):
        return base + "/images/generations"
    return base + "/api/v3/images/generations"


def wan_endpoint(base: str) -> str:
    return (base or "").rstrip("/") + "/api/v1/services/aigc/video-generation/video-synthesis"


def wan_task_endpoint(base: str, task_id: str) -> str:
    return (base or "").rstrip("/") + "/api/v1/tasks/" + str(task_id)


if __name__ == "__main__":
    print(json.dumps({"image": image_cfg(), "video": video_cfg()}, indent=2))
