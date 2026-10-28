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
    urai login [key]                     save a master key for remote use
    urai logout                          forget saved remote credentials
    urai whoami                          show remote token status
    urai swarm "t1" "t2" [...]            parallel multi-agent fan-out
    urai plugin list|enable|disable|serve  OpenClaw-style plugins
    urai browse "goal" --steps file.json  human-like browser run
    urai mcp                             MCP stdio server (Claude/opencode tools)
    urai evaluate "task" --expect a,b   scored check via running server
    urai api [--host ADDR] [--port P]   start Urai API + web playground (:8777)
    urai studio [--port P]               start API (if needed) + open the Studio
    urai tui                            interactive terminal UI via the API
    urai key list|create|revoke         manage API keys (unlimited quota option)
    urai wiki search|add|get|list       knowledge wiki
    urai agents list|create|run|delete  named persistent agents
    urai routines list|create|run|del   scheduled recurring tasks
    urai vibe "task" [--workspace DIR]  agentic coding session (plan with --plan)
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request

from .envfile import load as _load_env

_load_env()   # pick up .env before reading defaults

BASE = "http://127.0.0.1:8777"
DEFAULT_REMOTE = os.environ.get("URAI_REMOTE_URL", BASE)


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
        print("urai chat — remote API (empty line quits)")
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


# ── v3 helpers: studio / keys / wiki / agents / routines / vibe / tui ─────────

def _api_base(port=None):
    return (os.environ.get("URAI_API") or f"http://127.0.0.1:{port or 8777}").rstrip("/")


