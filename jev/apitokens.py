#!/usr/bin/env python3
"""API tokens: generated, revocable, quota-counted access (stdlib only).

Master key stays for admins. Issued tokens (`urai_...`) give apps and users
metered access: quota 0 = unlimited, else N calls then 403. Every use is
counted with last-used timestamps — the management UI shows working state.
Store: data/api_tokens.json. Never logged, never committed with values
(empty file ships; issue via superadmin).
"""
import json
import os
import secrets
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOK_FILE = ROOT / "data" / "api_tokens.json"


def _tok_file() -> Path:
    """Token store; follows URAI_DATA_DIR like the rest of the runtime."""
    d = os.environ.get("URAI_DATA_DIR")
    return (Path(d) if d else ROOT / "data") / "api_tokens.json"


def _load() -> dict:
    try:
        return json.loads(_tok_file().read_text())
    except Exception:
        return {}


def _save(d: dict):
    f = _tok_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(d, indent=2) + "\n")


def issue(label: str = "", quota: int = 0) -> dict:
    d = _load()
    tok = "urai_" + secrets.token_urlsafe(24)
    d[tok] = {"label": (label or "untitled")[:80], "quota": max(0, int(quota or 0)),
              "used": 0, "created": int(time.time()), "last_used": 0, "active": True}
    _save(d)
    return {"ok": True, "id": tok, "token": tok, **d[tok]}


def list_tokens() -> list:
    d = _load()
    return [{"token": t[:10] + "…" + t[-4:], "id": t, **v} for t, v in d.items()]


def revoke(prefix_or_id: str) -> dict:
    key = (prefix_or_id or "").strip()
    # An empty/short prefix would match (and revoke) the wrong token.
    if len(key) < 8:
        return {"ok": False, "error": "token id or prefix too short (min 8 chars)"}
    d = _load()
    for t in list(d):
        if t == key or t.startswith(key):
            d[t]["active"] = False
            _save(d)
            return {"ok": True, "id": t}
    return {"ok": False, "error": "unknown token"}


def check(raw: str):
    """Validate a presented token. Returns record dict or None. No logging."""
    tok = (raw or "").strip()
    if not tok.startswith("urai_"):
        return None
    d = _load()
    r = d.get(tok)
    if not r or not r.get("active"):
        return None
    if r.get("quota", 0) > 0 and r.get("used", 0) >= r["quota"]:
        return None
    return {"id": tok, **r}


def record_use(tok_id: str):
    try:
        d = _load()
        if tok_id in d:
            d[tok_id]["used"] = d[tok_id].get("used", 0) + 1
            d[tok_id]["last_used"] = int(time.time())
            _save(d)
    except Exception:
        pass
