#!/usr/bin/env python3
"""
jev/serve.py — Urai sidecar control server.

Manages the llama-server process, GPU detection, model switching,
model downloads, and image generation.
Listens on 127.0.0.1:8778 (internal only — never exposed to internet).

GET  /status              — health + active model info
GET  /gpu                 — GPU detection
GET  /model/list          — all registry entries
POST /model/use           — {"id": "qwen3-17b"}  switch active model
POST /model/download      — {"id": "qwen3-8b"}   download from HF
POST /imagine             — text-to-image via SD-Turbo
POST /serve/start         — start llama-server for active model
POST /serve/stop          — stop llama-server
GET  /serve/status        — is llama-server running?
POST /embed               — get embeddings (proxies to :8081)
POST /nlp                 — {"text"} -> {nlp, vibe} request understanding
"""
from __future__ import annotations

import base64
import json
import os
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jev import imagine as _imagine
from jev import models_registry as reg
from jev import serve_ctl as ctl
from jev.gpu import detect

PORT = int(os.environ.get("SIDECAR_PORT", "8778"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass  # quiet

    def send_json(self, data: dict, code: int = 200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def read_body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/status":
            active_id, entry = reg.active_model()
            running = ctl.is_up()
            try:
                from jev import cache as _cache
                cache_stats = _cache.get_cache().stats()
            except Exception:
                cache_stats = {}
            self.send_json({
                "ok": True,
                "active_model": active_id,
                "llama_running": running,
                "model_kind": entry.get("kind"),
                "model_params": entry.get("params"),
                "tg_toks": entry.get("tg_toks"),
                "repo_root": str(ROOT),
                "cache": cache_stats,
            })
        elif p == "/gpu":
            self.send_json(detect())
        elif p == "/model/list":
            registry = reg.load()
            self.send_json({
                "active": registry["active"],
                "models": registry["models"],
            })
        elif p == "/serve/status":
            self.send_json({"running": ctl.is_up()})
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        p = self.path.split("?")[0]
        body = self.read_body()

        if p == "/model/use":
            model_id = body.get("id", "")
            if not model_id:
                self.send_json({"error": "id required"}, 400); return
            try:
                ctl.stop()
                # Update active in registry
                registry = reg.load()
                if model_id not in registry["models"]:
                    self.send_json({"error": f"unknown model: {model_id}"}, 404); return
                registry["active"] = model_id
                reg.save(registry)
                entry = registry["models"][model_id]
                if entry.get("kind") in ("chat", "vision"):
                    _start_model(model_id, entry)
                self.send_json({"ok": True, "active": model_id})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif p == "/model/download":
            model_id = body.get("id", "")
            if not model_id:
                self.send_json({"error": "id required"}, 400); return
            def _dl():
                try:
                    reg.download(model_id)
                except Exception as e:
                    print(f"[sidecar] download {model_id}: {e}", flush=True)
            threading.Thread(target=_dl, daemon=True).start()
            self.send_json({"ok": True, "message": f"downloading {model_id}"})

        elif p == "/cache/clear":
            try:
                from jev import cache as _cache
                cleared = _cache.get_cache().clear()
            except Exception as e:
                self.send_json({"error": str(e)}, 500); return
            self.send_json({"ok": True, "cleared": cleared})

        elif p == "/nlp":
            # Request understanding + style plan (Phase 2). Pure, deterministic.
            text = body.get("text", "")
            meta = {}
            try:
                from jev import nlp as _nlp
                from jev import vibe as _vibe
                analysis = _nlp.analyze(text)
                v = _vibe.plan(analysis, {}) if _vibe.enabled() else {}
                if v:
                    v["directive"] = _vibe.directive(v)
                meta = {"nlp": analysis, "vibe": v}
            except Exception as e:
                self.send_json({"error": str(e)}, 500); return
            self.send_json(meta)

        elif p == "/imagine":
            prompt   = body.get("prompt", "")
            steps    = int(body.get("steps") or 0) or None
            width    = int(body.get("width") or 512)
            height   = int(body.get("height") or 512)
            out_path = body.get("output_path")
            meta = {}
            try:
                from jev import nlp as _nlp
                analysis = _nlp.analyze(prompt)
                meta = {"nlp": analysis}
                if steps is None and analysis.get("urgency", 0) > 0.5:
                    steps = 1
            except Exception:
                pass
            try:
                t0 = time.time()
                res = _imagine.generate(prompt, out_path, steps, width, height)
                if not res.get("ok"):
                    self.send_json({"error": res.get("error", "imagine failed"),
                                    **meta}, 500); return
                ms = int((time.time() - t0) * 1000)
                data_url = ""
                try:
                    with open(res["path"], "rb") as f:
                        data_url = "data:image/png;base64," + base64.b64encode(f.read()).decode()
                except Exception:
                    pass
                self.send_json({"path": res["path"], "data_url": data_url,
                                "duration_ms": ms, **meta})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif p == "/serve/start":
            active_id, entry = reg.active_model()
            model_id = body.get("id") or active_id
            try:
                result = _start_model(model_id, entry)
                self.send_json(result)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif p == "/serve/stop":
            ctl.stop()
            self.send_json({"ok": True})

        elif p == "/embed":
            text = body.get("text", "")
            try:
                payload = json.dumps({"input": text}).encode()
                req_obj = urllib.request.Request(
                    "http://127.0.0.1:8081/v1/embeddings",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req_obj, timeout=30) as r:
                    result = json.loads(r.read())
                self.send_json(result)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
        else:
            self.send_json({"error": "not found"}, 404)


def _start_model(model_id: str, entry: dict) -> dict:
    """Start llama-server for a given model entry."""
    model_path = str(ROOT / entry["path"])
    mmproj = None
    if entry.get("kind") == "vision":
        files = entry.get("files", [])
        for f in files:
            if "mmproj" in f["path"]:
                mmproj = str(ROOT / f["path"])
                break
    return ctl.start(model_path, mmproj=mmproj)


def main():
    print(f"[sidecar] Starting on 127.0.0.1:{PORT}  repo={ROOT}", flush=True)
    # Auto-start llama-server if a model is active and not already running
    if not ctl.is_up():
        try:
            active_id, entry = reg.active_model()
            if entry.get("kind") in ("chat", "vision"):
                print(f"[sidecar] Auto-starting llama-server for '{active_id}'", flush=True)
                threading.Thread(
                    target=lambda: _start_model(active_id, entry),
                    daemon=True
                ).start()
        except Exception as e:
            print(f"[sidecar] Warning: auto-start: {e}", flush=True)

    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[sidecar] Ready", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[sidecar] Stopping", flush=True)
        ctl.stop()


if __name__ == "__main__":
    main()
