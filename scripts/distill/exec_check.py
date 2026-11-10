#!/usr/bin/env python3
"""Execution check: run candidate Python blocks, don't just compile them.

Safety (prototype-grade, documented limits):
  - each block runs in its own temp dir, `timeout 20`, minimal env
  - wall-clock + CPU bounded; stdout/stderr captured (4 KB cap)
  - NOT a real sandbox: no seccomp/network namespace. Treat as
    untrusted-code runner for OUR OWN pipeline only, never for arbitrary
    user uploads. On a shared box, run under a dedicated uid / container.

Pass rule: the block must execute with exit 0 AND every module-level
`assert` must hold AND every zero-arg `test_*` function must run clean.
"""

import os
import subprocess
import sys
import tempfile
import textwrap

TIMEOUT_S = 20
OUT_CAP = 4096

HARNESS_TAIL = """

# --- ownai exec harness: run zero-arg test_* functions ---
import traceback as _tb
_failures = []
for _name in sorted(dir()):
    if _name.startswith("test_") and callable(eval(_name)):
        try:
            eval(_name)()
        except Exception:
            _failures.append((_name, _tb.format_exc(limit=3)))
if _failures:
    print("HARNESS-FAILURES:", [n for n, _ in _failures])
    raise SystemExit(1)
"""


def run_block(code: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="ownai-exec-") as td:
        path = os.path.join(td, "candidate.py")
        with open(path, "w") as f:
            f.write(textwrap.dedent(code) + "\n" + HARNESS_TAIL)
        try:
            p = subprocess.run(
                [sys.executable, path],
                capture_output=True, text=True, timeout=TIMEOUT_S,
                cwd=td, env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
            )
            ok = p.returncode == 0
            err = "" if ok else (p.stderr or p.stdout or f"exit={p.returncode}")[-OUT_CAP:]
            return {"ran": True, "passed": ok, "error": err,
                    "stdout": (p.stdout or "")[-OUT_CAP:]}
        except subprocess.TimeoutExpired:
            return {"ran": True, "passed": False,
                    "error": f"timeout after {TIMEOUT_S}s", "stdout": ""}
        except Exception as e:
            return {"ran": False, "passed": False, "error": f"runner: {e}", "stdout": ""}
