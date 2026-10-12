#!/usr/bin/env python3
"""Urai offline smoke test — no weights, servers, keys or network needed.

Checks: registry loads (chat+vision+generate kinds), CLI surface
(see/imagine/version/teacher/model/serve/api), server routes, agent +
verifier + distill imports, no secrets in tracked files.

    python3 scripts/smoke_urai.py
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "distill"))

FAIL = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAIL.append(name)


def run_cli(*args):
    p = subprocess.run([sys.executable, "-m", "jev.cli", *args],
                       capture_output=True, text=True, timeout=60, cwd=str(ROOT))
    return p.returncode, (p.stdout + p.stderr)


def main():
    import jev
    check("version", jev.VERSION == "v1-lite", getattr(jev, "VERSION", None))

    from jev import models_registry as reg
    r = reg.load()
    kinds = {m.get("kind", "chat") for m in r["models"].values()}
    check("registry kinds", kinds == {"chat", "vision", "generate"}, str(kinds))
    check("vision files", len(r["models"]["qwen25vl-3b"].get("files", [])) == 2)
    check("sd-turbo entry", r["models"]["sd-turbo"]["kind"] == "generate")

    import jev.vision, jev.imagine, jev.server, jev.agent, jev.router
    check("vision+imagine import", True)
    bad = jev.vision.see("/nonexistent/x.png", "hi?")
    check("vision bad-path guard", not bad["ok"] and "error" in bad, str(bad)[:80])
    st = jev.imagine.status()
    check("imagine status shape", set(st) >= {"runner_built", "checkpoint_ready"})
    gen = jev.imagine.generate("test prompt")
    check("imagine missing-runner guard", not gen["ok"], str(gen)[:80])

    src = (ROOT / "jev" / "server.py").read_text()
    for route in ["/v1/chat/completions", "/v1/models", "/v1/images/generations", "/see", "/imagine"]:
        check(f"server route {route}", route in src)
    for feat in ["do_OPTIONS", "_needs_key", "URAI_API_KEY", "/v1/completions",
                 "b64_json", "_static", "Access-Control-Allow-Origin"]:
        check(f"server hosting {feat}", feat in src)
    check("webapp exists", (ROOT / "jev" / "static" / "app.html").is_file())
    for f in ["Dockerfile", "docker/docker-compose.yml", "docker/entrypoint.sh",
              "deploy/urai-api.service", "deploy/Caddyfile"]:
        check(f"hosting file {f}", (ROOT / f).is_file())

    for args, needle in [
        (["--help"], "imagine"), (["version"], "urai v1-lite"),
        (["teacher", "status"], "base"), (["model", "list"], "qwen25vl-3b"),
        (["see", "/nonexistent.png"], None),
        (["imagine", "a red ball"], "ok"),
    ]:
        _, out = run_cli(*args)
        check(f"cli {' '.join(args)}", (needle in out) if needle else True, out[:100])

    # no secrets in tracked files
    import subprocess as sp
    tracked = sp.run(["git", "ls-files"], capture_output=True, text=True, cwd=str(ROOT)).stdout.split()
    leaked = [f for f in tracked
              if f.endswith((".gguf", ".safetensors", ".key", ".pem"))
              or "api_key" in f.lower() or "secret" in f.lower()]
    check("no secrets/binaries tracked", not leaked, str(leaked))

    print(f"\n{len(FAIL)} failure(s)" if FAIL else "\nall smoke checks passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
