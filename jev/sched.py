#!/usr/bin/env python3
"""Scheduler: cron-style background agent jobs + llama-server watchdog (stdlib only).

Jobs live in data/sched_jobs.json:
  [{"id","task","every_s","enabled","last_run","last_status"}]
Runs append to data/sched_runs/<id>.jsonl. A daemon thread ticks every
30s inside the API process (started by serve()). OpenClaw-style "cron"
plugin hook fires on every job run so plugins can react.

Watchdog (self-healing serve):
  A second daemon thread monitors llama-server every WATCHDOG_INTERVAL_S.
  If the /health probe fails WATCHDOG_FAIL_THRESH times consecutively,
  it restarts llama-server using the same command from serve_ctl.py.
  Restart attempts are rate-limited (WATCHDOG_RESTART_COOLDOWN_S).
  All events logged to data/watchdog.log.
"""
import json
import os
import subprocess
import threading
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOBS_FILE = ROOT / "data" / "sched_jobs.json"
RUNS_DIR = ROOT / "data" / "sched_runs"
WATCHDOG_LOG = ROOT / "data" / "watchdog.log"
TICK_S = 30

# Watchdog tuning (all overridable via env)
WATCHDOG_INTERVAL_S = int(os.environ.get("URAI_WATCHDOG_INTERVAL", "20"))
WATCHDOG_FAIL_THRESH = int(os.environ.get("URAI_WATCHDOG_FAILS", "3"))
WATCHDOG_RESTART_COOLDOWN_S = int(os.environ.get("URAI_WATCHDOG_COOLDOWN", "60"))
LLAMA_URL = os.environ.get("JEV_LLAMA_URL", "http://127.0.0.1:8080")

_started = False
_watchdog_started = False
_watchdog_lock = threading.Lock()
_last_restart: float = 0.0
_fail_count: int = 0


# ── Watchdog helpers ──────────────────────────────────────────────────────────

def _wlog(msg: str):
    """Append timestamped line to watchdog.log (best-effort)."""
    try:
        WATCHDOG_LOG.parent.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(WATCHDOG_LOG, "a") as f:
            f.write(f"{ts}  {msg}\n")
    except Exception:
        pass


def _llama_healthy() -> bool:
    try:
        urllib.request.urlopen(LLAMA_URL + "/health", timeout=5).read()
        return True
    except Exception:
        return False


def _llama_pid() -> int | None:
    """Return PID of running llama-server process, or None."""
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "llama-server"], text=True).strip()
        pids = [int(p) for p in out.splitlines() if p.strip().isdigit()]
        return pids[0] if pids else None
    except Exception:
        return None


def _start_llama() -> bool:
    """Restart llama-server using serve_ctl.py logic. Returns True if launched."""
    try:
        from . import serve_ctl as _ctl
        result = _ctl.start()
        return result.get("ok", False)
    except Exception as e:
        _wlog(f"serve_ctl.start() failed: {e}")
        # Fallback: try direct subprocess using env hints
        try:
            llama_bin = os.environ.get(
                "URAI_LLAMA_BIN",
                str(ROOT / "third_party" / "llama.cpp" / "build" / "bin" / "llama-server"))
            model_path = os.environ.get("URAI_LLAMA_MODEL_PATH", "")
            if not model_path:
                # Infer from registry
                reg_path = ROOT / "model" / "registry.json"
                reg = json.loads(reg_path.read_text())
                active = reg.get("active", "")
                model_path = str(ROOT / reg["models"][active]["path"])
            cmd = [llama_bin, "--model", model_path,
                   "--port", "8080", "--host", "127.0.0.1",
                   "--ctx-size", "4096", "--threads", "4", "-ngl", "99"]
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return True
        except Exception as e2:
            _wlog(f"direct llama restart failed: {e2}")
            return False


def watchdog_status() -> dict:
    """Return current watchdog state for /metrics and /health."""
    global _fail_count, _last_restart
    return {
        "healthy": _llama_healthy(),
        "consecutive_fails": _fail_count,
        "last_restart": int(_last_restart) if _last_restart else None,
        "watchdog_interval_s": WATCHDOG_INTERVAL_S,
        "watchdog_fail_thresh": WATCHDOG_FAIL_THRESH,
    }


