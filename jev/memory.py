#!/usr/bin/env python3
"""Active Memory: long-lived facts, preferences and decisions (stdlib only).

Store: data/memory/facts.jsonl rows {id, kind, text, weight, hits, ts, vec?}.
recall() uses two-tier scoring:
  1. Semantic (cosine): if EmbeddingBackend is healthy, vectors are stored
     on remember() and cosine-scored on recall(). Vectors cached in row.
  2. Keyword fallback: if embedding server is down or vec absent, falls
     back to keyword-overlap + recency + hits scoring (original behaviour).
This means memory quality improves automatically when the embed model is
running, and degrades gracefully when it isn't — no config required.

The agent injects top recalls into every run (see agent.py).
"""
from __future__ import annotations
import json
import math
import re
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEM_FILE = ROOT / "data" / "memory" / "facts.jsonl"
KINDS = ("fact", "preference", "decision")
VEC_DIM = 768  # nomic-embed-text-v1.5 default; ignored if embed returns different dim

_WORD = re.compile(r"[a-z0-9]{3,}")


# ── Embedding helpers (optional) ──────────────────────────────────────────────

def _embed(text: str) -> list[float] | None:
    """Return embedding vector or None if embedding server unavailable."""
    try:
        from .backends import EmbeddingBackend
        be = EmbeddingBackend()
        if not be.healthy():
            return None
        vecs = be.embed(text)
        return vecs[0] if vecs else None
    except Exception:
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ── Storage ───────────────────────────────────────────────────────────────────

def _load() -> list:
    try:
        return [json.loads(l) for l in MEM_FILE.read_text().splitlines() if l.strip()]
    except Exception:
        return []


def _save(rows: list):
    MEM_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEM_FILE.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
        + ("\n" if rows else ""))


# ── Public API ────────────────────────────────────────────────────────────────

def remember(text: str, kind: str = "fact", weight: float = 1.0) -> dict:
    """Store a memory, deduplicating exact-normalised entries.
    If embedding server is up, stores a vector for later semantic recall.
    """
    text = (text or "").strip()[:1000]
    if not text:
        return {"ok": False, "error": "empty text"}
    if kind not in KINDS:
        kind = "fact"
    rows = _load()

    # Dedup by keyword normalisation (cheap, no network)
    norm = " ".join(sorted(set(_WORD.findall(text.lower()))))
    for r in rows:
        if " ".join(sorted(set(_WORD.findall(r.get("text", "").lower())))) == norm:
            r["hits"] = r.get("hits", 0) + 1
            r["weight"] = max(r.get("weight", 1.0), float(weight))
            # Backfill vector if missing and embed is now available
            if not r.get("vec"):
                v = _embed(text)
                if v:
                    r["vec"] = v
            _save(rows)
            return {"ok": True, "id": r["id"], "deduped": True}

    rec: dict = {
        "id": uuid.uuid4().hex[:8],
        "kind": kind,
        "text": text,
        "weight": float(weight),
        "hits": 0,
        "ts": int(time.time()),
    }
    # Try to embed at store time (non-blocking; skip if server down)
    v = _embed(text)
    if v:
        rec["vec"] = v

    rows.append(rec)
    _save(rows[-500:])
    return {"ok": True, "id": rec["id"], "embedded": bool(v)}


def recall(query: str, top: int = 3) -> list:
    """Recall most relevant memories for query.

    Uses semantic cosine scoring when both the query and stored rows have
    vectors.  Falls back to keyword+recency scoring otherwise.
    The two modes can mix within a single recall call: rows with vectors
    get cosine scores; rows without get keyword scores; both are ranked
    together on a normalised [0,1] scale.
    """
    query = (query or "").strip()
    if not query:
        return []

    rows = _load()
    if not rows:
        return []

    # Try to embed the query (non-blocking)
    q_vec = _embed(query)
    words = set(_WORD.findall(query.lower()))
    now = time.time()

    scored: list[tuple[float, dict]] = []
    has_semantic = bool(q_vec)

    for r in rows:
        r_vec = r.get("vec")
        if has_semantic and r_vec:
            # Semantic path: cosine similarity (already 0–1 range)
            score = _cosine(q_vec, r_vec)
            # Boost by weight and hits, slight recency bonus
            age_days = max(0.0, (now - r.get("ts", now)) / 86400.0)
            score = score * r.get("weight", 1.0) * (1 + 0.05 * r.get("hits", 0)) \
                / (1 + age_days / 90.0)
        else:
            # Keyword path (original behaviour)
            rw = set(_WORD.findall(r.get("text", "").lower()))
            overlap = len(words & rw)
            if not overlap:
                continue
            age_days = max(0.0, (now - r.get("ts", now)) / 86400.0)
            score = overlap * r.get("weight", 1.0) * (1 + 0.1 * r.get("hits", 0)) \
                / (1 + age_days / 30.0)
            # Normalise keyword score to ~[0,1] (heuristic: max overlap ~5)
            score = min(score / max(len(words), 1), 1.0)

        if score > 0:
            scored.append((score, r))

    scored.sort(key=lambda x: -x[0])
    return [{"id": r["id"], "kind": r["kind"], "text": r["text"],
             "score": round(s, 4),
             "semantic": bool(has_semantic and r.get("vec"))}
            for s, r in scored[:top]]


def reembed_all() -> dict:
    """Backfill vectors for all stored memories that lack them.
    Call once after installing the embed model: urai memory reembed
    Returns {"ok": True, "updated": N, "skipped": M}.
    """
    rows = _load()
    updated = 0
    skipped = 0
    for r in rows:
        if r.get("vec"):
            skipped += 1
            continue
        v = _embed(r.get("text", ""))
        if v:
            r["vec"] = v
            updated += 1
        else:
            # Embed server not available — stop trying
            break
    if updated:
        _save(rows)
    return {"ok": True, "updated": updated, "skipped": skipped,
            "total": len(rows)}


def forget(mid: str) -> dict:
    rows = [r for r in _load() if r.get("id") != mid]
    _save(rows)
    return {"ok": True, "id": mid, "remaining": len(rows)}


def list_all(limit: int = 50) -> list:
    return _load()[-limit:]
