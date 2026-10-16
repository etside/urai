#!/usr/bin/env python3
"""Urai offline smoke test — no weights, servers, keys or network needed.

Checks: registry loads (chat+vision+generate kinds), CLI surface
(see/imagine/version/teacher/model/serve/api), server routes, agent +
verifier + distill imports, no secrets in repo.

    python3 scripts/smoke_urai.py            # full (CI, VPS, GPU boxes)
    python3 scripts/smoke_urai.py --offline  # device-safe: no network,
                                             # no subprocesses (rule: no
                                             # heavy work on the small box —
                                             # heavy runs live on the VPS
                                             # and GitHub Actions)
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
    offline = "--offline" in sys.argv  # device-safe: no network, no subprocesses
    import jev
    check("version", jev.VERSION == "v2", getattr(jev, "VERSION", None))

    from jev import models_registry as reg
    r = reg.load()
    kinds = {m.get("kind", "chat") for m in r["models"].values()}
    check("registry kinds", kinds == {"chat", "vision", "generate", "embedding"}, str(kinds))
    check("vision files", len(r["models"]["qwen25vl-3b"].get("files", [])) == 2)
    check("sd-turbo entry", r["models"]["sd-turbo"]["kind"] == "generate")
    check("embed-small entry", r["models"]["embed-small"]["kind"] == "embedding")

    import jev.vision, jev.imagine, jev.server, jev.agent, jev.router
    from jev.backends import EmbeddingBackend
    from jev.agent import extract_tool_calls, run_tool_call
    from jev.tools import web_search, web_fetch
    check("vision+imagine+embed+tools import", True)
    check("tool parse+exec", run_tool_call(
        extract_tool_calls('x\n```tool\n{"tool": "run", "args": {"argv": ["git", "status"]}}\n```')[0]
    ).get("ok") in (True, False))  # executes (ok) or refuses cleanly
    ws = {"ok": True, "output": "offline-skip"} if offline else web_search("test", top=1)
    check("web_search live", ws["ok"] and len(ws["output"]) > 0, ws["output"][:80])
    check("web_fetch ssrf guard",
          web_fetch("http://127.0.0.1:9/").get("ok") is False)
    import scripts.learn.ingest as _ing  # noqa - import check only
    from jev.skills import all_skills, match as skills_match
    check("skills load", len(all_skills()) >= 3,
          str([s["name"] for s in all_skills()]))
    check("skills match", any(s["name"] == "webapp-testing" for s in
                              skills_match("test the webapp login page")))
    check("learn docs+scripts", (ROOT / "docs" / "LEARN.md").is_file()
          and (ROOT / "scripts" / "learn" / "ingest.py").is_file()
          and (ROOT / "scripts" / "learn" / "render.py").is_file())
    bad = jev.vision.see("/nonexistent/x.png", "hi?")
    check("vision bad-path guard", not bad["ok"] and "error" in bad, str(bad)[:80])
    st = jev.imagine.status()
    check("imagine status shape", set(st) >= {"runner_built", "checkpoint_ready"})
    if offline:
        check("imagine generate (offline-skip)", True)
    else:
        gen = jev.imagine.generate("test prompt")
        check("imagine missing-runner guard", not gen["ok"], str(gen)[:80])

    src = (ROOT / "jev" / "server.py").read_text()
    for route in ["/v1/chat/completions", "/v1/models", "/v1/images/generations", "/see", "/imagine"]:
        check(f"server route {route}", route in src)
    for feat in ["do_OPTIONS", "_needs_key", "URAI_API_KEY", "/v1/completions",
                 "/v1/embeddings", "b64_json", "_static", "Access-Control-Allow-Origin"]:
        check(f"server hosting {feat}", feat in src)
    check("webapp exists", (ROOT / "jev" / "static" / "app.html").is_file())
    for f in ["Dockerfile", "docker/docker-compose.yml", "docker/entrypoint.sh",
              "deploy/urai-api.service", "deploy/Caddyfile"]:
        check(f"hosting file {f}", (ROOT / f).is_file())

    for args, needle in [
        (["--help"], "imagine"), (["version"], "urai v2"),
        (["teacher", "status"], "base"), (["model", "list"], "qwen25vl-3b"),
        (["model", "list"], "embed-small"),
        (["see", "/nonexistent.png"], None),
        (["imagine", "a red ball"], "ok"),
        (["embed", "hello"], "embedding server down"),
    ]:
        if offline:
            check("cli surface (offline-skip)", True)
            break
        _, out = run_cli(*args)
        ok = True if needle is None else (needle in out)
        if list(args) == ["embed", "hello"]:
            # embed server up (dims vector) and down (message) both pass
            ok = ("embedding server down" in out) or ('"dims"' in out)
        check(f"cli {' '.join(args)}", ok, out[:100])

    # no secrets in tracked files
    import subprocess as sp
    tracked = sp.run(["git", "ls-files"], capture_output=True, text=True, cwd=str(ROOT)).stdout.split()
    leaked = [f for f in tracked
              if f.endswith((".gguf", ".safetensors", ".key", ".pem"))
              or "api_key" in f.lower() or "secret" in f.lower()]
    check("no secrets/binaries tracked", not leaked, str(leaked))

    check_understanding()

    print(f"\n{len(FAIL)} failure(s)" if FAIL else "\nall smoke checks passed")
    return 1 if FAIL else 0


def check_understanding():
    """Offline assertions for the NLP / vibe / profile / retrieval pillars.

    Deterministic and network-free: the embedding path is forced to its
    hashed bag-of-words fallback by pointing URAI_EMBED_URL at a dead port.
    """
    import importlib
    import os
    import tempfile

    os.environ["URAI_EMBED_URL"] = "http://127.0.0.1:9"

    from jev import nlp as _nlp, vibe as _vibe, retrieval as _ret
    a = _nlp.analyze("this is broken and I'm frustrated, fix asap")
    check("nlp sentiment negative", a["sentiment"]["label"] == "negative",
          str(a["sentiment"]))
    check("nlp intent debug", a["intent"] == "debug", a["intent"])
    check("nlp language en", a["language"] == "en", a["language"])
    check("nlp redflags empty for benign text", a["redflags"] == [], str(a["redflags"]))

    v = _vibe.plan_for("thanks, great work")
    check("vibe plan has nlp", "sentiment" in v.get("nlp", {}))
    check("vibe renders directive", "Style contract" in v.get("directive", ""),
          v.get("directive", "")[:80])
    check("vibe positive -> warm", v.get("warmth", 0) > 0.5, str(v.get("warmth")))

    docs = ["heap memory leak in C++ allocation", "how to bake sourdough bread"]
    rows = _ret.rank("heap memory leak", docs, top=2)
    check("retrieval ranks relevant first", bool(rows) and rows[0]["text"] == docs[0],
          str([r["text"] for r in rows]))
    hv = _ret.hash_vector("heap memory leak")
    check("retrieval hash vector normalised",
          abs(sum(x * x for x in hv) - 1.0) < 1e-6)

    with tempfile.TemporaryDirectory() as td:
        os.environ["URAI_PROFILES"] = os.path.join(td, "profiles.json")
        from jev import profile as _prof
        importlib.reload(_prof)
        r = _prof.set_pref("ci-user", "warmth", 0.9)
        check("profile set_pref", r.get("ok") and
              _prof.get("ci-user").get("warmth") == 0.9, str(r))
        _prof.observe("ci-user", {}, targets={"warmth": 0.1})
        check("profile observe nudges", "warmth" in _prof.get("ci-user"),
              str(_prof.get("ci-user")))
        bad = _prof.set_pref("ci-user", "not_a_field", 1)
        check("profile rejects bad key", bad.get("ok") is False, str(bad))


if __name__ == "__main__":
    sys.exit(main())
