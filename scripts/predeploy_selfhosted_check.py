#!/usr/bin/env python3
"""Predeploy self-hosted integrity gate (stdlib only).

Fails unless the public Urai surface is served by the local llama.cpp runtime
and no default path can silently proxy chat to another provider's model.

Checks
  1. model/registry.json has a local GGUF path for the active chat model
  2. the public model surface is exactly ``urai`` and ``cyberurai``
  3. every internal/legacy id folds into one of those two public ids
  4. default routing never selects TeacherAPIBackend, even when TEACHER_* is set
  5. /health, /v1/models and /v1/capabilities advertise self-hosted provenance
  6. deploy units / Procfile do not enable a teacher or external LLM endpoint
  7. optional: the active GGUF and llama-server binary exist on the host

Usage
  python3 scripts/predeploy_selfhosted_check.py
  python3 scripts/predeploy_selfhosted_check.py --require-weights --require-engine
  python3 scripts/predeploy_selfhosted_check.py --json /tmp/urai-gate.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PUBLIC = ("urai", "cyberurai")
FORBIDDEN_ENV = ("TEACHER_BASE_URL", "TEACHER_API_KEY", "TEACHER_MODEL",
                 "URAI_ALLOW_TEACHER")

_checks = []
_failures = []


def _record(name, fn):
    try:
        detail = fn()
    except Exception as e:  # noqa: BLE001 - report any gate failure, never crash
        msg = f"{type(e).__name__}: {e}"
        _checks.append({"check": name, "ok": False, "detail": msg})
        _failures.append(name)
    else:
        _checks.append({"check": name, "ok": True, "detail": detail or ""})


def _env_override(**values):
    old = {k: os.environ.get(k) for k in values}
    for k, v in values.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return old


def _env_restore(old):
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def check_registry(require_weights):
    reg_path = ROOT / "model" / "registry.json"
    assert reg_path.is_file(), f"missing {reg_path}"
    reg = json.loads(reg_path.read_text())
    active = reg.get("active")
    assert active, "registry.active is missing"
    entry = (reg.get("models") or {}).get(active)
    assert isinstance(entry, dict), f"active entry missing for {active!r}"
    path = str(entry.get("path") or "")
    assert path, f"{active}: path is missing"
    assert "://" not in path, f"{active}: path is a remote URL ({path})"
    assert path.startswith("model/"), f"{active}: path is outside model/ ({path})"
    assert entry.get("kind", "chat") in ("chat", "vision"), \
        f"{active}: unsupported kind {entry.get('kind')!r}"
    if require_weights:
        f = ROOT / path
        assert f.is_file(), f"weights not on host: {path}"
        assert f.stat().st_size > 1_000_000, f"weights look too small: {path}"
    return {"active": active, "path": path, "kind": entry.get("kind", "chat"),
            "weights_present": (ROOT / path).is_file()}


def check_brand():
    from jev import brand
    assert tuple(brand.PUBLIC) == PUBLIC, \
        f"public ids changed: {brand.PUBLIC!r}"
    listed = [m["id"] for m in brand.brand_list(True)]
    assert listed == list(PUBLIC), f"/v1/models would list {listed!r}"
    aliases = ("qwen3-4b", "qwen3-17b", "laya", "jev-local-student", "local",
               "auto", "urai-fast", "urai-ultra", "urai-cyber", "cyberurai-v1")
    for alias in aliases:
        got = brand.brand_id(alias)
        assert got in PUBLIC, f"internal id {alias!r} leaked as {got!r}"
    for model in brand.brand_list(True):
        assert model.get("self_hosted") is True, \
            f"{model['id']}: self_hosted is not True"
        assert model.get("external_fallback") is False, \
            f"{model['id']}: external_fallback is not False"
    return {"public": list(PUBLIC), "aliases_folded": len(aliases)}


def check_router_gate():
    from jev import router
    from jev.backends import LlamaServerBackend, TeacherAPIBackend

    original = LlamaServerBackend.healthy
    LlamaServerBackend.healthy = lambda self: True  # pretend local is up
    try:
        old = _env_override(
            TEACHER_BASE_URL="https://gate.invalid/v1",
            TEACHER_API_KEY="gate-dummy-key-not-used",
            TEACHER_MODEL="gate-dummy-model",
            URAI_ALLOW_TEACHER=None,
        )
        try:
            assert router.teacher_allowed() is False, \
                "teacher opt-in is on by default"
            seen = []
            for level in range(5):
                backend, _verify, _fallback = router.pick_backend(level)
                seen.append(f"L{level}:{backend.name}")
                assert not isinstance(backend, TeacherAPIBackend), \
                    f"L{level} selected teacher-api without opt-in"
                assert backend.name == "llama-local", \
                    f"L{level} selected non-local backend {backend.name!r}"
        finally:
            _env_restore(old)

        old = _env_override(URAI_ALLOW_TEACHER="1")
        try:
            assert router.teacher_allowed() is True, \
                "URAI_ALLOW_TEACHER=1 did not enable the offline teacher"
            backend, _verify, _fallback = router.pick_backend(4)
            assert backend.name == "teacher-api", \
                "opt-in control did not reach teacher-api"
        finally:
            _env_restore(old)
    finally:
        LlamaServerBackend.healthy = original
    return {"default": seen, "opt_in": "URAI_ALLOW_TEACHER=1"}


def check_server_surface():
    from jev import server
    from jev.backends import LlamaServerBackend, TeacherAPIBackend

    original = server.LlamaServerBackend.healthy
    server.LlamaServerBackend.healthy = lambda self: True
    try:
        models = server._models()
        ids = [m["id"] for m in models]
        assert ids == list(PUBLIC), f"/v1/models returned {ids!r}"

        caps = server._capabilities()
        dep = caps.get("deployment") or {}
        assert dep.get("self_hosted") is True, "capabilities: self_hosted missing"
        assert dep.get("external_fallback") is False, \
            "capabilities: external fallback is enabled"
        assert dep.get("public_models") == list(PUBLIC), \
            "capabilities: public_models mismatch"
        assert dep.get("inference") == "llama.cpp", \
            "capabilities: inference engine is not llama.cpp"
        weights = dep.get("weights") or {}
        assert weights.get("local") is True, \
            "capabilities: active weights are not local"
        features = [str(f).lower() for f in caps.get("features", [])]
        assert not any("cloud fallback" in f for f in features), \
            "capabilities still advertises a cloud fallback"
        assert any("self-hosted" in f for f in features), \
            "capabilities does not advertise self-hosted inference"

        local = LlamaServerBackend()
        external = TeacherAPIBackend.__new__(TeacherAPIBackend)
        assert server._backend_meta(local).get("self_hosted") is True
        assert server._backend_meta(external).get("self_hosted") is False
        assert server._backend_meta(external).get("origin") == "external"
    finally:
        server.LlamaServerBackend.healthy = original
    return {"models": ids, "inference": "llama.cpp"}


def check_deploy_env():
    candidates = [ROOT / "Procfile", ROOT / "Dockerfile"]
    for pattern in ("deploy/**/*.service", "deploy/**/*.yml",
                    "deploy/**/*.yaml", "deploy/**/*.sh",
                    "config/*.json", ".github/workflows/deploy*.yml"):
        candidates.extend(ROOT.glob(pattern))
    seen, flagged = [], []
    for f in sorted(set(candidates)):
        if not f.is_file():
            continue
        seen.append(str(f.relative_to(ROOT)))
        for lineno, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            for key in FORBIDDEN_ENV:
                if not (s.startswith(key + "=") or f" {key}=" in s):
                    continue
                if key == "URAI_ALLOW_TEACHER" and s.endswith(("=0", "=false",
                                                              "=no", "=off")):
                    continue
                flagged.append(f"{f.relative_to(ROOT)}:{lineno}: {key}")
    assert not flagged, "external model config found: " + "; ".join(flagged)

    for key in ("OPENAI_BASE_URL", "ANTHROPIC_BASE_URL", "TEACHER_BASE_URL"):
        assert not os.environ.get(key), \
            f"{key} is set in the deploy environment"
    return {"files_scanned": len(seen)}


def check_engine():
    binary = ROOT / "third_party" / "llama.cpp" / "build" / "bin" / "llama-server"
    assert binary.is_file(), f"llama-server not built: {binary}"
    assert os.access(binary, os.X_OK), f"llama-server not executable: {binary}"
    return {"engine": str(binary.relative_to(ROOT))}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Urai self-hosted predeploy gate")
    ap.add_argument("--require-weights", action="store_true",
                    help="fail unless the active GGUF exists on this host")
    ap.add_argument("--require-engine", action="store_true",
                    help="fail unless llama-server is built on this host")
    ap.add_argument("--json", default="", help="write the JSON report here")
    args = ap.parse_args(argv)

    _record("registry is local", lambda: check_registry(args.require_weights))
    _record("public surface is urai/cyberurai", check_brand)
    _record("routing never proxies by default", check_router_gate)
    _record("server advertises self-hosted", check_server_surface)
    _record("deploy cannot enable a teacher", check_deploy_env)
    if args.require_engine:
        _record("llama-server is built", check_engine)

    report = {
        "ok": not _failures,
        "root": str(ROOT),
        "public_models": list(PUBLIC),
        "failures": _failures,
        "checks": _checks,
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.json:
        Path(args.json).write_text(text + "\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
