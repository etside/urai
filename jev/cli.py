#!/usr/bin/env python3
"""
Urai CLI — unified command-line interface for the merged Urai system.
Talks to the Go API server (default :8777) for inference,
and directly to the jev sidecar (:8778) for model management.

Usage:
  urai chat                          interactive REPL
  urai ask "question"                one-shot answer
  urai agent "task"                  agentic run (plan/tool/verify)
  urai model list                    show all models + active
  urai model use <id>                switch active model
  urai model download <id>           download from HuggingFace
  urai model bench [--id ID]         benchmark a model
  urai serve start|stop|status       llama-server lifecycle
  urai gpu                           GPU info
  urai see <image> [question]        vision inference
  urai imagine "prompt" [-o out.png] text-to-image
  urai embed "text"                  get embedding vector
  urai api [--port 8777]             start the Go server + sidecar
  urai info                          system info
  urai version                       version
"""
from __future__ import annotations

import argparse, json, os, subprocess, sys, time
from pathlib import Path
import urllib.request, urllib.error

API_URL     = os.environ.get("URAI_API_URL",     "http://localhost:8777")
SIDECAR_URL = os.environ.get("URAI_SIDECAR_URL", "http://localhost:8778")
API_KEY     = os.environ.get("URAI_API_KEY",     "")
REPO_ROOT   = Path(__file__).parent.parent

VERSION = "3.0.0"


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _req(url: str, body: dict | None = None, timeout: int = 120) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    method = "POST" if data else "GET"
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body_txt}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot reach {url}: {e.reason}") from e


def api(path: str, body=None, timeout=120):
    return _req(f"{API_URL}{path}", body, timeout)


def sidecar(path: str, body=None, timeout=30):
    return _req(f"{SIDECAR_URL}{path}", body, timeout)


# ── Streaming chat ────────────────────────────────────────────────────────────

def stream_chat(messages: list, model: str = "auto") -> str:
    import urllib.request
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": True,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    req = urllib.request.Request(
        f"{API_URL}/v1/chat/completions",
        data=payload,
        headers=headers,
        method="POST",
    )
    full = ""
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            for raw_line in r:
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"].get("content", "")
                    if delta:
                        print(delta, end="", flush=True)
                        full += delta
                except Exception:
                    pass
    except KeyboardInterrupt:
        pass
    print()  # newline after stream
    return full


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_chat(args):
    """Interactive REPL."""
    model = getattr(args, "model", "auto") or "auto"
    history = []
    print(f"Urai v{VERSION} — model: {model} — Ctrl-C or empty line to quit")
    while True:
        try:
            user = input("\n> ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not user:
            break
        history.append({"role": "user", "content": user})
        reply = stream_chat(history, model)
        if reply:
            history.append({"role": "assistant", "content": reply})


def cmd_ask(args):
    """One-shot answer."""
    model = getattr(args, "model", "auto") or "auto"
    stream_chat([{"role": "user", "content": args.question}], model)


def cmd_agent(args):
    """Agentic run."""
    model = getattr(args, "model", "auto") or "auto"
    print(f"[agent] Running: {args.task}")
    result = api("/v1/agent/run", {
        "model": model,
        "messages": [{"role": "user", "content": args.task}],
        "max_iterations": getattr(args, "max_iter", 20) or 20,
        "parallel_tools": True,
    }, timeout=300)
    resp = result.get("result") or {}
    choices = resp.get("choices") or []
    if choices:
        print(choices[0].get("message", {}).get("content", ""))
    print(f"\n[agent] Iterations: {result.get('iterations')}  "
          f"Tool calls: {result.get('tool_calls')}  "
          f"Stop: {result.get('stop_reason')}  "
          f"Time: {result.get('duration_ms')}ms")


def cmd_model(args):
    sub = args.sub
    if sub == "list":
        try:
            data = api("/v1/models")
        except Exception:
            data = sidecar("/model/list")
        models = data.get("data") or data.get("models") or {}
        active = data.get("active", "")
        if isinstance(models, list):
            for m in models:
                marker = "●" if m.get("id") == active or m.get("id") == f"local/{active}" else " "
                print(f"{marker} {m['id']:<35} {m.get('owned_by','')}")
        else:
            for mid, entry in models.items():
                marker = "●" if mid == active else " "
                print(f"{marker} {mid:<25} {entry.get('kind',''):<10} "
                      f"{entry.get('params',''):<8} {entry.get('role','')}")

    elif sub == "use":
        r = sidecar("/model/use", {"id": args.id})
        print(f"Switched to {r.get('active','?')}")

    elif sub == "download":
        print(f"Downloading {args.id}…")
        r = sidecar("/model/download", {"id": args.id}, timeout=1800)
        print(r.get("message", "done"))

    elif sub == "bench":
        model_id = getattr(args, "id", None)
        cmd = ["./bin/urai", "model", "bench"]
        if model_id:
            cmd += ["--id", model_id]
        subprocess.run(cmd, cwd=str(REPO_ROOT))

    else:
        print(f"Unknown model subcommand: {sub}")


def cmd_serve(args):
    sub = args.sub
    if sub == "start":
        model_id = getattr(args, "id", None)
        r = sidecar("/serve/start", {"id": model_id} if model_id else {})
        print("Started" if r.get("ok") else f"Error: {r.get('error')}")
    elif sub == "stop":
        sidecar("/serve/stop")
        print("Stopped")
    elif sub == "status":
        r = sidecar("/serve/status")
        print("running" if r.get("running") else "stopped")


def cmd_gpu(args):
    r = sidecar("/gpu")
    print(json.dumps(r, indent=2))


def cmd_see(args):
    """Vision inference."""
    import base64, mimetypes
    img_src = args.image
    if img_src.startswith("http"):
        data_url = img_src
    else:
        mime = mimetypes.guess_type(img_src)[0] or "image/jpeg"
        with open(img_src, "rb") as f:
            data_url = f"data:{mime};base64," + base64.b64encode(f.read()).decode()
    question = getattr(args, "question", None) or "Describe this image."
    r = api("/see", {"image": data_url, "question": question})
    print(r.get("answer", r))


def cmd_imagine(args):
    """Text-to-image."""
    out = getattr(args, "output", None) or f"urai_{int(time.time())}.png"
    print(f"Generating: {args.prompt}")
    r = api("/imagine", {
        "prompt": args.prompt,
        "steps":  getattr(args, "steps", 2) or 2,
        "width":  getattr(args, "width",  512) or 512,
        "height": getattr(args, "height", 512) or 512,
        "output_path": out,
    }, timeout=600)
    if r.get("path"):
        print(f"Saved to: {r['path']}  ({r.get('duration_ms', '?')}ms)")
    else:
        print(f"Error: {r.get('error', r)}")


def cmd_embed(args):
    r = sidecar("/embed", {"text": args.text})
    data = r.get("data", [{}])
    if data and "embedding" in data[0]:
        emb = data[0]["embedding"]
        print(f"Embedding dim={len(emb)}  first5={emb[:5]}")
    else:
        print(json.dumps(r, indent=2))


def cmd_api(args):
    """Start Go server + jev sidecar."""
    port = getattr(args, "port", 8777) or 8777
    print(f"[urai] Starting sidecar on :8778…")
    sidecar_proc = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "jev" / "serve.py")],
        env={**os.environ, "URAI_REPO": str(REPO_ROOT)},
    )
    time.sleep(1)

    binary = REPO_ROOT / "bin" / "urai-server"
    if not binary.exists():
        binary = REPO_ROOT / "urai-server"
    if not binary.exists():
        print("[urai] Go binary not found. Build with: make build")
        sidecar_proc.terminate()
        return

    key_arg = []
    if API_KEY:
        key_arg = [f"--api-key={API_KEY}"]

    print(f"[urai] Starting Go server on :{port}…")
    go_proc = subprocess.Popen(
        [str(binary), f"--port={port}", f"--repo={REPO_ROOT}"] + key_arg,
    )
    print(f"[urai] Running — http://localhost:{port}")
    print("[urai] Ctrl-C to stop")
    try:
        go_proc.wait()
    except KeyboardInterrupt:
        go_proc.terminate()
        sidecar_proc.terminate()


