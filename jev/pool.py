#!/usr/bin/env python3
"""Pool control: opt models in/out of the orchestration pool (stdlib only).

File data/pool.json: {"allow": [...], "deny": [...]} (ids or tiers).
Empty allow = all local models eligible. Router + tiers enforce it.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POOL_FILE = ROOT / "data" / "pool.json"


def load() -> dict:
    try:
        d = json.loads(POOL_FILE.read_text())
        return {"allow": d.get("allow", []), "deny": d.get("deny", [])}
    except Exception:
        return {"allow": [], "deny": []}


def save(allow=None, deny=None) -> dict:
    POOL_FILE.parent.mkdir(parents=True, exist_ok=True)
    d = {"allow": list(allow or []), "deny": list(deny or [])}
    POOL_FILE.write_text(json.dumps(d, indent=2) + "\n")
    return d


def allowed(name: str) -> bool:
    p = load()
    if name in p["deny"]:
        return False
    if p["allow"]:
        return name in p["allow"]
    return True
