#!/usr/bin/env python3
"""Urai API — OpenAI-compatible + token gate (master 856777) + superadmin + repo sync.

  Token policy:
    - Master key 856777 -> unlimited, cost 0 (usage.total_tokens = 0).
    - Guest (no/wrong key) -> 5 free responses, then blocked per IP/device
      with "Free Token Expired / 0 available Token".
    - Unblock by POST /auth/unlock {master_key:"856777"} or via superadmin.
    - Approval flow: POST /auth/request {device_id, whatsapp, gmail}
      -> appears in /superadmin/messages for manual approve.

  Superadmin (hidden, key=856777):
    GET  /superadmin/messages?key=856777
    POST /superadmin/approve  {key, device_id|ip, whatsapp, gmail}
    POST /superadmin/unblock  {key, ip|device_id}

  Repo <-> VPS link:
    GET  /v1/repo/status  -> git sha/branch/dirty + active model + version
    POST /v1/repo/sync {key} -> git pull --ff-only on /opt/urai (manual deploy)

  Stdlib only.
"""

import base64
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .agent import run_agent
from .backends import LlamaServerBackend, MockBackend
from .router import route
from . import tools as tool_engine

PORT = int(os.environ.get("URAI_PORT", "8777"))
STATIC_DIR = Path(__file__).resolve().parent / "static"
API_KEY = os.environ.get("URAI_API_KEY", "")
CORS_ORIGIN = os.environ.get("URAI_CORS_ORIGIN", "*")

MASTER_API_KEY = os.environ.get("URAI_MASTER_KEY", "856777")
FREE_LIMIT = int(os.environ.get("URAI_FREE_LIMIT", "5"))
BLOCK_SECONDS = int(os.environ.get("URAI_BLOCK_SECONDS", "1800"))

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("URAI_DATA_DIR", str(ROOT / "data")))
STATE_FILE = DATA_DIR / "token_state.json"

_guarded = ("/v1/", "/chat", "/generate", "/agent", "/tools",
            "/evaluate", "/see", "/imagine")

# ---------------------------------------------------------------- token store
_lock = threading.RLock()
_state = {
    "free_used": {},       # ip_or_device -> count
    "blocked": {},         # ip_or_device -> blocked_until (epoch)
    "approved": {},        # device_hash/id or ip -> {whatsapp,gmail,at,active}
    "live_log": [],        # [{t, ip, device, kind, preview, ...}]
    "stats": {"total_requests": 0, "blocked_hits": 0, "master_hits": 0},
}


def _load_state():
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if STATE_FILE.is_file():
            d = json.loads(STATE_FILE.read_text())
            for k in ("free_used", "blocked", "approved", "stats"):
                if k in d:
                    _state[k] = d[k]
            _state["live_log"] = d.get("live_log", [])[-200:]
    except Exception:
        pass


def _save_state():
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        d = {k: _state[k] for k in ("free_used", "blocked", "approved", "stats")}
        d["live_log"] = _state["live_log"][-200:]
        STATE_FILE.write_text(json.dumps(d))
    except Exception:
        pass


_load_state()


def _log(kind, ip="", device="", preview="", extra=None):
    try:
        with _lock:
            _state["live_log"].append({
                "t": int(time.time()),
                "kind": kind, "ip": ip, "device": device,
                "preview": (preview or "")[:220], "extra": extra or {},
            })
            _state["live_log"] = _state["live_log"][-200:]
        if len(_state["live_log"]) % 5 == 0:
            _save_state()
    except Exception:
        pass


def _client_ip(handler):
    try:
        fwd = handler.headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[0].strip()
        return (handler.client_address[0] if handler.client_address else "unknown")
    except Exception:
        return "unknown"


def _extract_master(body, headers, query):
    # 1. Authorization header
    try:
        auth = headers.get("Authorization", "") if headers else ""
        if auth == "Bearer " + MASTER_API_KEY or auth.strip() == MASTER_API_KEY:
            return True
    except Exception:
        pass
    # 2. body fields
    try:
        for k in ("master_key", "masterKey", "key", "token", "secret"):
            if isinstance(body, dict) and str(body.get(k, "")).strip() == MASTER_API_KEY:
                return True
    except Exception:
        pass
    # 3. query ?key=
    try:
        if isinstance(query, dict) and str(query.get("key", "")) == MASTER_API_KEY:
            return True
    except Exception:
        pass
    return False


def _device_id(body, headers, query):
    for src in (body,):
        if isinstance(src, dict):
            for k in ("device_id", "deviceId", "device", "did"):
                v = str(src.get(k, "") or "").strip()
                if v:
                    return v[:80]
    try:
        v = (headers.get("X-Device-Id", "") or "").strip()
        if v:
            return v[:80]
    except Exception:
        pass
    try:
        if isinstance(query, dict) and query.get("device_id"):
            return str(query["device_id"])[:80]
    except Exception:
        pass
    return ""


def _identity(ip, device):
    return (device or ip or "unknown")[:100]


def _is_approved_locked(ident, ip, device):
    for k in (ident, ip, device):
        if k and _state["approved"].get(k, {}).get("active"):
            return True
    return False


def _is_approved(ident, ip, device):
    with _lock:
        return _is_approved_locked(ident, ip, device)


def _check_access(ip, device, is_master):
    ident = _identity(ip, device)
    now = time.time()
    with _lock:
        _state["stats"]["total_requests"] += 1
        if is_master:
            _state["stats"]["master_hits"] += 1
            # master unblocks automatically
            _state["blocked"].pop(ident, None)
            _state["blocked"].pop(ip, None)
            if device:
                _state["blocked"].pop(device, None)
            return True, "master", 0
        if _is_approved_locked(ident, ip, device):
            return True, "approved_device", 0
        # blocked?
        for k in (ident, ip, device):
            if k and k in _state["blocked"]:
                if now < _state["blocked"][k]:
                    _state["stats"]["blocked_hits"] += 1
                    return False, "blocked", 0
                else:
                    _state["blocked"].pop(k, None)
                    _state["free_used"].pop(k, None)
        used = int(_state["free_used"].get(ident, 0))
        if used >= FREE_LIMIT:
            _state["blocked"][ident] = now + BLOCK_SECONDS
            _state["stats"]["blocked_hits"] += 1
            return False, "expired", 0
        return True, "free", max(0, FREE_LIMIT - used - 1)


def _prune_store():
    # bound memory: keep at most 2000 free-counters / 1000 blocks (oldest out)
    if len(_state["free_used"]) > 2000:
        for k in list(_state["free_used"])[:len(_state["free_used"]) - 2000]:
            _state["free_used"].pop(k, None)
    if len(_state["blocked"]) > 1000:
        ordered = sorted(_state["blocked"].items(), key=lambda kv: kv[1])
        for k, _ in ordered[:len(ordered) - 1000]:
            _state["blocked"].pop(k, None)


def _record_use(ip, device, is_master):
    ident = _identity(ip, device)
    with _lock:
        if is_master:
            return
        if _is_approved_locked(ident, ip, device):
            return
        _prune_store()
        _state["free_used"][ident] = int(_state["free_used"].get(ident, 0)) + 1
        if int(_state["free_used"][ident]) >= FREE_LIMIT:
            _state["blocked"][ident] = time.time() + BLOCK_SECONDS
    _save_state()


def _expired_payload(blocked_until=0):
    return {
        "status": "error",
        "code": "free_token_expired",
        "message": "Free Token Expired / 0 available Token. Submit master key 856777 as request fund message to restore access.",
        "master_hint": "POST /auth/unlock {\"master_key\":\"856777\",\"device_id\":\"...\"}",
        "approval_hint": "POST /auth/request {\"device_id\":\"...\",\"whatsapp\":\"...\",\"gmail\":\"...\"}",
        "blocked_until": int(blocked_until) if blocked_until else 0,
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0},
    }


def _needs_key(path: str) -> bool:
    return bool(API_KEY) and (path == "/chat" or path.startswith(_guarded[0])
                              or path in _guarded[1:])