def cmd_info(args):
    try:
        r = api("/v1/info")
        print(json.dumps(r, indent=2))
    except Exception as e:
        print(f"Cannot reach API: {e}")


def cmd_version(args):
    print(f"Urai v{VERSION}")


# ── Argument parser ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(prog="urai", description="Urai — standalone AI")
    sub = parser.add_subparsers(dest="cmd")

    # chat
    p = sub.add_parser("chat", help="interactive REPL")
    p.add_argument("--model", default="auto")

    # ask
    p = sub.add_parser("ask", help="one-shot answer")
    p.add_argument("question")
    p.add_argument("--model", default="auto")

    # agent
    p = sub.add_parser("agent", help="agentic run")
    p.add_argument("task")
    p.add_argument("--model", default="auto")
    p.add_argument("--max-iter", type=int, default=20)

    # model
    p = sub.add_parser("model", help="model management")
    ms = p.add_subparsers(dest="sub")
    ms.add_parser("list")
    mu = ms.add_parser("use");      mu.add_argument("id")
    md = ms.add_parser("download"); md.add_argument("id")
    mb = ms.add_parser("bench");    mb.add_argument("--id", default=None)

    # serve
    p = sub.add_parser("serve", help="llama-server lifecycle")
    ss = p.add_subparsers(dest="sub")
    st = ss.add_parser("start"); st.add_argument("--id", default=None)
    ss.add_parser("stop")
    ss.add_parser("status")

    # gpu
    sub.add_parser("gpu", help="GPU info")

    # see
    p = sub.add_parser("see", help="vision inference")
    p.add_argument("image", help="file path or URL")
    p.add_argument("question", nargs="?", default=None)

    # imagine
    p = sub.add_parser("imagine", help="text-to-image")
    p.add_argument("prompt")
    p.add_argument("-o", "--output", default=None)
    p.add_argument("--steps", type=int, default=2)
    p.add_argument("--width",  type=int, default=512)
    p.add_argument("--height", type=int, default=512)

    # embed
    p = sub.add_parser("embed", help="get embeddings")
    p.add_argument("text")

    # api
    p = sub.add_parser("api", help="start Go server + sidecar")
    p.add_argument("--port", type=int, default=8777)
    p.add_argument("--host", default="127.0.0.1")

    # info / version
    sub.add_parser("info",    help="system info")
    sub.add_parser("version", help="print version")

    args = parser.parse_args()

    dispatch = {
        "chat":    cmd_chat,
        "ask":     cmd_ask,
        "agent":   cmd_agent,
        "model":   cmd_model,
        "serve":   cmd_serve,
        "gpu":     cmd_gpu,
        "see":     cmd_see,
        "imagine": cmd_imagine,
        "embed":   cmd_embed,
        "api":     cmd_api,
        "info":    cmd_info,
        "version": cmd_version,
    }

    fn = dispatch.get(args.cmd)
    if fn is None:
        parser.print_help()
        return
    try:
        fn(args)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
