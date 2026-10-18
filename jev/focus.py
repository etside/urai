#!/usr/bin/env python3
"""Active Focus: what Urai is working on right now (stdlib only).

A small stack in data/focus.json: [{id, label, detail, ts}]. The top item
is injected into every agent run as "Active focus", so multi-step work
stays on track across turns and devices. Set it when starting real work,
clear it when done — like a Wonder-style focus anchor.
"""
import json
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOCUS_FILE = ROOT / "data" / "focus.json"
MAX_STACK = 5


def _load() -> dict:
    try:
        d = json.loads(FOCUS_FILE.read_text())
        if isinstance(d.get("stack"), list):
            return d
    except Exception:
        pass
    return {"stack": [], "updated": 0}


def _save(d: dict):
    FOCUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    FOCUS_FILE.write_text(json.dumps(d, indent=2) + "\n")


def set_focus(label: str, detail: str = "") -> dict:
    d = _load()
    item = {"id": uuid.uuid4().hex[:8], "label": (label or "")[:200],
            "detail": (detail or "")[:1000], "ts": int(time.time())}
    d["stack"] = ([item] + d["stack"])[:MAX_STACK]
    d["updated"] = item["ts"]
    _save(d)
    return {"ok": True, **item}


def current() -> dict:
    d = _load()
    return d["stack"][0] if d["stack"] else {}


def clear() -> dict:
    _save({"stack": [], "updated": int(time.time())})
    return {"ok": True}


def context_block() -> str:
    c = current()
    if not c:
        return ""
    out = "Active focus: " + c.get("label", "")
    if c.get("detail"):
        out += " — " + c["detail"]
    return out