# Discovery routes that stay public even when URAI_AUTH_GET hardens other GETs.
_PUBLIC_GET = ("/health", "/v1/models", "/models", "/v1/capabilities",
               "/v1/info", "/status", "/v1/docs", "/v1/token/status",
               "/v1/media/profiles", "/v1/integrations")


def _auth_get_enabled() -> bool:
    try:
        from . import config as _config
        return _config.get().AUTH_GET
    except Exception:
        return os.environ.get("URAI_AUTH_GET", "") in ("1", "true", "yes", "on")


def _stream_enabled() -> bool:
    try:
        from . import config as _config
        return _config.get().STREAM
    except Exception:
        return True


def _models():
    # Public surface only: two brands (urai, cyberurai). Internal backend ids
    # (qwen*, coder*, laya, jev-local-student, teacher fallback) stay in
    # metadata/traces and are never listed as selectable models.
    local = LlamaServerBackend()
    up = local.healthy()
    from .brand import brand_list
    return brand_list(up)


def _capabilities() -> dict:
    """One unified surface: models + their modes, then features / skills /
    methods / plugins. The UI renders this instead of a long model list."""
    from .brand import BRANDS, brand_list
    up = LlamaServerBackend().healthy()
    models = []
    for b in brand_list(up):
        modes = BRANDS.get(b["id"], {}).get("modes", [])
        models.append({**b, "modes": modes})
    skills = []
    try:
        from . import skills as _skills
        skills = [{"name": s["name"], "description": s["description"]}
                  for s in _skills.all_skills()]
    except Exception:
        pass
    plugins = []
    try:
        from . import plugins as _plugins
        plugins = [{"name": p.get("name"), "version": p.get("version", ""),
                    "description": p.get("description", ""),
                    "enabled": bool(p.get("enabled")),
                    "hooks": p.get("hooks", [])}
                   for p in _plugins.all_plugins()]
    except Exception:
        pass
    return {
        "identity": "Urai, developed by Tynio LTD",
        "models": models,
        "features": [
            "local-first zero-cost chat (cloud fallback)",
            "large context window (configurable, q8_0 KV cache)",
            "tool-use + agent + parallel swarm",
            "vision (images) + image generation + video animatic",
            "character-consistent video: H3 Ref2VA VSA + Wan 3.0 + Seedream 4.0",
            "OpenAI-compatible API + MCP + IDE integration",
            "human-like browser with approval safety",
            "memory, focus, schedules and few-shot self-learning",
        ],
        "skills": skills,
        "methods": [
            {"id": "classify", "desc": "per-request difficulty routing (L0-L4)"},
            {"id": "nlp", "desc": "request understanding: intent, sentiment, urgency, red flags"},
            {"id": "vibe", "desc": "sentiment-conditioned style directive injected before generation"},
            {"id": "retrieval", "desc": "memory + focus hybrid retrieval (relevance x recency)"},
            {"id": "cache", "desc": "prompt cache with near-identical matching (TTL + LRU)"},
            {"id": "verify", "desc": "consistency sampling + verification on hard tasks"},
            {"id": "distill", "desc": "teacher->student distillation into verified data"},
            {"id": "self-improve", "desc": "failure-mining loop promotes chunks to few-shots"},
            {"id": "tools", "desc": "repo/tool packs with jail + plan-approval guards"},
        ],
        "plugins": plugins,
        "media": _media_profiles(),
        "context_window": {
            "default": int(os.environ.get("URAI_CTX", "8192")),
            "note": "raise with URAI_CTX / --ctx; q8_0 KV keeps RAM low",
        },
    }


def _urai_meta(text: str) -> dict:
    """NLP analysis + vibe style plan for a chat turn (urai.nlp / urai.vibe)."""
    text = (text or "").strip()
    if not text:
        return {}
    meta = {}
    analysis = {}
    try:
        from . import nlp as _nlp
        analysis = _nlp.analyze(text)
        meta["nlp"] = analysis
    except Exception:
        pass
    try:
        from . import vibe as _vibe
        v = _vibe.plan(analysis) if analysis else _vibe.plan_for(text)
        if v:
            v["directive"] = _vibe.directive(v)
        meta["vibe"] = v
    except Exception:
        pass
    return meta


def _apply_vibe(msgs: list) -> tuple:
    """Run NLP + vibe on the last user turn, prepend the style directive, and
    return (msgs, meta). Every chat turn passes through this BEFORE the LLM.
    Deterministic and never raises; no-op when there is no text."""
    if not isinstance(msgs, list):
        return msgs, {}
    meta = _urai_meta(_text_of(msgs))
    directive = (meta.get("vibe") or {}).get("directive")
    if directive:
        msgs = [{"role": "system", "content": directive}] + msgs
    return msgs, meta


def _normalize_error(obj, code):
    """One error contract: {"error":{"message","type","code"}}. Rewrites the
    legacy flat {"error":"..."} shape for any 4xx/5xx response (idempotent)."""
    if code < 400 or not isinstance(obj, dict) or not isinstance(obj.get("error"), str):
        return obj
    obj = dict(obj)
    msg = obj.pop("error")
    if code == 403:
        etype = "auth_error"
    elif code >= 500:
        etype = "server_error"
    else:
        etype = "invalid_request_error"
    ecode = obj.pop("code", None) or {
        400: "invalid_request", 401: "invalid_api_key",
        403: "forbidden", 404: "not_found", 429: "rate_limited",
    }.get(code, "server_error" if code >= 500 else "error")
    obj["error"] = {"message": msg, "type": etype, "code": ecode}
    return obj


def _complete(backend, msgs, max_tokens=256, temperature=0.2) -> dict:
    """backend.complete() behind the prompt cache (never raises on cache error)."""
    from . import cache as _cache
    try:
        return _cache.cached_complete(backend, msgs, max_tokens, temperature)
    except Exception:
        return backend.complete(msgs, max_tokens=max_tokens, temperature=temperature)


def _with_cache(meta: dict, res: dict) -> dict:
    """Fold cache-hit info into the response `urai` metadata block."""
    meta = dict(meta or {})
    if isinstance(res, dict) and "cached" in res:
        meta["cached"] = bool(res.get("cached"))
        if res.get("cache_hit"):
            meta["cache_hit"] = res["cache_hit"]
    return meta


_START_TS = time.time()


def _metrics_snapshot() -> dict:
    """Single source of truth for /admin/metrics + /metrics."""
    from . import config as _config
    try:
        cfg = _config.get()
        env = "prod" if cfg.is_prod() else "dev"
        auth_get, stream = cfg.AUTH_GET, cfg.STREAM
    except Exception:
        env, auth_get, stream = "dev", _auth_get_enabled(), _stream_enabled()
    try:
        from . import cache as _cache
        cache_stats = _cache.get_cache().stats()
    except Exception:
        cache_stats = {}
    local = LlamaServerBackend()
    with _lock:
        stats = dict(_state["stats"])
        free_used = int(sum(_state["free_used"].values()))
        blocked = int(sum(1 for v in _state["blocked"].values() if float(v) > time.time()))
        approved = int(sum(1 for v in _state["approved"].values()
                           if isinstance(v, dict) and v.get("active")))
        live = len(_state["live_log"])
    return {
        "uptime_seconds": round(time.time() - _START_TS, 1),
        "env": env, "auth_get": bool(auth_get), "stream": bool(stream),
        "local_llama": local.healthy(),
        "active_model": _repo_status().get("active_model"),
        "version": _repo_status().get("version"),
        "requests": stats,
        "tokens": {"free_used_total": free_used,
                   "free_limit": FREE_LIMIT,
                   "blocked_identities": blocked,
                   "approved_identities": approved},
        "log_entries": live,
        "cache": cache_stats,
    }


