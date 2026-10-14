#!/usr/bin/env python3
"""
jev/serve.py — Urai sidecar control server.

Manages the llama-server process, GPU detection, model switching,
model downloads, image generation, and embeddings.
Listens on :8778 (internal only — not exposed to the internet).

Routes (all JSON in/out):
  GET  /status              — health + active model info
  GET  /gpu                 — GPU detection
  GET  /model/list          — all registry entries
  POST /model/use           — switch active model  {"id": "qwen3-17b"}
  POST /model/download      — download from HF     {"id": "qwen3-8b"}
  POST /imagine             — text-to-image via SD-Turbo
  POST /serve/start         — start llama-server
  POST /serve/stop          — stop llama-server
  GET  /serve/status        — llama-server running?
  POST /embed               — get embeddings from embed model
"""

from __future__ import annotations
import json, os, sys, time, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# Allow importing existing jev modules from urai v1
REPO_ROOT = Path(os.environ.get("URAI_REPO", str(Path(__file__).parent.parent)))
sys.path.insert(0, str(REPO_ROOT))

from jev.models_registry import ModelsRegistry
from jev.serve_ctl       import ServeCtl
from jev.gpu             import detect_gpu
from jev.imagine         import run_imagine

PORT     = int(os.environ.get("SIDECAR_PORT", "8778"))
REGISTRY = ModelsRegistry(REPO_ROOT / "model" / "registry.json")
CTL      = ServeCtl(REGISTRY, REPO_ROOT)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # suppress default noisy logs

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

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/status":
            active_id = REGISTRY.active_model()
            entry     = REGISTRY.get(active_id) if active_id else None
            running   = CTL.is_running()
            self.send_json({
                "ok":           True,
                "active_model": active_id,
                "llama_running": running,
                "model_kind":   entry.get("kind") if entry else None,
                "model_params": entry.get("params") if entry else None,
                "tg_toks":      entry.get("tg_toks") if entry else None,
                "repo_root":    str(REPO_ROOT),
            })
        elif p == "/gpu":
            self.send_json(detect_gpu())
        elif p == "/model/list":
            self.send_json({"models": REGISTRY.all(), "active": REGISTRY.active_model()})
        elif p == "/serve/status":
            self.send_json({"running": CTL.is_running()})
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        p    = self.path.split("?")[0]
        body = self.read_body()

        if p == "/model/use":
            model_id = body.get("id", "")
            if not model_id:
                self.send_json({"error": "id required"}, 400); return
            try:
                CTL.stop()
                REGISTRY.set_active(model_id)
                entry = REGISTRY.get(model_id)
                if entry.get("kind") in ("chat", "vision"):
                    CTL.start(model_id)
                self.send_json({"ok": True, "active": model_id})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif p == "/model/download":
            model_id = body.get("id", "")
            if not model_id:
                self.send_json({"error": "id required"}, 400); return
            # Kick off download in a thread; respond immediately
            def _dl():
                try:
                    REGISTRY.download(model_id)
                except Exception as e:
                    print(f"[sidecar] download {model_id}: {e}", flush=True)
            threading.Thread(target=_dl, daemon=True).start()
            self.send_json({"ok": True, "message": f"downloading {model_id}"})

        elif p == "/imagine":
            prompt   = body.get("prompt", "")
            neg      = body.get("negative_prompt", "")
            steps    = int(body.get("steps") or 2)
            width    = int(body.get("width")  or 512)
            height   = int(body.get("height") or 512)
            out_path = body.get("output_path") or f"/tmp/urai_imagine_{int(time.time())}.png"
            try:
                t0 = time.time()
                run_imagine(
                    prompt=prompt,
                    negative_prompt=neg,
                    steps=steps,
                    width=width,
                    height=height,
                    output_path=out_path,
                    repo_root=REPO_ROOT,
                )
                ms = int((time.time() - t0) * 1000)
                # Encode to base64 data-URL for inline return
                import base64
                data_url = ""
                try:
                    with open(out_path, "rb") as f:
                        data_url = "data:image/png;base64," + base64.b64encode(f.read()).decode()
                except Exception:
                    pass
                self.send_json({"path": out_path, "data_url": data_url, "duration_ms": ms})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif p == "/serve/start":
            model_id = body.get("id") or REGISTRY.active_model()
            try:
                CTL.start(model_id)
                self.send_json({"ok": True, "model": model_id})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif p == "/serve/stop":
            CTL.stop()
            self.send_json({"ok": True})

        elif p == "/embed":
            text = body.get("text", "")
            try:
                import urllib.request
                payload = json.dumps({"input": text}).encode()
                req = urllib.request.Request(
                    "http://127.0.0.1:8081/v1/embeddings",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=30) as r:
                    result = json.loads(r.read())
                self.send_json(result)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        else:
            self.send_json({"error": "not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def main():
    print(f"[sidecar] Starting on :{PORT}  repo={REPO_ROOT}", flush=True)
    # Auto-start llama-server if a model is active
    active = REGISTRY.active_model()
    if active:
        entry = REGISTRY.get(active)
        if entry and entry.get("kind") in ("chat", "vision"):
            print(f"[sidecar] Auto-starting llama-server for '{active}'", flush=True)
            try:
                CTL.start(active)
            except Exception as e:
                print(f"[sidecar] Warning: auto-start failed: {e}", flush=True)

    server = HTTPServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[sidecar] Stopping", flush=True)
        CTL.stop()


if __name__ == "__main__":
    main()
