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
from .backends import LlamaServerBackend, MockBackend, CloudAPIBackend
from .router import route

# ── Response cache (LRU, in-process) ──────────────────────────────────────
import collections, hashlib as _hs
_CACHE_MAX = int(os.environ.get('URAI_CACHE_MAX', '256'))
_CACHE_TTL = int(os.environ.get('URAI_CACHE_TTL', '60'))  # seconds
_cache: collections.OrderedDict = collections.OrderedDict()  # key -> (value, expires)
_cache_lock = threading.RLock()

def _cache_get(key):
    with _cache_lock:
        entry = _cache.get(key)
        if entry and time.time() < entry[1]:
            _cache.move_to_end(key)
            return entry[0]
        if entry:
            del _cache[key]
        return None

def _cache_put(key, value):
    with _cache_lock:
        _cache[key] = (value, time.time() + _CACHE_TTL)
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)

def _cache_key(msgs, model, max_tokens, temp):
    raw = json.dumps([msgs, model, max_tokens, round(temp, 2)], sort_keys=True)
    return _hs.md5(raw.encode()).hexdigest()

# ── Metrics ────────────────────────────────────────────────────────────────
_metrics = {'requests': 0, 'cache_hits': 0, 'errors': 0,
            'stream_requests': 0, 'started_at': int(time.time())}
_metrics_lock = threading.Lock()

def _m_inc(k, n=1):
    with _metrics_lock:
        _metrics[k] = _metrics.get(k, 0) + n

from . import tools as tool_engine
from . import voice as _voice_module

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


