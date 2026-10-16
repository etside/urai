#!/usr/bin/env python3
"""Sessions: server-side conversation memory (stdlib only).

Each session is a JSONL file under data/sessions/<sid>.jsonl with
{"role","content","ts"} rows. /agent persists turns when the caller passes
session_id (created when absent). History is re-injected as agent context,
so conversations survive restarts and work across devices.
"""
import json
import secrets
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SESS_DIR = ROOT / "data" / "sessions"
MAX_ROWS = 200


def new_id() -> str:
    return secrets.token_hex(8)


def append(sid: str, role: str, content: str) -> str:
    sid = (sid or "").strip() or new_id()
    if not all(c.isalnum() or c in "-_" for c in sid):
        sid = new_id()
    SESS_DIR.mkdir(parents=True, exist_ok=True)
    fp = SESS_DIR / f"{sid}.jsonl"
    with open(fp, "a") as f:
        f.write(json.dumps({"role": role, "content": (content or "")[:8000],
                            "ts": int(time.time())}, ensure_ascii=False) + "\n")
    try:
        lines = fp.read_text().splitlines()
        if len(lines) > MAX_ROWS:
            fp.write_text("\n".join(lines[-MAX_ROWS:]) + "\n")
    except Exception:
        pass
    return sid


def clear(sid: str) -> dict:
    try:
        (SESS_DIR / f"{sid}.jsonl").unlink()
    except Exception:
        pass
    return {"ok": True, "session_id": sid}


def history(sid: str, limit: int = 40) -> list:
    try:
        rows = []
        for line in (SESS_DIR / f"{sid}.jsonl").read_text().splitlines()[-limit:]:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows
    except Exception:
        return []
