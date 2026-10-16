#!/usr/bin/env python3
"""Prompt cache — the "fastest LLM" fast path.

Caches completions keyed by (model, messages, max_tokens, temperature) so an
identical prompt is served from memory instead of the model. When
``CACHE_SIMILARITY > 0`` a *near-identical* prompt (high token-set Jaccard
overlap with a fresh entry for the same model + params) is also served, which
is where most real repeat traffic lands.

Policy:
  * LRU eviction at ``CACHE_MAX`` entries.
  * TTL expiry at ``CACHE_TTL`` seconds (checked on read).
  * Manual invalidation via ``clear()`` (exposed at ``POST /admin/cache/clear``).
  * ``CACHE_ENABLED=false`` bypasses the cache entirely (debugging).

Stats (hits/misses/typing) are exported at ``/admin/metrics`` and ``/metrics``.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import OrderedDict

_TOKEN = re.compile(r"[a-z0-9]+")


def _flatten(messages) -> str:
    parts = []
    for m in messages or []:
        if isinstance(m, dict):
            c = m.get("content", "")
            if isinstance(c, list):
                parts += [str(p.get("text", "")) for p in c
                          if isinstance(p, dict) and p.get("type") == "text"]
            else:
                parts.append(str(c))
        else:
            parts.append(str(m))
    return "\n".join(parts)


def _tokens(text: str) -> set:
    return set(_TOKEN.findall((text or "").lower()))


def similarity(a: str, b: str) -> float:
    """Token-set Jaccard similarity in [0, 1] (deterministic, stdlib)."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


class PromptCache:
    def __init__(self, max_entries=None, ttl_seconds=None, similarity=None,
                 enabled=None, clock=time.time):
        self._lock = threading.RLock()
        self._cache = OrderedDict()
        self._max = max_entries
        self._ttl = ttl_seconds
        self._sim = similarity
        self._enabled = enabled
        self._clock = clock
        self._hits = 0
        self._exact_hits = 0
        self._similar_hits = 0
        self._misses = 0
        self._bypassed = 0
        self._evictions = 0
        self._expires = 0
        self._clears = 0

    # ------------------------------------------------------------- config
    def _cfg(self):
        try:
            from . import config as _config
            return _config.get()
        except Exception:
            return None

    @property
    def enabled(self) -> bool:
        if self._enabled is not None:
            return self._enabled
        c = self._cfg()
        return c.CACHE_ENABLED if c else True

    @property
    def ttl(self) -> float:
        if self._ttl is not None:
            return self._ttl
        c = self._cfg()
        return c.CACHE_TTL if c else 300

    @property
    def max_entries(self) -> int:
        if self._max is not None:
            return self._max
        c = self._cfg()
        return c.CACHE_MAX if c else 256

    @property
    def similarity_threshold(self) -> float:
        if self._sim is not None:
            return self._sim
        c = self._cfg()
        return c.CACHE_SIMILARITY if c else 0.0

    # ---------------------------------------------------------------- key
    def _key(self, model, messages, max_tokens, temperature):
        h = hashlib.sha256()
        h.update(str(model).encode())
        h.update(json.dumps(messages, sort_keys=True, default=str).encode())
        h.update(str(max_tokens).encode())
        h.update(str(temperature).encode())
        return h.hexdigest()

    def _fresh(self, entry) -> bool:
        return (self._clock() - entry["ts"]) <= self.ttl

    # --------------------------------------------------------------- read
    def lookup(self, model, messages, max_tokens, temperature) -> dict:
        """Return {"content","hit","similarity","age_s"} or None on miss."""
        if not self.enabled:
            with self._lock:
                self._bypassed += 1
            return None
        key = self._key(model, messages, max_tokens, temperature)
        prompt = _flatten(messages)
        with self._lock:
            entry = self._cache.get(key)
            if entry is not None:
                if self._fresh(entry):
                    self._cache.move_to_end(key)
                    entry["hits"] = entry.get("hits", 0) + 1
                    self._hits += 1
                    self._exact_hits += 1
                    return {"content": entry["content"], "hit": "exact",
                            "similarity": 1.0,
                            "age_s": round(self._clock() - entry["ts"], 3)}
                # stale -> drop and fall through to similarity scan
                del self._cache[key]
                self._expires += 1

            threshold = self.similarity_threshold
            if threshold > 0 and prompt:
                best, best_score = None, 0.0
                for k, e in list(self._cache.items()):
                    if not self._fresh(e):
                        del self._cache[k]
                        self._expires += 1
                        continue
                    if (e.get("model") != model
                            or e.get("max_tokens") != max_tokens
                            or e.get("temperature") != temperature):
                        continue
                    score = similarity(prompt, e.get("prompt", ""))
                    if score > best_score:
                        best, best_score = k, score
                if best is not None and best_score >= threshold:
                    e = self._cache[best]
                    self._cache.move_to_end(best)
                    e["hits"] = e.get("hits", 0) + 1
                    self._hits += 1
                    self._similar_hits += 1
                    return {"content": e["content"], "hit": "similar",
                            "similarity": round(best_score, 4),
                            "age_s": round(self._clock() - e["ts"], 3)}

            self._misses += 1
            return None

    def get(self, model, messages, max_tokens, temperature):
        r = self.lookup(model, messages, max_tokens, temperature)
        return r["content"] if r else None

    # -------------------------------------------------------------- write
    def put(self, model, messages, max_tokens, temperature, content):
        if not self.enabled or content is None:
            return None
        key = self._key(model, messages, max_tokens, temperature)
        with self._lock:
            self._cache[key] = {
                "content": content,
                "prompt": _flatten(messages),
                "ts": self._clock(),
                "hits": 0,
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            self._cache.move_to_end(key)
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)
                self._evictions += 1
        return key

    # -------------------------------------------------------- invalidation
    def clear(self) -> dict:
        with self._lock:
            n = len(self._cache)
            self._cache.clear()
            self._clears += 1
        return {"ok": True, "cleared": n}

    def invalidate(self, predicate) -> int:
        removed = 0
        with self._lock:
            for k, e in list(self._cache.items()):
                try:
                    if predicate(e):
                        del self._cache[k]
                        removed += 1
                except Exception:
                    continue
        return removed

    def expire(self) -> int:
        removed = 0
        with self._lock:
            for k, e in list(self._cache.items()):
                if not self._fresh(e):
                    del self._cache[k]
                    removed += 1
                    self._expires += 1
        return removed

    # ------------------------------------------------------------- stats
    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "enabled": self.enabled,
                "hits": self._hits,
                "exact_hits": self._exact_hits,
                "similar_hits": self._similar_hits,
                "misses": self._misses,
                "bypassed": self._bypassed,
                "hit_rate": round(self._hits / total, 4) if total else 0.0,
                "size": len(self._cache),
                "max": self.max_entries,
                "ttl_s": self.ttl,
                "similarity": self.similarity_threshold,
                "evictions": self._evictions,
                "expires": self._expires,
                "clears": self._clears,
            }


