"""
urai/memory.py — Persistent memory module for Urai AI with vector RAG.

Stores and retrieves facts, user preferences, and learned information.
Supports semantic search over memories and recent conversation turns
using cosine-similarity embeddings.

Vector RAG approach inspired by Odysseus (odysseus-dev/odysseus src/memory_vector.py).
Embedding backend uses the existing EmbeddingBackend abstraction; numpy is used for
cosine similarity if available, with a pure-Python fallback.

Storage layout (JSON lines in data/memory.jsonl):
  {"id": "<uuid>", "text": "...", "tags": [...], "embedding": [...], "ts": 1234567890}
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from typing import Any

# ---------------------------------------------------------------------------
# Optional accelerators
# ---------------------------------------------------------------------------

try:
    import numpy as np
    _NUMPY = True
except ImportError:
    np = None  # type: ignore[assignment]
    _NUMPY = False

# ---------------------------------------------------------------------------
# Paths / config
# ---------------------------------------------------------------------------

_DATA_DIR = os.environ.get("URAI_DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
_MEMORY_FILE = os.path.join(_DATA_DIR, "memory.jsonl")
_AUDIT_FILE = os.path.join(_DATA_DIR, "memory_audit.jsonl")

_EMBED_DIM = 384  # default embedding dimension (matches many sentence-transformers)


# ---------------------------------------------------------------------------
# Embedding backend abstraction
# ---------------------------------------------------------------------------

class EmbeddingBackend:
    """Compute text embeddings. Uses sentence-transformers if available,
    then falls back to a deterministic TF-IDF-style hash embedding."""

    _model = None
    _lock = threading.Lock()

    @classmethod
    def embed(cls, text: str) -> list[float]:
        with cls._lock:
            if cls._model is None:
                cls._model = cls._load_model()
        try:
            return cls._model(text)
        except Exception:  # noqa: BLE001
            return _hash_embed(text)

    @staticmethod
    def _load_model():
        try:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415
            _st = SentenceTransformer("all-MiniLM-L6-v2")

            def _encode(text: str) -> list[float]:
                return _st.encode(text, normalize_embeddings=True).tolist()

            return _encode
        except Exception:  # noqa: BLE001
            return _hash_embed


def _hash_embed(text: str, dim: int = _EMBED_DIM) -> list[float]:
    """Deterministic pseudo-embedding using character n-gram hashing (no deps)."""
    vec = [0.0] * dim
    text = text.lower()
    ngrams = [text[i:i + 3] for i in range(len(text) - 2)] or [text]
    for ng in ngrams:
        h = int(hashlib.md5(ng.encode()).hexdigest(), 16)
        idx = h % dim
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


# ---------------------------------------------------------------------------
# Cosine similarity (numpy if available, else pure Python)
# ---------------------------------------------------------------------------

def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Return cosine similarity in [0, 1]."""
    if _NUMPY:
        va = np.array(a, dtype=np.float32)
        vb = np.array(b, dtype=np.float32)
        denom = (np.linalg.norm(va) * np.linalg.norm(vb))
        if denom == 0:
            return 0.0
        return float(np.dot(va, vb) / denom)
    # Pure Python fallback
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _ensure_data_dir() -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)


