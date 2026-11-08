#!/usr/bin/env python3
"""Urai first-party runtime: muse-spark-1.3 served by Urai weights (stdlib only).

Loads Urai weights from models/urai-muse-spark-1.3/ (n-gram student trained on
the Urai repo corpus). No external model endpoint is ever called: if weights
are absent, is_loaded() is False and callers must return 503 — never mock,
never vendor fallback.

Public API:
    load_runtime() -> UraiRuntime (lazy singleton)
    is_loaded() -> bool
    complete(messages, max_tokens, temperature) -> dict
    complete_with_image(image_bytes, mime, question, ...) -> dict
    CONTEXT_WINDOW / VISION / PDF flags for /v1/models
"""
from .runtime import UraiRuntime, load_runtime, is_loaded
from .vision import complete_with_image, describe_image

CONTEXT_WINDOW = 8192
VISION = True
PDF = True
MODEL_ID = "muse-spark-1.3"
BACKEND = "urai"

def complete(messages, max_tokens=256, temperature=0.2):
    return load_runtime().complete(messages, max_tokens=max_tokens, temperature=temperature)

__all__ = [
    "UraiRuntime", "load_runtime", "is_loaded", "complete",
    "complete_with_image", "describe_image",
    "CONTEXT_WINDOW", "VISION", "PDF", "MODEL_ID", "BACKEND",
]
