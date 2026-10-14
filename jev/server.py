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


def _record_use(ip, device, is_master):
    ident = _identity(ip, device)
    with _lock:
        if is_master:
            return
        if _is_approved_locked(ident, ip, device):
            return
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
    ms = [{"id": "jev-local-student", "owned_by": "ownai",
           "available": local.healthy()}]
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
        try:
            return json.loads(raw)
        except Exception:
            return {}

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
        if p in ("/", "/app", "/app/") or p.startswith("/app/") or p == "/superadmin":
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
                 "/agent", "/tools", "/evaluate", "/see", "/imagine",
                 "/v1/images/generations", "/v1/embeddings")
        needs_gate = (p == "/chat" or p.startswith("/v1/") or p in gated[2:])
        if needs_gate and p not in ("/v1/models",):
            allowed, reason, remaining = _check_access(ip, device, is_master)
            if not allowed:
                with _lock:
                    blk = float(_state["blocked"].get(ident, 0))
                _log("blocked", ip, device, _text_of(_as_messages((body or {}).get("messages", [])))[:120] if isinstance(body, dict) else (body or {}).get("task", "")[:120] if isinstance(body, dict) else "")
                return self._send(_expired_payload(blk), 403)
            # record use AFTER success? record now for simplicity (prevents abuse on errors too)
            # we record after successful generation below; store flag
            body["_urai_authed"] = bool(is_master)
            body["_urai_reason"] = reason
            body["_urai_remaining"] = remaining

        # ---- handlers ----
        if p == "/chat":
            msgs = _as_messages(body.get("messages", []))
            # identity guard: always Urai / Tynio LTD
            try:
                r = route(_text_of(msgs))
                res = r["backend"].complete(
                    msgs, body.get("max_tokens", 256),
                    body.get("temperature", 0.2))
                content = res["content"]
            except Exception as e:
                return self._send({"error": str(e)[:300]}, 502)
            _record_use(ip, device, bool(body.get("_urai_authed")))
            _log("chat", ip, device, _text_of(msgs)[:160] + " -> " + content[:120],
                 {"master": bool(body.get("_urai_authed"))})
            if body.get("stream"):
                return self._stream(content, res.get("model", "jev-local-student"))
            usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0}
            return self._send({
                "id": "chatcmpl-urai", "object": "chat.completion",
                "model": res.get("model", "jev-local-student"),
                "choices": [{"index": 0, "message": {"role": "assistant",
                                                     "content": content},
                             "finish_reason": "stop"}],
                "usage": usage,
                "urai": {"level": r["level"], "backend": r["backend"].name,
                         "tokens_remaining": body.get("_urai_remaining", 0),
                         "auth": body.get("_urai_reason", "free")},
                "jev": {"level": r["level"], "backend": r["backend"].name}})

        if p == "/v1/chat/completions":
            msgs = _as_messages(body.get("messages", []))
            if _has_image(msgs):
                from . import vision as _vision
                img, question = _split_image(msgs)
                if img is None:
                    return self._send({"error": "no image found in messages"}, 400)
                res = _vision.see(img, question or "Describe this image.",
                                  body.get("max_tokens", 512),
                                  body.get("temperature", 0.2))
                if not res["ok"]:
                    return self._send({"error": res["error"]}, 502)
                content = res["answer"]
            else:
                try:
                    r = route(_text_of(msgs))
                    res = r["backend"].complete(
                        msgs, body.get("max_tokens", 256),
                        body.get("temperature", 0.2))
                    content = res["content"]
                except Exception as e:
                    return self._send({"error": str(e)[:300]}, 502)
            model = body.get("model", res.get("model", "jev-local-student"))
            _record_use(ip, device, bool(body.get("_urai_authed")))
            _log("chat", ip, device, _text_of(msgs)[:160] + " -> " + str(content)[:120],
                 {"master": bool(body.get("_urai_authed")), "model": model})
            if body.get("stream"):
                return self._stream(content, model)
            return self._send({
                "id": "chatcmpl-urai", "object": "chat.completion",
                "created": int(time.time()), "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant",
                                                     "content": content},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                          "total_tokens": 0, "cost": 0},
                "urai": {"tokens_remaining": body.get("_urai_remaining", 0),
                         "auth": body.get("_urai_reason", "free")}})

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
            model = body.get("model", res.get("model", "jev-local-student"))
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

        if p == "/agent":
            result = run_agent(body.get("task", ""),
                               body.get("files", {}),
                               body.get("budget_tokens", 2048))
            _record_use(ip, device, bool(body.get("_urai_authed")))
            _log("agent", ip, device, str(body.get("task", ""))[:160])
            result["usage"] = {"total_tokens": 0, "cost": 0}
            return self._send(result)

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
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for i in range(0, len(content), 64):
            piece = json.dumps({
                "id": "chatcmpl-urai", "object": "chat.completion.chunk",
                "model": model,
                "choices": [{"index": 0,
                             "delta": {"content": content[i:i + 64]},
                             "finish_reason": None}]})
            self.wfile.write(f"data: {piece}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")


def serve(port=PORT, host="127.0.0.1"):
    srv = ThreadingHTTPServer((host, port), Handler)
    from . import VERSION
    print(f"Urai {VERSION} API+web on http://{host}:{port}  "
          f"(/health /v1/* /app)  auth={'on' if API_KEY else 'off (localhost only)'}")
    srv.serve_forever()


if __name__ == "__main__":
    serve()