_cache = PromptCache()


def get_cache() -> PromptCache:
    return _cache


def model_of(backend) -> str:
    return str(getattr(backend, "model", None) or getattr(backend, "name", "?"))


def cached_complete(backend, messages, max_tokens=256, temperature=0.2) -> dict:
    """backend.complete() with a prompt-cache fast path.

    Returns the backend result augmented with ``cached``/``cache_hit``. On a
    cache hit the backend is never called. Never raises on cache errors — the
    cache is an optimisation, not a dependency.
    """
    c = get_cache()
    model = model_of(backend)
    try:
        hit = c.lookup(model, messages, max_tokens, temperature)
    except Exception:
        hit = None
    if hit:
        return {"content": hit["content"], "backend": getattr(backend, "name", "cache"),
                "cached": True, "cache_hit": hit["hit"],
                "cache_similarity": hit["similarity"], "cache_age_s": hit["age_s"],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                          "total_tokens": 0, "cost": 0}}
    res = backend.complete(messages, max_tokens=max_tokens, temperature=temperature)
    try:
        c.put(model, messages, max_tokens, temperature, res.get("content"))
    except Exception:
        pass
    res = dict(res) if isinstance(res, dict) else {"content": str(res)}
    res.setdefault("cached", False)
    return res


if __name__ == "__main__":
    import json
    c = get_cache()
    msgs = [{"role": "user", "content": "hello world"}]
    c.put("urai", msgs, 64, 0.2, "hi!")
    print(json.dumps({"exact": c.get("urai", msgs, 64, 0.2),
                      "stats": c.stats()}, indent=2))
