#!/usr/bin/env python3
"""Urai MCP server (Model Context Protocol, stdio, stdlib only).

Lets Claude Code / opencode / Claude Desktop / OpenClaw drive Urai as tools:
chat, agent, swarm, vision, image-gen, video-gen, browse, embeddings, model registry, evaluation (10 tools).

  Add to the MCP client config (served from this repo, no install):
    {"mcpServers": {"urai": {"command": "python3",
                             "args": ["/abs/path/to/urai/jev/mcp_server.py"]}}}
  Or via launcher:  ./bin/urai mcp   (starts stdio server on this process)

Protocol: newline-delimited JSON-RPC 2.0 (initialize, tools/list,
tools/call, ping). Every tool returns {content:[{type:text}]}.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SERVER_INFO = {"name": "urai", "version": "v1-lite"}


def _t(name, desc, props, required=()):
    return {"name": name, "description": desc,
            "inputSchema": {"type": "object", "properties": props,
                            "required": list(required)}}


TOOLS = [
    _t("urai_ask", "One-shot answer from the routed backend.",
       {"text": {"type": "string"}, "max_tokens": {"type": "integer", "default": 512}}, ["text"]),
    _t("urai_agent", "Multi-step plan/tool/verify task run. Returns answer + trace.",
       {"task": {"type": "string"}}, ["task"]),
    _t("urai_see", "Ask a question about a local image file (vision model must be served).",
       {"image": {"type": "string"}, "question": {"type": "string", "default": "Describe this image in detail."}}, ["image"]),
    _t("urai_imagine", "Generate a PNG from a prompt (stable-diffusion.cpp).",
       {"prompt": {"type": "string"}, "out": {"type": "string"},
        "steps": {"type": "integer", "default": 2}, "seed": {"type": "integer", "default": 7}}, ["prompt"]),
    _t("urai_video", "Text-to-video: local CPU slideshow (animatic-grade) or SOTA provider proxy (Higgsfield/Runway keys).",
       {"prompt": {"type": "string"}, "duration": {"type": "integer", "default": 4},
        "width": {"type": "integer", "default": 512}, "height": {"type": "integer", "default": 512},
        "fps": {"type": "integer", "default": 4}, "provider": {"type": "string", "default": "auto"}}, ["prompt"]),
    _t("urai_swarm", "Parallel multi-agent fan-out (Kimi/Hermes-style swarm).",
       {"tasks": {"type": "array"}, "max_workers": {"type": "integer", "default": 3}}, ["tasks"]),
    _t("urai_browse", "Human-like browser run (goto/click/fill). Auth fields pause for user approval.",
       {"goal": {"type": "string", "default": ""}, "steps": {"type": "array"}}, []),
    _t("urai_embed", "Embed one or more texts (embedding server must be up).",
       {"texts": {"type": ["string", "array"]}}, ["texts"]),
    _t("urai_model_list", "Registry: ids, kinds, roles, availability, bench numbers.", {}),
    _t("urai_evaluate", "Run a task through the agent and score expected substrings.",
       {"task": {"type": "string"}, "expect": {"type": "string", "default": ""}}, ["task"]),
]


def tool_call(name, args):
    """Execute a tool; returns plain text for the MCP content envelope."""
    args = args or {}
    if name == "urai_ask":
        from jev.router import route
        r = route(args.get("text", ""))
        res = r["backend"].complete(
            [{"role": "user", "content": args.get("text", "")}],
            args.get("max_tokens", 512))
        return res["content"]
    if name == "urai_agent":
        from jev.agent import run_agent
        return json.dumps(run_agent(args.get("task", "")), indent=2)[:6000]
    if name == "urai_see":
        from jev import vision
        res = vision.see(args.get("image", ""),
                         args.get("question", "Describe this image in detail."))
        if not res["ok"]:
            raise RuntimeError(res["error"])
        return res["answer"]
    if name == "urai_imagine":
        from jev import imagine
        res = imagine.generate(args.get("prompt", ""), args.get("out"),
                               args.get("steps"), args.get("width"),
                               args.get("height"), args.get("seed", 7))
        if not res["ok"]:
            raise RuntimeError(res["error"])
        return json.dumps(res, indent=2)
    if name == "urai_video":
        from jev import video
        res = video.generate(args.get("prompt", ""), args.get("out"),
                             args.get("duration", 4), args.get("width", 512),
                             args.get("height", 512), args.get("fps", 4),
                             args.get("seed", 7), args.get("provider", "auto"))
        if not res.get("ok"):
            raise RuntimeError(res.get("error", "video failed"))
        return json.dumps(res, indent=2)
    if name == "urai_swarm":
        from jev.swarm import run_swarm
        tasks = args.get("tasks", [])
        if isinstance(tasks, str):
            tasks = [tasks]
        return json.dumps(run_swarm(tasks, args.get("max_workers", 3)), indent=2)[:8000]
    if name == "urai_browse":
        from jev import browser as _b
        res = _b.run_steps(args.get("steps", []), goal=args.get("goal", ""))
        return json.dumps(res, indent=2)[:6000]
    if name == "urai_embed":
        from jev.backends import EmbeddingBackend
        be = EmbeddingBackend()
        if not be.healthy():
            raise RuntimeError("embedding server down; run: urai serve start --model embed-small")
        vecs = be.embed(args.get("texts", ""))
        return json.dumps({"model": be.model, "count": len(vecs),
                           "dims": [len(v) for v in vecs]}) + \
            (" (vectors omitted: set full=1)" if not args.get("full") else
             "\n" + json.dumps(vecs)[:8000])
    if name == "urai_model_list":
        from jev import models_registry as reg
        r = reg.load()
        lines = []
        for mid, m in r["models"].items():
            mark = " [active]" if mid == r["active"] else ""
            lines.append(f"{mid}{mark}: {m['params']} {m['quant']} "
                         f"role={m['role']} kind={m.get('kind', 'chat')}")
        return "\n".join(lines)
    if name == "urai_evaluate":
        from jev.agent import run_agent
        exp = [e for e in args.get("expect", "").split(",") if e]
        result = run_agent(args.get("task", ""))
        hits = [e for e in exp if e in result.get("answer", "")]
        return json.dumps({"score": (len(hits) / len(exp)) if exp else None,
                           "hits": hits, **result}, indent=2)[:6000]
    raise ValueError(f"unknown tool: {name}")


def _resp(mid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": mid}
    if error is not None:
        msg["error"] = {"code": -32603, "message": str(error)[:500]}
    else:
        msg["result"] = result
    return msg


def handle(msg):
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        return _resp(mid, {"protocolVersion": "2024-11-05",
                           "capabilities": {"tools": {}},
                           "serverInfo": SERVER_INFO})
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return _resp(mid, {})
    if method == "tools/list":
        return _resp(mid, {"tools": TOOLS})
    if method == "tools/call":
        try:
            text = tool_call(params.get("name", ""), params.get("arguments"))
            return _resp(mid, {"content": [{"type": "text", "text": text}]})
        except Exception as e:
            return _resp(mid, {"content": [{"type": "text",
                                            "text": f"error: {e}"}]})
    return _resp(mid, error=f"unknown method: {method}")


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        out = handle(msg)
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
