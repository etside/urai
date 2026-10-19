#!/usr/bin/env python3
"""Active Memory: long-lived facts, preferences and decisions (stdlib only).

Store: data/memory/facts.jsonl rows {id, kind, text, weight, hits, ts}.
recall() scores by keyword overlap + recency + hits, so the most useful
memories surface automatically. The agent injects top recalls into every
run (see agent.py) — this is Urai's Wonder-like active memory: it remembers
across sessions without retraining.
"""
import json
import re
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEM_FILE = ROOT / "data" / "memory" / "facts.jsonl"
KINDS = ("fact", "preference", "decision")

_WORD = re.compile(r"[a-z0-9]{3,}")


def _load() -> list:
    try:
        return [json.loads(l) for l in MEM_FILE.read_text().splitlines() if l.strip()]
    except Exception:
        return []


def _save(rows: list):
    MEM_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEM_FILE.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
                        + ("\n" if rows else ""))


def remember(text: str, kind: str = "fact", weight: float = 1.0) -> dict:
    text = (text or "").strip()[:1000]
    if not text:
        return {"ok": False, "error": "empty text"}
    if kind not in KINDS:
        kind = "fact"
    rows = _load()
    norm = " ".join(sorted(set(_WORD.findall(text.lower()))))
    for r in rows:
        if " ".join(sorted(set(_WORD.findall(r.get("text", "").lower())))) == norm:
            r["hits"] = r.get("hits", 0) + 1
            r["weight"] = max(r.get("weight", 1.0), float(weight))
            _save(rows)
            return {"ok": True, "id": r["id"], "deduped": True}
    rec = {"id": uuid.uuid4().hex[:8], "kind": kind, "text": text,
           "weight": float(weight), "hits": 0, "ts": int(time.time())}
    rows.append(rec)
    _save(rows[-500:])
    return {"ok": True, **rec}


def recall(query: str, top: int = 3) -> list:
    words = set(_WORD.findall((query or "").lower()))
    if not words:
        return []
    now = time.time()
    scored = []
    for r in _load():
        rw = set(_WORD.findall(r.get("text", "").lower()))
        overlap = len(words & rw)
        if not overlap:
            continue
        age_days = max(0.0, (now - r.get("ts", now)) / 86400.0)
        score = overlap * r.get("weight", 1.0) * (1 + 0.1 * r.get("hits", 0)) \
            / (1 + age_days / 30.0)
        scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    return [{"id": r["id"], "kind": r["kind"], "text": r["text"],
             "score": round(s, 3)} for s, r in scored[:top]]


def forget(mid: str) -> dict:
    rows = [r for r in _load() if r.get("id") != mid]
    _save(rows)
    return {"ok": True, "id": mid, "remaining": len(rows)}


def list_all(limit: int = 50) -> list:
    return _load()[-limit:]
