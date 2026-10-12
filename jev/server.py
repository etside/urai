#!/usr/bin/env python3
"""Urai local API — OpenAI-compatible where practical (mission §22).

  GET  /health     -> {status, backends}
  GET  /models     -> OpenAI-style model list (local student + teacher fallback)
  POST /chat       -> {messages, max_tokens?, temperature?, stream?}
  POST /generate   -> {prompt, ...} (completions-style convenience)
  POST /agent      -> {task, files?} full plan/tool/verify loop
  POST /tools      -> {tool, args} direct tool call (jailed)
  POST /evaluate   -> {task, expected_contains?} quick scored check

Stdlib only. SSE streaming supported on /chat with "stream": true.
"""

import json
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .agent import run_agent
from .backends import LlamaServerBackend, MockBackend
from .router import route
from . import tools as tool_engine

PORT = 8777


def _models():
    local = LlamaServerBackend()
    ms = [{"id": "jev-local-student", "owned_by": "ownai",
           "available": local.healthy()}]
    ms.append({"id": "jev-teacher-fallback", "owned_by": "external",
               "available": False})
    return ms


class Handler(BaseHTTPRequestHandler):
    server_version = "JEV/0.1"

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/health":
            local = LlamaServerBackend()
            self._send({"status": "ok", "local_llama": local.healthy(),
                        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        elif self.path == "/models":
            self._send({"object": "list",
                        "data": [{"object": "model", **m} for m in _models()]})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        try:
            body = self._read_json()
        except Exception:
            return self._send({"error": "invalid json"}, 400)

        if self.path == "/chat":
            msgs = body.get("messages", [])
            prompt = " ".join(m.get("content", "") for m in msgs)
            r = route(prompt)
            try:
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

        if self.path == "/generate":
            msgs = [{"role": "user", "content": body.get("prompt", "")}]
            r = route(body.get("prompt", ""))
            try:
                res = r["backend"].complete(msgs, body.get("max_tokens", 256))
            except Exception as e:
                return self._send({"error": str(e)[:300]}, 502)
            return self._send({"text": res["content"], "backend": res["backend"]})

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


def serve(port=PORT):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    from . import VERSION
    print(f"Urai {VERSION} on http://127.0.0.1:{port}  (/health /models /chat /agent)")
    srv.serve_forever()


if __name__ == "__main__":
    serve()
