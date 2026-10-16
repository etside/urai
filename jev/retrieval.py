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


if __name__ == "__main__":
    import json
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "heap memory leak"
    print(json.dumps(rank(q, ["heap memory leak in C++", "how to bake bread"]), indent=2))
