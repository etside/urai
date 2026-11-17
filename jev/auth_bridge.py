"""Use urai-router as the credential-routing authority for Urai services.

This is a thin caller: it asks `urai-router auth use <service> --json` which
credential profile is available/active. It never reads, stores or prints a
secret value itself. If urai-router is not installed, callers get an honest
`available:false` instead of an exception.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _router() -> tuple[list[str], str | None]:
    exe = shutil.which("urai-router")
    if exe:
        return [exe], None
    candidates = [
        os.environ.get("URAI_ROUTER_DIR", ""),
        str(Path.home() / "urai-router"),
        "/root/urai-router",
        "/home/reeha/urai-router",
    ]
    for directory in candidates:
        if directory and (Path(directory) / "urai_router" / "__init__.py").is_file():
            return ["python3", "-m", "urai_router"], directory
    return [], None


def call(*parts: str) -> dict[str, Any]:
    base, cwd = _router()
    if not base:
        return {"ok": False, "available": False, "error": "urai-router not found (set URAI_ROUTER_DIR)"}
    try:
        proc = subprocess.run(
            [*base, *parts], cwd=cwd, capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "available": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        payload = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError):
        payload = None
    if payload is None:
        return {
            "ok": False, "available": False,
            "error": (proc.stderr or proc.stdout or f"urai-router exited {proc.returncode}").strip()[:500],
        }
    payload["available"] = bool(payload.get("ok", payload.get("profiles")))
    return payload


def use(service: str, preferred: str | None = None) -> dict[str, Any]:
    args = ["auth", "use", service, "--json"]
    if preferred:
        args += ["--preferred", preferred]
    result = call(*args)
    result["service"] = service
    if not result.get("available") and service == "colab":
        # Routing needs more credentials: tell the caller exactly how to add
        # another Google account instead of failing opaquely.
        result["next_profile"] = "colab-oauth-2"
        result["launch_hint"] = "urai-router auth launch colab-oauth-2  # opens Google sign-in in your browser"
    return result


def status() -> dict[str, Any]:
    return call("auth", "status", "--json")
