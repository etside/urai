#!/usr/bin/env python3
"""LRU prompt cache for repeated queries.

Caches completions keyed by (model, messages_hash, max_tokens, temperature).
Avoids re-processing identical prompts, saving tokens and latency.
"""

import hashlib
import json
import time
from collections import OrderedDict

_MAX_ENTRIES = 128
_TTL_SECONDS = 300


class PromptCache:
    def __init__(self, max_entries=_MAX_ENTRIES, ttl_seconds=_TTL_SECONDS):
        self._cache = OrderedDict()
        self._max = max_entries
        self._ttl = ttl_seconds
        self._hits = 0
        self._misses = 0

    def _key(self, model, messages, max_tokens, temperature):
        h = hashlib.sha256()
        h.update(model.encode())
        h.update(json.dumps(messages, sort_keys=True).encode())
        h.update(str(max_tokens).encode())
        h.update(str(temperature).encode())
        return h.hexdigest()

    def get(self, model, messages, max_tokens, temperature):
        key = self._key(model, messages, max_tokens, temperature)
        entry = self._cache.get(key)
        if entry is None:
            self._misses += 1
            return None
        if time.time() - entry["ts"] > self._ttl:
            del self._cache[key]
            self._misses += 1
            return None
        self._cache.move_to_end(key)
        self._hits += 1
        return entry["content"]

    def put(self, model, messages, max_tokens, temperature, content):
        key = self._key(model, messages, max_tokens, temperature)
        self._cache[key] = {"content": content, "ts": time.time()}
        self._cache.move_to_end(key)
        if len(self._cache) > self._max:
            self._cache.popitem(last=False)

    def stats(self):
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 3) if total else 0,
            "size": len(self._cache),
        }


_cache = PromptCache()


def get_cache():
    return _cache