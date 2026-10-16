#!/usr/bin/env python3
"""Hybrid retrieval — connect the embeddings endpoint to memory/skills/fewshots.

Before this module, memory/fewshots/skills used keyword overlap only and the
/v1/embeddings endpoint was never used for recall. `rank(query, docs)` blends a
BM25 lexical score with a cosine score over embeddings when the embedding server
is up, and degrades cleanly to BM25 over locally-hashed bag-of-words vectors when
it is not. Deterministic fallback => works on a CPU VPS and in CI, no GPU.
"""

import hashlib
import math
import re
import time

_DIM = 256
_TOKEN = re.compile(r"[a-zA-ZÀ-ÿ']+|[\u4E00-\u9FFF]+")


def _tokens(text: str) -> list:
    return [t.lower() for t in _TOKEN.findall(text or "")]


def hash_vector(text: str, dim: int = _DIM) -> list:
    """Deterministic hashed bag-of-words vector (offline embedding fallback)."""
    vec = [0.0] * dim
    for tok in _tokens(text):
        h = int(hashlib.blake2b(tok.encode(), digest_size=8).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h >> 8) & 1 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def embed(texts):
    """Embed via the embedding server when available, else hashed vectors."""
    if isinstance(texts, str):
        texts = [texts]
    try:
        from .backends import EmbeddingBackend
        be = EmbeddingBackend()
        if be.healthy():
            vecs = be.embed(texts)
            if vecs and isinstance(vecs[0], (list, tuple)):
                return [list(map(float, v)) for v in vecs]
    except Exception:
        pass
    return [hash_vector(t) for t in texts]


