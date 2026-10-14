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
    urai video "prompt" [-o out.mp4]     text-to-video (local animatic or provider)
    urai login [key]                     save VPS master key (856777) for remote use
    urai logout                          forget saved remote credentials
    urai whoami                          show remote token status
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
DEFAULT_REMOTE = "https://urai.daddyai.online"


def _cfg_path():
    d = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(d, "urai", "config.json")


def _cfg_load():
    try:
        with open(_cfg_path()) as f:
            return json.load(f)
    except Exception:
        return {}


def _cfg_save(cfg):
    p = _cfg_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(cfg, f, indent=2)


def _remote_base():
    return (os.environ.get("URAI_REMOTE_URL")
            or _cfg_load().get("remote_url")
            or DEFAULT_REMOTE).rstrip("/")


def _master_key():
    return (os.environ.get("URAI_MASTER_KEY")
            or _cfg_load().get("master_key") or "")


def _device_id():
    cfg = _cfg_load()
    dev = (os.environ.get("URAI_DEVICE_ID") or cfg.get("device_id") or "")
    if not dev:
        import random, string
        dev = "cli-" + "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))
        cfg["device_id"] = dev
        try:
            _cfg_save(cfg)
        except Exception:
            pass
    return dev


def call(method, path, payload=None, timeout=300, remote=False):
    base = _remote_base() if remote else BASE
    if isinstance(payload, dict):
        payload = dict(payload)
        payload.setdefault("device_id", _device_id())
    data = json.dumps(payload or {}).encode() if payload is not None else None
    headers = {"Content-Type": "application/json", "X-Device-Id": _device_id()}
    key = _master_key()
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(base + path, data, headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def remote_chat_once(messages, max_tokens=512):
    """One remote chat turn (non-streaming) against the VPS API."""
    d = call("POST", "/v1/chat/completions",
             {"messages": messages, "max_tokens": max_tokens, "stream": False},
             timeout=300, remote=True)
    if isinstance(d, dict) and d.get("choices"):
        return d["choices"][0]["message"]["content"]
    return json.dumps(d)[:4000]


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


def cmd_chat(args):
    remote = bool(getattr(args, "remote", False) or os.environ.get("URAI_REMOTE"))
    if remote:
        print("urai chat — remote VPS (master key 856777, empty line quits)")
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
                text = remote_chat_once(history[-8:])
                print(text)
                history.append({"role": "assistant", "content": text})
            except Exception as e:
                print(f"\n[error: {e} — check: urai whoami]")
        return
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

    p = sub.add_parser("chat"); p.add_argument("--remote", action="store_true",
        help="use VPS API instead of local model (needs: urai login)")
    p = sub.add_parser("ask"); p.add_argument("text")
    p.add_argument("--remote", action="store_true",
        help="use VPS API instead of local model (needs: urai login)")
    p = sub.add_parser("agent"); p.add_argument("text")
    p.add_argument("--remote", action="store_true",
        help="use VPS /agent instead of local run (needs: urai login)")

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
    p = sub.add_parser("skill"); p.add_argument("action", nargs="?",
                                                default="list")
    p = sub.add_parser("video"); p.add_argument("prompt")
    p.add_argument("-o", "--out", default=None)
    p.add_argument("--duration", type=int, default=4)
    p.add_argument("--remote", action="store_true",
        help="render on VPS API instead of locally")
    p = sub.add_parser("login"); p.add_argument("key", nargs="?",
        help="master key (856777); omit to read URAI_MASTER_KEY env")
    p.add_argument("--url", default=None, help="API base URL")
    p = sub.add_parser("logout")
    p = sub.add_parser("whoami")
    p = sub.add_parser("mcp")
    p = sub.add_parser("api"); p.add_argument("--port", type=int, default=8777)
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address (use 0.0.0.0 for LAN/VPS + URAI_API_KEY)")

    args = ap.parse_args(argv)

    if args.cmd == "chat":
        return cmd_chat(args)

    if args.cmd == "ask":
        if args.remote or os.environ.get("URAI_REMOTE"):
            try:
                print(remote_chat_once([{"role": "user", "content": args.text}])[:4000])
            except Exception as e:
                sys.exit(f"remote ask failed ({e}); check: urai whoami")
            return
        from .agent import run_agent
        print(json.dumps(run_agent(args.text), indent=2)[:4000])
        return

    if args.cmd == "agent":
        if args.remote or os.environ.get("URAI_REMOTE"):
            try:
                print(json.dumps(call("POST", "/agent", {"task": args.text}),
                                 indent=2)[:6000])
            except Exception as e:
                sys.exit(f"remote agent failed ({e}); check: urai whoami")
            return
        from .agent import run_agent
        print(json.dumps(run_agent(args.text), indent=2)[:6000])
        return

    if args.cmd == "login":
        key = args.key or os.environ.get("URAI_MASTER_KEY", "")
        if not key:
            sys.exit("usage: urai login <master-key>  (VPS master key is 856777)")
        cfg = _cfg_load()
        cfg["master_key"] = key
        if args.url:
            cfg["remote_url"] = args.url.rstrip("/")
        _cfg_save(cfg)
        try:
            st = call("GET", "/v1/token/status?device_id=" + _device_id(),
                      remote=True)
            print(json.dumps({"saved": True, "token": st}, indent=2)[:1000])
        except Exception as e:
            print(json.dumps({"saved": True, "verify": f"unverified: {e}"}))
        return

    if args.cmd == "logout":
        cfg = _cfg_load()
        cfg.pop("master_key", None)
        _cfg_save(cfg)
        print("logged out (master key forgotten)")
        return

    if args.cmd == "whoami":
        try:
            print(json.dumps(call("GET", "/v1/token/status?device_id=" + _device_id(),
                                  remote=True), indent=2)[:2000])
        except Exception as e:
            sys.exit(f"whoami failed ({e}); is the VPS reachable?")
        return

    if args.cmd == "video":
        if args.remote or os.environ.get("URAI_REMOTE"):
            try:
                print(json.dumps(call("POST", "/v1/videos/generations",
                                      {"prompt": args.prompt, "out": args.out,
                                       "duration": args.duration}), indent=2)[:4000])
            except Exception as e:
                sys.exit(f"remote video failed ({e}); check: urai whoami")
            return
        from . import video
        res = video.generate(args.prompt, args.out, duration=args.duration)
        print(json.dumps(res, indent=2))
        if not res.get("ok"):
            sys.exit(1)
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

    if args.cmd == "skill":
        from . import skills as _skills
        for s in _skills.all_skills():
            print(f"{s['name']}: {s['description'][:120]}")
        return

    if args.cmd == "mcp":
        from .mcp_server import main as mcp_main
        return mcp_main()

    if args.cmd == "api":
        from .server import serve
        return serve(args.port, args.host)


if __name__ == "__main__":
    sys.exit(main())
