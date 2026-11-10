#!/usr/bin/env python3
"""engine.py — thin completion helper used by vibe.py and edit.py.

Picks the best available backend at call time:
  1. LlamaServerBackend (local llama-server, if healthy)
  2. CloudAPIBackend via OpenRouter (if OPENROUTER_API_KEY set)
  3. TeacherAPIBackend (if TEACHER_API_KEY set)
Raises RuntimeError if no backend is available.
"""

from __future__ import annotations
import os


def _get_backend():
    from .backends import LlamaServerBackend, CloudAPIBackend, TeacherAPIBackend
    local = LlamaServerBackend()
    if local.healthy():
        return local
    if os.environ.get("OPENROUTER_API_KEY"):
        return CloudAPIBackend(provider="openrouter")
    if os.environ.get("TEACHER_API_KEY"):
        return TeacherAPIBackend()
    raise RuntimeError(
        "No LLM backend available: llama-server not running and no cloud key set. "
        "Start the server with `urai serve start` or set OPENROUTER_API_KEY."
    )


def complete(backend=None, messages: list = None, max_tokens: int = 1024,
             temperature: float = 0.2) -> dict:
    """Call backend.complete(), auto-selecting backend if None.

    Returns {"content": str, ...} matching the backend contract.
    """
    if backend is None or (hasattr(backend, 'healthy') and not backend.healthy()):
        backend = _get_backend()
    return backend.complete(messages or [], max_tokens=max_tokens,
                            temperature=temperature)
