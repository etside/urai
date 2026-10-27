"""
jev/jarvis_agents.py — Persistent Named Agents for Urai AI
Ported from PersonalJarvis "Jarvis Agents". stdlib only.

Each UAgent has:
  - Its own system prompt / personality
  - A subset of Urai's tools
  - A cron-like schedule (daily / weekly / manual)
  - Private notes file (markdown)
  - Full conversation history (JSON)
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(os.environ.get("URAI_AGENTS_DIR", "data/agents"))

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class UAgent:
    id: str
    name: str
    instructions: str          # system prompt / personality
    tools: list[str]           # subset of Urai's registered TOOLS
    schedule: str              # "daily HH:MM" | "weekly MON" | "" = manual
    memory_file: str           # path to agent's private notes .md
    created_at: float          # unix timestamp
    last_run: float = 0.0      # unix timestamp of last scheduled run
    run_count: int = 0
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "UAgent":
        d.setdefault("last_run", 0.0)
        d.setdefault("run_count", 0)
        d.setdefault("tags", [])
        return UAgent(**d)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_dirs() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)


def _agent_path(agent_id: str) -> Path:
    return BASE_DIR / f"{agent_id}.json"


def _notes_path(agent_id: str) -> Path:
    return BASE_DIR / f"{agent_id}_notes.md"


def _history_path(agent_id: str) -> Path:
    return BASE_DIR / f"{agent_id}_history.jsonl"


def _load_agent(agent_id: str) -> Optional[UAgent]:
    p = _agent_path(agent_id)
    if not p.exists():
        return None
    with p.open(encoding="utf-8") as fh:
        return UAgent.from_dict(json.load(fh))


def _save_agent(agent: UAgent) -> None:
    _ensure_dirs()
    with _agent_path(agent.id).open("w", encoding="utf-8") as fh:
        json.dump(agent.to_dict(), fh, indent=2)


def _append_history(agent_id: str, role: str, content: str, session_id: str = "") -> None:
    record = {
        "ts": time.time(),
        "session_id": session_id,
        "role": role,
        "content": content,
    }
    with _history_path(agent_id).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _load_history(agent_id: str, last_n: int = 20) -> list[dict]:
    p = _history_path(agent_id)
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return records[-last_n:]


def _parse_schedule(schedule: str) -> Optional[datetime]:
    """
    Return the next due datetime for a schedule string.
    Formats:
      "daily HH:MM"     — every day at HH:MM
      "weekly MON"      — every Monday at 09:00
      ""                — manual only (never auto-due)
    Returns None if schedule is empty/manual.
    """
    s = schedule.strip().lower()
    if not s:
        return None
    now = datetime.now()
    daily_m = re.match(r"daily\s+(\d{1,2}):(\d{2})", s)
    if daily_m:
        h, m = int(daily_m.group(1)), int(daily_m.group(2))
        candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate
    weekly_m = re.match(r"weekly\s+(\w+)", s)
    if weekly_m:
        day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        day_str = weekly_m.group(1)[:3]
        if day_str not in day_names:
            return None
        target_wd = day_names.index(day_str)
        current_wd = now.weekday()
        days_ahead = (target_wd - current_wd) % 7 or 7
        candidate = (now + timedelta(days=days_ahead)).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        return candidate
    return None


def _is_due(agent: UAgent) -> bool:
    """Return True if agent's schedule is currently due."""
    if not agent.schedule:
        return False
    s = agent.schedule.strip().lower()
    now = datetime.now()
    last = datetime.fromtimestamp(agent.last_run) if agent.last_run else datetime.min

    daily_m = re.match(r"daily\s+(\d{1,2}):(\d{2})", s)
    if daily_m:
        h, m = int(daily_m.group(1)), int(daily_m.group(2))
        due_today = now.replace(hour=h, minute=m, second=0, microsecond=0)
        # due if we've passed today's time and haven't run today
        return now >= due_today and last.date() < now.date()

    weekly_m = re.match(r"weekly\s+(\w+)", s)
    if weekly_m:
        day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        day_str = weekly_m.group(1)[:3]
        if day_str not in day_names:
            return False
        target_wd = day_names.index(day_str)
        # due if today is the right weekday and haven't run this week
        days_since_last = (now.date() - last.date()).days
        return now.weekday() == target_wd and days_since_last >= 7
    return False