def _load_all() -> list[dict]:
    _ensure_data_dir()
    if not os.path.exists(_MEMORY_FILE):
        return []
    records = []
    with open(_MEMORY_FILE, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def _save_all(records: list[dict]) -> None:
    _ensure_data_dir()
    with open(_MEMORY_FILE, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _append_record(record: dict) -> None:
    _ensure_data_dir()
    with open(_MEMORY_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Core memory operations (existing API — preserved)
# ---------------------------------------------------------------------------

def remember(text: str, tags: list[str] | None = None) -> dict:
    """Store a new memory. Returns the stored record."""
    if not text or not text.strip():
        return {"ok": False, "error": "empty text"}

    record = {
        "id": str(uuid.uuid4()),
        "text": text.strip(),
        "tags": tags or [],
        "embedding": EmbeddingBackend.embed(text),
        "ts": time.time(),
    }
    _append_record(record)
    return {"ok": True, "id": record["id"], "text": record["text"]}


def recall(query: str, top: int = 5) -> list[dict]:
    """Retrieve the most relevant memories for a query using vector similarity.

    Returns list of {id, text, tags, score, ts}.
    """
    return rag_search(query, top=top, include_conversation=False)


def forget(memory_id: str) -> dict:
    """Delete a memory by ID."""
    records = _load_all()
    original_len = len(records)
    records = [r for r in records if r.get("id") != memory_id]
    if len(records) == original_len:
        return {"ok": False, "error": f"memory {memory_id!r} not found"}
    _save_all(records)
    return {"ok": True, "deleted": memory_id}


def list_all() -> list[dict]:
    """Return all stored memories (without embeddings to keep output readable)."""
    return [
        {"id": r.get("id"), "text": r.get("text"), "tags": r.get("tags", []), "ts": r.get("ts")}
        for r in _load_all()
    ]


def reembed_all() -> dict:
    """Re-compute embeddings for all stored memories (alias for reindex_all, synchronous)."""
    return reindex_all(background=False)


# ---------------------------------------------------------------------------
# New vector RAG capabilities
# ---------------------------------------------------------------------------

# In-memory cache for recent conversation turns (not persisted)
_conversation_buffer: list[dict] = []
_conversation_lock = threading.Lock()


def reindex_all(background: bool = True) -> dict:
    """Rebuild all vector embeddings for stored memories.

    Parameters
    ----------
    background:
        If True (default), run in a background thread and return immediately.
        If False, block until complete.

    Returns
    -------
    dict with keys: ok, message, [count] (when background=False)
    """
    def _do_reindex():
        records = _load_all()
        updated = 0
        for r in records:
            new_emb = EmbeddingBackend.embed(r.get("text", ""))
            r["embedding"] = new_emb
            updated += 1
        _save_all(records)
        return updated

    if background:
        def _thread_target():
            try:
                count = _do_reindex()
                _audit("reindex_all", {}, {"count": count})
            except Exception as exc:  # noqa: BLE001
                _audit("reindex_all", {}, {"error": str(exc)})

        t = threading.Thread(target=_thread_target, daemon=True)
        t.start()
        return {"ok": True, "message": "Reindexing started in background"}
    else:
        try:
            count = _do_reindex()
            return {"ok": True, "message": "Reindex complete", "count": count}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}


def rag_search(
    query: str,
    top: int = 5,
    include_conversation: bool = True,
    min_score: float = 0.0,
) -> list[dict]:
    """Semantic search over ALL stored memories + recent conversation turns.

    Parameters
    ----------
    query:
        Natural-language search query.
    top:
        Maximum number of results to return.
    include_conversation:
        If True, also score recent in-memory conversation turns.
    min_score:
        Minimum cosine similarity threshold (0.0 – 1.0).

    Returns
    -------
    Sorted list of {id, text, tags, score, ts, source} dicts.
    """
    if not query.strip():
        return []

    q_emb = EmbeddingBackend.embed(query)
    candidates = []

    # Persistent memories
    for r in _load_all():
        emb = r.get("embedding")
        if not emb:
            emb = EmbeddingBackend.embed(r.get("text", ""))
        score = _cosine_sim(q_emb, emb)
        if score >= min_score:
            candidates.append({
                "id": r.get("id", ""),
                "text": r.get("text", ""),
                "tags": r.get("tags", []),
                "score": round(score, 4),
                "ts": r.get("ts", 0),
                "source": "memory",
            })

    # In-memory conversation turns
    if include_conversation:
        with _conversation_lock:
            turns = list(_conversation_buffer)
        for t in turns:
            emb = t.get("embedding")
            if not emb:
                emb = EmbeddingBackend.embed(t.get("text", ""))
            score = _cosine_sim(q_emb, emb)
            if score >= min_score:
                candidates.append({
                    "id": t.get("id", ""),
                    "text": t.get("text", ""),
                    "tags": t.get("tags", []),
                    "score": round(score, 4),
                    "ts": t.get("ts", 0),
                    "source": "conversation",
                })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:top]


def add_conversation_to_memory(messages: list[dict]) -> dict:
    """Index conversation turns and extract memorable facts.

    Parameters
    ----------
    messages:
        List of {"role": "user"|"assistant", "content": "..."} dicts.

    Behaviour
    ---------
    1. Appends all turns to the in-memory conversation buffer for RAG search.
    2. Extracts "facts" from the conversation (user statements, preferences,
       named entities, explicit remembers) and persists them via remember().

    Returns
    -------
    dict with keys: ok, buffered, extracted_facts
    """
    if not messages:
        return {"ok": True, "buffered": 0, "extracted_facts": 0}

    buffered = 0
    with _conversation_lock:
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "").strip()
            if not content:
                continue
            turn = {
                "id": str(uuid.uuid4()),
                "text": f"[{role}] {content}",
                "tags": [role, "conversation"],
                "embedding": EmbeddingBackend.embed(content),
                "ts": time.time(),
            }
            _conversation_buffer.append(turn)
            buffered += 1
        # Keep buffer bounded (last 200 turns)
        if len(_conversation_buffer) > 200:
            del _conversation_buffer[:-200]

    # Extract facts worth persisting
    facts = _extract_facts(messages)
    saved = 0
    for fact in facts:
        r = remember(fact, tags=["auto", "conversation_extract"])
        if r.get("ok"):
            saved += 1

    return {"ok": True, "buffered": buffered, "extracted_facts": saved}


