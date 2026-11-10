#!/usr/bin/env python3
"""Plugins: OpenClaw-style capability packs for Urai (stdlib only).

Layout:
  plugins/<name>/plugin.json   {"name","version","description","enabled","hooks":[]}
  plugins/<name>/*.py          implementation (imported lazily by hook)

Hooks (examples): "message" (channel text in), "task" (agent task pre-step),
"browser" (browser automation request), "cron" (scheduled tick).

Core never depends on a plugin: unknown/disabled plugins are skipped with a
warning. `urai plugin list|enable|disable`, `urai plugin serve <channel>`.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS_DIR = ROOT / "plugins"

BUILTINS = ("browser", "telegram")


def _manifest(p: Path) -> dict:
    try:
        d = json.loads((p / "plugin.json").read_text())
    except Exception:
        return {}
    d["_dir"] = str(p)
    d.setdefault("name", p.name)
    d.setdefault("enabled", False)
    d.setdefault("hooks", [])
    return d


def all_plugins() -> list:
    out = []
    if not PLUGINS_DIR.is_dir():
        return out
    for p in sorted(PLUGINS_DIR.iterdir()):
        if not p.is_dir() or p.name.startswith((".", "_")):
            continue
        if not (p / "plugin.json").is_file():
            continue
        m = _manifest(p)
        if m:
            out.append(m)
    return out


def get(name: str) -> dict:
    for m in all_plugins():
        if m["name"] == name:
            return m
    return {}


def set_enabled(name: str, enabled: bool) -> dict:
    m = get(name)
    if not m:
        return {"ok": False, "error": f"unknown plugin: {name}"}
    mp = Path(m["_dir"]) / "plugin.json"
    try:
        d = json.loads(mp.read_text())
        d["enabled"] = bool(enabled)
        mp.write_text(json.dumps(d, indent=2))
        return {"ok": True, "name": name, "enabled": bool(enabled)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def emit(hook: str, payload: dict) -> list:
    """Dispatch hook to enabled plugins; returns [(plugin, result)]."""
    out = []
    for m in all_plugins():
        if not m.get("enabled") or hook not in (m.get("hooks") or []):
            continue
        try:
            mod = __import__(f"plugins.{m['name']}.handler",
                             fromlist=["on_hook"])
            out.append((m["name"], mod.on_hook(hook, dict(payload or {}))))
        except Exception as e:
            out.append((m["name"], {"ok": False, "error": str(e)[:200]}))
    return out
