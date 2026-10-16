#!/usr/bin/env python3
"""Conductor: Fugu-style role orchestration over the local pool (stdlib only).

Thinker decomposes -> Workers execute shards in parallel -> Verifier merges.
One model pool, one endpoint, no API keys: roles are prompt-specialized runs
of the local student (teacher-backed only when TEACHER_* is configured).

Use: run_conductor(task, files, budget_tokens) or /agent/swarm {"mode":"conductor"}.
"""
import json
import re
import time

from .agent import run_agent
from .swarm import run_swarm

THINKER_SYS = ("You decompose complex tasks. Reply ONLY as a JSON array of "
               '2-6 short independent subtask strings, e.g. ["...","..."]. '
               "No prose, no markdown fences.")
VERIFIER_SYS = ("You merge worker outputs into one final answer. Drop "
                "contradictions, keep verified claims, stay concise.")


def _parse_subtasks(text: str, fallback: str):
    try:
        m = re.search(r"\[.*\]", text or "", re.DOTALL)
        items = json.loads(m.group(0)) if m else []
        items = [str(x).strip() for x in items if str(x).strip()][:6]
        if len(items) >= 2:
            return items
    except Exception:
        pass
    return [fallback]


def run_conductor(task: str, files: dict = None, budget_tokens: int = 2048,
                  max_workers: int = 3) -> dict:
    t0 = time.time()
    trace = [{"step": "conductor-start"}]
    think = run_agent(f"{THINKER_SYS}\n\nTASK:\n{task}",
                      files or {}, budget_tokens=1024)
    subtasks = _parse_subtasks(think.get("answer", ""), task)
    trace.append({"step": "thinker", "subtasks": len(subtasks)})
    worker_tasks = [{"task": f"You are a Worker agent. Solve only this shard, "
                             f"show evidence:\n{s}",
                     "files": files or {}, "budget_tokens": budget_tokens}
                    for s in subtasks[:max(1, max_workers)]]
    if len(subtasks) > len(worker_tasks):
        worker_tasks[-1]["task"] += "\nAlso cover: " + "; ".join(subtasks[len(worker_tasks):])
    swarm = run_swarm(worker_tasks, max_workers=max_workers)
    trace.append({"step": "workers", "succeeded": swarm.get("succeeded", 0),
                  "total": swarm.get("total", 0)})
    outs = [r.get("answer", "") for r in swarm.get("results", []) if r.get("answer")]
    if not outs:
        return {"ok": False, "error": "all workers failed", "trace": trace,
                "elapsed_s": round(time.time() - t0, 2)}
    verify = run_agent(
        f"{VERIFIER_SYS}\n\nORIGINAL TASK:\n{task}\n\nWORKER OUTPUTS:\n"
        + "\n\n---\n\n".join(outs[:8]),
        files or {}, budget_tokens=budget_tokens)
    trace.append({"step": "verifier", "fixes": verify.get("fixes", 0)})
    return {"ok": True, "answer": verify.get("answer", ""),
            "mode": "conductor", "subtasks": subtasks,
            "workers": {"succeeded": swarm.get("succeeded", 0),
                        "total": swarm.get("total", 0)},
            "elapsed_s": round(time.time() - t0, 2), "trace": trace}