def _api_ok(base, timeout=2):
    try:
        with urllib.request.urlopen(base + "/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _wait_api(base, seconds=25):
    import time
    t0 = time.time()
    while time.time() - t0 < seconds:
        if _api_ok(base):
            return True
        time.sleep(0.4)
    return False


def _post(base, path, payload, key="", timeout=600):
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(base + path, data, headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _json_out(obj, limit=8000):
    print(json.dumps(obj, indent=2, default=str)[:limit])


def cmd_studio(args):
    base = _api_base(getattr(args, "port", 8777))
    if not _api_ok(base):
        print(f"starting Urai API on {base} …", flush=True)
        env = dict(os.environ)
        subprocess.Popen(
            [sys.executable, "-m", "jev.cli", "api",
             "--port", str(getattr(args, "port", 8777)),
             "--host", getattr(args, "host", "127.0.0.1")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, env=env,
        )
        if not _wait_api(base, 30):
            sys.exit(f"server did not answer /health on {base} — run `urai api` to see why")
    url = base + "/app"
    print("Urai Studio →", url)
    if not getattr(args, "no_open", False):
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    return 0


def cmd_key(args):
    if args.remote:
        if args.action == "list":
            return _json_out(call("GET", "/v1/keys", remote=True))
        if args.action == "create":
            return _json_out(call("POST", "/v1/keys/generate",
                                  {"label": args.value or "cli", "quota": args.quota},
                                  remote=True))
        return _json_out(call("DELETE", "/v1/keys/" + args.value, remote=True))

    from . import apitokens
    if args.action == "list":
        toks = apitokens.list_tokens()
        if not toks:
            print("no keys yet — create one:  urai key create my-laptop")
            return 0
        for t in toks:
            state = "active" if t.get("active", True) else "revoked"
            print(f"{t.get('token','?'):<18} {t.get('label',''):<22} "
                  f"quota={'unlimited' if not t.get('quota') else t['quota']:<9} "
                  f"used={t.get('used',0):<5} {state}")
            print(f"  id: {t.get('id','')}")
        return 0
    if args.action == "create":
        r = apitokens.issue(args.value or "cli", args.quota)
        _json_out(r)
        print("\nStore this token now — it is shown once.", file=sys.stderr)
        return 0
    _json_out(apitokens.revoke(args.value))
    return 0


def cmd_vibe(args):
    if args.remote:
        return _json_out(call("POST", "/vibe",
                              {"task": args.task, "workspace": args.workspace,
                               "plan_only": args.plan, "max_steps": args.max_steps},
                              remote=True))
    from .vibe import vibe_session
    res = vibe_session(args.task, workspace=args.workspace,
                       plan_only=args.plan, max_steps=args.max_steps)
    _json_out(res)
    return 0


def cmd_wiki(args):
    from . import wiki
    if args.action == "search":
        if not args.value:
            sys.exit("usage: urai wiki search <query>")
        hits = wiki.wiki_search(args.value, top=args.top)
        for h in hits:
            print(f"{h.get('title','?'):<32} {h.get('category',''):<12} "
                  f"{h.get('score','')}")
            snippet = (h.get("snippet") or "").strip().replace("\n", " ")
            if snippet:
                print("   ", snippet[:160])
        if not hits:
            print("no matches")
        return 0
    if args.action == "add":
        if not args.value:
            sys.exit("usage: urai wiki add <title> [--content TEXT] [--category C]")
        content = args.content or getattr(args, "body", "") or sys.stdin.read()
        _json_out(wiki.wiki_add(args.value, content, args.category))
        return 0
    if args.action == "get":
        r = wiki.wiki_get(args.value)
        if not r:
            sys.exit("not found: " + args.value)
        print(r.get("content") or json.dumps(r, indent=2)[:6000])
        return 0
    rows = wiki.wiki_list(args.category)
    for e in rows:
        print(f"{e.get('title','?'):<36} {e.get('category',''):<12} {e.get('updated','')}")
    if not rows:
        print("wiki is empty — add one:  urai wiki add \"Title\" --content \"...\"")
    return 0


def cmd_agents(args):
    from . import jarvis_agents as ja
    if args.action == "list":
        rows = ja.list_agents()
        for a in rows:
            print(f"{a.get('id','?'):<10} {a.get('name',''):<24} "
                  f"runs={a.get('run_count',0):<4} sched={a.get('schedule') or '-'}")
        if not rows:
            print("no agents — create one:  urai agents create Scout --instructions \"...\"")
        return 0
    if args.action == "create":
        if not args.value:
            sys.exit("usage: urai agents create <name> [--instructions TEXT]")
        tools = [t.strip() for t in args.tools.split(",") if t.strip()]
        a = ja.create_agent(args.value, args.instructions, tools, args.schedule)
        _json_out(a.to_dict() if hasattr(a, "to_dict") else a)
        return 0
    if args.action == "run":
        if not args.value:
            sys.exit("usage: urai agents run <agent-id> [message]")
        msg = (getattr(args, "message", "") or args.instructions
               or "What is your current focus?")
        _json_out(ja.run_agent_turn(args.value, msg))
        return 0
    _json_out(ja.delete_agent(args.value))
    return 0


def cmd_routines(args):
    from . import routines as rt
    if args.action == "list":
        rows = rt.list_routines()
        for r in rows:
            print(f"{r.get('id','?'):<10} {r.get('name',''):<24} "
                  f"sched={r.get('schedule',''):<12} enabled={r.get('enabled',True)}")
        if not rows:
            print("no routines — create one:  urai routines create Morning --prompt \"...\" --schedule daily@09:00")
        return 0
    if args.action == "create":
        if not args.value:
            sys.exit("usage: urai routines create <name> --prompt TEXT [--schedule SPEC]")
        _json_out(rt.create_routine(args.value, args.prompt, args.schedule))
        return 0
    if args.action == "run":
        _json_out(rt.run_routine(args.value))
        return 0
    _json_out(rt.delete_routine(args.value))
    return 0


_TUI_HELP = """commands:
  /help              this help
  /clear             clear the conversation
  /model <id>        set model (default: urai)
  /key <token>       use this API token for the session
  /save <file>       save the transcript as JSON
  /quit              exit
anything else is sent to the local Urai API."""


def cmd_tui(args):
    base = _api_base()
    if not _api_ok(base):
        print(f"Urai API not reachable at {base}.")
        print("Start it with:  urai api --port 8777   (or: urai studio)")
        return 1
    key = _master_key()
    model = os.environ.get("URAI_MODEL", "urai")
    hist: list[dict] = []
    print("Urai TUI — /help for commands, /quit to exit")
    while True:
        try:
            line = input("\nurai› ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("/quit", "/exit", "q"):
            return 0
        if line == "/help":
            print(_TUI_HELP)
            continue
        if line == "/clear":
            hist.clear()
            print("(cleared)")
            continue
        if line.startswith("/model "):
            model = line.split(None, 1)[1].strip()
            print("(model:", model, ")")
            continue
        if line.startswith("/key "):
            key = line.split(None, 1)[1].strip()
            print("(key set for this session)")
            continue
        if line.startswith("/save "):
            path = line.split(None, 1)[1].strip()
            try:
                with open(path, "w") as f:
                    json.dump(hist, f, indent=2)
                print("(saved", path, ")")
            except Exception as e:
                print("(save failed:", e, ")")
            continue

        msgs = hist + [{"role": "user", "content": line}]
        print()
        parts: list[str] = []
        try:
            payload = json.dumps({"model": model, "messages": msgs,
                                  "max_tokens": 2048, "stream": True}).encode()
            headers = {"Content-Type": "application/json"}
            if key:
                headers["Authorization"] = "Bearer " + key
            req = urllib.request.Request(base + "/v1/chat/completions", payload,
                                         headers, method="POST")
            with urllib.request.urlopen(req, timeout=900) as resp:
                for raw in resp:
                    s = raw.decode("utf-8", errors="replace").strip()
                    if not s.startswith("data: "):
                        continue
                    chunk = s[6:]
                    if chunk == "[DONE]":
                        break
                    try:
                        obj = json.loads(chunk)
                        delta = (obj.get("choices", [{}])[0]
                                 .get("delta", {}).get("content", ""))
                        if not delta:
                            delta = obj.get("choices", [{}])[0].get("text", "")
                    except Exception:
                        delta = chunk
                    if delta:
                        parts.append(delta)
                        sys.stdout.write(delta)
                        sys.stdout.flush()
        except Exception as e:
            print(f"\n[error: {e}]")
            continue
        print()
        answer = "".join(parts).strip()
        if answer:
            hist += [{"role": "user", "content": line},
                     {"role": "assistant", "content": answer}]
            hist = hist[-20:]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="urai")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("chat"); p.add_argument("--remote", action="store_true",
        help="use VPS API instead of local model (needs: urai login)")
    p = sub.add_parser("ask"); p.add_argument("text")
    p.add_argument("--remote", action="store_true",
        help="use VPS API instead of local model (needs: urai login)")
    p = sub.add_parser("agent"); p.add_argument("text")
    p.add_argument("--plan", action="store_true",
                   help="propose file writes, do not apply")
    p.add_argument("--session", default="",
                   help="persist turns under this session id")
    p.add_argument("--no-remember", action="store_true")
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
        help="master key; omit to read URAI_MASTER_KEY env")
    p.add_argument("--url", default=None, help="API base URL")
    p = sub.add_parser("logout")
    p = sub.add_parser("whoami")
    p = sub.add_parser("swarm"); p.add_argument("tasks", nargs="+")
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--remote", action="store_true",
        help="fan out on VPS /agent/swarm (needs: urai login)")
    p = sub.add_parser("plugin"); p.add_argument("action",
        choices=["list", "enable", "disable", "serve"], nargs="?", default="list")
    p.add_argument("name", nargs="?", default=None)
    p = sub.add_parser("browse"); p.add_argument("goal")
    p.add_argument("--steps", default=None, help="JSON file with steps array")
    p.add_argument("--remote", action="store_true",
        help="run on VPS /browser/run (needs: urai login)")
    p = sub.add_parser("mcp")
    p = sub.add_parser("api"); p.add_argument("--port", type=int, default=8777)
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address (use 0.0.0.0 for LAN/VPS + URAI_API_KEY)")

    # ── v3: studio, keys, wiki, agents, routines, vibe, tui ──────────────
    p = sub.add_parser("studio", help="start the API (if needed) and open the Studio")
    p.add_argument("--port", type=int, default=8777)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--no-open", action="store_true")

    p = sub.add_parser("key", help="manage API keys")
    p.add_argument("action", nargs="?", default="list",
                   choices=["list", "create", "revoke"])
    p.add_argument("value", nargs="?", default="",
                   help="label (create) or token/prefix (revoke)")
    p.add_argument("--quota", type=int, default=0, help="0 = unlimited")
    p.add_argument("--remote", action="store_true")

    p = sub.add_parser("vibe", help="vibe-code a task inside a workspace")
    p.add_argument("task")
    p.add_argument("--workspace", default=".")
    p.add_argument("--plan", action="store_true", help="propose writes only")
    p.add_argument("--max-steps", type=int, default=20)
    p.add_argument("--remote", action="store_true")

    p = sub.add_parser("wiki", help="knowledge wiki")
    p.add_argument("action", nargs="?", default="search",
                   choices=["search", "add", "get", "list"])
    p.add_argument("value", nargs="?", default="")
    p.add_argument("body", nargs="?", default="", help="page body (add)")
    p.add_argument("--content", default="", help="page body (add); stdin if omitted")
    p.add_argument("--category", default="concepts")
    p.add_argument("--top", type=int, default=5)

    p = sub.add_parser("agents", help="named persistent agents")
    p.add_argument("action", nargs="?", default="list",
                   choices=["list", "create", "run", "delete"])
    p.add_argument("value", nargs="?", default="", help="name (create) / id")
    p.add_argument("message", nargs="?", default="", help="message (run)")
    p.add_argument("--instructions", default="")
    p.add_argument("--tools", default="")
    p.add_argument("--schedule", default="")

    p = sub.add_parser("routines", help="scheduled recurring tasks")
    p.add_argument("action", nargs="?", default="list",
                   choices=["list", "create", "run", "delete"])
    p.add_argument("value", nargs="?", default="", help="name (create) / id")
    p.add_argument("--prompt", default="")
    p.add_argument("--schedule", default="manual")

    sub.add_parser("tui", help="interactive terminal UI over the local API")

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
                print(json.dumps(call("POST", "/agent", {"task": args.text,
                                 "plan": args.plan, "session_id": args.session,
                                 "remember": not args.no_remember}, remote=True),
                                 indent=2)[:6000])
            except Exception as e:
                sys.exit(f"remote agent failed ({e}); check: urai whoami")
            return
        from .agent import run_agent
        print(json.dumps(run_agent(args.text, plan=args.plan,
                                   history=[]), indent=2)[:6000])
        return

    if args.cmd == "login":
        key = args.key or os.environ.get("URAI_MASTER_KEY", "")
        if not key:
            sys.exit("usage: urai login <master-key>  [--url https://your-host]")
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

    if args.cmd == "swarm":
        if args.remote or os.environ.get("URAI_REMOTE"):
            try:
                print(json.dumps(call("POST", "/agent/swarm",
                                      {"tasks": args.tasks,
                                       "max_workers": args.workers}, remote=True), indent=2)[:8000])
            except Exception as e:
                sys.exit(f"remote swarm failed ({e}); check: urai whoami")
            return
        from .swarm import run_swarm
        print(json.dumps(run_swarm(args.tasks, args.workers), indent=2)[:8000])
        return

    if args.cmd == "plugin":
        from . import plugins as _pl
        if args.action == "list":
            for m in _pl.all_plugins():
                print(f"{m['name']}: {'on' if m.get('enabled') else 'off'} — {m.get('description','')[:90]}")
            return
        if args.action in ("enable", "disable"):
            if not args.name:
                sys.exit("usage: urai plugin enable|disable <name>")
            print(json.dumps(_pl.set_enabled(args.name, args.action == "enable")))
            return
        if args.action == "serve":
            if args.name == "telegram":
                from plugins.telegram.handler import serve_forever
                return serve_forever()
            sys.exit("usage: urai plugin serve telegram")
        return

    if args.cmd == "browse":
        steps = []
        if args.steps:
            steps = json.load(open(args.steps))
        if args.remote or os.environ.get("URAI_REMOTE"):
            try:
                print(json.dumps(call("POST", "/browser/run",
                                      {"goal": args.goal, "steps": steps}, remote=True), indent=2)[:6000])
            except Exception as e:
                sys.exit(f"remote browse failed ({e}); check: urai whoami")
            return
        from . import browser as _b
        print(json.dumps(_b.run_steps(steps, goal=args.goal), indent=2)[:6000])
        return

    if args.cmd == "mcp":
        from .mcp_server import main as mcp_main
        return mcp_main()

    if args.cmd == "studio":
        return cmd_studio(args)
    if args.cmd == "key":
        return cmd_key(args)
    if args.cmd == "vibe":
        return cmd_vibe(args)
    if args.cmd == "wiki":
        return cmd_wiki(args)
    if args.cmd == "agents":
        return cmd_agents(args)
    if args.cmd == "routines":
        return cmd_routines(args)
    if args.cmd == "tui":
        return cmd_tui(args)

    if args.cmd == "api":
        from .server import serve
        return serve(args.port, args.host)


if __name__ == "__main__":
    sys.exit(main())
