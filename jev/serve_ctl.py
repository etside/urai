#!/usr/bin/env python3
"""llama-server lifecycle for the JEV CLI (stdlib only).

  jev serve start [--model ID] [--ctx N] [--port P]
  jev serve stop
  jev serve status

Auto: picks active registry model, thread count, ctx, and --n-gpu-layers
from gpu.offload_policy(). Restarts replace the running server.
"""

import os
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "third_party" / "llama.cpp" / "build" / "bin"
PIDFILE = Path("/tmp/jev-llama-server.pid")


def _lib_env():
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = str(BIN) + ":" + env.get("LD_LIBRARY_PATH", "")
    return env


def is_up(port=8080):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5)
        return True
    except Exception:
        return False


def start(model_path, ctx=2048, threads=None, port=8080, ngl=None):
    from .gpu import offload_policy
    if ngl is None:
        ngl = offload_policy()["ngl"]
    threads = threads or max(1, (os.cpu_count() or 4) - 1)
    stop()
    cmd = [str(BIN / "llama-server"), "-m", model_path, "-c", str(ctx),
           "-t", str(threads), "--port", str(port),
           "--n-gpu-layers", str(ngl)]
    log = open("/tmp/jev-llama-server.log", "ab")
    p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, env=_lib_env(),
                         start_new_session=True)
    PIDFILE.write_text(str(p.pid))
    for _ in range(60):
        if is_up(port):
            return {"ok": True, "pid": p.pid, "port": port,
                    "ngl": ngl, "threads": threads, "ctx": ctx}
        time.sleep(2)
    return {"ok": False, "error": "server did not become healthy; see /tmp/jev-llama-server.log"}


def stop():
    if PIDFILE.exists():
        try:
            os.kill(int(PIDFILE.read_text().strip()), signal.SIGTERM)
        except Exception:
            pass
        PIDFILE.unlink(missing_ok=True)
    subprocess.run(["pkill", "-f", "llama-server"], capture_output=True)
    return {"ok": True}
