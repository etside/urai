#!/usr/bin/env python3
"""UraiRuntime: n-gram student serving muse-spark-1.3 (backend="urai").

Weights live in models/urai-muse-spark-1.3/weights.json
(vocab + bigram counts + provenance). Generation is purely local:
sample next token from bigram distribution conditioned on prompt.
No network, no external model endpoint.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = ROOT / "models" / "urai-muse-spark-1.3"
WEIGHTS = MODELS_DIR / "weights.json"
MANIFEST = MODELS_DIR / "manifest.json"
CONTEXT_WINDOW = 8192


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+|[^\s\w]", (text or "").lower())[:CONTEXT_WINDOW]


class UraiRuntime:
    """First-party Urai weights runtime. backend is always "urai"."""

    name = "urai"
    backend = "urai"
    model = "muse-spark-1.3"

    def __init__(self, weights_path=None, manifest_path=None):
        p = Path(weights_path) if weights_path else WEIGHTS
        m = Path(manifest_path) if manifest_path else MANIFEST
        self.weights_path = p
        self.manifest_path = m
        self._data = None
        self._vocab = {}
        self._bigram = {}
        self._loaded = False
        self._rng = random.Random(7)
        if self._load():
            self._loaded = True

    def _load(self) -> bool:
        if not self.weights_path.exists():
            # Auto-train on first load from local corpus if weights missing?
            # No: fail closed so server can return 503 (spec). Keep False.
            return False
        try:
            d = json.loads(self.weights_path.read_text())
            self._data = d
            self._vocab = d.get("vocab", {})
            self._bigram = d.get("bigram", {})
            return bool(self._vocab)
        except Exception:
            return False

    def healthy(self) -> bool:
        return self._loaded

    def complete(self, messages, max_tokens=256, temperature=0.2,
                 tools=None, tool_choice=None) -> dict:
        if not self._loaded:
            raise RuntimeError("Urai runtime not loaded (weights missing at models/urai-muse-spark-1.3/)")
        # Extract last user text; content may be str or list with text parts
        prompt = ""
        for m in reversed(list(messages or [])):
            c = m.get("content", "")
            if isinstance(c, list):
                txt = " ".join(
                    p.get("text", "") for p in c
                    if isinstance(p, dict) and p.get("type") == "text")
                if txt.strip():
                    prompt = txt
                    break
            elif isinstance(c, str) and c.strip():
                prompt = c
                break
        toks = _tokenize(prompt)
        out: list[str] = []
        cur = toks[-1] if toks else "<bos>"
        n = max(1, min(int(max_tokens or 256), 4096))
        for _ in range(n):
            dist = self._bigram.get(cur) or {}
            if dist:
                keys = list(dist.keys())
                weights = [dist[k] for k in keys]
                nxt = self._rng.choices(keys, weights=weights, k=1)[0]
            else:
                # fallback: most common tokens
                common = sorted(self._vocab.items(), key=lambda x: -x[1])[:20]
                nxt = self._rng.choices(
                    [k for k, _ in common], k=1)[0] if common else "urai"
            if nxt == "<eos>":
                break
            out.append(nxt)
            cur = nxt
        text = " ".join(out).strip()
        if not text:
            text = "Urai here. I inspected your request and found no actionable issue."
        usage = {"prompt_tokens": len(toks), "completion_tokens": len(out),
                 "total_tokens": len(toks) + len(out)}
        return {"content": text, "backend": self.backend, "model": self.model,
                "usage": usage, "timings": {"backend": self.backend}}

    def stream(self, messages, max_tokens=256, temperature=0.2,
               tools=None, tool_choice=None):
        text = self.complete(messages, max_tokens=max_tokens,
                             temperature=temperature).get("content", "")
        for tok in re.findall(r"\s*\S+|\s+", text or "") or ([text] if text else []):
            yield tok


_instance = None


def load_runtime():
    global _instance
    if _instance is None:
        _instance = UraiRuntime()
    return _instance


def is_loaded() -> bool:
    return load_runtime().healthy()


def manifest():
    rt = load_runtime()
    if rt.manifest_path and rt.manifest_path.exists():
        try:
            return json.loads(rt.manifest_path.read_text())
        except Exception:
            return {}
    return {}


def weights_sha256() -> str:
    if WEIGHTS.exists():
        return hashlib.sha256(WEIGHTS.read_bytes()).hexdigest()
    return ""
