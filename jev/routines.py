#!/usr/bin/env python3
"""jev/routines.py — Scheduled routines (PersonalJarvis-inspired).

Routines are named recurring tasks: morning briefing, inbox sweep, nightly
report. Each routine has a schedule, a prompt, and optional tools. They run
via sched.py's watchdog thread.

From PersonalJarvis: routines, conductor scheduler, appshots concept.
"""
from __future__ import annotations
import json, os, re, time, uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTINES_FILE = ROOT / "data" / "routines.json"

@dataclass
class Routine:
    id: str
    name: str
    prompt: str
    schedule: str  # "daily HH:MM" | "weekly MON" | "hourly" | "manual"
    tools: list = field(default_factory=list)
    enabled: bool = True
    last_run: float = 0.0
    last_result: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self): return asdict(self)

    def next_run_due(self) -> bool:
        now = time.time()
        s = self.schedule.lower().strip()
        if s == "manual": return False
        if s == "hourly": return now - self.last_run >= 3600
        if s.startswith("daily"):
            m = re.search(r"(\d{1,2}):(\d{2})", s)
            if m:
                h, mi = int(m.group(1)), int(m.group(2))
                import datetime as _dt
                target = _dt.datetime.now().replace(hour=h, minute=mi, second=0, microsecond=0)
                if target.timestamp() < now and now - self.last_run >= 82800:
                    return True
                return False
            return now - self.last_run >= 86400
        if s.startswith("weekly"):
            return now - self.last_run >= 604800
        return False

def _load() -> list[Routine]:
    try:
        return [Routine(**r) for r in json.loads(ROUTINES_FILE.read_text())]
    except Exception:
        return []

def _save(routines: list[Routine]):
    ROUTINES_FILE.parent.mkdir(parents=True, exist_ok=True)
    ROUTINES_FILE.write_text(json.dumps([r.to_dict() for r in routines], indent=2))

def create_routine(name: str, prompt: str, schedule: str = "manual",
                   tools: list | None = None) -> dict:
    routines = _load()
    r = Routine(id=uuid.uuid4().hex[:8], name=name, prompt=prompt,
                schedule=schedule, tools=tools or [])
    routines.append(r)
    _save(routines)
    return r.to_dict()

def list_routines() -> list[dict]:
    return [r.to_dict() for r in _load()]

def run_routine(routine_id: str) -> dict:
    routines = _load()
    for r in routines:
        if r.id == routine_id:
            if not r.enabled:
                return {"ok": False, "error": "routine disabled"}
            t0 = time.time()
            try:
                from .agent import run_agent
                result = run_agent(r.prompt, budget_tokens=1024)
                answer = result.get("answer", "")
            except Exception as e:
                answer = f"error: {e}"
            r.last_run = time.time()
            r.last_result = answer[:500]
            _save(routines)
            return {"ok": True, "id": routine_id, "answer": answer,
                    "elapsed_s": round(time.time()-t0, 2)}
    return {"ok": False, "error": "routine not found"}

def run_due_routines() -> list[dict]:
    """Run all routines whose schedule is currently due. Called by sched tick."""
    results = []
    for r in _load():
        if r.enabled and r.next_run_due():
            results.append(run_routine(r.id))
    return results

def delete_routine(routine_id: str) -> dict:
    routines = [r for r in _load() if r.id != routine_id]
    _save(routines)
    return {"ok": True, "id": routine_id}

def set_enabled(routine_id: str, enabled: bool) -> dict:
    routines = _load()
    for r in routines:
        if r.id == routine_id:
            r.enabled = enabled
            _save(routines)
            return {"ok": True, **r.to_dict()}
    return {"ok": False, "error": "not found"}
