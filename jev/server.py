#!/usr/bin/env python3
"""Urai API — OpenAI-compatible where practical + hosted webapp (mission §22).

  GET  /health                  -> {status, backends}
  GET  / or /app/<file>         -> hosted web playground (no auth)
  GET  /models, /v1/models      -> OpenAI-style model list
  POST /chat                    -> {messages, max_tokens?, temperature?, stream?}
  POST /v1/chat/completions     -> OpenAI chat (roles, vision image_url, stream)
  POST /v1/completions          -> OpenAI legacy completions {prompt, ...}
  POST /generate                -> {prompt, ...} convenience
  POST /agent                   -> {task, files?} full plan/tool/verify loop
  POST /tools                   -> {tool, args} direct tool call (jailed)
  POST /evaluate                -> {task, expected_contains?} scored check
  POST /see                     -> {image, question?} vision answer
  POST /imagine, /v1/images/generations -> {prompt, ...} PNG (url or b64_json)

Hosting: bind --host (default 127.0.0.1). Set URAI_API_KEY to require
`Authorization: Bearer <key>` on every API route (/health + web UI stay
open; the UI sends the key from its key field). CORS open (configurable
via URAI_CORS_ORIGIN, default *) so browser apps can call it.

Stdlib only. SSE streaming supported with "stream": true.
"""

import base64
import json
import mimetypes
import os
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .agent import run_agent
from .backends import LlamaServerBackend, MockBackend
from .router import route
from . import tools as tool_engine

PORT = 8777
STATIC_DIR = Path(__file__).resolve().parent / "static"
API_KEY = os.environ.get("URAI_API_KEY", "")
CORS_ORIGIN = os.environ.get("URAI_CORS_ORIGIN", "*")

# API routes (everything else: /health open, / + /app/* static UI open)
_guarded = ("/v1/", "/chat", "/generate", "/agent", "/tools",
            "/evaluate", "/see", "/imagine")


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
    """Normalize to [{role, content}] preserving roles (legacy strings ok)."""
    msgs = []
    for m in raw or []:
        if isinstance(m, str):
            msgs.append({"role": "user", "content": m})
        elif isinstance(m, dict):
            msgs.append({"role": m.get("role", "user"),
                         "content": m.get("content", "")})
    return msgs


def _text_of(msgs) -> str:
    """Plain-text view of messages for routing (ignores image parts)."""
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
    """Return (image_ref, question). image_ref is a data: URL or file path."""
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


