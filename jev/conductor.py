#!/usr/bin/env python3
"""Conductor v2: PlanningFlow-style orchestration for Urai (stdlib only).

Ported from OpenManus's PlanningFlow concept and merged with Urai's existing
Fugu-style conductor (Thinker → Workers → Verifier).

New in v2:
  - PlanStepStatus enum for fine-grained step lifecycle tracking
  - Plan dataclass with typed steps and agent_type routing
  - create_plan(task) — LLM produces a structured execution plan
  - execute_plan(plan, files, budget_tokens) — step-by-step execution with
    BLOCKED propagation and independent-step continuation
  - plan_status(plan_id) — live status snapshot from _active_plans
  - run_conductor() remains backward-compatible (now delegates to plan engine)

Agent type routing:
  coder    — code generation / debugging tasks
  browser  — information retrieval / web-style lookup tasks
  planner  — sub-decomposition of complex steps
  casual   — general Q&A / prose tasks (default)

Use: run_conductor(task, files, budget_tokens) or /agent/swarm {"mode":"conductor"}.
"""

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .agent import run_agent
from .swarm import run_swarm

# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

THINKER_SYS = (
    "You decompose complex tasks. Reply ONLY as a JSON array of "
    '2-6 short independent subtask strings, e.g. ["...","..."]. '
    "No prose, no markdown fences."
)

VERIFIER_SYS = (
    "You merge worker outputs into one final answer. Drop "
    "contradictions, keep verified claims, stay concise."
)

PLANNER_SYS = (
    "You are a planning assistant. Given a task, produce a structured execution "
    "plan as a JSON object with the following schema:\n"
    '{\n'
    '  "steps": [\n'
    '    {\n'
    '      "id": "<short_snake_case_id>",\n'
    '      "description": "<what this step does>",\n'
    '      "agent_type": "<coder|browser|planner|casual>",\n'
    '      "depends_on": ["<step_id>", ...]  // may be empty\n'
    '    }\n'
    '  ]\n'
    '}\n\n'
    "Rules:\n"
    "- 2 to 8 steps only.\n"
    "- agent_type must be one of: coder, browser, planner, casual.\n"
    "- depends_on lists step ids that must complete before this step starts.\n"
    "- Reply ONLY with the JSON object. No markdown fences, no prose."
)

STEP_SYS_BY_TYPE = {
    "coder": (
        "You are a coding specialist. Produce precise, working code. "
        "Show your reasoning, then give the final implementation."
    ),
    "browser": (
        "You are an information retrieval specialist. Summarise relevant "
        "facts clearly, citing sources where possible."
    ),
    "planner": (
        "You are a sub-task planner. Break this step into a concise sequence "
        "of actions and reason through each one."
    ),
    "casual": (
        "You are a helpful general assistant. Answer clearly and concisely."
    ),
}

# ---------------------------------------------------------------------------
# PlanStepStatus enum
# ---------------------------------------------------------------------------


class PlanStepStatus(Enum):
    """Lifecycle states for a single plan step."""
    NOT_STARTED = "not_started"
    IN_PROGRESS  = "in_progress"
    COMPLETED    = "completed"
    BLOCKED      = "blocked"


# ---------------------------------------------------------------------------
# Plan dataclasses (no pydantic — stdlib only)
# ---------------------------------------------------------------------------


@dataclass
class PlanStep:
    """A single executable step within a Plan."""
    id: str
    description: str
    agent_type: str = "casual"           # coder | browser | planner | casual
    depends_on: list = field(default_factory=list)
    status: PlanStepStatus = PlanStepStatus.NOT_STARTED
    result: str = ""
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "agent_type": self.agent_type,
            "depends_on": self.depends_on,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass
