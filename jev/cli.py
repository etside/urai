#!/usr/bin/env python3
"""urai CLI — local + GPU-wise AI tool (stdlib only).

    urai chat                          interactive REPL, streams tokens
    urai ask "question"                 one-shot answer (NLP/vibe styled)
    urai agent "multi-step task"        plan/tool/verify loop
    urai agent apply <file|-|>           land --plan proposals via /agent/apply
    urai apply <file|-|>                 alias of `agent apply`
    urai model list                     registry + availability + bench numbers
    urai model download <id>            fetch GGUF from HF into model/base
    urai model use <id>                 set active model (restarts server)
    urai model bench [--id ID]          llama-bench row for a model
    urai serve start|stop|status|restart  llama-server lifecycle (GPU-aware)
    urai gpu                            detect GPU + offload policy
    urai see <image> [question]          ask about a picture (vision model)
    urai imagine <prompt> [-o out.png]   text-to-image (stable-diffusion.cpp)
    urai image <prompt>                  alias of imagine
    urai embed "text..."                 vectors (embedding server)
    urai video "prompt" [--provider P] [--ref IMG...]   video (ref2va/local/provider)
    urai login [key]                     save VPS master key (856777) for remote use
    urai logout                          forget saved remote credentials
    urai whoami                          show remote token status
    urai swarm "t1" "t2" [...]            parallel / conductor multi-agent fan-out
    urai skill [list|show|enable|disable]  markdown capability packs
    urai plugin list|enable|disable|serve  OpenClaw-style plugins
    urai browse "goal" --steps file.json  human-like browser run
    urai mcp                             MCP stdio server (Claude/opencode tools)
    urai evaluate "task" --expect a,b   scored check via running server
    urai profile [--ident ID] [--set k=v]  sticky user preferences
    urai vibe on|off                     toggle sentiment-conditioned generation
    urai tasks [list|add|run|rm]         scheduled agent jobs (/agent/jobs)
    urai theme light|dark|system         UI theme preference
    urai api [--host ADDR] [--port P]   start Urai API + web playground (:8777)
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8777"
DEFAULT_REMOTE = "https://urai.daddyai.online"
BRANDS = ("urai", "cyberurai")


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
    """Write the config atomically: parent dir 0700, file 0600 (never world-readable)."""
    p = _cfg_path()
    d = os.path.dirname(p)
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except Exception:
        pass
    tmp = p + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, p)
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass


def _mask(secret):
    """Never echo a master key: keep only a 2-char hint on each side."""
    s = str(secret or "")
    if len(s) <= 4:
        return "*" * len(s)
    return s[:2] + "*" * (len(s) - 4) + s[-2:]


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


def _vibe_enabled():
    import os as _os
    v = _os.environ.get("URAI_VIBE")
    if v is None:
        cfg = _cfg_load()
        if "vibe" in cfg:
            return bool(cfg["vibe"])
        return True
    return str(v).strip().lower() not in ("0", "off", "false", "no")


def _apply_config_env():
    """Export persisted prefs (vibe) into the environment for local runs."""
    cfg = _cfg_load()
    if "URAI_VIBE" not in os.environ and "vibe" in cfg:
        os.environ["URAI_VIBE"] = "1" if cfg["vibe"] else "0"


def _brand(args):
    return getattr(args, "model", None) or getattr(args, "brand", None) or "urai"


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


def call_soft(method, path, payload=None, timeout=600, remote=False):
    """Like call(), but never raises: returns (body, status). Non-2xx bodies are
    parsed so the {ok:false, installed:false, status:{missing}} contract survives."""
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
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp), resp.status
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = {"error": f"HTTP {e.code}"}
        return body, e.code
    except Exception as e:
        return {"error": str(e)}, 0


def _is_missing_error(res):
    err = str((res or {}).get("error", "")).lower()
    return (bool((res or {}).get("installed") is False)
            or any(x in err for x in ("not installed", "not reachable", "missing weights")))


def _remote_missing_ref2va():
    """Server drops status.missing on the 502 not-installed response; fetch the
    video runner status endpoint to recover the exact missing file names."""
    try:
        st, _ = call_soft("GET", "/v1/videos/generations", remote=True, timeout=60)
        return ((st or {}).get("ref2va") or {}).get("missing") or []
    except Exception:
        return []


def _print_video_missing(res, provider="ref2va", remote=False):
    missing = ((res.get("status") or {}).get("missing")) or []
    if not missing and remote and str(provider).lower().startswith(("ref2va", "h3", "vsa", "auto")):
        missing = _remote_missing_ref2va()
    if missing:
        print("missing files:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
    else:
        print("install on the server: scripts/video/install_ref2va_vsa.sh",
              file=sys.stderr)


def _print_video_result(res, as_json=False, provider="auto", remote=False):
    """Print provider_label/weights/steps/sampler/scheduler/duration. Returns ok."""
    if as_json:
        print(json.dumps(res, indent=2))
        return bool(res.get("ok"))
    if not res.get("ok"):
        print(f"video failed: {res.get('error', 'unknown error')}", file=sys.stderr)
        if _is_missing_error(res):
            _print_video_missing(res, provider=provider, remote=remote)
        return False
    w = res.get("weights") or {}
    s = res.get("settings") or {}
    lines = ["provider: " + str(res.get("provider_label") or res.get("provider") or "?")]
    if res.get("path"):
        lines.append("path: " + str(res["path"]))
    if w.get("diffusion_model"):
        lines.append("diffusion_model: " + str(w["diffusion_model"]))
    if w.get("turbo_lora"):
        lines.append("turbo_lora: %s (strength %s)" %
                     (w["turbo_lora"], w.get("turbo_lora_strength", 1.0)))
    if w.get("vsa_gate"):
        lines.append("vsa_gate: " + str(w["vsa_gate"]))
    if w.get("text_encoder"):
        lines.append("text_encoder: " + str(w["text_encoder"]))
    if s.get("steps") is not None:
        lines.append("steps: " + str(s["steps"]))
    if s.get("sampler"):
        lines.append("sampler: " + str(s["sampler"]))
    if s.get("scheduler"):
        lines.append("scheduler: " + str(s["scheduler"]))
    if s.get("sparsity") is not None:
        lines.append("sparsity: " + str(s["sparsity"]))
    if res.get("duration") is not None:
        lines.append("duration: " + str(res["duration"]) + "s")
    if res.get("grade"):
        lines.append("grade: " + str(res["grade"]))
    print("\n".join(lines))
    return True


def _dim(s):
    if sys.stdout.isatty():
        return "\033[2m" + s + "\033[0m"
    return s


def _urai_lines(meta):
    """Compact [nlp]/[vibe] summary lines from a response `urai` block."""
    nlp = (meta or {}).get("nlp") or {}
    vibe = (meta or {}).get("vibe") or {}
    if nlp:
        sent = nlp.get("sentiment") or {}
        rf = nlp.get("redflags") or []
        nlp_line = ("[nlp] lang=%s sentiment=%s(%.2f) emotion=%s intent=%s "
                    "urgency=%.2f cx=%.2f redflags=%s") % (
            nlp.get("language", "?"), sent.get("label", "neutral"),
            float(sent.get("score", 0.0)), nlp.get("emotion", "?"),
            nlp.get("intent", "?"), float(nlp.get("urgency", 0.0)),
            float(nlp.get("complexity", 0.0)),
            ",".join(str(x) for x in rf) if rf else "none")
    else:
        nlp_line = "[nlp] unavailable"
    if vibe:
        w = float(vibe.get("warmth", 0.0))
        tone = "warm" if w > 0.6 else "neutral" if w > 0.35 else "cool"
        directive = vibe.get("directive") or ""
        vibe_line = ("[vibe] structure=%s formatting=%s tone=%s lang=%s "
                     "de-escalate=%s directive=%d lines") % (
            vibe.get("structure", "?"), vibe.get("formatting", "?"), tone,
            vibe.get("language", "?"),
            "yes" if vibe.get("de-escalate") else "no",
            len(directive.splitlines()) if directive else 0)
    else:
        vibe_line = "[vibe] unavailable"
    return [nlp_line, vibe_line]


def _print_urai(meta, verbose=1):
    """Print the [nlp]/[vibe] summary; full directive only on -vv."""
    for line in _urai_lines(meta):
        print(line)
    directive = (((meta or {}).get("vibe") or {}).get("directive") or "")
    if verbose and verbose >= 2 and directive:
        for dl in directive.splitlines():
            print(_dim("    " + dl))


def remote_chat_turn(messages, max_tokens=512, model="urai"):
    """One remote chat turn; returns the full JSON response (incl. `urai`)."""
    return call("POST", "/v1/chat/completions",
                {"messages": messages, "max_tokens": max_tokens, "stream": False,
                 "model": model},
                timeout=300, remote=True)


def remote_chat_once(messages, max_tokens=512, model="urai"):
    """One remote chat turn (non-streaming) against the VPS API."""
    d = remote_chat_turn(messages, max_tokens, model)
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


def _style(text, ident=None, history=None):
    """NLP analyze + profile blend -> style plan + directive (never raises)."""
    try:
        from .vibe import plan_for
        return plan_for(text, ident or _device_id(), history=history)
    except Exception:
        return {}


def _observe(ident, plan):
    try:
        from .profile import observe
        if plan:
            observe(ident, {}, targets={k: plan.get(k) for k in
                     ("formality", "warmth", "verbosity", "humor",
                      "technical_depth", "emoji") if plan.get(k) is not None})
    except Exception:
        pass


def cmd_chat(args):
    verbose = int(getattr(args, "verbose", 0) or 0)
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
                turn = remote_chat_turn(history[-8:])
                if isinstance(turn, dict) and turn.get("choices"):
                    text = turn["choices"][0]["message"]["content"]
                else:
                    text = json.dumps(turn)[:4000]
                print(text)
                history.append({"role": "assistant", "content": text})
                if verbose:
                    _print_urai(turn.get("urai") if isinstance(turn, dict) else None,
                                verbose)
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
            if verbose:
                _print_urai(None, verbose)
        except Exception as e:
            print(f"[error: {e} — is the model server up? run: urai serve start]")


def _cmd_apply(args, path):
    """Land `--plan` proposals via POST /agent/apply. Shared by `urai apply`
    and `urai agent apply`."""
    try:
        raw = sys.stdin.read() if path == "-" else open(path).read()
        doc = json.loads(raw)
    except Exception as e:
        sys.exit(f"could not read proposals ({e})")
    if isinstance(doc, dict):
        proposals = doc.get("proposals") or doc.get("plan") or []
    else:
        proposals = doc
    if not isinstance(proposals, list):
        sys.exit('expected a JSON array of proposals or {"proposals": [...]}')
    key = _master_key() or "856777"
    try:
        d = call("POST", "/agent/apply",
                 {"proposals": proposals, "master_key": key},
                 remote=getattr(args, "remote", False))
    except Exception as e:
        sys.exit(f"apply failed ({e}); is the API up? run: urai api")
    results = d.get("results", []) if isinstance(d, dict) else []
    for i, r in enumerate(results):
        ok = bool(r.get("ok"))
        tool = r.get("tool") or (r.get("proposal") or {}).get("tool", "?")
        print(f"[{i}] {'applied' if ok else 'FAILED'}: {tool}"
              + ("" if ok else f" — {r.get('error', '')}"))
    applied = sum(1 for r in results if r.get("ok"))
    print(f"summary: {applied}/{len(results)} applied")


def _skills_state_path():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "data", "skills_state.json")


def _skills_state():
    try:
        with open(_skills_state_path()) as f:
            return json.load(f)
    except Exception:
        return {}


def _skills_state_save(st):
    p = _skills_state_path()
    os.makedirs(os.path.dirname(p), mode=0o700, exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=2)
    os.replace(tmp, p)


def main(argv=None):
    _apply_config_env()
    if argv is None:
        argv = sys.argv[1:]
    argv = list(argv)
    # allow the documented `urai agent apply` form as well as `urai apply`
    if len(argv) >= 2 and argv[0] == "agent" and argv[1] == "apply":
        argv = ["apply"] + argv[2:]
    ap = argparse.ArgumentParser(prog="urai")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("chat"); p.add_argument("--remote", action="store_true",
        help="use VPS API instead of local model (needs: urai login)")
    p.add_argument("-v", "--verbose", action="count", default=0,
        help="print the [nlp]/[vibe] analysis summary (twice: full directive)")

    p = sub.add_parser("ask"); p.add_argument("text")
    p.add_argument("--remote", action="store_true",
        help="use VPS API instead of local model (needs: urai login)")
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--model", "--brand", dest="model", choices=list(BRANDS),
                   default="urai", help="brand/tier sent to the model")

    p = sub.add_parser("agent"); p.add_argument("text")
    p.add_argument("apply_file", nargs="?", default=None,
                   help="with 'apply': JSON proposals file (or - for stdin)")
    p.add_argument("--plan", action="store_true",
                   help="propose file writes, do not apply")
    p.add_argument("--session", default="",
                   help="persist turns under this session id")
    p.add_argument("--no-remember", action="store_true")
    p.add_argument("--remote", action="store_true",
        help="use VPS /agent instead of local run (needs: urai login)")
    p.add_argument("--model", "--brand", dest="model", choices=list(BRANDS),
                   default="urai", help="brand/tier sent to the model")
    p.add_argument("-v", "--verbose", action="count", default=0,
        help="print the [nlp]/[vibe] analysis summary (twice: full directive)")

    p = sub.add_parser("apply")
    p.add_argument("file", help="JSON file of --plan proposals, or - for stdin")
    p.add_argument("--remote", action="store_true",
        help="apply on the VPS (needs: urai login)")

    p = sub.add_parser("model")
    p.add_argument("action", choices=["list", "download", "use", "bench"])
    p.add_argument("id", nargs="?")
    p.add_argument("--ctx", type=int, default=int(os.environ.get("URAI_CTX", "8192")))

    p = sub.add_parser("serve")
    p.add_argument("action", choices=["start", "stop", "status", "restart"])
    p.add_argument("--model", default=None)
    p.add_argument("--ctx", type=int, default=int(os.environ.get("URAI_CTX", "8192")))
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--all", action="store_true",
                   help="stop/restart every server (chat + embed)")
    p.add_argument("--spec", default=None,
                   help="speculative decoding, e.g. ngram-mod (free) — see docs/TRAINING.md#speed")

    sub.add_parser("gpu")
    sub.add_parser("version")
    p = sub.add_parser("teacher")
    p.add_argument("action", choices=["status", "test"])
    p = sub.add_parser("evaluate"); p.add_argument("text")
    p.add_argument("--expect", default="")
    p.add_argument("--remote", action="store_true",
        help="score on the VPS (needs: urai login)")

    p = sub.add_parser("see"); p.add_argument("image")
    p.add_argument("question", nargs="?", default="Describe this image in detail.")
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--remote", action="store_true",
        help="use VPS /see (needs: urai login)")

    p = sub.add_parser("imagine"); p.add_argument("prompt")
    p.add_argument("-o", "--out", default=None)
    p.add_argument("--steps", type=int, default=None)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--remote", action="store_true",
        help="render on VPS /v1/images/generations (needs: urai login)")

    p = sub.add_parser("image"); p.add_argument("prompt")
    p.add_argument("-o", "--out", default=None)
    p.add_argument("--steps", type=int, default=None)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--remote", action="store_true",
        help="alias of imagine")

    p = sub.add_parser("embed"); p.add_argument("text", nargs="+")
    p.add_argument("--remote", action="store_true",
        help="embed on VPS /v1/embeddings (needs: urai login)")

    p = sub.add_parser("skill"); p.add_argument("action", nargs="?", default="list",
                                                choices=["list", "show", "add", "enable", "disable"])
    p.add_argument("name", nargs="?", default=None)
    p.add_argument("--desc", default="", help="one-line description for `skill add`")

    p = sub.add_parser("studio")
    p.add_argument("action", nargs="?", default="status",
                   choices=["status", "image", "video", "see"],
                   help="media surface: list profiles (status) or generate/analyse")
    p.add_argument("prompt", nargs="?", default=None,
                   help="prompt (image/video) or image path (see)")
    p.add_argument("-o", "--out", default=None)
    p.add_argument("--remote", action="store_true",
        help="use the VPS media endpoints (needs: urai login)")

    p = sub.add_parser("video"); p.add_argument("prompt")
    p.add_argument("-o", "--out", default=None)
    p.add_argument("--duration", type=int, default=4)
    p.add_argument("--provider", default="auto",
                   choices=["auto", "ref2va", "local", "higgsfield", "runway"],
                   help="auto | ref2va (H3 Ref2VA VSA) | local animatic | higgsfield | runway")
    p.add_argument("--ref", action="append", default=[], metavar="PATH",
                   help="reference image path/URL for ref2va (repeatable)")
    p.add_argument("--width", type=int, default=None)
    p.add_argument("--height", type=int, default=None)
    p.add_argument("--frames", type=int, default=None)
    p.add_argument("--sparsity", type=float, default=None)
    p.add_argument("--json", action="store_true", dest="as_json",
                   help="print the full result JSON (weights/settings/provenance)")
    p.add_argument("--remote", action="store_true",
        help="render on VPS API instead of locally")
    p = sub.add_parser("login"); p.add_argument("key", nargs="?",
        help="master key (856777); omit to read URAI_MASTER_KEY env")
    p.add_argument("--url", default=None, help="API base URL")
    p = sub.add_parser("logout")
    p = sub.add_parser("whoami")
    p = sub.add_parser("swarm"); p.add_argument("tasks", nargs="+")
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--mode", choices=["parallel", "conductor"], default="parallel")
    p.add_argument("--remote", action="store_true",
        help="fan out on VPS /agent/swarm (needs: urai login)")
    p.add_argument("--model", "--brand", dest="model", choices=list(BRANDS),
                   default="urai", help="brand/tier sent to the model")

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

    p = sub.add_parser("profile")
    p.add_argument("--ident", default=None, help="profile identity (default: device id)")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="set a preference (repeatable)")
    p = sub.add_parser("vibe"); p.add_argument("action", choices=["on", "off", "status"],
                                               nargs="?", default="status")
    p = sub.add_parser("tasks")
    p.add_argument("action", nargs="?", default="list",
                   choices=["list", "add", "run", "rm"])
    p.add_argument("task", nargs="?", default=None, help="task text for `add`")
    p.add_argument("--id", default=None, help="job id for `run` / `rm`")
    p.add_argument("--every", type=int, default=3600, help="seconds between runs")
    p.add_argument("--remote", action="store_true",
        help="manage jobs on the VPS (needs: urai login)")
    p = sub.add_parser("theme"); p.add_argument("value", choices=["light", "dark", "system"])

    args = ap.parse_args(argv)

    if args.cmd == "chat":
        return cmd_chat(args)

    if args.cmd == "ask":
        brand = _brand(args)
        if args.remote or os.environ.get("URAI_REMOTE"):
            try:
                print(remote_chat_once([{"role": "user", "content": args.text}],
                                       model=brand)[:4000])
            except Exception as e:
                sys.exit(f"remote ask failed ({e}); check: urai whoami")
            return
        ident = _device_id()
        plan = _style(args.text, ident)
        directive = plan.get("directive", "") if plan else ""
        messages = ([{"role": "system", "content": directive}] if directive else []) + \
                   [{"role": "user", "content": args.text}]
        try:
            from .router import route
            r = route(args.text, tier=brand)
            res = r["backend"].complete(messages, max_tokens=args.max_tokens)
        except Exception as e:
            sys.exit(f"local ask failed ({e}); is the model server up? run: urai serve start")
        print(str(res.get("content", "")).strip())
        _observe(ident, plan)
        return

    if args.cmd == "agent":
        if args.text == "apply":
            return _cmd_apply(args, getattr(args, "apply_file", None) or "-")
        brand = _brand(args)
        verbose = int(getattr(args, "verbose", 0) or 0)
        if args.remote or os.environ.get("URAI_REMOTE"):
            try:
                d = call("POST", "/agent", {"task": args.text,
                         "plan": args.plan, "session_id": args.session,
                         "remember": not args.no_remember,
                         "tier": brand, "model": brand}, remote=True)
            except Exception as e:
                sys.exit(f"remote agent failed ({e}); check: urai whoami")
            print(json.dumps(d, indent=2)[:6000])
            if verbose:
                _print_urai(d.get("urai") if isinstance(d, dict) else None, verbose)
            return
        from . import sessions as _sess
        from .agent import run_agent
        sid = args.session
        hist = _sess.history(sid) if sid else []
        ident = _device_id()
        plan = _style(args.text, ident, history=hist)
        directive = plan.get("directive", "") if plan else ""
        task = (directive + "\n\n" + args.text) if directive else args.text
        result = run_agent(task, plan=args.plan, history=hist, tier=brand)
        if not args.no_remember:
            sid = _sess.append(sid, "user", args.text)
            _sess.append(sid, "assistant", str(result.get("answer", "")))
            result["session_id"] = sid
        print(json.dumps(result, indent=2)[:6000])
        if verbose:
            _print_urai(result.get("urai"), verbose)
        _observe(ident, plan)
        return

    if args.cmd == "apply":
        return _cmd_apply(args, args.file)

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
            print(json.dumps({"saved": True, "master_key": _mask(key),
                              "token": st}, indent=2)[:1000])
        except Exception as e:
            print(json.dumps({"saved": True, "master_key": _mask(key),
                              "verify": f"unverified: {e}"}))
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

    if args.cmd == "studio":
        remote = bool(getattr(args, "remote", False) or os.environ.get("URAI_REMOTE"))
        if args.action == "status":
            try:
                d = call("GET", "/v1/media/profiles", remote=remote)
            except Exception as e:
                sys.exit(f"studio status failed ({e}); is the API up? run: urai api")
            profiles = d.get("profiles", []) if isinstance(d, dict) else []
            print(f"media profiles{' (remote)' if remote else ''}:")
            for pr in profiles:
                print(f"  - {pr.get('id')}: {pr.get('provider', '?')} "
                      f"{str(pr.get('desc', ''))[:80]}")
            if not profiles:
                print("  (none advertised; see docs/VIDEO_REF2VA.md)")
            return
        if not args.prompt:
            sys.exit(f"usage: urai studio {args.action} <prompt|image>")
        if args.action == "see":
            args = argparse.Namespace(cmd="see", image=args.prompt,
                                      question="Describe this image in detail.",
                                      max_tokens=512, remote=remote)
        elif args.action == "image":
            args = argparse.Namespace(cmd="imagine", prompt=args.prompt,
                                      out=args.out, steps=None, seed=7,
                                      remote=remote)
        else:  # video
            args = argparse.Namespace(cmd="video", prompt=args.prompt,
                                      out=args.out, duration=4, provider="auto",
                                      ref=[], width=None, height=None, frames=None,
                                      sparsity=None, as_json=False, remote=remote)

    if args.cmd == "video":
        settings = {}
        for key in ("width", "height", "frames", "sparsity"):
            val = getattr(args, key, None)
            if val is not None:
                settings[key] = val
        refs = list(args.ref or [])
        if args.remote or os.environ.get("URAI_REMOTE"):
            payload = {"prompt": args.prompt, "out": args.out,
                       "duration": args.duration, "provider": args.provider,
                       "ref_images": refs or None,
                       "settings": settings or None}
            body, code = call_soft("POST", "/v1/videos/generations", payload, remote=True)
            if not isinstance(body, dict):
                sys.exit(f"remote video failed (bad response: {body!r})")
            ok = _print_video_result(body, as_json=args.as_json,
                                     provider=args.provider, remote=True)
            if not ok:
                if _is_missing_error(body):
                    sys.exit(1)
                sys.exit(f"remote video failed: {body.get('error') or f'HTTP {code}'}")
            return
        from . import video
        res = video.generate(args.prompt, args.out, duration=args.duration,
                             width=args.width if args.width else 512,
                             height=args.height if args.height else 512,
                             provider=args.provider, ref_images=refs,
                             settings=settings or None)
        _print_video_result(res, as_json=args.as_json, provider=args.provider)
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
            print(json.dumps({"chat": serve_ctl.stop(),
                              "embed": serve_ctl.emb_stop()}))
            return
        if args.action == "restart":
            serve_ctl.stop()
            serve_ctl.emb_stop()
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
        if args.remote or os.environ.get("URAI_REMOTE"):
            try:
                print(json.dumps(call("POST", "/see",
                                      {"image": args.image, "question": args.question,
                                       "max_tokens": args.max_tokens}, remote=True),
                                 indent=2)[:4000])
            except Exception as e:
                sys.exit(f"remote see failed ({e}); check: urai whoami")
            return
        from . import vision
        res = vision.see(args.image, args.question, args.max_tokens)
        if not res["ok"]:
            sys.exit(res["error"])
        print(res["answer"])
        return

    if args.cmd in ("imagine", "image"):
        if args.remote or os.environ.get("URAI_REMOTE"):
            try:
                print(json.dumps(call("POST", "/v1/images/generations",
                                      {"prompt": args.prompt, "out": args.out,
                                       "steps": args.steps, "seed": args.seed}),
                                 indent=2)[:4000])
            except Exception as e:
                sys.exit(f"remote imagine failed ({e}); check: urai whoami")
            return
        from . import imagine
        res = imagine.generate(args.prompt, args.out, args.steps,
                               seed=args.seed)
        print(json.dumps(res, indent=2))
        if not res["ok"]:
            sys.exit(1)
        return

    if args.cmd == "embed":
        if args.remote or os.environ.get("URAI_REMOTE"):
            try:
                d = call("POST", "/v1/embeddings",
                         {"input": args.text, "model": "local-embed"}, remote=True)
                print(json.dumps({"count": len(d.get("data", [])),
                                  "dims": [len(x.get("embedding", []))
                                           for x in d.get("data", [])],
                                  "model": d.get("model", "local-embed")},
                                 indent=2))
            except Exception as e:
                sys.exit(f"remote embed failed ({e}); check: urai whoami")
            return
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
                                  {"task": args.text, "expected_contains": exp},
                                  remote=(args.remote or bool(os.environ.get("URAI_REMOTE")))),
                             indent=2)[:4000])
        except Exception as e:
            print(f"API server not running ({e}); start with: urai api")
        return

    if args.cmd == "skill":
        from . import skills as _skills
        if args.action == "list":
            for s in _skills.all_skills():
                print(f"{s['name']}: {s['description'][:120]}")
            return
        if args.action == "add":
            if not args.name:
                sys.exit("usage: urai skill add <name> [--desc TEXT]")
            try:
                info = _skills.add_skill(args.name, getattr(args, "desc", "") or "")
            except ValueError as e:
                sys.exit(str(e))
            print(f"created skill: {info['name']} -> {info['path']}")
            return
        if args.action == "show":
            if not args.name:
                sys.exit("usage: urai skill show <name>")
            for s in _skills.all_skills():
                if s["name"] == args.name:
                    print(open(s["path"]).read())
                    return
            sys.exit(f"unknown skill: {args.name}")
        if not args.name:
            sys.exit(f"usage: urai skill {args.action} <name>")
        known = {s["name"] for s in _skills.all_skills()}
        if args.name not in known:
            sys.exit(f"unknown skill: {args.name}")
        st = _skills_state()
        st[args.name] = (args.action == "enable")
        _skills_state_save(st)
        print(f"{args.name}: {'enabled' if st[args.name] else 'disabled'}")
        return

    if args.cmd == "swarm":
        brand = _brand(args)
        if args.remote or os.environ.get("URAI_REMOTE"):
            try:
                print(json.dumps(call("POST", "/agent/swarm",
                                      {"tasks": args.tasks,
                                       "max_workers": args.workers,
                                       "mode": args.mode,
                                       "model": brand, "tier": brand},
                                      remote=True), indent=2)[:8000])
            except Exception as e:
                sys.exit(f"remote swarm failed ({e}); check: urai whoami")
            return
        if args.mode == "conductor":
            from .conductor import run_conductor
            print(json.dumps(run_conductor(" ".join(args.tasks), {},
                                           max_workers=args.workers),
                             indent=2)[:8000])
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

    if args.cmd == "api":
        from .server import serve
        return serve(args.port, args.host)

    if args.cmd == "profile":
        from . import profile as _prof
        ident = args.ident or _device_id()
        if args.set:
            for kv in args.set:
                if "=" not in kv:
                    sys.exit(f"bad --set '{kv}' (use key=value)")
                k, v = kv.split("=", 1)
                k = k.strip()
                try:
                    val = float(v)
                    if val.is_integer():
                        val = int(val)
                except ValueError:
                    val = v
                print(json.dumps(_prof.set_pref(ident, k, val)))
            return
        print(json.dumps({"ident": ident, "profile": _prof.get(ident)}, indent=2))
        return

    if args.cmd == "vibe":
        if args.action == "status":
            print(f"vibe {'on' if _vibe_enabled() else 'off'}")
            return
        cfg = _cfg_load()
        cfg["vibe"] = (args.action == "on")
        _cfg_save(cfg)
        os.environ["URAI_VIBE"] = "1" if cfg["vibe"] else "0"
        print(f"vibe {'on' if cfg['vibe'] else 'off'}")
        return

    if args.cmd == "tasks":
        payload = {"action": args.action}
        if args.action == "add":
            if not args.task:
                sys.exit("usage: urai tasks add \"task text\" [--every 3600]")
            payload["task"] = args.task
            payload["every_s"] = args.every
        if args.action in ("run", "rm"):
            if not args.id:
                sys.exit(f"usage: urai tasks {args.action} --id <job-id>")
        if args.action == "run":
            payload["id"] = args.id
        if args.action == "rm":
            payload["action"] = "delete"
            payload["id"] = args.id
        try:
            print(json.dumps(call("POST", "/agent/jobs", payload,
                                  remote=args.remote), indent=2)[:4000])
        except Exception as e:
            sys.exit(f"tasks failed ({e}); is the API up? run: urai api")
        return

    if args.cmd == "theme":
        cfg = _cfg_load()
        cfg["theme"] = args.value
        _cfg_save(cfg)
        print(f"theme: {args.value}")
        return


if __name__ == "__main__":
    sys.exit(main())
