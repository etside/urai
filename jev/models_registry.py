#!/usr/bin/env python3
"""Model registry: Urai first-party only.

  registry file: model/registry.json
  First-party artifact: models/urai-muse-spark-1.3/ (weights.json + manifest.json).
  `urai model download` fetches ONLY Urai-hosted artifacts and refuses vendor
  model ids or vendor-hosted URLs.

Stdlib only.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "model" / "registry.json"
ALLOWED = ("urai-muse-spark-1.3",)
URAI_ARTIFACT_ROOT = "models/urai-muse-spark-1.3"

DEFAULTS = {
    "active": "urai-muse-spark-1.3",
    "models": {
        "urai-muse-spark-1.3": {
            "path": f"{URAI_ARTIFACT_ROOT}/weights.json",
            "params": "n-gram-student",
            "quant": "json",
            "role": "primary",
            "kind": "chat",
            "hf": "",
            "context_window": 8192,
            "vision": True,
            "pdf": True,
            "note": "First-party Urai weights (Urai corpus n-gram). See config/platform.json."
        },
    },
}


def load():
    if REGISTRY.exists():
        reg = json.loads(REGISTRY.read_text())
        # Migrate: first-party only (drop vendor entries)
        models = {k: v for k, v in reg.get("models", {}).items() if k in ALLOWED}
        if not models:
            models = dict(DEFAULTS["models"])
            reg["models"] = models
            reg["active"] = "urai-muse-spark-1.3"
            save(reg)
        else:
            if reg.get("models") != models:
                reg["models"] = models
                save(reg)
        if reg.get("active") not in reg["models"]:
            reg["active"] = "urai-muse-spark-1.3"
            save(reg)
        return reg
    save(DEFAULTS)
    return json.loads(json.dumps(DEFAULTS))


def save(reg):
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(reg, indent=2) + "\n")


def active_model(reg=None):
    reg = reg or load()
    m = reg["models"][reg["active"]]
    return reg["active"], m


def active_path():
    mid, m = active_model()
    p = ROOT / m["path"]
    return mid, str(p) if p.exists() else None


_ALLOWED_HOSTS = ("urai.daddyai.online", "urai.model", "localhost", "127.0.0.1")


def _is_urai_url(url: str) -> bool:
    if not url:
        # No remote URL: local first-party artifact (weights already in repo)
        return True
    u = url.lower()
    if any(v in u for v in ("huggingface.co", "qwen", "openai", "anthropic",
                            "meta", "together")):
        return False
    return any(h in u for h in _ALLOWED_HOSTS) or u.startswith("models/")


def download(mid, progress=True):
    reg = load()
    if mid not in ALLOWED:
        raise ValueError(f"refused: vendor/non-Urai model id not allowed: {mid}")
    if mid not in reg["models"]:
        raise KeyError(f"unknown model id: {mid}")
    m = reg["models"][mid]
    jobs = m.get("files") or [{"path": m["path"], "hf": m.get("hf", "")}]
    for j in jobs:
        if not _is_urai_url(j.get("hf", "")):
            raise ValueError(f"refused: non-Urai artifact URL for {mid}")
    # First-party weights ship in-repo; verify presence, never fetch vendor.
    outs = []
    for j in jobs:
        dest = ROOT / j["path"]
        if not dest.exists():
            raise FileNotFoundError(
                f"Urai weights missing at {dest} (expected first-party artifact)")
        outs.append(str(dest))
    print(f"ready {mid}: kind={m.get('kind', 'chat')} (first-party, local)")
    return outs[-1]