def _extract_facts(messages: list[dict]) -> list[str]:
    """Heuristically extract memorable facts from conversation messages.

    Looks for:
    - Explicit "remember that ..." / "don't forget ..." user statements
    - User preferences ("I prefer ...", "I like ...", "I hate ...")
    - Named entities introduced by the user (simple heuristic: capitalised phrases)
    - Short declarative user statements (< 100 chars, no question mark)
    """
    facts: list[str] = []
    remember_re = re.compile(
        r"(?:remember|note|don't forget|keep in mind)[:\s]+(.+)", re.IGNORECASE
    )
    preference_re = re.compile(
        r"(?:i (?:prefer|like|love|hate|dislike|use|work with|am using))[:\s]+(.+)",
        re.IGNORECASE,
    )

    for msg in messages:
        if msg.get("role") != "user":
            continue
        text = msg.get("content", "").strip()
        if not text:
            continue

        for m in remember_re.finditer(text):
            fact = m.group(1).strip().rstrip(".")
            if fact:
                facts.append(fact)

        for m in preference_re.finditer(text):
            fact = m.group(0).strip().rstrip(".")
            if fact:
                facts.append(fact)

        # Short declarative sentences
        sentences = re.split(r"[.!]", text)
        for s in sentences:
            s = s.strip()
            if 10 < len(s) < 100 and "?" not in s and not any(f in s.lower() for f in facts):
                # Must contain a verb (very rough filter to avoid pure questions)
                if re.search(r"\b(?:is|are|was|were|have|has|had|will|can|do|does)\b", s, re.I):
                    facts.append(s)

    # Deduplicate (case-insensitive)
    seen: set[str] = set()
    unique: list[str] = []
    for f in facts:
        key = f.lower()
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique[:20]  # cap to avoid flooding memory


# ---------------------------------------------------------------------------
# Internal audit helper
# ---------------------------------------------------------------------------

def _audit(op: str, args: dict, result: dict) -> None:
    _ensure_data_dir()
    entry = {
        "ts": time.time(),
        "op": op,
        "args": args,
        "result": result,
    }
    try:
        with open(_AUDIT_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Module-level convenience: search alias
# ---------------------------------------------------------------------------

def search(query: str, top: int = 5) -> list[dict]:
    """Alias for rag_search — semantic search over memories and conversation."""
    return rag_search(query, top=top)


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile, sys  # noqa: E401

    # Use a temp dir so we don't pollute anything
    tmp = tempfile.mkdtemp()
    os.environ["URAI_DATA_DIR"] = tmp
    # Reload globals after env change
    globals()["_DATA_DIR"] = tmp
    globals()["_MEMORY_FILE"] = os.path.join(tmp, "memory.jsonl")

    r = remember("The user prefers dark mode", tags=["preference"])
    print("remember:", r)

    r2 = remember("Python is the primary language for Urai", tags=["tech"])
    print("remember:", r2)

    hits = rag_search("What language is used?", top=3)
    print("rag_search:", hits)

    msgs = [
        {"role": "user", "content": "Remember that my name is Alex."},
        {"role": "assistant", "content": "Noted, Alex!"},
        {"role": "user", "content": "I prefer short responses."},
    ]
    r3 = add_conversation_to_memory(msgs)
    print("add_conversation_to_memory:", r3)

    hits2 = rag_search("What is the user's name?", top=3)
    print("rag_search after conversation:", hits2)

    ri = reindex_all(background=False)
    print("reindex_all:", ri)
