#!/usr/bin/env python3
"""API tokens: generated, revocable, quota-counted access (stdlib only).

Master key stays for admins. Issued tokens (`urai_...`) give apps and users
metered access: quota 0 = unlimited, else N calls then 403. Every use is
counted with last-used timestamps — the management UI shows working state.
Store: data/api_tokens.json. Never logged, never committed with values
(empty file ships; issue via superadmin).
"""
import json
import secrets
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOK_FILE = ROOT / "data" / "api_tokens.json"


def _load() -> dict:
    try:
        return json.loads(TOK_FILE.read_text())
    except Exception:
        return {}


def _save(d: dict):
    TOK_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOK_FILE.write_text(json.dumps(d, indent=2) + "\n")


def issue(label: str = "", quota: int = 0) -> dict:
    d = _load()
    tok = "urai_" + secrets.token_urlsafe(24)
    d[tok] = {"label": (label or "untitled")[:80], "quota": max(0, int(quota or 0)),
              "used": 0, "created": int(time.time()), "last_used": 0, "active": True}
    _save(d)
    return {"ok": True, "token": tok, **d[tok]}


def list_tokens() -> list:
    d = _load()
    return [{"token": t[:10] + "…" + t[-4:], "id": t, **v} for t, v in d.items()]


def revoke(prefix_or_id: str) -> dict:
    d = _load()
    for t in list(d):
        if t == prefix_or_id or t.startswith(prefix_or_id):
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
