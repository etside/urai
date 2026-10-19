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
EMB_PIDFILE = Path("/tmp/urai-embed-server.pid")
EMB_PORT = 8081


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


def start(model_path, ctx=None, threads=None, port=8080, ngl=None,
          mmproj=None, spec=None):
    from .gpu import offload_policy
    if ctx is None:
        ctx = int(os.environ.get("URAI_CTX", "8192"))
    if ngl is None:
        ngl = offload_policy()["ngl"]
    threads = threads or max(1, (os.cpu_count() or 4) - 1)
    stop()
    cmd = [str(BIN / "llama-server"), "-m", model_path, "-c", str(ctx),
           "-t", str(threads), "--port", str(port),
           "--n-gpu-layers", str(ngl),
           # KV-cache quant: often a bigger RAM win than one more weight
           # bit (q8_0 = safe default; use q4_0/q5_0 when RAM is tight).
           "-ctk", "q8_0", "-ctv", "q8_0"]
    if mmproj:
        # vision model: llama.cpp mtmd path (text GGUF + vision projector)
        cmd += ["--mmproj", str(mmproj)]
    if spec:
        # speculative decoding, e.g. "ngram-mod" (free, no draft model).
        # EAGLE-3 needs a draft head: --spec-type draft-eagle3 --md <head>.
        cmd += ["--spec-type", str(spec)]
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
    # kills only the tracked chat/vision server (never the embedding one)
    if PIDFILE.exists():
        try:
            os.kill(int(PIDFILE.read_text().strip()), signal.SIGTERM)
        except Exception:
            pass
        PIDFILE.unlink(missing_ok=True)
    return {"ok": True}


def stop_all():
    stop()
    emb_stop()
    subprocess.run(["pkill", "-f", "llama-server"], capture_output=True)
    return {"ok": True}


def emb_up(port=EMB_PORT):
    return is_up(port)


def emb_start(model_path, port=EMB_PORT, threads=None):
    """Embedding server: llama-server --embedding (OpenAI /v1/embeddings)."""
    threads = threads or max(1, (os.cpu_count() or 4) - 1)
    emb_stop()
    cmd = [str(BIN / "llama-server"), "-m", model_path, "--embedding",
           "-t", str(threads), "--port", str(port)]
    log = open("/tmp/urai-embed-server.log", "ab")
    p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, env=_lib_env(),
                         start_new_session=True)
    EMB_PIDFILE.write_text(str(p.pid))
    for _ in range(60):
        if is_up(port):
            return {"ok": True, "pid": p.pid, "port": port,
                    "threads": threads, "mode": "embedding"}
        time.sleep(2)
    return {"ok": False,
            "error": "embed server did not become healthy; see /tmp/urai-embed-server.log"}


def emb_stop():
    if EMB_PIDFILE.exists():
        try:
            os.kill(int(EMB_PIDFILE.read_text().strip()), signal.SIGTERM)
        except Exception:
            pass
        EMB_PIDFILE.unlink(missing_ok=True)
    return {"ok": True}
