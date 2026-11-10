#!/usr/bin/env python3
"""Proactive goals agent: file-based multi-step plans with approval queue.

Goals are persisted as JSON in data/goals/. Each goal has steps; the
scheduler tick advances pending steps. Steps involving external actions
(browser, email, payment, send, delete) require manual approval before
execution.

Stdlib only. Uses jev.agent.run_agent for step execution and jev.events
for event logging.
"""
from __future__ import annotations
import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
GOALS_DIR = ROOT / "data" / "goals"
APPROVAL_FILE = GOALS_DIR / "approval_queue.json"

# Keywords that mark a step as requiring human approval
APPROVAL_KEYWORDS = {"browser", "email", "payment", "send", "post to",
                     "delete", "purchase", "transfer", "deploy", "publish"}


@dataclass
class GoalStep:
    id: str
    description: str
    status: str = "pending"  # pending | running | done | failed | awaiting_approval
    result: str = ""
    requires_approval: bool = False
    approved_at: float = 0.0


@dataclass
class Goal:
    id: str
    title: str
    deadline: str = ""
    constraints: str = ""
    steps: List[GoalStep] = field(default_factory=list)
    status: str = "active"  # active | completed | paused
    created_at: float = field(default_factory=time.time)


def _ensure_dir():
    GOALS_DIR.mkdir(parents=True, exist_ok=True)


def _goal_path(goal_id: str) -> Path:
    return GOALS_DIR / f"{goal_id}.json"


def _load_goal(goal_id: str) -> Goal | None:
    p = _goal_path(goal_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        steps = [GoalStep(**s) for s in data.get("steps", [])]
        return Goal(
            id=data["id"], title=data["title"], deadline=data.get("deadline", ""),
            constraints=data.get("constraints", ""), steps=steps,
            status=data.get("status", "active"),
            created_at=data.get("created_at", time.time()),
        )
    except Exception:
        return None


def _save_goal(goal: Goal):
    _ensure_dir()
    data = asdict(goal)
    _goal_path(goal.id).write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _needs_approval(description: str) -> bool:
    desc_lower = description.lower()
    return any(kw in desc_lower for kw in APPROVAL_KEYWORDS)


def list_goals() -> list:
    _ensure_dir()
    out = []
    for p in sorted(GOALS_DIR.glob("*.json")):
        if p.name == "approval_queue.json":
            continue
        try:
            data = json.loads(p.read_text())
            out.append(data)
        except Exception:
            continue
    return out


def get_goal(goal_id: str) -> dict | None:
    g = _load_goal(goal_id)
    if g is None:
        return None
    return asdict(g)


def create_goal(title: str, deadline: str = "",
                constraints: str = "") -> dict:
    """Create a goal with an LLM-generated multi-step plan."""
    _ensure_dir()
    goal_id = uuid.uuid4().hex[:8]

    # Generate steps via the agent
    prompt = (
        f"Create a multi-step plan for: {title}. "
        f"Deadline: {deadline or 'flexible'}. "
        f"Constraints: {constraints or 'none'}. "
        "Return ONLY a JSON array of step descriptions (strings). "
        "Example: [\"step 1 description\", \"step 2 description\"]"
    )
    steps_raw = []
    try:
        from .agent import run_agent as _run_agent
        res = _run_agent(prompt, budget_tokens=1024)
        answer = res.get("answer", "")
        # Extract JSON array from the answer
        import re
        m = re.search(r'\[.*\]', answer, re.DOTALL)
        if m:
            steps_raw = json.loads(m.group(0))
    except Exception:
        pass

    # Fallback: single step if LLM didn't produce a plan
    if not steps_raw or not isinstance(steps_raw, list):
        steps_raw = [title]

    steps = [
        GoalStep(
            id=uuid.uuid4().hex[:8],
            description=str(s),
            requires_approval=_needs_approval(str(s)),
        )
        for s in steps_raw
    ]

    goal = Goal(id=goal_id, title=title, deadline=deadline,
                constraints=constraints, steps=steps)
    _save_goal(goal)
    return asdict(goal)


def approve_step(goal_id: str, step_id: str) -> dict:
    """Mark a step as approved so it can run on the next tick."""
    g = _load_goal(goal_id)
    if g is None:
        return {"ok": False, "error": "goal not found"}
    for s in g.steps:
        if s.id == step_id:
            s.requires_approval = False
            s.approved_at = time.time()
            if s.status == "awaiting_approval":
                s.status = "pending"
            _save_goal(g)
            return {"ok": True, "goal_id": goal_id, "step_id": step_id}
    return {"ok": False, "error": "step not found"}


def delete_goal(goal_id: str) -> dict:
    p = _goal_path(goal_id)
    if p.exists():
        p.unlink()
        return {"ok": True, "id": goal_id}
    return {"ok": False, "error": "goal not found"}


def tick():
    """Advance all active goals by one step. Called by the scheduler."""
    from .events import emit as _emit

    _ensure_dir()
    for p in GOALS_DIR.glob("*.json"):
        if p.name == "approval_queue.json":
            continue
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        if data.get("status") != "active":
            continue

        goal_id = data.get("id", "")
        steps = data.get("steps", [])
        # Find the next pending step
        next_step = None
        for s in steps:
            if s.get("status") in ("pending", "awaiting_approval"):
                next_step = s
                break
        if next_step is None:
            # All steps done — mark goal completed
            if all(s.get("status") == "done" for s in steps):
                data["status"] = "completed"
                p.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            continue

        # If step requires approval and isn't approved, mark awaiting
        if next_step.get("requires_approval") and not next_step.get("approved_at"):
            if next_step["status"] != "awaiting_approval":
                next_step["status"] = "awaiting_approval"
                p.write_text(json.dumps(data, indent=2, ensure_ascii=False))
                _emit(goal_id, "goal_step_awaiting", "goals",
                      tool="goal", input_summary=next_step.get("description", "")[:200],
                      output_summary="awaiting approval", status=True)
            continue

        # Execute the step
        next_step["status"] = "running"
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        _emit(goal_id, "goal_step_start", "goals",
              tool="run_agent", input_summary=next_step.get("description", "")[:200],
              output_summary="running", status=True)
        try:
            from .agent import run_agent as _run_agent
            res = _run_agent(next_step.get("description", ""), budget_tokens=1024)
            ok = res.get("ok", False)
            next_step["status"] = "done" if ok else "failed"
            next_step["result"] = (res.get("answer", "") or "")[:2000]
        except Exception as e:
            next_step["status"] = "failed"
            next_step["result"] = str(e)[:300]
        _emit(goal_id, "goal_step_done", "goals",
              tool="run_agent", input_summary=next_step.get("description", "")[:120],
              output_summary=next_step.get("result", "")[:200],
              status=next_step["status"] == "done")
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False))
