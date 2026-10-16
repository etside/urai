#!/usr/bin/env python3
"""Urai-local MCP server (stdlib, stdio): read-only VPS introspection.

Exposes Urai internals as MCP tools so any MCP client — including Urai's
own agent via jev/mcp_client.py — can call them. Self-loop entry in
mcp_clients.json proves the consume path end-to-end with zero downloads.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _rows(path, limit=2000):
    try:
        return [json.loads(l) for l in open(path).read().splitlines()
                if l.strip()][:limit]
    except Exception:
        return []


TOOLS = {
    "repo_status": {
        "description": "git status/log of the Urai repo (short)",
        "run": lambda a: _sh(["git", "-C", str(ROOT), "status", "--short"])},
    "dataset_stats": {
        "description": "verified dataset row counts per file",
        "run": lambda a: {"files": {
            p.name: sum(1 for _ in open(p))
            for p in sorted((ROOT / "data" / "verified").glob("*.jsonl"))}}},
    "bench_latest": {
        "description": "latest bench accuracies per category",
        "run": lambda a: _bench()},
    "service_health": {
        "description": "local HTTP health of API + teachers (no secrets)",
        "run": lambda a: _health()},
}


def _sh(argv):
    import subprocess
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=20)
        return {"ok": p.returncode == 0, "output": (p.stdout + p.stderr)[-2000:]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _bench():
    try:
        reps = sorted((ROOT / "eval" / "reports").glob("bench-*.json"))
        d = json.loads(reps[-1].read_text())
        return {"report": reps[-1].name,
                "accuracy": {k: v.get("accuracy")
                             for k, v in d.get("categories", {}).items()}}
    except Exception as e:
        return {"error": str(e)[:150]}


def _health():
    import urllib.request
    out = {}
    for name, url in (("api", "http://127.0.0.1:8777/health"),
                      ("teacher4b", "http://127.0.0.1:8080/health"),
                      ("embed", "http://127.0.0.1:8081/health")):
        try:
            urllib.request.urlopen(url, timeout=5).read()
            out[name] = "ok"
        except Exception as e:
            out[name] = f"down: {str(e)[:60]}"
    return out


def _handle(req: dict):
    rid, method, params = req.get("id"), req.get("method"), req.get("params", {})
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid,
                "result": {"protocolVersion": "2024-11-05",
                           "serverInfo": {"name": "urai-local", "version": "1"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": [
            {"name": n, "description": t["description"], "inputSchema": {"type": "object"}}
            for n, t in TOOLS.items()]}}
    if method == "tools/call":
        name = params.get("name", "")
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32601, "message": f"unknown tool: {name}"}}
        try:
            res = TOOLS[name]["run"](params.get("arguments", {}))
            return {"jsonrpc": "2.0", "id": rid,
                    "result": {"content": [{"type": "text",
                                            "text": json.dumps(res)[:4000]}]}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32603, "message": str(e)[:200]}}
    if method and method.startswith("notifications/"):
        return None
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": f"unknown method: {method}"}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            resp = _handle(json.loads(line))
        except Exception as e:
            resp = {"jsonrpc": "2.0", "id": None,
                    "error": {"code": -32700, "message": str(e)[:150]}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
