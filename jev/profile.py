#!/usr/bin/env python3
"""User profile — sticky preferences, adapted from observed requests.

Profiles are keyed by request identity (device id or ip) and persisted to
data/profiles.json. `get(ident)` returns the blended preference dict used by
vibe.plan; `observe(ident, nlp)` nudges it with an exponential moving average so
the assistant drifts toward the user's habitual language/length/depth over time.

Sticky (persisted) vs transient (per-request sentiment) is deliberate: a single
angry message should not permanently make the assistant cold.
"""

import json
import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILE = Path(os.environ.get("URAI_PROFILES", str(ROOT / "data" / "profiles.json")))
_LOCK = threading.RLock()
_ALPHA = 0.12  # EMA weight for new observations

_FIELDS = ("formality", "warmth", "verbosity", "humor", "technical_depth", "emoji")


def _load():
    try:
        return json.loads(FILE.read_text())
    except Exception:
        return {}


def _save(d):
    try:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=2) + "\n")
        tmp.replace(FILE)
    except Exception:
        pass


def get(ident: str) -> dict:
    if not ident:
        return {}
    with _LOCK:
        return dict(_load().get(ident, {}))


def set_pref(ident: str, key: str, value):
    if not ident or key not in _FIELDS + ("language",):
        return {"ok": False, "error": "bad key or identity"}
    with _LOCK:
        d = _load()
        rec = d.setdefault(ident, {})
        rec[key] = value
        rec["updated"] = int(time.time())
        _save(d)
    return {"ok": True, "ident": ident, "profile": rec}


def observe(ident: str, nlp: dict, targets: dict = None):
    """Nudge sticky prefs from one request. Never raises."""
    if not ident or not nlp:
        return
    try:
        t = targets or {}
        exp = nlp.get("_desired") or t
        with _LOCK:
            d = _load()
            rec = d.setdefault(ident, {})
            for f in _FIELDS:
                want = exp.get(f)
                if want is None:
                    continue
                cur = float(rec.get(f, 0.5))
                rec[f] = round(cur * (1 - _ALPHA) + float(want) * _ALPHA, 4)
            if nlp.get("language") and nlp["language"] != "en":
                rec["language"] = nlp["language"]
            rec.setdefault("requests", 0)
            rec["requests"] = int(rec["requests"]) + 1
            rec["updated"] = int(time.time())
            _save(d)
    except Exception:
        pass


def all_profiles() -> dict:
    with _LOCK:
        return _load()


def clear(ident: str) -> dict:
    with _LOCK:
        d = _load()
        existed = d.pop(ident, None)
        _save(d)
    return {"ok": True, "removed": bool(existed)}