def _prometheus_text(snap: dict) -> str:
    c = snap.get("cache") or {}
    r = snap.get("requests") or {}
    t = snap.get("tokens") or {}
    lines = [
        "# HELP urai_uptime_seconds Process uptime.",
        "# TYPE urai_uptime_seconds gauge",
        f"urai_uptime_seconds {snap.get('uptime_seconds', 0)}",
        "# HELP urai_local_llama_up Whether the local llama-server is reachable.",
        "# TYPE urai_local_llama_up gauge",
        f"urai_local_llama_up {1 if snap.get('local_llama') else 0}",
        "# HELP urai_requests_total Total requests seen.",
        "# TYPE urai_requests_total counter",
        f"urai_requests_total {r.get('total_requests', 0)}",
        "# HELP urai_blocked_hits_total Requests rejected by the free-token gate.",
        "# TYPE urai_blocked_hits_total counter",
        f"urai_blocked_hits_total {r.get('blocked_hits', 0)}",
        "# HELP urai_master_hits_total Requests authenticated with the master key.",
        "# TYPE urai_master_hits_total counter",
        f"urai_master_hits_total {r.get('master_hits', 0)}",
        "# HELP urai_free_tokens_used Free tokens consumed across identities.",
        "# TYPE urai_free_tokens_used gauge",
        f"urai_free_tokens_used {t.get('free_used_total', 0)}",
        "# HELP urai_cache_entries Cached prompt responses held.",
        "# TYPE urai_cache_entries gauge",
        f"urai_cache_entries {c.get('size', 0)}",
        "# HELP urai_cache_hits_total Prompt cache hits.",
        "# TYPE urai_cache_hits_total counter",
        f"urai_cache_hits_total {c.get('hits', 0)}",
        "# HELP urai_cache_misses_total Prompt cache misses.",
        "# TYPE urai_cache_misses_total counter",
        f"urai_cache_misses_total {c.get('misses', 0)}",
        "# HELP urai_cache_evictions_total Prompt cache evictions.",
        "# TYPE urai_cache_evictions_total counter",
        f"urai_cache_evictions_total {c.get('evictions', 0)}",
    ]
    return "\n".join(lines) + "\n"


def _media_profiles() -> list:
    try:
        from .video import profiles as _p
        return _p()
    except Exception:
        return []


def _as_messages(raw) -> list:
    msgs = []
    for m in raw or []:
        if isinstance(m, str):
            msgs.append({"role": "user", "content": m})
        elif isinstance(m, dict):
            msgs.append({"role": m.get("role", "user"),
                         "content": m.get("content", "")})
    return msgs


def _text_of(msgs) -> str:
    out = []
    for m in msgs:
        c = m.get("content", "")
        if isinstance(c, list):
            out += [p.get("text", "") for p in c if p.get("type") == "text"]
        else:
            out.append(str(c))
    return "\n".join(out)


def _has_image(msgs) -> bool:
    return any(isinstance(m.get("content"), list) and
               any(p.get("type") == "image_url" for p in m["content"])
               for m in msgs)


def _split_image(msgs):
    question = ""
    for m in reversed(msgs):
        c = m.get("content", "")
        if not isinstance(c, list):
            if not question and isinstance(c, str):
                question = c
            continue
        for p in c:
            if p.get("type") == "text" and not question:
                question = p.get("text", "")
            if p.get("type") == "image_url":
                u = (p.get("image_url") or {}).get("url", "")
                return u, question
    return None, question


