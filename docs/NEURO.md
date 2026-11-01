# Urai Neurology Layer — Requirements & Design

## Goal

Give Urai persistent, searchable memory of documents and conversations so that
answers are grounded in retrieved evidence rather than parameterised knowledge
alone.  The layer is lightweight (stdlib only, no PyTorch), opt-in via an env
flag, and degrades gracefully when disabled.

---

## Component Table

| Component | File | Status | Role |
|-----------|------|--------|------|
| Document RAG | `jev/rag.py` | **NEW** | Ingest, embed, search, inject |
| Episodic memory | `jev/memory.py` | EXISTS | Short-term conversation memory |
| Intent router | `jev/router.py` | **UPGRADED** | TF-IDF intent classifier added |
| Context builder | `jev/context.py` | **UPGRADED** | RAG injection + history compression |

---

## Data Flow

```
User query
    │
    ▼
_tfidf_classify(prompt)          ← jev/router.py
    │ agent label + confidence
    ▼
RAG retrieve  context_for(query) ← jev/rag.py
    │ [DOCUMENTS] block
    ▼
ContextBuilder.to_messages()     ← jev/context.py
    │ system prompt with injected docs
    ▼
Qwen3 / chosen backend model
    │ raw answer
    ▼
evidence verify  (check citations against [DOCUMENTS])
    │
    ▼
Final answer → user
```

---

## Env Gate

| Variable | Values | Effect |
|----------|--------|--------|
| `URAI_NEURO` | `1` / `0` (default `0`) | Enables RAG injection in `context_for()` |
| `URAI_DATA_DIR` | path (default `data`) | Root directory for vector store and examples |

When `URAI_NEURO` is not set (or `0`), `context_for()` returns an empty string
and the context builder behaves exactly as before — no behaviour change.

---

## What Is NOT Needed

- **No PyTorch / ONNX for inference** — the RAG layer uses a hash-based
  embedding fallback. A real sentence-transformer can be plugged in by
  subclassing `EmbeddingBackend.encode()`, but is not required.
- **No external vector database** — embeddings are stored as JSONL files under
  `data/rag/`. For the scale Urai targets (hundreds of documents, thousands of
  chunks) a flat brute-force cosine search is fast enough.
- **No network calls** — the entire pipeline runs locally.
- **No new runtime dependencies** — everything uses Python stdlib. `numpy` is
  used for the dot product when present but is never imported unconditionally.

---

## TF-IDF Router Details

The classifier trains at first call from 40 hardcoded seed examples (10 per
class: `casual`, `coder`, `browser`, `planner`) plus any examples written by
`_learn()` to `data/router_examples.jsonl`.  It uses a nearest-centroid
approach over TF-IDF vectors.  Confidence threshold for TF-IDF acceptance is
**0.4** (cosine similarity); below that, legacy keyword-regex fires.

---

## File Layout

```
urai/
├── jev/
│   ├── rag.py          ← NEW  (this PR)
│   ├── context.py      ← UPGRADED (this PR)
│   ├── router.py       ← UPGRADED (this PR)
│   └── memory.py       ← EXISTS (unchanged)
├── docs/
│   └── NEURO.md        ← NEW  (this PR)
└── data/
    ├── rag/            ← created at runtime by rag.ingest()
    │   └── <doc_id>.jsonl
    └── router_examples.jsonl  ← created at runtime by router._learn()
```

---

## Acceptance Criteria

1. `jev.rag.ingest(source, doc_id)` stores chunks in `data/rag/<doc_id>.jsonl`.
2. `jev.rag.search(query)` returns ranked results without external services.
3. `ContextBuilder.to_messages(rag=True)` prepends a `[DOCUMENTS]` block when
   `URAI_NEURO=1` and relevant chunks exist.
4. `jev.router.classify(prompt)` uses TF-IDF first, keyword fallback second.
5. All four files import cleanly with `python -c "import jev.rag, jev.context, jev.router"`.
6. `URAI_NEURO=0` (default): zero behaviour change from pre-neuro Urai.