class Plan:
    """A structured execution plan for a task."""
    id: str
    task: str
    steps: list = field(default_factory=list)   # list[PlanStep]
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    final_answer: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task": self.task,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "final_answer": self.final_answer,
        }

    def completed_steps(self) -> list:
        return [s for s in self.steps if s.status == PlanStepStatus.COMPLETED]

    def blocked_steps(self) -> list:
        return [s for s in self.steps if s.status == PlanStepStatus.BLOCKED]

    def is_done(self) -> bool:
        return all(
            s.status in (PlanStepStatus.COMPLETED, PlanStepStatus.BLOCKED)
            for s in self.steps
        )


# ---------------------------------------------------------------------------
# In-memory plan store
# ---------------------------------------------------------------------------

_active_plans: dict[str, Plan] = {}


# ---------------------------------------------------------------------------
# Plan creation
# ---------------------------------------------------------------------------


def _parse_plan_json(text: str) -> dict | None:
    """Extract and parse the first JSON object from LLM output."""
    try:
        m = re.search(r"\{.*\}", text or "", re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except Exception:
        pass
    return None


def create_plan(task: str, budget_tokens: int = 1024) -> Plan:
    """Ask the LLM to produce a structured plan for *task*.

    Falls back to a single-step casual plan if the LLM returns unparseable
    output or fewer than 2 steps.
    """
    plan_id = str(uuid.uuid4())[:8]
    raw = run_agent(
        f"{PLANNER_SYS}\n\nTASK:\n{task}",
        {},
        budget_tokens=budget_tokens,
    )
    parsed = _parse_plan_json(raw.get("answer", ""))

    steps: list[PlanStep] = []
    if parsed and isinstance(parsed.get("steps"), list):
        for i, raw_step in enumerate(parsed["steps"][:8]):
            if not isinstance(raw_step, dict):
                continue
            step_id = str(raw_step.get("id") or f"step_{i+1}").strip()
            description = str(raw_step.get("description") or "").strip()
            agent_type = str(raw_step.get("agent_type") or "casual").strip()
            depends_on = raw_step.get("depends_on") or []
            if not isinstance(depends_on, list):
                depends_on = []
            if agent_type not in STEP_SYS_BY_TYPE:
                agent_type = "casual"
            if description:
                steps.append(PlanStep(
                    id=step_id,
                    description=description,
                    agent_type=agent_type,
                    depends_on=[str(d) for d in depends_on],
                ))

    # Fallback: treat the whole task as one casual step
    if len(steps) < 1:
        steps = [PlanStep(id="step_1", description=task, agent_type="casual")]

    plan = Plan(id=plan_id, task=task, steps=steps)
    _active_plans[plan_id] = plan
    return plan


# ---------------------------------------------------------------------------
# Plan execution
# ---------------------------------------------------------------------------


def _step_is_runnable(step: PlanStep, plan: Plan) -> bool:
    """Return True if all dependencies are COMPLETED (or there are none)."""
    if step.status != PlanStepStatus.NOT_STARTED:
        return False
    completed_ids = {s.id for s in plan.completed_steps()}
    return all(dep in completed_ids for dep in step.depends_on)


def _execute_step(
    step: PlanStep,
    task_context: str,
    files: dict,
    budget_tokens: int,
) -> None:
    """Run a single plan step in-place, updating its status and result."""
    sys_prompt = STEP_SYS_BY_TYPE.get(step.agent_type, STEP_SYS_BY_TYPE["casual"])
    prompt = (
        f"{sys_prompt}\n\n"
        f"OVERALL TASK:\n{task_context}\n\n"
        f"YOUR STEP ({step.id}):\n{step.description}"
    )
    step.status = PlanStepStatus.IN_PROGRESS
    step.started_at = time.time()
    try:
        result = run_agent(prompt, files, budget_tokens=budget_tokens)
        answer = result.get("answer", "")
        if answer:
            step.result = answer
            step.status = PlanStepStatus.COMPLETED
        else:
            step.error = result.get("error", "empty answer")
            step.status = PlanStepStatus.BLOCKED
    except Exception as exc:
        step.error = str(exc)
        step.status = PlanStepStatus.BLOCKED
    finally:
        step.finished_at = time.time()


def _mark_downstream_blocked(plan: Plan, blocked_step_id: str) -> None:
    """Mark any step that depends (directly or transitively) on a blocked step."""
    changed = True
    blocked_ids = {blocked_step_id}
    while changed:
        changed = False
        for step in plan.steps:
            if step.status in (PlanStepStatus.NOT_STARTED, PlanStepStatus.BLOCKED):
                if any(dep in blocked_ids for dep in step.depends_on):
                    if step.status != PlanStepStatus.BLOCKED:
                        step.status = PlanStepStatus.BLOCKED
                        step.error = f"blocked by dependency: {blocked_step_id}"
                        blocked_ids.add(step.id)
                        changed = True


def execute_plan(
    plan: Plan,
    files: dict = None,
    budget_tokens: int = 2048,
) -> dict:
    """Execute all steps in *plan*, respecting dependencies.

    Steps whose dependencies are BLOCKED are themselves marked BLOCKED.
    Independent steps that are still runnable continue executing.

    Returns a result dict compatible with the legacy run_conductor return shape.
    """
    files = files or {}
    t0 = time.time()
    trace: list[dict] = [{"step": "plan-start", "plan_id": plan.id,
                          "total_steps": len(plan.steps)}]

    # Simple round-robin scheduler — iterate until nothing is runnable
    max_rounds = len(plan.steps) + 2
    for _round in range(max_rounds):
        runnable = [s for s in plan.steps if _step_is_runnable(s, plan)]
        if not runnable:
            break

        # Execute runnable steps (could be parallelised via run_swarm in future)
        for step in runnable:
            _execute_step(step, plan.task, files, budget_tokens)
            trace.append({
                "step": step.id,
                "status": step.status.value,
                "agent_type": step.agent_type,
                "elapsed_s": round(step.finished_at - step.started_at, 2),
            })
            if step.status == PlanStepStatus.BLOCKED:
                _mark_downstream_blocked(plan, step.id)

        if plan.is_done():
            break

    # Collect completed outputs for synthesis
    completed = plan.completed_steps()
    blocked = plan.blocked_steps()

    if not completed:
        plan.finished_at = time.time()
        return {
            "ok": False,
            "error": "all plan steps blocked or failed",
            "plan_id": plan.id,
            "trace": trace,
            "elapsed_s": round(time.time() - t0, 2),
        }

    # Verifier merges completed outputs
    outputs = [f"[{s.id} / {s.agent_type}]\n{s.result}" for s in completed]
    verify = run_agent(
        f"{VERIFIER_SYS}\n\nORIGINAL TASK:\n{plan.task}\n\nWORKER OUTPUTS:\n"
        + "\n\n---\n\n".join(outputs[:8]),
        files,
        budget_tokens=budget_tokens,
    )

    plan.final_answer = verify.get("answer", "")
    plan.finished_at = time.time()

    trace.append({
        "step": "verifier",
        "completed_steps": len(completed),
        "blocked_steps": len(blocked),
    })

    return {
        "ok": True,
        "answer": plan.final_answer,
        "plan_id": plan.id,
        "completed_steps": len(completed),
        "blocked_steps": len(blocked),
        "trace": trace,
        "elapsed_s": round(time.time() - t0, 2),
    }


# ---------------------------------------------------------------------------
# Plan status query
# ---------------------------------------------------------------------------


def plan_status(plan_id: str) -> dict:
    """Return a snapshot of the current step statuses for *plan_id*.

    Returns an error dict if the plan is not found in _active_plans.
    """
    plan = _active_plans.get(plan_id)
    if plan is None:
        return {"ok": False, "error": f"plan '{plan_id}' not found"}

    steps_summary = []
    for s in plan.steps:
        entry = {
            "id": s.id,
            "description": s.description[:80],
            "agent_type": s.agent_type,
            "status": s.status.value,
        }
        if s.status == PlanStepStatus.BLOCKED and s.error:
            entry["error"] = s.error
        if s.status == PlanStepStatus.COMPLETED:
            entry["result_preview"] = s.result[:120]
        steps_summary.append(entry)

    return {
        "ok": True,
        "plan_id": plan_id,
        "task_preview": plan.task[:100],
        "steps": steps_summary,
        "completed": len(plan.completed_steps()),
        "blocked": len(plan.blocked_steps()),
        "is_done": plan.is_done(),
        "created_at": plan.created_at,
        "finished_at": plan.finished_at or None,
    }


# ---------------------------------------------------------------------------
# Legacy helpers (kept for backward compatibility)
# ---------------------------------------------------------------------------


def _parse_subtasks(text: str, fallback: str) -> list[str]:
    """Parse a JSON array of subtask strings from LLM output."""
    try:
        m = re.search(r"\[.*\]", text or "", re.DOTALL)
        items = json.loads(m.group(0)) if m else []
        items = [str(x).strip() for x in items if str(x).strip()][:6]
        if len(items) >= 2:
            return items
    except Exception:
        pass
    return [fallback]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_conductor(
    task: str,
    files: dict = None,
    budget_tokens: int = 2048,
    max_workers: int = 3,
    use_planning: bool = True,
) -> dict:
    """Orchestrate a task using either the PlanningFlow (default) or legacy
    Thinker→Workers→Verifier pipeline.

    Args:
        task:          The user task string.
        files:         Optional dict of filename→content passed to agents.
        budget_tokens: Per-agent token budget.
        max_workers:   Max parallel workers (legacy path only).
        use_planning:  If True (default), use create_plan+execute_plan.
                       Set False to fall back to the original swarm pipeline.

    Returns:
        dict with keys: ok, answer, trace, elapsed_s, and (planning path)
        plan_id, completed_steps, blocked_steps.
    """
    if use_planning:
        plan = create_plan(task, budget_tokens=min(budget_tokens, 1024))
        return execute_plan(plan, files=files, budget_tokens=budget_tokens)

    # ── Legacy path (original Fugu-style conductor) ──────────────────────
    t0 = time.time()
    trace = [{"step": "conductor-start"}]

    think = run_agent(
        f"{THINKER_SYS}\n\nTASK:\n{task}",
        files or {},
        budget_tokens=1024,
    )
    subtasks = _parse_subtasks(think.get("answer", ""), task)
    trace.append({"step": "thinker", "subtasks": len(subtasks)})

    worker_tasks = [
        {
            "task": (
                f"You are a Worker agent. Solve only this shard, show evidence:\n{s}"
            ),
            "files": files or {},
            "budget_tokens": budget_tokens,
        }
        for s in subtasks[: max(1, max_workers)]
    ]
    if len(subtasks) > len(worker_tasks):
        worker_tasks[-1]["task"] += "\nAlso cover: " + "; ".join(
            subtasks[len(worker_tasks):]
        )

    swarm = run_swarm(worker_tasks, max_workers=max_workers)
    trace.append({
        "step": "workers",
        "succeeded": swarm.get("succeeded", 0),
        "total": swarm.get("total", 0),
    })

    outs = [r.get("answer", "") for r in swarm.get("results", []) if r.get("answer")]
    if not outs:
        return {
            "ok": False,
            "error": "all workers failed",
            "trace": trace,
            "elapsed_s": round(time.time() - t0, 2),
        }

    verify = run_agent(
        f"{VERIFIER_SYS}\n\nORIGINAL TASK:\n{task}\n\nWORKER OUTPUTS:\n"
        + "\n\n---\n\n".join(outs[:8]),
        files or {},
        budget_tokens=budget_tokens,
    )

    trace.append({"step": "verifier"})
    return {
        "ok": True,
        "answer": verify.get("answer", ""),
        "trace": trace,
        "elapsed_s": round(time.time() - t0, 2),
    }