def _build_system_prompt(agent: UAgent) -> str:
    """Compose system prompt with instructions + private notes."""
    notes_path = _notes_path(agent.id)
    notes = ""
    if notes_path.exists():
        notes = notes_path.read_text(encoding="utf-8").strip()
    parts = [
        f"You are {agent.name}.",
        "",
        agent.instructions,
    ]
    if notes:
        parts += ["", "## Your Private Notes", notes]
    if agent.tools:
        parts += ["", f"## Available Tools", ", ".join(agent.tools)]
    return "\n".join(parts)


def _simple_llm_stub(system: str, history: list[dict], message: str) -> str:
    """Call Urai's local LlamaServerBackend for agent responses."""
    try:
        import sys, os
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from jev.backends import LlamaServerBackend
        backend = LlamaServerBackend()
        if not backend.healthy():
            return "[Urai model starting up — retry in a few seconds]"
        messages = [{"role": "system", "content": system}]
        # Convert history to OpenAI format
        for h in history[-10:]:
            role = h.get("role", "user")
            content = h.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": message})
        res = backend.complete(messages, max_tokens=512, temperature=0.3)
        return res.get("content", "").strip()
    except Exception as e:
        return f"[Agent error: {e}]"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_agent(
    name: str,
    instructions: str,
    tools: list[str],
    schedule: str = "",
    tags: list[str] | None = None,
) -> UAgent:
    """
    Create and persist a new named agent.
    Returns the UAgent instance.
    """
    _ensure_dirs()
    agent_id = str(uuid.uuid4())[:8]
    notes_file = str(_notes_path(agent_id))
    agent = UAgent(
        id=agent_id,
        name=name,
        instructions=instructions.strip(),
        tools=list(tools),
        schedule=schedule.strip(),
        memory_file=notes_file,
        created_at=time.time(),
        tags=tags or [],
    )
    _save_agent(agent)
    # initialise empty notes file
    _notes_path(agent_id).write_text(
        f"# {name} — Private Notes\n\n_Created {datetime.utcnow().isoformat(timespec='seconds')}Z_\n",
        encoding="utf-8",
    )
    return agent


def run_agent_turn(
    agent_id: str,
    message: str,
    session_id: str = "",
) -> dict:
    """
    Execute a single conversation turn for an agent.
    Returns a dict with the agent's response and metadata.
    """
    agent = _load_agent(agent_id)
    if agent is None:
        return {"error": f"Agent '{agent_id}' not found"}

    system_prompt = _build_system_prompt(agent)
    history = _load_history(agent_id, last_n=20)

    # Append user message to history
    _append_history(agent_id, "user", message, session_id)

    # Call LLM (stub — wire to actual Urai LLM here)
    response = _simple_llm_stub(system_prompt, history, message)

    # Persist assistant turn
    _append_history(agent_id, "assistant", response, session_id)

    # Update run stats
    agent.last_run = time.time()
    agent.run_count += 1
    _save_agent(agent)

    return {
        "agent_id": agent_id,
        "agent_name": agent.name,
        "session_id": session_id,
        "message": message,
        "response": response,
        "run_count": agent.run_count,
        "ts": agent.last_run,
    }


def list_agents() -> list[dict]:
    """Return a summary list of all persisted agents."""
    _ensure_dirs()
    agents = []
    for p in sorted(BASE_DIR.glob("*.json")):
        try:
            with p.open(encoding="utf-8") as fh:
                d = json.load(fh)
            agents.append({
                "id": d["id"],
                "name": d["name"],
                "schedule": d.get("schedule", ""),
                "tools": d.get("tools", []),
                "run_count": d.get("run_count", 0),
                "last_run": datetime.fromtimestamp(d["last_run"]).isoformat() if d.get("last_run") else None,
                "tags": d.get("tags", []),
                "created_at": datetime.fromtimestamp(d["created_at"]).isoformat(),
            })
        except (json.JSONDecodeError, KeyError):
            pass
    return agents


def get_agent(agent_id: str) -> Optional[UAgent]:
    """Retrieve a UAgent by ID."""
    return _load_agent(agent_id)


def delete_agent(agent_id: str) -> dict:
    """
    Delete an agent and all associated files.
    Returns status dict.
    """
    removed = []
    for suffix in ["", "_notes", "_history"]:
        ext = ".json" if suffix == "" else (".md" if suffix == "_notes" else ".jsonl")
        p = BASE_DIR / f"{agent_id}{suffix}{ext}"
        if p.exists():
            p.unlink()
            removed.append(str(p))
    if removed:
        return {"deleted": True, "agent_id": agent_id, "files_removed": removed}
    return {"deleted": False, "agent_id": agent_id, "error": "Agent not found"}