def _watchdog_loop():
    global _fail_count, _last_restart
    _wlog("watchdog started")
    while True:
        try:
            if _llama_healthy():
                if _fail_count > 0:
                    _wlog(f"llama-server recovered after {_fail_count} fails")
                _fail_count = 0
            else:
                _fail_count += 1
                _wlog(f"llama-server unhealthy (fail {_fail_count}/{WATCHDOG_FAIL_THRESH})")
                if _fail_count >= WATCHDOG_FAIL_THRESH:
                    now = time.time()
                    with _watchdog_lock:
                        since_last = now - _last_restart
                        if since_last < WATCHDOG_RESTART_COOLDOWN_S:
                            _wlog(f"restart skipped — cooldown {int(WATCHDOG_RESTART_COOLDOWN_S - since_last)}s remaining")
                        else:
                            pid = _llama_pid()
                            if pid:
                                try:
                                    os.kill(pid, 9)
                                    _wlog(f"killed stale llama-server pid={pid}")
                                    time.sleep(1)
                                except Exception:
                                    pass
                            _wlog("attempting llama-server restart...")
                            ok = _start_llama()
                            _last_restart = time.time()
                            _fail_count = 0
                            _wlog(f"restart {'succeeded' if ok else 'FAILED'}")
                            # Notify plugins
                            try:
                                from . import plugins as _pl
                                _pl.emit("watchdog_restart",
                                         {"ok": ok, "ts": int(_last_restart)})
                            except Exception:
                                pass
        except Exception as e:
            _wlog(f"watchdog tick error: {e}")
        time.sleep(WATCHDOG_INTERVAL_S)


# ── Scheduler ─────────────────────────────────────────────────────────────────

def _load() -> list:
    try:
        return json.loads(JOBS_FILE.read_text())
    except Exception:
        return []


def _save(jobs: list):
    JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    JOBS_FILE.write_text(json.dumps(jobs, indent=2) + "\n")


def list_jobs() -> list:
    return _load()


def add_job(task: str, every_s: int = 3600) -> dict:
    jobs = _load()
    job = {"id": uuid.uuid4().hex[:8], "task": task,
           "every_s": max(60, int(every_s or 3600)), "enabled": True,
           "last_run": 0, "last_status": "never"}
    jobs.append(job)
    _save(jobs)
    return job


def set_enabled(job_id: str, enabled: bool) -> dict:
    jobs = _load()
    for j in jobs:
        if j["id"] == job_id:
            j["enabled"] = bool(enabled)
            _save(jobs)
            return {"ok": True, **j}
    return {"ok": False, "error": "unknown job"}


def delete_job(job_id: str) -> dict:
    jobs = [j for j in _load() if j["id"] != job_id]
    _save(jobs)
    return {"ok": True, "id": job_id}


def run_job(job: dict) -> dict:
    from .agent import run_agent
    t0 = time.time()
    try:
        res = run_agent(job["task"], budget_tokens=2048)
        status = "ok" if res.get("ok") else "agent-failed"
        summary = (res.get("answer") or "")[:2000]
    except Exception as e:
        status, summary = "error", str(e)[:500]
    rec = {"ts": int(time.time()), "job": job["id"],
           "elapsed_s": round(time.time() - t0, 1),
           "status": status, "summary": summary}
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RUNS_DIR / f"{job['id']}.jsonl", "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    jobs = _load()
    for j in jobs:
        if j["id"] == job["id"]:
            j["last_run"] = rec["ts"]
            j["last_status"] = status
    _save(jobs)
    try:
        from . import plugins as _pl
        _pl.emit("cron", {"job": job["id"], "status": status})
    except Exception:
        pass
    return rec


def job_runs(job_id: str, limit: int = 20) -> list:
    try:
        rows = (RUNS_DIR / f"{job_id}.jsonl").read_text().splitlines()
        return [json.loads(r) for r in rows[-limit:] if r.strip()]
    except Exception:
        return []


def _tick():
    while True:
        try:
            now = time.time()
            for job in _load():
                if job.get("enabled") and \
                        now - job.get("last_run", 0) >= job.get("every_s", 3600):
                    run_job(job)
            # Run due routines (PersonalJarvis-style scheduled tasks)
            try:
                from .routines import run_due_routines as _rdr
                _rdr()
            except Exception:
                pass
            # Run due named agents
            try:
                from .jarvis_agents import run_due_agents as _rda
                _rda()
            except Exception:
                pass
        except Exception:
            pass
        time.sleep(TICK_S)


def start():
    """Start scheduler tick + llama-server watchdog (idempotent)."""
    global _started, _watchdog_started
    if not _started:
        _started = True
        threading.Thread(target=_tick, daemon=True, name="urai-sched").start()
    if not _watchdog_started:
        _watchdog_started = True
        threading.Thread(target=_watchdog_loop, daemon=True,
                         name="urai-watchdog").start()