def cosine(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def bm25(query: str, docs: list, k1: float = 1.5, b: float = 0.75) -> list:
    q = _tokens(query)
    if not q or not docs:
        return [0.0] * len(docs)
    toks = [_tokens(d) for d in docs]
    lens = [len(t) or 1 for t in toks]
    avg = sum(lens) / len(lens)
    df = {}
    for t in toks:
        for w in set(t):
            df[w] = df.get(w, 0) + 1
    n = len(docs)
    scores = []
    for t, dl in zip(toks, lens):
        tf = {}
        for w in t:
            tf[w] = tf.get(w, 0) + 1
        s = 0.0
        for w in q:
            if w not in tf:
                continue
            idf = math.log(1 + (n - df.get(w, 0) + 0.5) / (df.get(w, 0) + 0.5))
            s += idf * (tf[w] * (k1 + 1)) / (tf[w] + k1 * (1 - b + b * dl / avg))
        scores.append(s)
    mx = max(scores) or 1.0
    return [s / mx for s in scores]


def rank(query: str, docs: list, top: int = 5, items: list = None) -> list:
    """Hybrid rank. `docs` = list[str] or list[dict]; returns list[dict]
    {"index", "score", "lexical", "semantic", "text", "item?"} sorted desc."""
    texts, metas = [], []
    for d in docs:
        if isinstance(d, dict):
            texts.append(str(d.get("text", d.get("content", ""))))
            metas.append(d)
        else:
            texts.append(str(d))
            metas.append(None)
    if not texts:
        return []
    lex = bm25(query, texts)
    sem = [0.0] * len(texts)
    try:
        vecs = embed([query] + texts)
        qv = vecs[0]
        sem = [cosine(qv, v) for v in vecs[1:]]
    except Exception:
        sem = [cosine(hash_vector(query), hash_vector(t)) for t in texts]
    out = []
    for i, (l, s) in enumerate(zip(lex, sem)):
        score = 0.5 * l + 0.5 * max(0.0, s)
        out.append({"index": i, "score": round(score, 4),
                    "lexical": round(l, 4), "semantic": round(s, 4),
                    "text": texts[i], "item": metas[i]})
    out.sort(key=lambda r: -r["score"])
    return out[:top]


def recall_memories(query: str, top: int = 3) -> list:
    """Rank ALL stored memories against the query (used by the agent)."""
    try:
        from . import memory as _mem
        facts = _mem.list_all() or []
    except Exception:
        return []
    if not facts:
        return []
    texts = [f.get("text", "") for f in facts]
    rows = rank(query, texts, top=top)
    return [{"text": r["text"], "score": r["score"],
             "kind": facts[r["index"]].get("kind", "fact"),
             "id": facts[r["index"]].get("id", "")} for r in rows]


# ------------------------------------------------ memory + focus index/query
def _memory_chunks() -> list:
    try:
        from . import memory as _mem
        rows = _mem.list_all(limit=1000) or []
    except Exception:
        return []
    out = []
    for r in rows:
        text = (r.get("text") or "").strip()
        if text:
            out.append({"text": text, "kind": r.get("kind", "fact"),
                        "id": r.get("id", ""), "ts": float(r.get("ts", 0) or 0),
                        "source": "memory"})
    return out


def _focus_chunks() -> list:
    try:
        from . import focus as _focus
        stack = _focus._load().get("stack", [])
    except Exception:
        return []
    out = []
    for it in stack:
        label = (it.get("label") or "").strip()
        detail = (it.get("detail") or "").strip()
        text = (label + (" — " + detail if detail else "")).strip()
        if text:
            out.append({"text": text, "kind": "focus", "id": it.get("id", ""),
                        "ts": float(it.get("ts", 0) or 0), "source": "focus"})
    return out


def chunks(sources=("memory", "focus")) -> list:
    """The retrieval index: every retrievable chunk from memory + focus."""
    out = []
    if "memory" in sources:
        out += _memory_chunks()
    if "focus" in sources:
        out += _focus_chunks()
    return out


def _recency(ts: float, now: float, halflife_days: float) -> float:
    if not ts:
        return 0.0
    age_days = max(0.0, (now - ts) / 86400.0)
    return math.exp(-math.log(2.0) * age_days / max(halflife_days, 0.1))


def query(prompt: str, top_k: int = None, sources=("memory", "focus"),
          chunks_=None, now: float = None, recency_weight: float = None,
          halflife_days: float = None) -> list:
    """Top-K relevant memory/focus chunks for `prompt`, ranked by a single
    blended score = (1-w)*relevance + w*recency. Offline-safe: uses the hashed
    embedding fallback when the embed server is down (works with no GPU)."""
    try:
        from . import config as _config
        cfg = _config.get()
        if top_k is None:
            top_k = cfg.RETRIEVAL_TOP_K
        if recency_weight is None:
            recency_weight = cfg.RETRIEVAL_RECENCY_WEIGHT
        if halflife_days is None:
            halflife_days = cfg.RETRIEVAL_HALFLIFE_DAYS
    except Exception:
        top_k = top_k or 5
        recency_weight = 0.25 if recency_weight is None else recency_weight
        halflife_days = halflife_days or 30.0
    now = time.time() if now is None else now
    recency_weight = max(0.0, min(1.0, float(recency_weight)))

    ch = chunks_ if chunks_ is not None else chunks(sources)
    if not ch:
        return []
    texts = [c.get("text", "") for c in ch]
    rel_map = {}
    try:
        for r in rank(prompt, texts, top=len(texts)):
            rel_map[r["index"]] = r["score"]
    except Exception:
        rel_map = {}
    rows = []
    for i, c in enumerate(ch):
        relevance = float(rel_map.get(i, 0.0))
        recency = _recency(c.get("ts", 0.0), now, halflife_days)
        score = (1.0 - recency_weight) * relevance + recency_weight * recency
        rows.append({
            "text": c.get("text", ""),
            "kind": c.get("kind", "fact"),
            "source": c.get("source", "memory"),
            "id": c.get("id", ""),
            "ts": int(c.get("ts", 0) or 0),
            "relevance": round(relevance, 4),
            "recency": round(recency, 4),
            "score": round(score, 4),
        })
    rows.sort(key=lambda r: -r["score"])
    return rows[:top_k]


_INDEX = {"count": 0, "built": 0, "sources": ()}


def build_index(sources=("memory", "focus")) -> dict:
    """(Re)build the retrieval index snapshot and return its size."""
    ch = chunks(sources)
    _INDEX["count"] = len(ch)
    _INDEX["built"] = int(time.time())
    _INDEX["sources"] = tuple(sources)
    return {"ok": True, "indexed": len(ch), "sources": list(sources)}


def index_stats() -> dict:
    return {"indexed": _INDEX["count"], "built": _INDEX["built"],
            "sources": list(_INDEX["sources"])}


if __name__ == "__main__":
    import json
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "heap memory leak"
    print(json.dumps(rank(q, ["heap memory leak in C++", "how to bake bread"]), indent=2))
