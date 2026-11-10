#!/usr/bin/env python3
"""Swarm: Kimi/Hermes-style multi-agent fan-out for Urai (stdlib only).

`run_swarm(tasks)` executes N agent tasks concurrently (threads), each with
its own plan/tool/verify budget via jev.agent.run_agent, then aggregates:
per-task answer + trace summary + swarm-level stats. Failures are isolated:
one task failing never blocks the others.

Use:
  from jev.swarm import run_swarm
  run_swarm(["summarise X", {"task": "write tests", "budget_tokens": 4096}],
            max_workers=3)
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .agent import run_agent

DEFAULT_WORKERS = 3
MAX_TASKS = 8


def _normalize(task):
    if isinstance(task, str):
        return {"task": task, "files": {}, "budget_tokens": 2048}
    t = dict(task)
    return {"task": t.get("task", ""), "files": t.get("files", {}),
            "budget_tokens": int(t.get("budget_tokens", 2048))}


def _run_one(item):
    idx, spec = item
    t0 = time.time()
    try:
        r = run_agent(spec["task"], spec["files"], spec["budget_tokens"])
        r["swarm_index"] = idx
        r["swarm_elapsed_s"] = round(time.time() - t0, 2)
        return r
    except Exception as e:
        return {"ok": False, "swarm_index": idx, "error": str(e)[:300],
                "answer": "", "elapsed_s": round(time.time() - t0, 2)}


def run_swarm(tasks, max_workers=DEFAULT_WORKERS) -> dict:
    t0 = time.time()
    specs = [_normalize(t) for t in (tasks or [])][:MAX_TASKS]
    if not specs:
        return {"ok": False, "error": "no tasks given", "results": []}
    workers = max(1, min(int(max_workers or DEFAULT_WORKERS), len(specs), MAX_TASKS))
    results = [None] * len(specs)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_run_one, (i, s)): i for i, s in enumerate(specs)}
        for f in as_completed(futs):
            try:
                r = f.result()
            except Exception as e:
                r = {"ok": False, "swarm_index": futs[f], "error": str(e)[:300]}
            results[r.get("swarm_index", futs[f])] = r
    ok_n = sum(1 for r in results if r and r.get("ok"))
    return {"ok": ok_n > 0, "total": len(results), "succeeded": ok_n,
            "failed": len(results) - ok_n, "workers": workers,
            "elapsed_s": round(time.time() - t0, 2), "results": results}
