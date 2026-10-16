#!/usr/bin/env python3
"""MCP client: consume external MCP servers from Urai (stdlib only).

Transport: JSON-RPC 2.0 over stdio (newline-delimited). Works with any
MCP server binary (npx, uvx, docker, native): configured in
mcp_clients.json: {"servers": {"github": {"cmd": ["npx","-y","..."], "enabled": true}}}.

Urai already SERVES tools (jev/mcp_server.py); this lets the agent also
CALL outside tools — the missing half of harness-grade MCP.
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "mcp_clients.json"
TIMEOUT_S = 60


def load_config() -> dict:
    try:
        return json.loads(CONFIG.read_text())
    except Exception:
        return {"servers": {}}


def save_config(cfg: dict):
    CONFIG.write_text(json.dumps(cfg, indent=2) + "\n")


class MCPClient:
    def __init__(self, cmd):
        self.cmd = cmd
        self.proc = None
        self._id = 0

    def __enter__(self):
        self.proc = subprocess.Popen(
            self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {}, "clientInfo": {"name": "urai", "version": "1"}})
        self._notify("notifications/initialized", {})
        return self

    def __exit__(self, *a):
        try:
            if self.proc:
                self.proc.terminate()
                self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass

    def _send(self, obj: dict):
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def _recv(self) -> dict:
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("MCP server closed stdout")
        return json.loads(line)

    def _rpc(self, method: str, params: dict):
        self._id += 1
        rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        while True:
            msg = self._recv()
            if msg.get("id") == rid:
                if "error" in msg:
                    raise RuntimeError(f"MCP error: {msg['error']}")
                return msg.get("result", {})
            # ignore async notifications while waiting

    def _notify(self, method: str, params: dict):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def list_tools(self) -> list:
        return self._rpc("tools/list", {}).get("tools", [])

    def call_tool(self, name: str, args: dict):
        return self._rpc("tools/call", {"name": name, "arguments": args or {}})


def _server_cmd(name: str) -> list:
    srv = (load_config().get("servers") or {}).get(name, {})
    if not srv.get("enabled", False):
        raise RuntimeError(f"MCP server '{name}' not configured/enabled "
                           f"(see mcp_clients.json)")
    cmd = srv.get("cmd") or []
    if not cmd:
        raise RuntimeError(f"MCP server '{name}' has no cmd")
    return cmd


def list_server_tools(server: str = "") -> dict:
    if server:
        names = [server]
    else:
        names = [n for n, s in (load_config().get("servers") or {}).items()
                 if s.get("enabled")]
    out = {}
    for name in names:
        try:
            with MCPClient(_server_cmd(name)) as c:
                out[name] = [{"name": t.get("name"),
                              "description": (t.get("description") or "")[:160]}
                             for t in c.list_tools()]
        except Exception as e:
            out[name] = {"error": str(e)[:200]}
    return {"ok": True, "servers": out}


def call_server_tool(server: str = "", tool: str = "", args=None) -> dict:
    try:
        with MCPClient(_server_cmd(server)) as c:
            res = c.call_tool(tool, dict(args or {}))
        return {"ok": True, "server": server, "tool": tool, "result": res}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
