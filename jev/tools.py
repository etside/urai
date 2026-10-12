#!/usr/bin/env python3
"""Tool engine: filesystem, terminal, git — jailed and allowlisted.

  - File reads confined under JEV_WORKSPACE (default: cwd).
  - Shell: allowlist of read-only/safe commands; everything else refused.
    No shell=True; argv-based; timeout-guarded.
  - Git: read-only subcommands only (status/log/diff/show).

Every call returns {"ok", "output"|"error"}. All executions are logged
to the agent trace by agent.py.
"""

import os
import subprocess

WORKSPACE = os.path.realpath(os.environ.get("JEV_WORKSPACE", os.getcwd()))
TIMEOUT_S = 30
OUT_CAP = 8000

SAFE_BINARIES = {"ls", "cat", "head", "tail", "wc", "grep", "rg", "find",
                 "git", "python3", "node", "npm", "lsblk", "df", "free",
                 "du", "sed", "awk", "sort", "uniq", "diff", "file",
                 "pytest", "ruff", "tsc", "cargo"}
GIT_SAFE = {"status", "log", "diff", "show", "branch", "rev-parse"}
BLOCKED_RE = ("rm ", "mv ", "dd ", ">", "mkfs", ":(){", "chmod 777")


def _jail(path: str) -> str:
    real = os.path.realpath(os.path.join(WORKSPACE, path))
    if real != WORKSPACE and not real.startswith(WORKSPACE + os.sep):
        raise PermissionError(f"path escapes workspace: {path}")
    return real


def read_file(path: str, max_chars: int = 12000) -> dict:
    try:
        with open(_jail(path)) as f:
            data = f.read(max_chars + 1)
        truncated = len(data) > max_chars
        return {"ok": True, "output": data[:max_chars], "truncated": truncated}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def run_cmd(argv: list) -> dict:
    if not argv or argv[0] not in SAFE_BINARIES:
        return {"ok": False, "error": f"binary not allowlisted: {argv[0] if argv else None}"}
    joined = " ".join(argv)
    if any(b in joined for b in BLOCKED_RE):
        return {"ok": False, "error": "blocked pattern in command"}
    if argv[0] == "git" and len(argv) > 1 and argv[1] not in GIT_SAFE:
        return {"ok": False, "error": f"git subcommand not read-only-safe: {argv[1]}"}
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           timeout=TIMEOUT_S, cwd=WORKSPACE)
        out = (p.stdout + p.stderr)[-OUT_CAP:]
        return {"ok": p.returncode == 0, "output": out,
                "error": None if p.returncode == 0 else out}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {TIMEOUT_S}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


TOOLS = {"read_file": read_file, "run": run_cmd}