class Handler(BaseHTTPRequestHandler):
    server_version = "JEV/0.1"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, Authorization")

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
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
        return got.startswith("Bearer ") and got[7:] == API_KEY

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _read_json(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def log_message(self, *a):
        pass

    def _static(self):
        rel = "app.html" if self.path in ("/", "/app", "/app/") else \
            self.path[len("/app/"):] if self.path.startswith("/app/") else None
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

    def do_GET(self):
        if self.path == "/health":
            local = LlamaServerBackend()
            self._send({"status": "ok", "local_llama": local.healthy(),
                        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        elif self.path in ("/models", "/v1/models"):
            self._send({"object": "list",
                        "data": [{"object": "model", **m} for m in _models()]})
        elif self.path in ("/", "/app", "/app/") or \
                self.path.startswith("/app/"):
            return self._static()
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        if not self._auth_ok():
            return self._deny()
        try:
            body = self._read_json()
        except Exception:
            return self._send({"error": "invalid json"}, 400)

        if self.path == "/chat":
            msgs = _as_messages(body.get("messages", []))
            try:
                r = route(_text_of(msgs))
                res = r["backend"].complete(
                    msgs, body.get("max_tokens", 256),
                    body.get("temperature", 0.2))
                content = res["content"]
            except Exception as e:
                return self._send({"error": str(e)[:300]}, 502)
            if body.get("stream"):
                return self._stream(content, res.get("model", "jev-local-student"))
            return self._send({
                "id": "chatcmpl-urai", "object": "chat.completion",
                "model": res.get("model", "jev-local-student"),
                "choices": [{"index": 0, "message": {"role": "assistant",
                                                     "content": content},
                             "finish_reason": "stop"}],
                "jev": {"level": r["level"], "backend": r["backend"].name}})

        if self.path == "/v1/chat/completions":
            # OpenAI-compatible: roles preserved, vision image_url parts
            # passed straight through to the local llama-server when it is
            # up, otherwise answered by the routed backend (text only).
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
            if body.get("stream"):
                return self._stream(content, model)
            return self._send({
                "id": "chatcmpl-urai", "object": "chat.completion",
                "created": int(time.time()), "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant",
                                                     "content": content},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                          "total_tokens": 0}})

        if self.path in ("/imagine", "/v1/images/generations"):
            from . import imagine as _imagine
            res = _imagine.generate(
                body.get("prompt", ""),
                body.get("out") or body.get("file"),
                body.get("steps"), body.get("width"), body.get("height"),
                body.get("seed", 7))
            if not res["ok"]:
                return self._send({"error": res["error"]}, 502)
            if body.get("response_format") == "b64_json":
                raw = Path(res["path"]).read_bytes()
                data = [{"b64_json": base64.b64encode(raw).decode()}]
            else:
                data = [{"url": "file://" + res["path"]}]
            return self._send({"created": int(time.time()), "data": data,
                               **{k: v for k, v in res.items()
                                   if k not in ("path",)}})

        if self.path == "/see":
            from . import vision as _vision
            res = _vision.see(body.get("image", ""),
                              body.get("question", "Describe this image."),
                              body.get("max_tokens", 512),
                              body.get("temperature", 0.2))
            if not res["ok"]:
                return self._send({"error": res["error"]}, 502)
            return self._send(res)

        if self.path == "/v1/embeddings":
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
            return self._send({
                "object": "list",
                "data": [{"object": "embedding", "index": i,
                          "embedding": v} for i, v in enumerate(vecs)],
                "model": body.get("model", "local-embed"),
                "usage": {"prompt_tokens": 0, "total_tokens": 0}})

        if self.path == "/generate":
            msgs = [{"role": "user", "content": body.get("prompt", "")}]
            r = route(body.get("prompt", ""))
            try:
                res = r["backend"].complete(msgs, body.get("max_tokens", 256))
            except Exception as e:
                return self._send({"error": str(e)[:300]}, 502)
            return self._send({"text": res["content"], "backend": res["backend"]})

        if self.path == "/v1/completions":
            # OpenAI legacy completions over the routed backend.
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
            if body.get("stream"):
                return self._stream(res["content"], model)
            return self._send({
                "id": "cmpl-urai", "object": "text_completion",
                "created": int(time.time()), "model": model,
                "choices": [{"index": 0, "text": res["content"],
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                          "total_tokens": 0}})

        if self.path == "/agent":
            result = run_agent(body.get("task", ""),
                               body.get("files", {}),
                               body.get("budget_tokens", 2048))
            return self._send(result)

        if self.path == "/tools":
            fn = tool_engine.TOOLS.get(body.get("tool", ""))
            if not fn:
                return self._send({"error": "unknown tool"}, 400)
            args = body.get("args", [])
            try:
                out = fn(*args) if isinstance(args, list) else fn(**args)
            except Exception as e:
                out = {"ok": False, "error": str(e)}
            return self._send(out)

        if self.path == "/evaluate":
            task = body.get("task", "")
            expected = body.get("expected_contains", [])
            result = run_agent(task)
            ans = result.get("answer", "")
            hits = [e for e in expected if e in ans]
            score = (len(hits) / len(expected)) if expected else None
            return self._send({"score": score, "hits": hits,
                               "expected": expected, **result})

        return self._send({"error": "not found"}, 404)

    def _stream(self, content, model):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        # chunked SSE emission (single full text, chunked delivery)
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
