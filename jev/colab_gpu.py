"""Optional Google Colab GPU wrapper for Urai.

Thin, safe wrapper over the official `colab` CLI (google-colab-cli). It never
builds shell strings, never stores credentials, and reports `available:false`
instead of failing when the CLI is absent or unauthenticated.

All remote execution is explicit: this module never provisions a runtime on
import, and never calls `colab stop` unless asked.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

DEFAULT_TIMEOUT = 600  # seconds; provisioning can take a couple of minutes


def binary() -> str | None:
    return shutil.which("colab")


def _run(args: list[str], timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    exe = binary()
    if not exe:
        return {"ok": False, "error": "colab CLI not found on PATH — see docs/COLAB_GPU.md"}
    try:
        proc = subprocess.run(
            [exe, *[str(a) for a in args]],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"colab {args[0] if args else ''} timed out after {timeout}s"}
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    result: dict[str, Any] = {"ok": proc.returncode == 0, "code": proc.returncode,
                              "args": args, "stdout": out[-4000:]}
    if err:
        result["stderr"] = err[-2000:]
    if proc.returncode != 0 and not err:
        result["error"] = out[-1000:] or f"colab exited {proc.returncode}"
    return result


def status() -> dict[str, Any]:
    exe = binary()
    result: dict[str, Any] = {
        "available": exe is not None,
        "bin": exe,
        "version": None,
        "sessions": None,
        "auth_hint": None,
    }
    if not exe:
        result["auth_hint"] = "pip install google-colab-cli (see docs/COLAB_GPU.md)"
        return result
    ver = _run(["version"], timeout=60)
    result["version"] = ver.get("stdout") or ver.get("error")
    ses = _run(["sessions"], timeout=120)
    result["sessions"] = ses.get("stdout") if ses.get("ok") else None
    if not ses.get("ok") or "sign in" in (ses.get("stdout") or "").lower():
        result["auth_hint"] = "run `colab usage` once and complete the Google OAuth sign-in"

    # Ask urai-router which Colab credential profile is active/available.
    # It is the routing authority; this wrapper only reports what it says.
    try:
        from jev.auth_bridge import use as router_use
        result["router"] = router_use("colab")
    except Exception as exc:  # optional integration must never break status
        result["router"] = {"available": False, "error": f"{type(exc).__name__}: {exc}"}
    return result


def new(session: str, gpu: str | None = None, tpu: str | None = None,
        high_mem: bool = False) -> dict[str, Any]:
    args = ["new", "-s", session]
    if gpu:
        args += ["--gpu", gpu]
    if tpu:
        args += ["--tpu", tpu]
    if high_mem:
        args.append("--high-mem")
    return _run(args)


def run(script: str, gpu: str | None = None, script_args: list[str] | None = None,
        keep: bool = False) -> dict[str, Any]:
    args = ["run"]
    if gpu:
        args += ["--gpu", gpu]
    if keep:
        args.append("--keep")
    args.append(script)
    if script_args:
        args += ["--", *[str(a) for a in script_args]]
    return _run(args, timeout=DEFAULT_TIMEOUT)


def execute(script: str, session: str | None = None) -> dict[str, Any]:
    args = ["exec"]
    if session:
        args += ["-s", session]
    args += ["-f", script]
    return _run(args)


def upload(session: str, local: str, remote: str) -> dict[str, Any]:
    return _run(["upload", "-s", session, local, remote])


def download(session: str, remote: str, local: str) -> dict[str, Any]:
    return _run(["download", "-s", session, remote, local])


def stop(session: str) -> dict[str, Any]:
    return _run(["stop", "-s", session], timeout=120)


def usage() -> dict[str, Any]:
    return _run(["usage"], timeout=120)


def cli(action: str, *values: str | None) -> int:
    """JSON CLI for `urai colab ...`. Values are positional and never shell-parsed."""
    v = [x for x in values if x is not None]
    try:
        if action == "status":
            result = status()
        elif action == "new":
            result = new(v[0], gpu=(v[1] if len(v) > 1 else None))
        elif action == "run":
            result = run(v[0], gpu=(v[1] if len(v) > 1 else None), script_args=v[2:])
        elif action == "exec":
            result = execute(v[0], session=(v[1] if len(v) > 1 else None))
        elif action == "upload":
            result = upload(v[0], v[1], v[2])
        elif action == "download":
            result = download(v[0], v[1], v[2])
        elif action == "stop":
            result = stop(v[0])
        elif action == "usage":
            result = usage()
        else:
            result = {"ok": False, "error": f"unknown action: {action}"}
    except (ValueError, IndexError) as exc:
        result = {"ok": False, "error": f"missing argument for {action}: {exc}"}
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok", result.get("available", True)) else 1