def _models():
    local = LlamaServerBackend()
    up = local.healthy()
    from .brand import brand_list
    ms = brand_list(up)
    ms.append({"id": "jev-local-student", "owned_by": "Urai", "available": up,
               "legacy": True})
    try:
        from . import models_registry as _reg
        reg = _reg.load()
        for mid, m in reg.get("models", {}).items():
            if m.get("kind") != "chat" or mid == "laya":
                continue
            mp = ROOT / m["path"]
            ms.append({"id": mid, "owned_by": "urai-local",
                       "available": bool(up and mp.exists()),
                       "active": mid == reg.get("active"),
                       "params": m.get("params", ""), "role": m.get("role", "")})
    except Exception:
        pass
    ms.append({"id": "jev-teacher-fallback", "owned_by": "external",
               "available": False})
    return ms


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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, Authorization, X-Device-Id")

    def _sec_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
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
        self._cors()
        self.end_headers()
        self.wfile.write(data)
        print(f"{self.client_address[0]} GET {self.path} -> 200", flush=True)

    # ---------------- GET ----------------
    def do_GET(self):
        p = self._path()
        q = self._query()
        if p == "/v1/cloud/usage":
            days = int(urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query).get("days", ["7"])[0])
            try:
                from .cloud_budget import usage_report as _ur
                return self._send(_ur(days=min(days, 90)))
            except Exception as e:
                return self._send({"error": str(e)[:200]}, 500)

        if p == "/metrics":
            from .router import routing_scores as _rs
            local = LlamaServerBackend()
            cloud = CloudAPIBackend()
            with _metrics_lock:
                m = dict(_metrics)
            m['uptime_s'] = int(time.time()) - m.pop('started_at', int(time.time()))
            m['cache_size'] = len(_cache)
            m['local_healthy'] = local.healthy()
            m['cloud_backend'] = getattr(cloud, '_model_id', None)
            m['cloud_healthy'] = cloud.healthy() if cloud.available else False
            m['routing_scores'] = _rs()
            try:
                from .sched import watchdog_status as _wd
                m['watchdog'] = _wd()
            except Exception:
                pass
            try:
                from .cloud_budget import usage_report as _ur
                m['cloud_budget'] = _ur(days=1)
            except Exception:
                pass
            return self._send(m)

        if p == "/health":
            local = LlamaServerBackend()
            try:
                voice_status = _voice_module.healthy()
            except Exception:
                voice_status = {}
            try:
                from .sched import watchdog_status as _wd
                wd = _wd()
            except Exception:
                wd = {}
            try:
                from .cloud_budget import day_total_usd as _dtu
                cloud_spend = _dtu()
            except Exception:
                cloud_spend = None
            self._send({"status": "ok", "local_llama": local.healthy(),
                        "voice": voice_status,
                        "watchdog": wd,
                        "cloud_spend_today_usd": cloud_spend,
                        "identity": "Urai, developed by Tynio LTD",
                        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            return
        if p in ("/v1/tools", "/v1/tools/schemas"):
            from .tools import TOOL_SCHEMAS
            return self._send({"object": "list",
                               "data": TOOL_SCHEMAS,
                               "count": len(TOOL_SCHEMAS)})

        if p in ("/models", "/v1/models"):
            self._send({"object": "list",
                        "data": [{"object": "model", **m} for m in _models()]})
            return
        if p == "/status":
            return self._status_page()
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
            # identity guard: always Urai / Tynio LTD
            try:
                from .brand import tier_of_brand as _tier_of
                r = route(_text_of(msgs), tier=_tier_of(body.get("model", "urai")))
                res = r["backend"].complete(
                    msgs, body.get("max_tokens", 256),
                    body.get("temperature", 0.2))
                content = res["content"]
            except RuntimeError as e:
                return self._send({"error": str(e)[:300], "code": "urai_starting", "retry_after": 5}, 503)
            except Exception as e:
                return self._send({"error": str(e)[:300]}, 502)
            _record_use(ip, device, bool(body.get("_urai_authed")))
            _log("chat", ip, device, _text_of(msgs)[:160] + " -> " + content[:120],
                 {"master": bool(body.get("_urai_authed"))})
            if body.get("stream"):
                return self._stream(content, __import__("jev.brand", fromlist=["brand_id"]).brand_id(res.get("model", "")))
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
                         "auth": body.get("_urai_reason", "free")},
                "jev": {"level": r["level"], "backend": r["backend"].name}})

        if p == "/v1/chat/completions":
            _m_inc('requests')
            msgs = _as_messages(body.get("messages", []))
            want_stream = bool(body.get("stream"))
            max_tokens = body.get("max_tokens", 256)
            temperature = float(body.get("temperature", 0.2))
            req_model = body.get("model", "urai")

            if _has_image(msgs):
                from . import vision as _vision
                img, question = _split_image(msgs)
                if img is None:
                    return self._send({"error": "no image found in messages"}, 400)
                res = _vision.see(img, question or "Describe this image.",
                                  max_tokens, temperature)
                if not res["ok"]:
                    _m_inc('errors')
                    return self._send({"error": res["error"]}, 502)
                content = res["answer"]
                backend_used = "vision"
                usage_out = {}
            else:
                try:
                    from .brand import tier_of_brand as _tier_of
                    tier = _tier_of(req_model)

                    # Check cache (skip for streaming — cache only non-stream)
                    ck = None
                    if not want_stream:
                        ck = _cache_key(msgs, req_model, max_tokens, temperature)
                        cached = _cache_get(ck)
                        if cached is not None:
                            _m_inc('cache_hits')
                            _record_use(ip, device, bool(body.get("_urai_authed")))
                            cached['urai']['cached'] = True
                            return self._send(cached)

                    # response_format json_object/json_schema
                    resp_fmt = body.get("response_format") or {}
                    if isinstance(resp_fmt, dict) and \
                            resp_fmt.get("type") in ("json_object", "json_schema"):
                        from .tools import force_json as _fj
                        schema = (resp_fmt.get("json_schema") or {}).get("schema")
                        fj = _fj(msgs, schema=schema, max_tokens=max_tokens)
                        if fj.get("ok"):
                            _record_use(ip, device, bool(body.get("_urai_authed")))
                            return self._send({
                                "id": "chatcmpl-urai",
                                "object": "chat.completion",
                                "created": int(time.time()),
                                "model": body.get("model", "urai"),
                                "choices": [{"index": 0,
                                             "message": {"role": "assistant",
                                                         "content": json.dumps(fj["data"])},
                                             "finish_reason": "stop"}],
                                "usage": {"prompt_tokens": 0,
                                          "completion_tokens": 0,
                                          "total_tokens": 0}})
                        return self._send({"error": fj.get("error","json mode failed")}, 422)

                    r = route(_text_of(msgs), tier=tier,
                              stream=want_stream)
                    backend = r['backend']

                    if want_stream:
                        _m_inc('stream_requests')
                        _record_use(ip, device, bool(body.get("_urai_authed")))
                        model = __import__('jev.brand', fromlist=['brand_id']).brand_id(req_model)
                        _log('chat_stream', ip, device, _text_of(msgs)[:160],
                             {'master': bool(body.get('_urai_authed')), 'model': model})
                        return self._stream_backend(backend, msgs, max_tokens, temperature, model)

                    res = backend.complete(msgs, max_tokens, temperature)
                    content = res["content"]
                    backend_used = res.get('backend', 'unknown')
                    usage_out = res.get('usage') or {}
                except RuntimeError as e:
                    # llama-server temporarily down — watchdog is restarting it
                    _m_inc('errors')
                    return self._send({
                        "error": str(e)[:300],
                        "code": "urai_starting",
                        "retry_after": 5,
                    }, 503)
                except Exception as e:
                    _m_inc('errors')
                    return self._send({"error": str(e)[:300]}, 502)

            from jev.brand import brand_id as _bid
            model = _bid(req_model)
            _record_use(ip, device, bool(body.get("_urai_authed")))
            _log("chat", ip, device, _text_of(msgs)[:160] + " -> " + str(content)[:120],
                 {"master": bool(body.get("_urai_authed")), "model": model})
            resp_obj = {
                "id": "chatcmpl-urai", "object": "chat.completion",
                "created": int(time.time()), "model": model,
                "choices": [{"index": 0,
                              "message": {"role": "assistant", "content": content},
                              "finish_reason": "stop"}],
                "usage": usage_out or {"prompt_tokens": 0, "completion_tokens": 0,
                                       "total_tokens": 0, "cost": 0},
                "urai": {"tokens_remaining": body.get("_urai_remaining", 0),
                          "auth": body.get("_urai_reason", "free"),
                          "cached": False}}
            if ck:
                _cache_put(ck, dict(resp_obj))
            return self._send(resp_obj)

        if p in ("/imagine", "/v1/images/generations"):
            from . import imagine as _imagine
            res = _imagine.generate(
                body.get("prompt", ""),
                body.get("out") or body.get("file"),
                body.get("steps"), body.get("width"), body.get("height"),
                body.get("seed", 7))
            if not res["ok"]:
                return self._send({"error": res["error"]}, 502)
            _record_use(ip, device, bool(body.get("_urai_authed")))
            if body.get("response_format") == "b64_json":
                raw = Path(res["path"]).read_bytes()
                data = [{"b64_json": base64.b64encode(raw).decode()}]
            else:
                data = [{"url": "file://" + res["path"]}]
            return self._send({"created": int(time.time()), "data": data,
                               **{k: v for k, v in res.items()
                                   if k not in ("path",)}})

        if p in ("/video", "/v1/videos/generations"):
            from . import video as _video
            res = _video.generate(
                body.get("prompt", ""), body.get("out"),
                body.get("duration", 4), body.get("width", 512),
                body.get("height", 512), body.get("fps", 4),
                body.get("seed", 7), body.get("provider", "auto"),
                body.get("provider_url"), body.get("provider_key"))
            if not res.get("ok"):
                return self._send({"ok": False, "error": res.get("error"),
                                   "grade": res.get("grade", "")}, 502)
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
            except RuntimeError as e:
                return self._send({"error": str(e)[:300], "code": "urai_starting", "retry_after": 5}, 503)
            except Exception as e:
                return self._send({"error": str(e)[:300]}, 502)
            _record_use(ip, device, bool(body.get("_urai_authed")))
            return self._send({
                "object": "list",
                "data": [{"object": "embedding", "index": i,
                          "embedding": v} for i, v in enumerate(vecs)],
                "model": body.get("model", "local-embed"),
                "usage": {"prompt_tokens": 0, "total_tokens": 0, "cost": 0}})


        if p == "/v1/audio/speech":
            # POST /v1/audio/speech — OpenAI-compatible TTS
            # Body: {model, input, voice, speed, response_format}
            text = body.get("input", body.get("text", ""))
            if not text:
                return self._send({"error": "input is required"}, 400)
            voice = body.get("voice", "alloy")
            speed = float(body.get("speed", 1.0))
            fmt = body.get("response_format", "mp3")
            language = body.get("language", "en")
            try:
                audio_bytes = _voice_module.tts(text, voice=voice, speed=speed,
                                                format=fmt, language=language)
            except RuntimeError as e:
                return self._send({"error": str(e)[:300], "code": "urai_starting", "retry_after": 5}, 503)
            except Exception as e:
                return self._send({"error": str(e)[:300]}, 502)
            _record_use(ip, device, bool(body.get("_urai_authed")))
            _log("tts", ip, device, text[:120], {"voice": voice, "fmt": fmt})
            ctype = "audio/mpeg" if fmt in ("mp3", "mpeg") else "audio/wav"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(audio_bytes)))
            self._cors()
            self._sec_headers()
            self.end_headers()
            self.wfile.write(audio_bytes)
            return

        if p == "/v1/audio/transcriptions":
            # POST /v1/audio/transcriptions — OpenAI-compatible STT
            # Expects multipart/form-data with file field, or JSON with {audio_b64, language}
            ctype_hdr = self.headers.get("Content-Type", "")
            language = None
            audio_bytes = b""
            filename = "audio.wav"
            if "multipart/form-data" in ctype_hdr:
                # Parse multipart manually (avoid deps)
                import cgi, io as _io
                n = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(n)
                # Use cgi.FieldStorage for multipart parsing
                environ = {
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": ctype_hdr,
                    "CONTENT_LENGTH": str(n),
                }
                form = cgi.FieldStorage(fp=_io.BytesIO(raw), environ=environ,
                                        keep_blank_values=True)
                if "file" in form:
                    item = form["file"]
                    audio_bytes = item.file.read()
                    filename = item.filename or "audio.wav"
                if "language" in form:
                    language = form.getvalue("language")
                # model field ignored (we pick based on URAI_WHISPER_MODEL)
            else:
                # JSON body already read — expect base64 audio
                import base64 as _b64
                b64 = body.get("audio_b64", "") or body.get("file", "")
                if not b64:
                    return self._send({"error": "file or audio_b64 required"}, 400)
                try:
                    audio_bytes = _b64.b64decode(b64)
                except Exception:
                    return self._send({"error": "invalid base64 audio"}, 400)
                language = body.get("language")
                filename = body.get("filename", "audio.wav")
            if not audio_bytes:
                return self._send({"error": "empty audio"}, 400)
            try:
                result = _voice_module.transcribe(audio_bytes, language=language,
                                                  filename=filename)
            except Exception as e:
                return self._send({"error": str(e)[:300]}, 502)
            _record_use(ip, device, bool(body.get("_urai_authed")))
            _log("stt", ip, device, f"lang={language or 'auto'} backend={result.get('backend')}",
                 {"duration_s": result.get("duration_s")})
            return self._send({
                "text": result.get("text", ""),
                "language": result.get("language", language or "auto"),
                "duration": result.get("duration_s"),
                "backend": result.get("backend"),
                "task": "transcribe",
            })

        if p == "/generate":
            msgs = [{"role": "user", "content": body.get("prompt", "")}]
            r = route(body.get("prompt", ""))
            try:
                res = r["backend"].complete(msgs, body.get("max_tokens", 256))
            except Exception as e:
                return self._send({"error": str(e)[:300]}, 502)
            _record_use(ip, device, bool(body.get("_urai_authed")))
            return self._send({"text": res["content"], "backend": res["backend"],
                               "usage": {"total_tokens": 0, "cost": 0}})

        if p == "/v1/completions":
            prompt = body.get("prompt", "")
            msgs = [{"role": "user", "content": prompt}]
            r = route(prompt)
            try:
                res = r["backend"].complete(
                    msgs, body.get("max_tokens", 256),
                    body.get("temperature", 0.2))
            except Exception as e:
                return self._send({"error": str(e)[:300]}, 502)
            model = body.get("model", __import__("jev.brand", fromlist=["brand_id"]).brand_id(res.get("model", "")))
            _record_use(ip, device, bool(body.get("_urai_authed")))
            if body.get("stream"):
                return self._stream(res["content"], model)
            return self._send({
                "id": "cmpl-urai", "object": "text_completion",
                "created": int(time.time()), "model": model,
                "choices": [{"index": 0, "text": res["content"],
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                          "total_tokens": 0, "cost": 0}})

        if p == "/v1/reason":
            msgs = _as_messages(body.get("messages", []))
            if not msgs:
                return self._send({"error": "messages required"}, 400)
            try:
                from .reason import reason as _reason
                res = _reason(msgs,
                              max_tokens=body.get("max_tokens", 1024),
                              temperature=body.get("temperature", 0.6))
                _record_use(ip, device, bool(body.get("_urai_authed")))
                return self._send(res)
            except Exception as e:
                return self._send({"error": str(e)[:300]}, 503)

        if p == "/v1/research":
            query = body.get("query", body.get("prompt", ""))
            if not query:
                return self._send({"error": "query required"}, 400)
            try:
                from .tools import research as _research
                res = _research(query, depth=int(body.get("depth", 3)))
                _record_use(ip, device, bool(body.get("_urai_authed")))
                return self._send(res)
            except Exception as e:
                return self._send({"error": str(e)[:300]}, 502)

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

    def _stream(self, content, model):
        """Buffer-then-stream (legacy path for non-backend callers)."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self._cors()
        self.end_headers()
        for i in range(0, max(len(content), 1), 64):
            piece = json.dumps({
                "id": "chatcmpl-urai", "object": "chat.completion.chunk",
                "model": model,
                "choices": [{"index": 0,
                             "delta": {"content": content[i:i + 64]},
                             "finish_reason": None}]})
            self.wfile.write(f"data: {piece}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")

    def _stream_backend(self, backend, msgs, max_tokens, temperature, model):
        """True SSE streaming — yields chunks from backend.stream_complete()."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self._cors()
        self._sec_headers()
        self.end_headers()
        try:
            for chunk in backend.stream_complete(msgs, max_tokens, temperature):
                if chunk and chunk != '[DONE]':
                    self.wfile.write(f'data: {chunk}\n\n'.encode())
                    self.wfile.flush()
        except Exception as e:
            err = json.dumps({'error': str(e)[:200]})
            self.wfile.write(f'data: {err}\n\n'.encode())
        finally:
            self.wfile.write(b'data: [DONE]\n\n')
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
<style>body{{background:#171717;color:#ececec;font-family:system-ui,sans-serif;
max-width:760px;margin:0 auto;padding:24px}}h1 span{{color:#10a37f}}
table{{width:100%;border-collapse:collapse}}td{{border:1px solid #3a3a3a;
padding:6px 10px;font-size:.85rem}}.ok{{color:#10a37f}}a{{color:#10a37f}}</style>
</head><body><h1>Urai is <span class="ok">● live</span></h1>
<p>Urai, developed by Tynio LTD · {_t.strftime('%Y-%m-%d %H:%M UTC', _t.gmtime())} ·
<a href="/welcome">landing</a> · <a href="/app">open app</a> ·
<a href="/v1/docs">docs</a></p>
<table>{rows}</table></body></html>"""
        return self._send_raw(html.encode(), "text/html")

    def _send_raw(self, data: bytes, ctype: str):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
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
