#!/usr/bin/env python3
"""Scheduler: cron-style background agent jobs (stdlib only).

Jobs live in data/sched_jobs.json:
  [{"id","task","every_s","enabled","last_run","last_status"}]
Runs append to data/sched_runs/<id>.jsonl. A daemon thread ticks every
30s inside the API process (started by serve()). OpenClaw-style "cron"
plugin hook fires on every job run so plugins can react.
"""
import json
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOBS_FILE = ROOT / "data" / "sched_jobs.json"
RUNS_DIR = ROOT / "data" / "sched_runs"
TICK_S = 30
_started = False


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
                if job.get("enabled") and now - job.get("last_run", 0) >= job.get("every_s", 3600):
                    run_job(job)
        except Exception:
            pass
        time.sleep(TICK_S)


def start():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_tick, daemon=True).start()
