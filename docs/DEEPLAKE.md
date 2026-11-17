# Urai × DeepLake — memory, versioned training data, media

DeepLake ([activeloopai/deeplake](https://github.com/activeloopai/deeplake),
Apache-2.0) is a multimodal data runtime: one API stores text, embeddings,
images, video and metadata, with **TQL vector/semantic search**, versioning,
and PyTorch/TensorFlow streaming. This is useful for Urai in three concrete
places — it does **not** give direct hardware control (see §5).

## Why it helps Urai

| Urai gap | DeepLake capability | Benefit |
|---|---|---|
| `jev/memory.py` is session/filesystem based | persistent datasets + `COSINE_SIMILARITY` / `BM25_SIMILARITY` queries | long-term agent memory that survives restarts and is searchable by meaning |
| distill sets are loose JSONL in `data/verified/` | `commit` / `tag` / `branch` / `history` / `revert_to` | reproducible dataset lineage; a bad import can be reverted without losing history |
| Kaggle/Modal jobs get data copied into the notebook | `ds.pytorch()` / `.tensorflow()` / `.batches()` streaming | stream batches straight from local/cloud storage into the GPU loop |
| Wan videos + Seedream images in `out/` | native-compressed image/video columns + metadata | one queryable asset catalogue with captions/embeddings |

## 1. Install (optional, zero credentials for local use)

```bash
python3 -m pip install -r requirements-deeplake.txt   # deeplake==4.7.4
python3 -c 'from jev.deeplake_store import status; import json; print(json.dumps(status(), indent=2))'
```

`status()` reports `available:false` with an install hint when DeepLake is not
installed. Urai never fails because the optional package is missing.

Default URLs (override with env):

| Env var | Default | Use |
|---|---|---|
| `URAI_DEEPLAKE_MEMORY` | `file://~/.urai/deeplake/memory` | agent memory + embeddings |
| `URAI_DEEPLAKE_DATA` | `file://~/.urai/deeplake/verified` | versioned distill/training rows |
| `URAI_DEEPLAKE_MEDIA` | `file://~/.urai/deeplake/media` | image/video asset catalogue |

Supported URL schemes (from the official dataset API): `mem://` (process-local),
`file://`, `s3://`, `gcs://`/`gs://`, `az://`/`azure://`, and `al://` (Deep Lake
cloud). A URL with no scheme is treated as `file://`.

## 2. Core API used (DeepLake v4)

```python
import deeplake
from deeplake import types

ds = deeplake.create("file:///path/to/ds")        # or deeplake.open(existing)
ds.add_column("text", types.Text())
ds.add_column("embedding", types.Embedding(768))
ds.add_column("meta", types.Dict())
ds.append({"text": ["hello"], "embedding": [[...]], "meta": [{"src": "urai"}]})
ds.commit("added memory")                          # versioned; ds.version / ds.history

view = deeplake.query(f'''
    SELECT * FROM "file:///path/to/ds"
    ORDER BY COSINE_SIMILARITY(embedding, ARRAY[0.1, 0.2, ...]) DESC
    LIMIT 5
''')
loader = view.pytorch()                            # streaming GPU batches
text = deeplake.query('SELECT * FROM "..." ORDER BY BM25_SIMILARITY(text, "gold bottle") DESC LIMIT 5')
```

Notes: `deeplake.exists(url)` guards create-vs-open; `open_read_only` is used
for consumers; `revert_to(version)` undoes a bad import while keeping history;
`creds={"aws_access_key_id":..., "aws_secret_access_key":...}` (or `ENV`) is
only needed for cloud URLs.

## 3. Urai module + CLI

`jev/deeplake_store.py` wraps those calls with Urai's defaults and honest
fallbacks:

```
urai deeplake status                       # installed? version? urls?
urai deeplake memory-add   memories.json   # [{text, embedding, meta?}, ...]
urai deeplake memory-search "0.1,0.2,..."  # cosine top-k (or pass a JSON array)
urai deeplake dataset-import data/verified/distill-now.jsonl
```

`memory-add` / `dataset-import` write and commit; `memory-search` is read-only.
All commands print JSON and never print credential values.

## 4. Kaggle / Modal GPU training

1. On the control box: `urai deeplake dataset-import data/verified/distill-now.jsonl`
   → a versioned `file://…/verified` dataset plus `ds.version`/`history`.
2. For **Kaggle T4**: upload the dataset folder as an input (as today with the
   JSONL) or use an `s3://` URL with `creds={"creds_key": ...}` if you have
   cloud storage. In the notebook: `ds = deeplake.open_read_only(...)`;
   `for batch in ds.pytorch(batch_size=4): ...` — no manual copying, and the
   exact dataset version is recorded in the adapter metadata.
3. For **Modal**: mount the same URL and pass `ds.tensorflow()`/`.pytorch()`
   to `scripts/train/modal_train.sh`. Streamed batches avoid a full copy per job.

This is the hardware-access benefit: DeepLake does not rent GPUs, it removes
the data-movement bottleneck once you already have Kaggle/Modal GPU time.

## 5. Honest limitations

- No GPU scheduling or provisioning — use Kaggle/Modal/DO for the GPU itself.
- `file://` datasets are local to one machine; use a cloud URL to share across
  the VPS and notebook runners.
- Vector search quality depends on the embedding model producing fixed-size
  vectors that match the `Embedding(size=...)` column.
- DeepLake is optional: core Urai chat/agent/CLI stays stdlib-first and passes
  its tests with or without it.
- Cloud credentials stay in env/`creds` dicts — never in dataset metadata,
  git, or CLI output.
