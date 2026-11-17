"""Optional DeepLake 4.x stores for Urai.

Three uses, all optional:
  * agent memory with cosine/BM25 search (jev/memory.py companion),
  * versioned distill/training datasets that can stream to a GPU dataloader,
  * a queryable catalogue of Wan videos / Seedream images.

Core Urai is stdlib-first; this module only imports deeplake inside functions,
so every command reports a clean status instead of crashing when the optional
package is absent. No credential value is ever printed or stored here.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

SCHEMES = ("mem://", "file://", "s3://", "gcs://", "gs://", "az://", "azure://", "al://")


def _default(suffix: str, env: str) -> str:
    return os.environ.get(env, f"file://{Path.home() / '.urai' / 'deeplake' / suffix}")


def memory_url(url: str | None = None) -> str:
    return url or _default("memory", "URAI_DEEPLAKE_MEMORY")


def data_url(url: str | None = None) -> str:
    return url or _default("verified", "URAI_DEEPLAKE_DATA")


def media_url(url: str | None = None) -> str:
    return url or _default("media", "URAI_DEEPLAKE_MEDIA")


def _dl():  # lazy optional import
    try:
        import deeplake  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "deeplake is not installed — run: python3 -m pip install -r requirements-deeplake.txt"
        ) from exc
    return deeplake


def status() -> dict[str, Any]:
    try:
        import importlib.metadata as md
        version = md.version("deeplake")
    except Exception:
        version = None
    return {
        "available": version is not None,
        "version": version,
        "schemes": list(SCHEMES),
        "urls": {
            "memory": memory_url(),
            "data": data_url(),
            "media": media_url(),
        },
        "hint": None if version else "python3 -m pip install -r requirements-deeplake.txt",
    }


def _open_or_create(url: str):
    dl = _dl()
    return dl.open(url) if dl.exists(url) else dl.create(url)


def _ensure_columns(ds, spec: dict[str, Any]) -> None:
    try:
        existing = set(ds.schema.keys())
    except Exception:
        existing = set()
    for name, dtype in spec.items():
        if name not in existing:
            ds.add_column(name, dtype())


def _jsonable(value: Any) -> Any:
    """Make numpy scalars/arrays from DeepLake rows JSON-serialisable."""
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            return tolist()
        except Exception:
            pass
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _rows(view) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in view:
        if isinstance(row, dict):
            item = dict(row)
        elif hasattr(row, "to_dict"):  # deeplake 4.x RowView
            item = row.to_dict()
        else:
            item = {}
            try:
                for key in row.keys():
                    item[key] = row[key]
            except Exception:
                item = {"value": str(row)}
        out.append({k: _jsonable(v) for k, v in item.items()})
    return out


def memory_add(rows: list[dict[str, Any]], url: str | None = None, message: str = "urai memory add") -> dict[str, Any]:
    """Append {text, embedding, meta?} rows to the memory dataset and commit."""
    if not rows:
        return {"ok": False, "error": "no rows supplied"}
    texts = [str(r.get("text", "")) for r in rows]
    vectors = [[float(x) for x in r["embedding"]] for r in rows]
    metas = [r.get("meta") or {} for r in rows]
    dims = len(vectors[0])
    if not dims or any(len(v) != dims for v in vectors):
        return {"ok": False, "error": "all embeddings must have the same non-zero size"}

    dl = _dl()
    target = memory_url(url)
    ds = _open_or_create(target)
    types = dl.types
    _ensure_columns(ds, {"text": types.Text, "embedding": lambda: types.Embedding(dims), "meta": types.Dict})
    ds.append({"text": texts, "embedding": vectors, "meta": metas})
    ds.commit(message)
    return {"ok": True, "url": target, "rows": len(rows), "dims": dims,
            "version": getattr(ds, "version", None)}


def memory_search(vector: list[float], limit: int = 5, url: str | None = None) -> dict[str, Any]:
    """Cosine top-k over stored memory. Read-only."""
    dl = _dl()
    target = memory_url(url)
    if not dl.exists(target):
        return {"ok": True, "url": target, "results": []}
    vals = ", ".join(str(float(x)) for x in vector)
    query = (
        f'SELECT * FROM "{target}" '
        f'ORDER BY COSINE_SIMILARITY(embedding, ARRAY[{vals}]) DESC '
        f'LIMIT {int(limit)}'
    )
    return {"ok": True, "url": target, "results": _rows(dl.query(query))}


def dataset_import(jsonl_path: str, url: str | None = None) -> dict[str, Any]:
    """Import a distill JSONL into a versioned dataset (prompt/response/score)."""
    path = Path(jsonl_path)
    if not path.is_file():
        return {"ok": False, "error": f"not a file: {jsonl_path}"}
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            records.append(obj)
    if not records:
        return {"ok": False, "error": "no JSON objects found"}

    dl = _dl()
    target = data_url(url)
    ds = _open_or_create(target)
    types = dl.types
    _ensure_columns(ds, {
        "prompt": types.Text,
        "response": types.Text,
        "source": types.Text,
        "score": types.Float32,
        "verified": types.Bool,
    })
    ds.append({
        "prompt": [str(r.get("prompt") or r.get("input") or "") for r in records],
        "response": [str(r.get("response") or r.get("output") or "") for r in records],
        "source": [str(r.get("source") or path.name) for r in records],
        "score": [float(r.get("score") or 0.0) for r in records],
        "verified": [bool(r.get("verified", True)) for r in records],
    })
    ds.commit(f"urai import {len(records)} rows from {path.name}")
    return {"ok": True, "url": target, "rows": len(records),
            "version": getattr(ds, "version", None)}


def media_import(rows: list[dict[str, Any]], url: str | None = None) -> dict[str, Any]:
    """Catalogue {path, kind, caption, embedding?} for generated media."""
    if not rows:
        return {"ok": False, "error": "no rows supplied"}
    dl = _dl()
    target = media_url(url)
    ds = _open_or_create(target)
    types = dl.types
    spec: dict[str, Any] = {"path": types.Text, "kind": types.Text, "caption": types.Text}
    dims = next((len(r["embedding"]) for r in rows if r.get("embedding")), None)
    if dims:
        spec["embedding"] = lambda: types.Embedding(dims)
    _ensure_columns(ds, spec)
    payload = {
        "path": [str(r.get("path", "")) for r in rows],
        "kind": [str(r.get("kind", "image")) for r in rows],
        "caption": [str(r.get("caption", "")) for r in rows],
    }
    if dims:
        payload["embedding"] = [[float(x) for x in r.get("embedding", [0.0] * dims)] for r in rows]
    ds.append(payload)
    ds.commit("urai media import")
    return {"ok": True, "url": target, "rows": len(rows)}


def cli(action: str, value: str | None = None, url: str | None = None) -> int:
    """Small JSON CLI used by `urai deeplake ...`. Returns a process exit code."""
    try:
        if action == "status":
            result = status()
        elif action == "memory-add":
            data = json.loads(Path(value or "").read_text(encoding="utf-8"))
            result = memory_add(data if isinstance(data, list) else [data], url=url)
        elif action == "memory-search":
            raw = value or "[]"
            try:
                vector = json.loads(raw)
            except json.JSONDecodeError:
                vector = [float(x) for x in raw.split(",") if x.strip()]
            result = memory_search(vector, url=url)
        elif action == "dataset-import":
            result = dataset_import(value or "", url=url)
        else:
            result = {"ok": False, "error": f"unknown action: {action}"}
    except RuntimeError as exc:
        result = {"ok": False, "error": str(exc)}
    except Exception as exc:  # never leak a traceback to the CLI user
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if result.get("ok", True) else 1