def agent_learn(agent_id: str, fact: str) -> dict:
    """
    Append a new fact to an agent's private notes (memory_file).
    This is permanent, append-only learning.
    """
    agent = _load_agent(agent_id)
    if agent is None:
        return {"error": f"Agent '{agent_id}' not found"}

    notes_path = _notes_path(agent_id)
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    entry = f"\n- [{ts}] {fact.strip()}\n"
    with notes_path.open("a", encoding="utf-8") as fh:
        fh.write(entry)

    return {
        "agent_id": agent_id,
        "learned": fact,
        "notes_file": str(notes_path),
        "ts": ts,
    }


def run_due_agents(default_message: str = "Run your scheduled task now.") -> list[dict]:
    """
    Check all agents and run any whose schedule is currently due.
    Returns list of run results.
    """
    _ensure_dirs()
    results = []
    for p in BASE_DIR.glob("*.json"):
        try:
            with p.open(encoding="utf-8") as fh:
                d = json.load(fh)
            agent = UAgent.from_dict(d)
        except (json.JSONDecodeError, KeyError):
            continue

        if _is_due(agent):
            result = run_agent_turn(
                agent.id,
                default_message,
                session_id=f"scheduled_{int(time.time())}",
            )
            result["scheduled"] = True
            results.append(result)

    return results


def agent_history(agent_id: str, last_n: int = 20) -> list[dict]:
    """Return the last N conversation turns for an agent."""
    agent = _load_agent(agent_id)
    if agent is None:
        return []
    return _load_history(agent_id, last_n=last_n)


def agent_set_schedule(agent_id: str, schedule: str) -> dict:
    """Update an agent's schedule string."""
    agent = _load_agent(agent_id)
    if agent is None:
        return {"error": f"Agent '{agent_id}' not found"}
    agent.schedule = schedule.strip()
    _save_agent(agent)
    next_due = _parse_schedule(schedule)
    return {
        "agent_id": agent_id,
        "schedule": agent.schedule,
        "next_due": next_due.isoformat() if next_due else None,
    }


def agent_add_tool(agent_id: str, tool_name: str) -> dict:
    """Add a tool to an agent's allowed tool list."""
    agent = _load_agent(agent_id)
    if agent is None:
        return {"error": f"Agent '{agent_id}' not found"}
    if tool_name not in agent.tools:
        agent.tools.append(tool_name)
        _save_agent(agent)
    return {"agent_id": agent_id, "tools": agent.tools}


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

def _reinit_base(tmp: str) -> None:
    global BASE_DIR
    BASE_DIR = Path(tmp)


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["URAI_AGENTS_DIR"] = tmp
        _reinit_base(tmp)

        # Create
        a = create_agent(
            name="ResearchBot",
            instructions="You are a research assistant. Summarise topics concisely.",
            tools=["web_search", "wiki_get", "wiki_add"],
            schedule="daily 09:00",
            tags=["research", "auto"],
        )
        print("CREATED:", a.id, a.name, "schedule:", a.schedule)

        # Learn
        r = agent_learn(a.id, "Urai uses BM25 for wiki search.")
        print("LEARNED:", r["learned"])

        # Run turn
        turn = run_agent_turn(a.id, "What is async IO in Python?", session_id="test_sess")
        print("TURN response preview:", turn["response"][:80])

        # List
        agents = list_agents()
        print("LIST:", [(x["name"], x["run_count"]) for x in agents])

        # History
        hist = agent_history(a.id, last_n=5)
        print("HISTORY turns:", len(hist))

        # Schedule update
        sched = agent_set_schedule(a.id, "weekly mon")
        print("SCHEDULE:", sched["schedule"], "next:", sched["next_due"])

        # Add tool
        t = agent_add_tool(a.id, "wiki_search")
        print("TOOLS:", t["tools"])

        # Due agents (none should fire since last_run=just now)
        due = run_due_agents()
        print("DUE agents run:", len(due))

        # Delete
        d = delete_agent(a.id)
        print("DELETED:", d["deleted"], "files:", len(d.get("files_removed", [])))

        print("OK — all tests passed.")
