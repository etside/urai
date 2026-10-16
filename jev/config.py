#!/usr/bin/env python3
"""Central runtime config for the JEV harness (env-driven).

One place to read feature flags so behaviour can change without code edits.
Values come from the environment; call ``reload()`` after mutating ``os.environ``
(e.g. in tests).

    CACHE_ENABLED=true|false      prompt cache on/off (default true)
    CACHE_TTL=<seconds>           cache entry lifetime (default 300)
    CACHE_MAX=<n>                 max entries, LRU eviction (default 256)
    CACHE_SIMILARITY=<0..1>       near-identical threshold (0 = exact only)
    MEMORY_ENABLED=true|false     Active Memory + retrieval on/off (default true)
    RETRIEVAL_TOP_K=<n>           memory chunks injected per request (default 5)
    RETRIEVAL_RECENCY_WEIGHT=<0..1>  blend of recency vs relevance (default .25)
    RETRIEVAL_HALFLIFE_DAYS=<days>   recency half-life (default 30)
    URAI_AUTH_GET=true|false      gate discovery GETs with the API key
                                  (default: on in prod, off otherwise)
    URAI_STREAM=true|false        real token streaming when the backend can
    URAI_ENV=prod|production      marks a production deployment
"""
from __future__ import annotations

import os

_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    v = str(v).strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return default


def _int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, default)).strip())
    except Exception:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(str(os.environ.get(name, default)).strip())
    except Exception:
        return default


def is_prod() -> bool:
    return (str(os.environ.get("URAI_ENV", "")).strip().lower()
            in ("prod", "production")) or _bool("URAI_PROD", False)


class Config:
    def __init__(self):
        self.reload()

    def reload(self):
        self.prod = is_prod()

        # prompt cache
        self.CACHE_ENABLED = _bool("CACHE_ENABLED", True)
        self.CACHE_TTL = max(0, _int("CACHE_TTL", 300))
        self.CACHE_MAX = max(1, _int("CACHE_MAX", 256))
        self.CACHE_SIMILARITY = max(0.0, min(1.0, _float("CACHE_SIMILARITY", 0.93)))

        # memory + retrieval
        self.MEMORY_ENABLED = _bool("MEMORY_ENABLED", True)
        self.RETRIEVAL_TOP_K = max(1, _int("RETRIEVAL_TOP_K", 5))
        self.RETRIEVAL_RECENCY_WEIGHT = max(
            0.0, min(1.0, _float("RETRIEVAL_RECENCY_WEIGHT", 0.25)))
        self.RETRIEVAL_HALFLIFE_DAYS = max(
            0.1, _float("RETRIEVAL_HALFLIFE_DAYS", 30.0))

        # api auth / streaming
        self.AUTH_GET = _bool("URAI_AUTH_GET", self.prod)
        self.STREAM = _bool("URAI_STREAM", True)

    def as_dict(self) -> dict:
        return {
            "prod": self.prod,
            "cache_enabled": self.CACHE_ENABLED,
            "cache_ttl": self.CACHE_TTL,
            "cache_max": self.CACHE_MAX,
            "cache_similarity": self.CACHE_SIMILARITY,
            "memory_enabled": self.MEMORY_ENABLED,
            "retrieval_top_k": self.RETRIEVAL_TOP_K,
            "retrieval_recency_weight": self.RETRIEVAL_RECENCY_WEIGHT,
            "retrieval_halflife_days": self.RETRIEVAL_HALFLIFE_DAYS,
            "auth_get": self.AUTH_GET,
            "stream": self.STREAM,
        }


_config = Config()


def get() -> Config:
    return _config


def reload() -> Config:
    _config.reload()
    return _config


if __name__ == "__main__":
    import json
    print(json.dumps(get().as_dict(), indent=2))
