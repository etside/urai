#!/usr/bin/env python3
"""jev/sandbox.py — Sandboxed code execution with optional Docker isolation.

execute(source, language='python', capture_images=True)
  → {ok, stdout, stderr, exit_code, duration_s, images: [base64…], language}

Docker path (when available):
  docker run --rm --network none --memory 256m --pids-limit 50
  with a temp-dir volume mount — full network isolation.

Fallback path (always available):
  subprocess in a temp dir (same approach as tools.run_code).

Matplotlib image capture:
  If capture_images=True, we prepend a matplotlib Agg backend switch and
  a plt.savefig hook before running. Any figures saved to /tmp/urai_plot_*.png
  are collected, base64-encoded, and returned in the images list.

No external deps beyond stdlib (matplotlib is optional — if absent, images=[]).
"""
from __future__ import annotations
import ast
import base64
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TIMEOUT_S = int(os.environ.get("JEV_RUN_TIMEOUT", "30"))
OUT_CAP = 8000

# ── Matplotlib image capture preamble ─────────────────────────────────────────

_MPL_PREAMBLE = """\
import os as _os, sys as _sys
try:
    import matplotlib as _mpl
    _mpl.use('Agg')
    import matplotlib.pyplot as _plt
    _orig_show = _plt.show
    _urai_imgs = []
    def _urai_show(*a, **kw):
        _fn = '/tmp/urai_plot_{n}.png'.format(n=len(_urai_imgs))
        _plt.savefig(_fn, bbox_inches='tight')
        _urai_imgs.append(_fn)
        _plt.close('all')
    _plt.show = _urai_show
    import atexit as _atexit
    def _urai_atexit():
        figs = _plt.get_fignums()
        if figs:
            _fn = '/tmp/urai_plot_{n}.png'.format(n=len(_urai_imgs))
            _plt.savefig(_fn, bbox_inches='tight')
            _urai_imgs.append(_fn)
            _plt.close('all')
    _atexit.register(_urai_atexit)
except ImportError:
    pass

"""


def _docker_available() -> bool:
    return bool(shutil.which("docker"))


def _run_docker(src_path: str, tmpdir: str, language: str) -> dict:
    """Run code inside Docker container with network/mem/pid isolation."""
    fname = {"python": "main.py", "javascript": "main.js", "bash": "main.sh"}.get(language, "main.py")
    # Copy file into tmpdir/work/
    work = os.path.join(tmpdir, "work")
    os.makedirs(work, exist_ok=True)
    shutil.copy(src_path, os.path.join(work, fname))

    if language in ("python", "python3"):
        cmd_inner = ["python3", f"/work/{fname}"]
        image = "python:3.11-slim"
    elif language in ("javascript", "js"):
        cmd_inner = ["node", f"/work/{fname}"]
        image = "node:20-slim"
    else:
        cmd_inner = ["bash", f"/work/{fname}"]
        image = "bash:5"

    docker_cmd = [
        "docker", "run", "--rm",
        "--network", "none",
        "--memory", "256m",
        "--pids-limit", "50",
        "-v", f"{work}:/work",
        image,
    ] + cmd_inner

    t0 = time.time()
    try:
        p = subprocess.run(docker_cmd, capture_output=True, text=True,
                           timeout=TIMEOUT_S)
        elapsed = round(time.time() - t0, 3)
        return {
            "ok": p.returncode == 0,
            "stdout": p.stdout[:OUT_CAP],
            "stderr": p.stderr[:2000],
            "exit_code": p.returncode,
            "duration_s": elapsed,
            "via": "docker",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": "", "exit_code": -1,
                "duration_s": TIMEOUT_S, "via": "docker",
                "error": f"timeout after {TIMEOUT_S}s"}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e)[:300],
                "exit_code": -1, "duration_s": round(time.time()-t0, 3),
                "via": "docker", "error": str(e)[:300]}


def _run_subprocess(source: str, language: str, tmpdir: str) -> dict:
    """Subprocess fallback (same approach as tools.run_code)."""
    env = {**os.environ,
           "PYTHONDONTWRITEBYTECODE": "1",
           "HOME": tmpdir,
           "TMPDIR": tmpdir}
    t0 = time.time()
    try:
        if language in ("python", "python3"):
            try:
                ast.parse(source)
            except SyntaxError as e:
                return {"ok": False, "stdout": "", "stderr": f"SyntaxError: {e}",
                        "exit_code": 1, "duration_s": 0.0, "via": "subprocess"}
            src_path = Path(tmpdir) / "main.py"
            src_path.write_text(source)
            cmd = [sys.executable, str(src_path)]
        elif language in ("javascript", "js"):
            src_path = Path(tmpdir) / "main.js"
            src_path.write_text(source)
            cmd = ["node", str(src_path)]
        else:  # bash/sh
            cmd = ["bash", "-c", source]

        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=TIMEOUT_S, cwd=tmpdir, env=env)
        elapsed = round(time.time() - t0, 3)
        return {
            "ok": p.returncode == 0,
            "stdout": p.stdout[:OUT_CAP],
            "stderr": p.stderr[:2000],
            "exit_code": p.returncode,
            "duration_s": elapsed,
            "via": "subprocess",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": "",
                "exit_code": -1, "duration_s": TIMEOUT_S, "via": "subprocess",
                "error": f"timeout after {TIMEOUT_S}s"}
    except FileNotFoundError as e:
        return {"ok": False, "stdout": "", "stderr": str(e),
                "exit_code": -1, "duration_s": round(time.time()-t0, 3),
                "via": "subprocess", "error": f"interpreter not found: {e}"}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e)[:300],
                "exit_code": -1, "duration_s": round(time.time()-t0, 3),
                "via": "subprocess", "error": str(e)[:300]}


def execute(source: str, language: str = "python",
            capture_images: bool = True) -> dict:
    """Execute code in a sandboxed environment.

    Returns:
        {ok, stdout, stderr, exit_code, duration_s, images: [base64_str, …],
         language, via}
    """
    if language not in ("python", "python3", "javascript", "js", "bash", "sh"):
        return {"ok": False, "error": f"unsupported language: {language}",
                "stdout": "", "stderr": "", "exit_code": 1,
                "duration_s": 0.0, "images": [], "language": language}

    # Normalise language name
    lang = "python" if language in ("python", "python3") else \
           "javascript" if language in ("javascript", "js") else "bash"

    # Prepend matplotlib capture preamble for Python
    actual_source = source
    if lang == "python" and capture_images:
        actual_source = _MPL_PREAMBLE + source

    with tempfile.TemporaryDirectory(prefix="urai-sandbox-") as tmpdir:
        # Write source file
        fname = {"python": "main.py", "javascript": "main.js", "bash": "main.sh"}[lang]
        src_path = os.path.join(tmpdir, fname)
        Path(src_path).write_text(actual_source)

        if _docker_available() and lang == "python":
            result = _run_docker(src_path, tmpdir, lang)
        else:
            result = _run_subprocess(actual_source, lang, tmpdir)

        # Collect matplotlib images
        images = []
        if lang == "python" and capture_images:
            for img_path in sorted(glob.glob("/tmp/urai_plot_*.png")):
                try:
                    with open(img_path, "rb") as f:
                        images.append(base64.b64encode(f.read()).decode())
                    os.unlink(img_path)
                except Exception:
                    pass

        result["images"] = images
        result["language"] = lang
        return result
