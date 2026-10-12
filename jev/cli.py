#!/usr/bin/env python3
"""urai CLI — local + GPU-wise AI tool (stdlib only).

    urai chat                          interactive REPL, streams tokens
    urai ask "question"                 one-shot answer
    urai agent "multi-step task"        plan/tool/verify loop
    urai model list                     registry + availability + bench numbers
    urai model download <id>            fetch GGUF from HF into model/base
    urai model use <id>                 set active model (restarts server)
    urai model bench [--id ID]          llama-bench row for a model
    urai serve start|stop|status        llama-server lifecycle (GPU-aware)
    urai gpu                            detect GPU + offload policy
    urai see <image> [question]          ask about a picture (vision model)
    urai imagine <prompt> [-o out.png]   text-to-image (stable-diffusion.cpp)
    urai embed "text..."                 vectors (embedding server)
    urai mcp                             MCP stdio server (Claude/opencode tools)
    urai evaluate "task" --expect a,b   scored check via running server
    urai api [--host ADDR] [--port P]   start Urai API + web playground (:8777)
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request

BASE = "http://127.0.0.1:8777"


def call(method, path, payload=None, timeout=300):
    data = json.dumps(payload or {}).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data,
                                 {"Content-Type": "application/json"},
                                 method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def stream_chat(messages, max_tokens=512):
    payload = json.dumps({"model": "jev-local-student", "messages": messages,
                          "max_tokens": max_tokens, "stream": True}).encode()
    req = urllib.request.Request("http://127.0.0.1:8080/v1/chat/completions",
                                 payload, {"Content-Type": "application/json"})
    full = []
    with urllib.request.urlopen(req, timeout=600) as resp:
        for line in resp:
            line = line.decode().strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                delta = json.loads(data)["choices"][0]["delta"].get("content", "")
            except (KeyError, json.JSONDecodeError):
                continue
            full.append(delta)
            print(delta, end="", flush=True)
    print()
    return "".join(full)


def cmd_chat(_):
    print("urai chat — streaming local model (empty line quits)")
    history = []
    while True:
        try:
            q = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            break
        history.append({"role": "user", "content": q})
        print("urai> ", end="", flush=True)
        try:
            text = stream_chat(history[-8:])
            history.append({"role": "assistant", "content": text})
        except Exception as e:
            print(f"[error: {e} — is the model server up? run: urai serve start]")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="urai")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("chat")
    p = sub.add_parser("ask"); p.add_argument("text")
    p = sub.add_parser("agent"); p.add_argument("text")

    p = sub.add_parser("model")
    p.add_argument("action", choices=["list", "download", "use", "bench"])
    p.add_argument("id", nargs="?")
    p.add_argument("--ctx", type=int, default=2048)

    p = sub.add_parser("serve")
    p.add_argument("action", choices=["start", "stop", "status"])
    p.add_argument("--model", default=None)
    p.add_argument("--ctx", type=int, default=2048)
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--spec", default=None,
                   help="speculative decoding, e.g. ngram-mod (free) — see docs/TRAINING.md#speed")

    sub.add_parser("gpu")
    sub.add_parser("version")
    p = sub.add_parser("teacher")
    p.add_argument("action", choices=["status", "test"])
    p = sub.add_parser("evaluate"); p.add_argument("text")
    p.add_argument("--expect", default="")
    p = sub.add_parser("see"); p.add_argument("image")
    p.add_argument("question", nargs="?", default="Describe this image in detail.")
    p.add_argument("--max-tokens", type=int, default=512)
    p = sub.add_parser("imagine"); p.add_argument("prompt")
    p.add_argument("-o", "--out", default=None)
    p.add_argument("--steps", type=int, default=None)
    p.add_argument("--seed", type=int, default=7)
    p = sub.add_parser("embed"); p.add_argument("text", nargs="+")
    p = sub.add_parser("mcp")
    p = sub.add_parser("api"); p.add_argument("--port", type=int, default=8777)
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address (use 0.0.0.0 for LAN/VPS + URAI_API_KEY)")

    args = ap.parse_args(argv)

    if args.cmd == "chat":
        return cmd_chat(args)

    if args.cmd == "ask":
        from .agent import run_agent
        print(json.dumps(run_agent(args.text), indent=2)[:4000])
        return

    if args.cmd == "agent":
        from .agent import run_agent
        print(json.dumps(run_agent(args.text), indent=2)[:6000])
        return

    if args.cmd == "model":
        from . import models_registry as reg
        from . import serve_ctl
        r = reg.load()
        if args.action == "list":
            for mid, m in r["models"].items():
                from pathlib import Path as P
                root = P(__file__).resolve().parents[1]
                paths = [f["path"] for f in m.get("files", [])] or [m["path"]]
                here = all((root / p).exists() for p in paths)
                mark = " [active]" if mid == r["active"] else ""
                bench = f" pp={m.get('pp_toks')}/tg={m.get('tg_toks')}" if m.get("tg_toks") else " (unbenchmarked)"
                print(f"{mid}{mark}: {m['params']} {m['quant']} role={m['role']} "
                      f"kind={m.get('kind', 'chat')} "
                      f"{'on-disk' if here else 'not-downloaded'}{bench}")
            return
        if args.action == "download":
            if not args.id:
                sys.exit("usage: urai model download <id>")
            reg.download(args.id)
            return
        if args.action == "use":
            if not args.id or args.id not in r["models"]:
                sys.exit(f"unknown model; choices: {list(r['models'])}")
            r["active"] = args.id
            reg.save(r)
            print(f"active model -> {args.id}")
            from pathlib import Path as P
            p = P(__file__).resolve().parents[1] / r["models"][args.id]["path"]
            if p.exists() and serve_ctl.is_up():
                print(serve_ctl.start(str(p), ctx=args.ctx))
            return
        if args.action == "bench":
            mid = args.id or r["active"]
            m = r["models"][mid]
            from pathlib import Path as P
            root = P(__file__).resolve().parents[1]
            mp = root / m["path"]
            if not mp.exists():
                sys.exit(f"{mid} not downloaded; run: urai model download {mid}")
            lib = root / "third_party/llama.cpp/build/bin"
            env = dict(os.environ, LD_LIBRARY_PATH=str(lib))
            out = subprocess.run(
                [str(lib / "llama-bench"), "-m", str(mp), "-p", "128",
                 "-n", "64", "-t", "2"], capture_output=True, text=True,
                timeout=900, env=env)
            print(out.stdout[-1500:] or out.stderr[-1500:])
            return

    if args.cmd == "serve":
        from . import serve_ctl, models_registry as reg
        if args.action == "status":
            print({"up": serve_ctl.is_up(args.port), "port": args.port})
            return
        if args.action == "stop":
            print(serve_ctl.stop())
            return
        mid = args.model or reg.load()["active"]
        m = reg.load()["models"][mid]
        from pathlib import Path as P
        root = P(__file__).resolve().parents[1]
        if m.get("kind") == "generate":
            sys.exit(f"{mid} is a checkpoint, not a server model — "
                     f"use: urai imagine \"prompt\"")
        if m.get("kind") == "embedding":
            mp = str(root / m["path"])
            if not P(mp).exists():
                sys.exit(f"{mid} not on disk; run: urai model download {mid}")
            print(serve_ctl.emb_start(mp, port=m.get("port", 8081)))
            return
        mp = str(root / m["path"])
        if not P(mp).exists():
            sys.exit(f"{mid} not on disk; run: urai model download {mid}")
        mmproj = None
        if m.get("kind") == "vision":
            cands = [root / f["path"] for f in m.get("files", [])
                     if "mmproj" in f["path"]]
            mmproj = str(cands[0]) if cands and cands[0].exists() else None
            if mmproj is None:
                sys.exit(f"{mid} needs its mmproj file; run: urai model download {mid}")
        print(serve_ctl.start(mp, ctx=args.ctx, port=args.port, mmproj=mmproj,
                              spec=args.spec))
        return

    if args.cmd == "version":
        from . import VERSION
        from . import models_registry as reg
        r = reg.load()
        print(f"urai {VERSION} (active model: {r['active']})")
        return

    if args.cmd == "teacher":
        import os as _os
        from .backends import TeacherAPIBackend
        if args.action == "status":
            print({"base": _os.environ.get("TEACHER_BASE_URL", "(not set)"),
                   "model": _os.environ.get("TEACHER_MODEL", "(not set)"),
                   "key": "set" if _os.environ.get("TEACHER_API_KEY") else "(not set)"})
            return
        try:
            t = TeacherAPIBackend()
        except KeyError as e:
            sys.exit(f"missing env {e}; see: urai teacher status")
        try:
            out = t.complete([{"role": "user", "content": "Reply with exactly: teacher-ok"}],
                             max_tokens=16)["content"]
            print(f"teacher-ok via {t.model}: {out.strip()[:200]}")
        except Exception as e:
            sys.exit(f"teacher call failed: {str(e)[:300]}")
        return

    if args.cmd == "gpu":
        import json as j
        from . import gpu
        g = gpu.detect()
        print(j.dumps({"gpu": g, "offload": gpu.offload_policy(g)}, indent=2))
        if g["vendor"] == "none":
            print(gpu.cuda_build_hint())
        return

    if args.cmd == "see":
        from . import vision
        res = vision.see(args.image, args.question, args.max_tokens)
        if not res["ok"]:
            sys.exit(res["error"])
        print(res["answer"])
        return

    if args.cmd == "imagine":
        from . import imagine
        res = imagine.generate(args.prompt, args.out, args.steps,
                               seed=args.seed)
        print(json.dumps(res, indent=2))
        if not res["ok"]:
            sys.exit(1)
        return

    if args.cmd == "embed":
        from .backends import EmbeddingBackend
        be = EmbeddingBackend()
        if not be.healthy():
            sys.exit("embedding server down; run: "
                     "urai model download embed-small && "
                     "urai serve start --model embed-small")
        vecs = be.embed(args.text)
        print(json.dumps({"model": be.model, "count": len(vecs),
                          "dims": [len(v) for v in vecs],
                          "embeddings": vecs}, indent=2)[:6000])
        return

    if args.cmd == "evaluate":
        exp = [e for e in args.expect.split(",") if e]
        try:
            print(json.dumps(call("POST", "/evaluate",
                                  {"task": args.text, "expected_contains": exp}),
                             indent=2)[:4000])
        except Exception as e:
            print(f"API server not running ({e}); start with: urai api")
        return

    if args.cmd == "mcp":
        from .mcp_server import main as mcp_main
        return mcp_main()

    if args.cmd == "api":
        from .server import serve
        return serve(args.port, args.host)


if __name__ == "__main__":
    sys.exit(main())
