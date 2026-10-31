"""
jev/rag.py — Document RAG engine for Urai.

stdlib only; numpy is used for cosine similarity when available but falls back
to a pure-Python dot-product implementation.

Env gate: set URAI_NEURO=1 to enable RAG injection in context.py.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Optional numpy import
# ---------------------------------------------------------------------------
try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:  # pragma: no cover
    np = None  # type: ignore
    _HAS_NUMPY = False

_DATA_DIR = Path(os.environ.get("URAI_DATA_DIR", "data")) / "rag"

# ---------------------------------------------------------------------------
# Embedding backend
# ---------------------------------------------------------------------------

class EmbeddingBackend:
    """Hash-based deterministic embedding (512-dim). Replace with a real model
    by subclassing and overriding encode()."""

    DIM = 512

    def encode(self, text: str) -> List[float]:
        """Return a normalised 512-float vector derived from text."""
        # Use SHA-512 bytes as seeds for 512 pseudo-random floats.
        digest = hashlib.sha512(text.encode("utf-8", errors="replace")).digest()
        # Unpack as 64 unsigned bytes, then tile/fold to 512 floats.
        raw = list(struct.unpack("64B", digest))
        # Expand to 512 by cycling with small perturbation.
        vec: List[float] = []
        for i in range(self.DIM):
            byte_val = raw[i % 64]
            perturb = (i * 2654435761) & 0xFFFFFFFF  # Knuth multiplicative hash
            vec.append(float((byte_val ^ (perturb & 0xFF)) + 1) / 256.0)
        return _normalise(vec)


def _normalise(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a: List[float], b: List[float]) -> float:
    if _HAS_NUMPY:
        return float(np.dot(np.array(a), np.array(b)))  # both already normalised
    return sum(x * y for x, y in zip(a, b))


# Module-level singleton so callers share state.
_backend: Optional[EmbeddingBackend] = None


def _get_backend() -> EmbeddingBackend:
    global _backend
    if _backend is None:
        _backend = EmbeddingBackend()
    return _backend


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _chunk_text(text: str, size: int = 512, overlap: int = 64) -> List[str]:
    """Split *text* into chunks of *size* characters with *overlap* overlap."""
    if not text:
        return []
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _doc_path(doc_id: str) -> Path:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Sanitise doc_id to a safe filename.
    safe = re.sub(r"[^\w.-]", "_", doc_id)
    return _DATA_DIR / f"{safe}.jsonl"


def _load_chunks(doc_id: str) -> List[Dict[str, Any]]:
    path = _doc_path(doc_id)
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def _save_chunks(doc_id: str, chunks: List[Dict[str, Any]]) -> None:
    path = _doc_path(doc_id)
    with path.open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(json.dumps(chunk, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest(
    source: str,
    doc_id: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Chunk *source* text, embed each chunk, and store in data/rag/<doc_id>.jsonl.

    Parameters
    ----------
    source    : raw text content (not a file path)
    doc_id    : unique identifier for this document
    metadata  : optional dict merged into every chunk record

    Returns
    -------
    Number of chunks stored.
    """
    meta = metadata or {}
    backend = _get_backend()
    raw_chunks = _chunk_text(source)
    records: List[Dict[str, Any]] = []
    for idx, chunk_text in enumerate(raw_chunks):
        vec = backend.encode(chunk_text)
        record: Dict[str, Any] = {
            "doc_id": doc_id,
            "chunk_idx": idx,
            "text": chunk_text,
            "embedding": vec,
        }
        record.update(meta)
        records.append(record)
    _save_chunks(doc_id, records)
    return len(records)


def search(
    query: str,
    top: int = 5,
) -> List[Dict[str, Any]]:
    """
    Cosine-similarity search over all ingested chunks.

    Returns
    -------
    List of up to *top* dicts: {doc_id, text, score, title}
    """
    if not _DATA_DIR.exists():
        return []
    backend = _get_backend()
    q_vec = backend.encode(query)
    results: List[Dict[str, Any]] = []
    for jsonl_file in _DATA_DIR.glob("*.jsonl"):
        doc_id = jsonl_file.stem
        for chunk in _load_chunks(doc_id):
            embedding = chunk.get("embedding")
            if not embedding:
                continue
            score = _cosine(q_vec, embedding)
            results.append({
                "doc_id": chunk.get("doc_id", doc_id),
                "text": chunk.get("text", ""),
                "score": score,
                "title": chunk.get("title", chunk.get("doc_id", doc_id)),
            })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top]


def context_for(
    query: str,
    max_chars: int = 2000,
) -> str:
    """
    Return a formatted string suitable for system-prompt injection.

    Format::

        [DOCUMENTS]
        [title]
        chunk text...
        [END]

    Falls back to empty string when no relevant chunks exist.
    """
    hits = search(query, top=10)
    if not hits:
        return ""
    lines: List[str] = ["[DOCUMENTS]"]
    used = len("[DOCUMENTS]\n[END]")
    for hit in hits:
        title_line = f"[{hit['title']}]"
        body = hit["text"]
        entry = f"{title_line}\n{body}\n"
        if used + len(entry) > max_chars:
            break
        lines.append(entry)
        used += len(entry)
    lines.append("[END]")
    return "\n".join(lines)


def delete(doc_id: str) -> bool:
    """Remove stored chunks for *doc_id*. Returns True if the file existed."""
    path = _doc_path(doc_id)
    if path.exists():
        path.unlink()
        return True
    return False


def list_docs() -> List[str]:
    """Return list of doc_ids currently stored."""
    if not _DATA_DIR.exists():
        return []
    return [p.stem for p in sorted(_DATA_DIR.glob("*.jsonl"))]