def _repo_status():
    out = {"repo": str(ROOT), "git": {}, "active_model": None, "version": None}
    try:
        r = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=5)
        out["git"]["sha"] = (r.stdout or "").strip()[:12]
        r2 = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
                            capture_output=True, text=True, timeout=5)
        out["git"]["branch"] = (r2.stdout or "").strip()
        r3 = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"],
                            capture_output=True, text=True, timeout=5)
        out["git"]["dirty"] = bool((r3.stdout or "").strip())
    except Exception as e:
        out["git"]["error"] = str(e)[:120]
    try:
        from . import models_registry as _reg
        reg = _reg.load()
        out["active_model"] = reg.get("active")
        out["models"] = sorted(list(reg.get("models", {}).keys()))
    except Exception as e:
        out["model_error"] = str(e)[:120]
    try:
        from . import VERSION as _v
        out["version"] = _v
    except Exception:
        pass
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "Urai/2.0"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
        self.send_header("Vary", "Origin")
        if CORS_ORIGIN and CORS_ORIGIN != "*":
            self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, Authorization, X-Device-Id, X-Admin-Key")

    def _sec_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def _reqid(self) -> str:
        rid = getattr(self, "_urai_rid", None)
        if not rid:
            rid = os.urandom(8).hex()
            self._urai_rid = rid
        return rid

    def _send(self, obj, code=200):
        obj = _normalize_error(obj, code)
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Request-Id", self._reqid())
        self._cors()
        self._sec_headers()
        self.end_headers()
        self.wfile.write(body)
        print(f"{self.client_address[0]} {self.command} {self.path} -> {code}",
              flush=True)

    def _deny(self):
        self._send({"error": {"message": "invalid API key",
                              "type": "invalid_request_error",
                              "code": "invalid_api_key"}}, 401)

    def _auth_ok(self) -> bool:
        if not _needs_key(self.path):
            return True
        got = self.headers.get("Authorization", "")
        if got.startswith("Bearer "):
            tok = got[7:].strip()
            if tok == API_KEY or tok == MASTER_API_KEY:
                return True
            try:
                from . import apitokens as _at
                _rec = _at.check(tok)
                if _rec:
                    _at.record_use(_rec["id"])
                    return True
            except Exception:
                pass
        return False

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _read_json(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n > 10_000_000:
            raise ValueError("body too large")
        raw = self.rfile.read(n) or b"{}"
        return json.loads(raw)  # strict: malformed JSON raises -> 400 in do_POST

    def _query(self):
        try:
            q = urllib.parse.urlparse(self.path).query
            return dict(urllib.parse.parse_qsl(q))
        except Exception:
            return {}

    def _path(self):
        try:
            return urllib.parse.urlparse(self.path).path
        except Exception:
            return self.path

    def log_message(self, *a):
        pass

    def _static(self):
        p = self._path()
        # hidden superadmin served by same app.html; JS detects path
        rel = "app.html" if p in ("/", "/app", "/app/", "/superadmin") else \
              "landing.html" if p in ("/welcome", "/welcome/") else \
            p[len("/app/"):] if p.startswith("/app/") else None
        if rel is None or ".." in rel:
            return self._send({"error": "not found"}, 404)
        f = STATIC_DIR / rel
        if not f.is_file():
            return self._send({"error": "not found"}, 404)
        data = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type",
                         mimetypes.guess_type(str(f))[0] or
                         "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Request-Id", self._reqid())
        self._cors()
        self.end_headers()
        self.wfile.write(data)
        print(f"{self.client_address[0]} GET {self.path} -> 200", flush=True)

    def _frontend(self):
        p = self._path()
        rel = p[len("/frontend/"):]
        if not rel or ".." in rel or rel.startswith("/"):
            return self._send({"error": "not found"}, 404)
        base = (ROOT / "frontend").resolve()
        f = (base / rel).resolve()
        try:
            f.relative_to(base)
        except ValueError:
            return self._send({"error": "not found"}, 404)
        if not f.is_file():
            return self._send({"error": "not found"}, 404)
        data = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type",
                         mimetypes.guess_type(str(f))[0] or
                         "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.send_header("X-Request-Id", self._reqid())
        self._cors()
        self.end_headers()
        self.wfile.write(data)
        print(f"{self.client_address[0]} GET {self.path} -> 200", flush=True)

    def _send_static_file(self, f, ctype):
        if not f.is_file():
            return self._send({"error": "not found"}, 404)
        data = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("X-Request-Id", self._reqid())
        self._cors()
        self.end_headers()
        self.wfile.write(data)
        print(f"{self.client_address[0]} GET {self.path} -> 200", flush=True)

    # ---------------- GET ----------------
    def do_GET(self):
        p = self._path()
        q = self._query()
        if _auth_get_enabled() and _needs_key(p) and p not in _PUBLIC_GET \
                and not p.startswith("/docs/") and not p.startswith("/frontend/"):
            if not self._auth_ok():
                return self._deny()
        if p == "/health":
            local = LlamaServerBackend()
            self._send({"status": "ok", "local_llama": local.healthy(),
                        "identity": "Urai, developed by Tynio LTD",
                        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            return
        if p in ("/models", "/v1/models"):
            self._send({"object": "list",
                        "data": [{"object": "model", **m} for m in _models()]})
            return
        if p == "/status":
            return self._status_page()
        if p == "/metrics":
            snap = _metrics_snapshot()
            body = _prometheus_text(snap).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("X-Request-Id", self._reqid())
            self._cors()
            self._sec_headers()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if p == "/admin/metrics":
            if str(q.get("key", "")) != MASTER_API_KEY and \
                    self.headers.get("X-Admin-Key") != MASTER_API_KEY:
                return self._send({"error": {"message": "forbidden",
                                             "type": "auth_error",
                                             "code": "forbidden"}}, 403)
            return self._send(_metrics_snapshot())
        if p == "/trace":
            return self._trace_page()
        if p == "/admin/trace":
            if str(q.get("key", "")) != MASTER_API_KEY and \
                    self.headers.get("X-Admin-Key") != MASTER_API_KEY:
                return self._send({"error": {"message": "forbidden",
                                             "type": "auth_error",
                                             "code": "forbidden"}}, 403)
            with _lock:
                return self._send({"events": _state["live_log"][-200:],
                                   "stats": _metrics_snapshot()})
        if p == "/v1/integrations":
            from .integrations import report as _ireport
            return self._send(_ireport())
        if p == "/v1/token/status":
            ip = _client_ip(self)
            device = _device_id({}, self.headers, q)
            ident = _identity(ip, device)
            with _lock:
                used = int(_state["free_used"].get(ident, 0))
                blk = float(_state["blocked"].get(ident, 0))
                appr = bool(_state["approved"].get(ident, {}).get("active"))
            self._send({"ip": ip, "device": device, "free_used": used,
                        "free_limit": FREE_LIMIT,
                        "remaining": max(0, FREE_LIMIT - used),
                        "blocked_until": int(blk) if blk > time.time() else 0,
                        "approved": appr,
                        "master_required": "856777"})
            return
        if p == "/v1/repo/status":
            self._send(_repo_status())
            return
        if p == "/superadmin/messages":
            if str(q.get("key", "")) != MASTER_API_KEY:
                return self._send({"error": "forbidden"}, 403)
            with _lock:
                self._send({
                    "live": _state["live_log"][-100:],
                    "approved": _state["approved"],
                    "blocked": _state["blocked"],
                    "free_used": _state["free_used"],
                    "stats": _state["stats"],
                })
            return
        if p.startswith("/browser/status/"):
            from . import browser as _b
            info = _b.run_status(p[len("/browser/status/"):].split("/")[0])
            return self._send(info, 200 if info.get("ok") else 404)
        if p.startswith("/v1/videos/"):
            from . import video as _video
            jid = p[len("/v1/videos/"):].split("/")[0]
            if jid in ("generations", ""):
                return self._send(_video.status())
            info = _video.job_info(jid)
            if not info.get("ok"):
                return self._send(info, 404)
            return self._send(info)
        if p == "/v1/capabilities":
            return self._send(_capabilities())
        if p == "/v1/media/profiles":
            from . import video as _video
            return self._send({"profiles": _video.profiles()})
        if p == "/v1/info":
            local = LlamaServerBackend()
            self._send({
                "name": "Urai", "identity": "Urai, developed by Tynio LTD",
                "version": _repo_status().get("version"),
                "active_model": _repo_status().get("active_model"),
                "local_llama": local.healthy(),
                "measured": {
                    "gen_toks_per_s": "6-9", "prompt_toks_per_s": "12-28",
                    "embed_dims": 768, "note": "llama-server slot timings on this CPU droplet (Qwen3-4B Q4_K_M); varies with load and context length",
                },
                "strengths": ["local-first zero-cost chat", "agent + swarm + tools",
                              "vision + image + video-animatic", "OpenAI-compatible API + MCP",
                              "human-like browser with approval safety"],
                "endpoints": ["/health", "/v1/models", "/v1/chat/completions",
                              "/v1/completions", "/v1/embeddings", "/agent", "/agent/swarm",
                              "/tools", "/evaluate", "/see", "/imagine",
                              "/v1/images/generations", "/video", "/v1/videos/generations",
                              "/v1/videos/<id>", "/browser/run", "/browser/status/<id>",
                              "/browser/approve", "/auth/unlock", "/auth/request",
                              "/v1/token/status", "/superadmin/messages",
                              "/v1/repo/status", "/v1/repo/sync", "/v1/info",
                              "/v1/docs", "/v1/notices", "/docs/<file>", "/superadmin"],
                "docs": "/v1/docs",
            })
            return
        if p == "/v1/benchmarks":
            rdir = ROOT / "eval" / "reports"
            reps = sorted(rdir.glob("bench-*.json"),
                          key=lambda f: f.stat().st_mtime) if rdir.is_dir() else []
            latest, latest_name = None, None
            for fp in reversed(reps):
                try:
                    d = json.loads(fp.read_text())
                    if isinstance(d.get("categories"), dict):
                        latest = {k: d.get(k) for k in
                                  ("tag", "started", "categories", "calls", "total_s")}
                        latest["report"] = fp.name
                        latest_name = fp.name
                        break
                except Exception:
                    continue
            self._send({"latest": latest, "latest_report": latest_name,
                        "reports": [r.name for r in reps[-10:]],
                        "method_doc": "/docs/BENCHMARKS.md"})
            return
        if p == "/v1/docs":
            docs = []
            ddir = ROOT / "docs"
            if ddir.is_dir():
                for f in sorted(ddir.glob("*.md")):
                    docs.append({"name": f.name, "url": f"/docs/{f.name}"})
            self._send({"docs": docs, "openapi": "OpenAI-compatible: /v1/chat/completions, /v1/completions, /v1/embeddings, /v1/models"})
            return
        if p == "/v1/notices":
            nf = DATA_DIR / "notices.json"
            try:
                items = json.loads(nf.read_text()).get("notices", []) if nf.is_file() else []
            except Exception:
                items = []
            self._send({"notices": items[-20:]})
            return
        if p == "/docs" or p.startswith("/docs/"):
            rel = p[len("/docs/"):] if p.startswith("/docs/") else ""
            if not rel or ".." in rel or "/" in rel or not rel.endswith(".md"):
                return self._send({"error": "use /v1/docs for the index, /docs/<file>.md for files"}, 404)
            f = ROOT / "docs" / rel
            if not f.is_file():
                return self._send({"error": "not found"}, 404)
            data = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self._cors()
            self.end_headers()
            self.wfile.write(data)
            print(f"{self.client_address[0]} GET {self.path} -> 200", flush=True)
            return
        if p == "/favicon.ico":
            return self._send_static_file(ROOT / "frontend" / "brand" / "favicon-32.png",
                                          "image/png")
        if p == "/manifest.webmanifest":
            return self._send_static_file(ROOT / "frontend" / "manifest.webmanifest",
                                          "application/manifest+json")
        if p.startswith("/frontend/"):
            return self._frontend()
        if p in ("/", "/app", "/app/", "/welcome", "/welcome/") or p.startswith("/app/") or p == "/superadmin":
            return self._static()
        self._send({"error": "not found"}, 404)

    # ---------------- POST ----------------
    def do_POST(self):
        p = self._path()
        q = self._query()
        if not self._auth_ok():
            return self._deny()
        try:
            body = self._read_json()
        except Exception:
            return self._send({"error": "invalid json"}, 400)

        ip = _client_ip(self)
        device = _device_id(body if isinstance(body, dict) else {}, self.headers, q)
        ident = _identity(ip, device)
        is_master = _extract_master(body if isinstance(body, dict) else {}, self.headers, q)
        _tok, _tok_id = None, ""
        if not is_master:
            try:
                from . import apitokens as _at
                _raw = ""
                _h = self.headers.get("Authorization", "") if self.headers else ""
                if _h.startswith("Bearer "):
                    _raw = _h[7:]
                if not _raw and isinstance(body, dict):
                    _raw = str(body.get("api_token", "") or "")
                if not _raw and isinstance(q, dict):
                    _raw = str(q.get("api_token", "") or "")
                _tok = _at.check(_raw)
                _tok_id = _tok["id"] if _tok else ""
            except Exception:
                _tok, _tok_id = None, ""
        authed = bool(is_master or _tok)

        # ---- admin (master-gated) ----
        if p == "/admin/cache/clear":
            if not is_master:
                return self._send({"error": {"message": "forbidden",
                                             "type": "auth_error",
                                             "code": "forbidden"}}, 403)
            try:
                from . import cache as _cache
                removed = _cache.get_cache().clear()
            except Exception as e:
                return self._send({"error": {"message": str(e)[:200],
                                             "type": "server_error",
                                             "code": "cache_clear_failed"}}, 500)
            _log("admin", ip, device, "cache clear")
            return self._send({"ok": True, "cleared": removed})

        # ---- open auth / repo / superadmin routes (token-gated internally) ----
        if p == "/auth/unlock":
            if is_master:
                with _lock:
                    for k in (ident, ip, device):
                        if k:
                            _state["blocked"].pop(k, None)
                            _state["free_used"].pop(k, None)
                    if device:
                        _state["approved"].setdefault(device, {}).update(
                            {"active": True, "at": int(time.time()), "via": "master_key"})
                _save_state()
                _log("unlock", ip, device, "master unlock ok")
                return self._send({"ok": True, "authenticated": True,
                                   "cost": 0,
                                   "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                                             "total_tokens": 0, "cost": 0}})
            _log("unlock_fail", ip, device, str((body or {}).get("master_key", ""))[:20])
            return self._send({"ok": False, "authenticated": False,
                               "message": "Invalid master key. Expected 856777."}, 401)

        if p == "/auth/request":
            wa = str((body or {}).get("whatsapp", ""))[:40]
            gm = str((body or {}).get("gmail", ""))[:80]
            msg = str((body or {}).get("message", ""))[:300]
            _log("approval_request", ip, device, msg or "approval request",
                 {"whatsapp": wa, "gmail": gm})
            _save_state()
            return self._send({"ok": True, "pending": True,
                               "message": "Request sent to superadmin. You will be approved after WhatsApp/Gmail verification."})

        if p == "/superadmin/tokens":
            if not is_master:
                return self._send({"error": "forbidden - master key required"}, 403)
            from . import apitokens as _at
            action = body.get("action", "list")
            if action == "issue":
                return self._send(_at.issue(body.get("label", ""),
                                            body.get("quota", 0)))
            if action == "revoke":
                return self._send(_at.revoke(body.get("id", "")))
            return self._send({"ok": True, "tokens": _at.list_tokens()})

        if p == "/superadmin/approve":
            if not is_master:
                return self._send({"error": "forbidden"}, 403)
            target = str((body or {}).get("device_id") or (body or {}).get("ip") or "")[:100]
            wa = str((body or {}).get("whatsapp", ""))[:40]
            gm = str((body or {}).get("gmail", ""))[:80]
            if not target:
                return self._send({"error": "device_id or ip required"}, 400)
            with _lock:
                _state["approved"][target] = {"whatsapp": wa, "gmail": gm,
                                              "at": int(time.time()), "active": True}
                _state["blocked"].pop(target, None)
                _state["free_used"].pop(target, None)
            _save_state()
            _log("approved", ip, target, f"approved {target} wa={wa} gmail={gm}")
            return self._send({"ok": True, "approved": target})

        if p == "/superadmin/unblock":
            if not is_master:
                return self._send({"error": "forbidden"}, 403)
            target = str((body or {}).get("ip") or (body or {}).get("device_id") or "")[:100]
            if not target:
                return self._send({"error": "ip or device_id required"}, 400)
            with _lock:
                _state["blocked"].pop(target, None)
                _state["free_used"].pop(target, None)
            _save_state()
            _log("unblocked", ip, target, f"unblocked {target}")
            return self._send({"ok": True, "unblocked": target})

        if p == "/v1/repo/sync":
            if not is_master:
                return self._send({"error": "forbidden - master key required"}, 403)
            try:
                r = subprocess.run(["git", "-C", str(ROOT), "pull", "--ff-only"],
                                   capture_output=True, text=True, timeout=120)
                out = (r.stdout or "") + (r.stderr or "")
                _log("repo_sync", ip, device, out[:200], {"rc": r.returncode})
                return self._send({"ok": r.returncode == 0, "rc": r.returncode,
                                   "log": out[-2000:], "status": _repo_status()})
            except Exception as e:
                return self._send({"ok": False, "error": str(e)[:300]}, 500)

        # ---- token-gated AI routes ----
        gated = ("/chat", "/v1/chat/completions", "/v1/completions", "/generate",
                 "/agent", "/agent/sessions", "/agent/jobs", "/tools", "/evaluate", "/see", "/imagine",
                 "/v1/images/generations", "/v1/embeddings",
                 "/v1/videos/generations")
        needs_gate = (p == "/chat" or p.startswith("/v1/") or p in gated[2:]
                      or p.startswith("/agent") or p.startswith("/browser/"))
        if needs_gate and p not in ("/v1/models",):
            allowed, reason, remaining = _check_access(ip, device, authed)
            if _tok:
                try:
                    from . import apitokens as _at2
                    _at2.record_use(_tok_id)
                except Exception:
                    pass
                reason = "api_token"
            if not allowed:
                with _lock:
                    blk = float(_state["blocked"].get(ident, 0))
                _log("blocked", ip, device, _text_of(_as_messages((body or {}).get("messages", [])))[:120] if isinstance(body, dict) else (body or {}).get("task", "")[:120] if isinstance(body, dict) else "")
                return self._send(_expired_payload(blk), 403)
            # record use AFTER success? record now for simplicity (prevents abuse on errors too)
            # we record after successful generation below; store flag
            body["_urai_authed"] = bool(is_master or _tok_id)
            body["_urai_reason"] = reason
            body["_urai_remaining"] = remaining

        # ---- handlers ----
        if p == "/chat":
            msgs = _as_messages(body.get("messages", []))
            user_text = _text_of(msgs)
            msgs, _meta = _apply_vibe(msgs)
            max_tokens = body.get("max_tokens", 256)
            temperature = body.get("temperature", 0.2)
            # identity guard: always Urai / Tynio LTD
            try:
                from .brand import tier_of_brand as _tier_of
                r = route(user_text, tier=_tier_of(body.get("model", "urai")))
            except Exception as e:
                return self._send({"error": str(e)[:300]}, 502)
            if body.get("stream"):
                _record_use(ip, device, bool(body.get("_urai_authed")))
                _log("chat", ip, device, user_text[:160] + " -> (stream)",
                     {"master": bool(body.get("_urai_authed"))})
                return self._stream(
                    None, __import__("jev.brand", fromlist=["brand_id"]).brand_id(body.get("model", "urai")),
                    _meta, backend=r["backend"], msgs=msgs,
                    max_tokens=max_tokens, temperature=temperature)
            try:
                res = _complete(r["backend"], msgs, max_tokens, temperature)
                content = res["content"]
                _meta = _with_cache(_meta, res)
            except Exception as e:
                return self._send({"error": str(e)[:300]}, 502)
            _record_use(ip, device, bool(body.get("_urai_authed")))
            _log("chat", ip, device, user_text[:160] + " -> " + content[:120],
                 {"master": bool(body.get("_urai_authed"))})
            usage = res.get("usage") or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0}
            return self._send({
                "id": "chatcmpl-urai", "object": "chat.completion",
                "model": __import__("jev.brand", fromlist=["brand_id"]).brand_id(res.get("model", "")),
                "choices": [{"index": 0, "message": {"role": "assistant",
                                                     "content": content},
                             "finish_reason": "stop"}],
                "usage": usage,
                "urai": {"level": r["level"], "backend": r["backend"].name,
                         "tokens_remaining": body.get("_urai_remaining", 0),
                         "auth": body.get("_urai_reason", "free"),
                         **_meta},
                "jev": {"level": r["level"], "backend": r["backend"].name}})

        if p == "/v1/chat/completions":
            msgs = _as_messages(body.get("messages", []))
            _meta = {}
            model = body.get("model", "urai")
            max_tokens = body.get("max_tokens", 256)
            temperature = body.get("temperature", 0.2)
            if _has_image(msgs):
                from . import vision as _vision
                img, question = _split_image(msgs)
                if img is None:
                    return self._send({"error": "no image found in messages"}, 400)
                res = _vision.see(img, question or "Describe this image.",
                                  body.get("max_tokens", 512), temperature)
                if not res["ok"]:
                    return self._send({"error": res["error"]}, 502)
                content = res["answer"]
                _meta = _urai_meta(_text_of(msgs))
                model = body.get("model", __import__("jev.brand", fromlist=["brand_id"]).brand_id(body.get("model", "urai")))
            else:
                user_text = _text_of(msgs)
                msgs, _meta = _apply_vibe(msgs)
                try:
                    from .brand import tier_of_brand as _tier_of
                    r = route(user_text, tier=_tier_of(body.get("model", "urai")))
                except Exception as e:
                    return self._send({"error": str(e)[:300]}, 502)
                model = __import__("jev.brand", fromlist=["brand_id"]).brand_id(
                    body.get("model", r["backend"].name))
                if body.get("stream"):
                    _record_use(ip, device, bool(body.get("_urai_authed")))
                    _log("chat", ip, device, user_text[:160] + " -> (stream)",
                         {"master": bool(body.get("_urai_authed")), "model": model})
                    return self._stream(None, model, _meta, backend=r["backend"],
                                        msgs=msgs, max_tokens=max_tokens,
                                        temperature=temperature)
                try:
                    res = _complete(r["backend"], msgs, max_tokens, temperature)
                    content = res["content"]
                    _meta = _with_cache(_meta, res)
                    model = body.get("model", __import__("jev.brand", fromlist=["brand_id"]).brand_id(res.get("model", "")))
                except Exception as e:
                    return self._send({"error": str(e)[:300]}, 502)
            _record_use(ip, device, bool(body.get("_urai_authed")))
            _log("chat", ip, device, _text_of(msgs)[:160] + " -> " + str(content)[:120],
                 {"master": bool(body.get("_urai_authed")), "model": model})
            return self._send({
                "id": "chatcmpl-urai", "object": "chat.completion",
                "created": int(time.time()), "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant",
                                                     "content": content},
                             "finish_reason": "stop"}],
                "usage": res.get("usage") or {"prompt_tokens": 0, "completion_tokens": 0,
                          "total_tokens": 0, "cost": 0},
                "urai": {"tokens_remaining": body.get("_urai_remaining", 0),
                         "auth": body.get("_urai_reason", "free"),
                         **_meta}})

        if p in ("/imagine", "/v1/images/generations"):
            from . import imagine as _imagine
            prompt = body.get("prompt", "")
            _meta = _urai_meta(prompt)
            steps = body.get("steps")
            # urgency -> fewer steps for faster feedback (never override caller)
            if steps is None and (_meta.get("nlp") or {}).get("urgency", 0) > 0.5:
                steps = 1
            res = _imagine.generate(
                prompt,
                body.get("out") or body.get("file"),
                steps, body.get("width"), body.get("height"),
                body.get("seed", 7), body.get("provider"))
            if not res["ok"]:
                return self._send({"error": res["error"]}, 502)
            _record_use(ip, device, bool(body.get("_urai_authed")))
            if body.get("response_format") == "b64_json":
                raw = Path(res["path"]).read_bytes()
                data = [{"b64_json": base64.b64encode(raw).decode()}]
            else:
                data = [{"url": "file://" + res["path"]}]
            return self._send({"created": int(time.time()), "data": data,
                               "urai": _meta,
                               **{k: v for k, v in res.items()
                                   if k not in ("path",)}})

        if p in ("/video", "/v1/videos/generations"):
            from . import video as _video
            res = _video.generate(
                body.get("prompt", ""), body.get("out"),
                body.get("duration", 4), body.get("width", 512),
                body.get("height", 512), body.get("fps", 4),
                body.get("seed", 7), body.get("provider", "auto"),
                body.get("provider_url"), body.get("provider_key"),
                ref_images=body.get("ref_images") or body.get("reference_images"),
                profile=body.get("profile"),
                settings=body.get("settings"))
            if not res.get("ok"):
                err = {"ok": False, "error": res.get("error"),
                       "grade": res.get("grade", ""),
                       "provider": res.get("provider", body.get("provider"))}
                if "installed" in res:
                    err["installed"] = res["installed"]
                if res.get("status"):
                    err["status"] = res["status"]
                return self._send(err, 502)
            _record_use(ip, device, bool(body.get("_urai_authed")))
            _log("video", ip, device, str(body.get("prompt", ""))[:160],
                 {"master": bool(body.get("_urai_authed")), "id": res.get("id")})
            if body.get("response_format") == "b64_json" and res.get("path"):
                try:
                    raw = Path(res["path"]).read_bytes()
                    if len(raw) < 8_000_000:
                        res["b64_json"] = base64.b64encode(raw).decode()
                        del res["path"]
                except Exception as e:
                    res["file_error"] = str(e)[:120]
            return self._send(res)

        if p == "/see":
            from . import vision as _vision
            res = _vision.see(body.get("image", ""),
                              body.get("question", "Describe this image."),
                              body.get("max_tokens", 512),
                              body.get("temperature", 0.2))
            if not res["ok"]:
                return self._send({"error": res["error"]}, 502)
            _record_use(ip, device, bool(body.get("_urai_authed")))
            return self._send(res)

        if p == "/v1/embeddings":
            from .backends import EmbeddingBackend
            be = EmbeddingBackend(model=body.get("model", "local-embed"))
            if not be.healthy():
                return self._send({"error": "embedding server down; run: "
                                            "urai model download embed-small && "
                                            "urai serve start --model embed-small"},
                                  502)
            try:
                vecs = be.embed(body.get("input", ""))
            except Exception as e:
                return self._send({"error": str(e)[:300]}, 502)
            _record_use(ip, device, bool(body.get("_urai_authed")))
            return self._send({
                "object": "list",
                "data": [{"object": "embedding", "index": i,
                          "embedding": v} for i, v in enumerate(vecs)],
                "model": body.get("model", "local-embed"),
                "usage": {"prompt_tokens": 0, "total_tokens": 0, "cost": 0}})

        if p == "/generate":
            prompt = body.get("prompt", "")
            msgs, _meta = _apply_vibe([{"role": "user", "content": prompt}])
            max_tokens = body.get("max_tokens", 256)
            temperature = body.get("temperature", 0.2)
            r = route(prompt, complexity=(_meta.get("nlp") or {}).get("complexity"))
            if body.get("stream"):
                _record_use(ip, device, bool(body.get("_urai_authed")))
                return self._stream(None, body.get("model", "urai"), _meta,
                                    backend=r["backend"], msgs=msgs,
                                    max_tokens=max_tokens, temperature=temperature)
            try:
                res = _complete(r["backend"], msgs, max_tokens, temperature)
            except Exception as e:
                return self._send({"error": str(e)[:300]}, 502)
            _record_use(ip, device, bool(body.get("_urai_authed")))
            return self._send({"text": res["content"], "backend": res["backend"],
                               "usage": {"total_tokens": 0, "cost": 0},
                               "urai": _with_cache(_meta, res)})

        if p == "/v1/completions":
            prompt = body.get("prompt", "")
            msgs, _meta = _apply_vibe([{"role": "user", "content": prompt}])
            max_tokens = body.get("max_tokens", 256)
            temperature = body.get("temperature", 0.2)
            r = route(prompt, complexity=(_meta.get("nlp") or {}).get("complexity"))
            model = body.get("model", "urai")
            if body.get("stream"):
                _record_use(ip, device, bool(body.get("_urai_authed")))
                return self._stream(None, model, _meta, backend=r["backend"],
                                    msgs=msgs, max_tokens=max_tokens,
                                    temperature=temperature)
            try:
                res = _complete(r["backend"], msgs, max_tokens, temperature)
            except Exception as e:
                return self._send({"error": str(e)[:300]}, 502)
            model = body.get("model", __import__("jev.brand", fromlist=["brand_id"]).brand_id(res.get("model", "")))
            _meta = _with_cache(_meta, res)
            _record_use(ip, device, bool(body.get("_urai_authed")))
            return self._send({
                "id": "cmpl-urai", "object": "text_completion",
                "created": int(time.time()), "model": model,
                "choices": [{"index": 0, "text": res["content"],
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                          "total_tokens": 0, "cost": 0},
                "urai": _meta})

        if p == "/agent":
            from . import sessions as _sess
            sid = body.get("session_id", "")
            hist = _sess.history(sid) if sid else []
            result = run_agent(body.get("task", ""),
                               body.get("files", {}),
                               body.get("budget_tokens", 2048),
                               body.get("consistency", 1),
                               body.get("plan", False),
                               history=hist,
                               tier=body.get("tier", "urai"))
            _record_use(ip, device, bool(body.get("_urai_authed")))
            _log("agent", ip, device, str(body.get("task", ""))[:160])
            if body.get("remember", True):
                sid = _sess.append(sid, "user", str(body.get("task", ""))[:8000])
                _sess.append(sid, "assistant", str(result.get("answer", ""))[:8000])
                result["session_id"] = sid
            result["usage"] = {"total_tokens": 0, "cost": 0}
            return self._send(result)

        if p == "/agent/sessions":
            from . import sessions as _sess
            action = body.get("action", "history")
            sid = body.get("session_id", "")
            if action == "history":
                return self._send({"ok": True, "session_id": sid,
                                   "history": _sess.history(sid)})
            if action == "clear":
                return self._send(_sess.clear(sid))
            if action == "summarize":
                hist = _sess.history(sid, limit=60)
                if not hist:
                    return self._send({"ok": False, "error": "empty session"})
                comp = run_agent(
                    "Condense this conversation into 5-8 durable bullets "
                    "(decisions, facts, open loops). Reply bullets only.",
                    {}, 1024, 1, history=hist)
                from . import memory as _mem
                rec = _mem.remember(comp.get("answer", "")[:1500], "fact")
                return self._send({"ok": True, "summary": comp.get("answer", ""),
                                   "memory": rec})
            if action == "list":
                return self._send({"ok": True,
                                   "sessions": _sess.list_sessions()})
            return self._send({"error": "unknown action"}, 400)

        if p == "/agent/jobs":
            from . import sched as _sched
            action = body.get("action", "list")
            if action == "list":
                return self._send({"ok": True, "jobs": _sched.list_jobs()})
            if action == "add":
                return self._send({"ok": True,
                                   "job": _sched.add_job(body.get("task", ""),
                                                         body.get("every_s", 3600))})
            if action == "toggle":
                return self._send(_sched.set_enabled(body.get("id", ""),
                                                     body.get("enabled", True)))
            if action == "delete":
                return self._send(_sched.delete_job(body.get("id", "")))
            if action == "run":
                jobs = [j for j in _sched.list_jobs() if j["id"] == body.get("id", "")]
                if not jobs:
                    return self._send({"error": "unknown job"}, 404)
                return self._send({"ok": True, "run": _sched.run_job(jobs[0])})
            if action == "runs":
                return self._send({"ok": True,
                                   "runs": _sched.job_runs(body.get("id", ""))})
            return self._send({"error": "unknown action"}, 400)

        if p == "/agent/memory":
            from . import memory as _mem
            action = body.get("action", "recall")
            if action == "remember":
                return self._send(_mem.remember(body.get("text", ""),
                                                body.get("kind", "fact")))
            if action == "recall":
                return self._send({"ok": True,
                                   "memories": _mem.recall(body.get("query", ""),
                                                           int(body.get("top", 5)))})
            if action == "forget":
                return self._send(_mem.forget(body.get("id", "")))
            if action == "list":
                return self._send({"ok": True, "memories": _mem.list_all()})
            return self._send({"error": "unknown action"}, 400)

        if p == "/agent/routing":
            from .router import routing_scores as _rs, TIERS as _tiers
            from .pool import load as _pool_load, save as _pool_save
            action = body.get("action", "scores")
            if action == "pool":
                return self._send({"ok": True, "pool": _pool_load()})
            if action == "pool_set":
                return self._send({"ok": True, "pool": _pool_save(
                    body.get("allow", []), body.get("deny", []))})
            return self._send({"ok": True, "tiers": sorted(_tiers),
                               "scores": _rs()})

        if p == "/agent/focus":
            from . import focus as _focus
            action = body.get("action", "current")
            if action == "set":
                return self._send(_focus.set_focus(body.get("label", ""),
                                                  body.get("detail", "")))
            if action == "current":
                return self._send({"ok": True, "focus": _focus.current()})
            if action == "clear":
                return self._send(_focus.clear())
            return self._send({"error": "unknown action"}, 400)

        if p == "/agent/apply":
            if not is_master:
                return self._send({"error": "forbidden - master key required"}, 403)
            from .agent import run_tool_call as _rtc
            results = []
            for spec in body.get("proposals", []) or []:
                if not isinstance(spec, dict) or "tool" not in spec:
                    results.append({"ok": False, "error": "bad proposal"})
                    continue
                if spec.get("tool") not in ("write_file", "edit_file"):
                    results.append({"ok": False,
                                    "error": "only write_file/edit_file apply"})
                    continue
                try:
                    results.append(_rtc(spec))
                except Exception as e:
                    results.append({"ok": False, "error": str(e)[:200]})
            _log("apply", ip, device, f"{len(results)} proposals",
                 {"master": True})
            return self._send({"ok": all(r.get("ok") for r in results),
                               "results": results})

        if p == "/agent/swarm":
            from .swarm import run_swarm
            try:
                tasks = body.get("tasks", [])
                if body.get("mode", "parallel") == "conductor":
                    from .conductor import run_conductor
                    result = run_conductor(" ".join(
                        t if isinstance(t, str) else t.get("task", "") for t in tasks),
                        body.get("files", {}), body.get("budget_tokens", 2048),
                        body.get("max_workers", 3))
                else:
                    result = run_swarm(tasks, body.get("max_workers", 3))
            except Exception as e:
                return self._send({"error": str(e)[:300]}, 502)
            _record_use(ip, device, bool(body.get("_urai_authed")))
            _log("swarm", ip, device, f"{len(tasks)} tasks",
                 {"master": bool(body.get("_urai_authed"))})
            result["usage"] = {"total_tokens": 0, "cost": 0}
            return self._send(result)

        if p == "/browser/run":
            from . import browser as _b
            res = _b.run_steps(body.get("steps", []), goal=body.get("goal", ""))
            _record_use(ip, device, bool(body.get("_urai_authed")))
            _log("browser", ip, device, str(body.get("goal", ""))[:160],
                 {"master": bool(body.get("_urai_authed")),
                  "needs_approval": bool(res.get("needs_approval"))})
            code = 200 if res.get("ok") or res.get("needs_approval") else 502
            return self._send(res, code)

        if p == "/browser/approve":
            from . import browser as _b
            res = _b.approve(body.get("run_id", ""), dict(body.get("secrets", {})))
            _log("browser_approve", ip, device, f"run={body.get('run_id','')[:20]}",
                 {"ok": bool(res.get("ok"))})
            return self._send(res, 200 if res.get("ok") else 400)

        if p == "/tools/reload":
            if not is_master:
                return self._send({"error": "forbidden - master key required"}, 403)
            import importlib as _il
            _il.reload(tool_engine)
            return self._send(tool_engine.reload_policy())

        if p == "/tools":
            fn = tool_engine.TOOLS.get(body.get("tool", ""))
            if not fn:
                return self._send({"error": "unknown tool"}, 400)
            args = body.get("args", [])
            try:
                out = fn(*args) if isinstance(args, list) else fn(**args)
            except Exception as e:
                out = {"ok": False, "error": str(e)}
            _record_use(ip, device, bool(body.get("_urai_authed")))
            return self._send(out)

        if p == "/evaluate":
            task = body.get("task", "")
            expected = body.get("expected_contains", [])
            result = run_agent(task)
            ans = result.get("answer", "")
            hits = [e for e in expected if e in ans]
            score = (len(hits) / len(expected)) if expected else None
            _record_use(ip, device, bool(body.get("_urai_authed")))
            return self._send({"score": score, "hits": hits,
                               "expected": expected, **result})

        return self._send({"error": "not found"}, 404)

    def _sse_chunk(self, text, model, rid, meta, finish=None):
        piece = json.dumps({
            "id": "chatcmpl-urai", "object": "chat.completion.chunk",
            "created": int(time.time()), "model": model,
            "request_id": rid, "urai": meta or {},
            "choices": [{"index": 0,
                         "delta": ({"content": text} if text else {}),
                         "finish_reason": finish}]})
        self.wfile.write(f"data: {piece}\n\n".encode())
        self.wfile.flush()

    def _stream(self, content=None, model="urai", meta=None, backend=None,
                msgs=None, max_tokens=256, temperature=0.2):
        """SSE stream. Real token passthrough when the backend can stream and
        URAI_STREAM is on; otherwise chunk a (possibly pre-generated) answer."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Request-Id", self._reqid())
        self._cors()
        self._sec_headers()
        self.end_headers()
        rid = self._reqid()
        streamed = False
        stream_fn = getattr(backend, "stream", None) if backend is not None else None
        if (_stream_enabled() and msgs is not None and callable(stream_fn)):
            try:
                for piece in stream_fn(msgs, max_tokens=max_tokens,
                                       temperature=temperature):
                    if piece:
                        streamed = True
                        self._sse_chunk(piece, model, rid, meta)
            except Exception:
                # partial output already sent; only fall back if nothing went out
                pass
        if not streamed:
            if not content and backend is not None and msgs is not None:
                try:
                    content = _complete(backend, msgs, max_tokens, temperature)["content"]
                except Exception:
                    content = ""
            for tok in re.findall(r"\s*\S+|\s+", content or "") or ([content] if content else []):
                self._sse_chunk(tok, model, rid, meta)
        self._sse_chunk("", model, rid, meta, finish="stop")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


    def _status_page(self):
        import time as _t
        from .integrations import report as _rep
        try:
            r = _rep()
        except Exception as e:
            r = {"ok": False, "items": []}
        rows = "".join(
            f"<tr><td>{i['name']}</td><td>{i['kind']}</td><td>{i['status']}</td></tr>"
            for i in r.get("items", []))
        html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Urai — live status</title>
<meta name="theme-color" content="#0060fc">
<link rel="icon" type="image/png" sizes="32x32" href="/frontend/brand/favicon-32.png">
<link rel="apple-touch-icon" sizes="180x180" href="/frontend/brand/apple-touch-icon.png">
<style>body{{margin:0;background:#171717;color:#ececec;font-family:system-ui,sans-serif;line-height:1.5}}
.wrap{{max-width:760px;margin:0 auto;padding:clamp(16px,4vw,24px)}}
.brand{{height:30px;width:auto;display:block;margin-bottom:10px}}
h1{{font-size:clamp(1.3rem,5vw,1.7rem)}}h1 span{{color:#4d94ff}}
.live{{display:inline-block;width:9px;height:9px;border-radius:50%;background:#00d890;
box-shadow:0 0 8px #00d890;animation:blink 2s infinite;vertical-align:middle;margin-right:7px}}
@keyframes blink{{50%{{opacity:.4}}}}
.tablewrap{{overflow-x:auto;-webkit-overflow-scrolling:touch;margin-top:14px;border-radius:10px}}
table{{width:100%;border-collapse:collapse;min-width:420px}}
td{{border:1px solid #3a3a3a;padding:8px 10px;font-size:.85rem}}
.ok{{color:#4d94ff}}a{{color:#4d94ff}}
@media(prefers-reduced-motion:reduce){{.live{{animation:none}}}}
@supports(padding:max(0px)){{.wrap{{padding-left:max(clamp(16px,4vw,24px),env(safe-area-inset-left));
padding-right:max(clamp(16px,4vw,24px),env(safe-area-inset-right))}}}}</style>
</head><body><div class="wrap">
<img class="brand" src="/frontend/brand/urai-logo-trans.png" alt="Urai">
<h1><span class="live"></span>Urai is <span class="ok">live</span></h1>
<p>Urai, developed by Tynio LTD · {_t.strftime('%Y-%m-%d %H:%M UTC', _t.gmtime())} ·
<a href="/welcome">landing</a> · <a href="/app">open app</a> ·
<a href="/v1/docs">docs</a></p>
<div class="tablewrap"><table>{rows}</table></div></div></body></html>"""
        return self._send_raw(html.encode(), "text/html")

    def _trace_page(self):
        html = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Urai - trace</title>
<meta name="theme-color" content="#0060fc">
<link rel="icon" type="image/png" sizes="32x32" href="/frontend/brand/favicon-32.png">
<style>body{margin:0;background:#171717;color:#ececec;font-family:system-ui,sans-serif}
.wrap{max-width:960px;margin:0 auto;padding:clamp(14px,4vw,24px)}
h1{font-size:1.3rem}h1 span{color:#4d94ff}
input,button{background:#1f1f1f;color:#ececec;border:1px solid #3a3a3a;border-radius:8px;padding:7px 9px}
.bars{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:12px 0}
.card{background:#1f1f1f;border:1px solid #333;border-radius:10px;padding:10px}
.card b{display:block;font-size:.72rem;color:#8a8a8a;text-transform:uppercase}
.card span{font-size:1.3rem;color:#4d94ff}
table{width:100%;border-collapse:collapse;margin-top:10px}
td,th{border:1px solid #3a3a3a;padding:6px 8px;font-size:.8rem;text-align:left}
.muted{color:#8a8a8a}</style></head><body><div class="wrap">
<h1><span>Urai</span> trace &amp; metrics</h1>
<p class="muted">master key required · <a href="/status" style="color:#4d94ff">status</a></p>
<p><input id="k" type="password" placeholder="master key" autocomplete="off">
<button onclick="go()">load</button></p>
<div class="bars" id="bars"></div>
<table><thead><tr><th>time</th><th>kind</th><th>ip</th><th>device</th><th>preview</th></tr></thead>
<tbody id="rows"></tbody></table>
<script>
const K=()=>document.getElementById('k').value||localStorage.getItem('uraik')||'';
document.getElementById('k').addEventListener('change',e=>localStorage.setItem('uraik',e.target.value));
async function go(){
 const key=K(); if(key)localStorage.setItem('uraik',key);
 const r=await fetch('/admin/trace?key='+encodeURIComponent(key));
 if(!r.ok){document.getElementById('bars').innerHTML='<div class="card"><b>error</b><span>403</span></div>';return;}
 const d=await r.json(); const s=d.stats||{};
 const c=s.cache||{}; const t=s.tokens||{}; const q=s.requests||{};
 const cards=[['uptime',(s.uptime_seconds||0)+'s'],['requests',q.total_requests||0],
  ['cache size',c.size||0],['cache hits',c.hits||0],['cache miss',c.misses||0],
  ['free used',t.free_used_total||0],['blocked',t.blocked_identities||0],
  ['llama',s.local_llama?'up':'down']];
 document.getElementById('bars').innerHTML=cards.map(x=>`<div class="card"><b>${x[0]}</b><span>${x[1]}</span></div>`).join('');
 document.getElementById('rows').innerHTML=(d.events||[]).slice().reverse().map(e=>{
  const tm=e.t?new Date(e.t*1000).toLocaleTimeString():'';
  return `<tr><td>${tm}</td><td>${e.kind||''}</td><td>${e.ip||''}</td><td>${(e.device||'').slice(0,10)}</td><td>${(e.preview||'').replace(/[<>]/g,'')}</td></tr>`;}).join('');
}
setInterval(go,5000); if(localStorage.getItem('uraik'))go();
</script></div></body></html>"""
        return self._send_raw(html.encode(), "text/html")

    def _send_raw(self, data: bytes, ctype: str):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Request-Id", self._reqid())
        self._cors()
        self.end_headers()
        self.wfile.write(data)


def serve(port=PORT, host="127.0.0.1"):
    try:
        from .sched import start as _sched_start
        _sched_start()
    except Exception:
        pass
    srv = ThreadingHTTPServer((host, port), Handler)
    from . import VERSION
    print(f"Urai {VERSION} API+web on http://{host}:{port}  "
          f"(/health /v1/* /app)  auth={'on' if API_KEY else 'off (localhost only)'}")
    srv.serve_forever()


if __name__ == "__main__":
    serve()
