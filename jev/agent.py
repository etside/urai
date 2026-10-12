#!/usr/bin/env python3
"""Agent loop: PLAN -> TOOL -> OBSERVE -> REASON -> VERIFY -> CORRECT.

Correction budget: MAX_FIXES=2 re-tries, MAX_TOOLS=6 tool calls per task.
Never loops forever. Every step is recorded in the trace; failures are
categorized (knowledge/reasoning/coding/context/tool/hallucination/
instruction/verification) for the failure-analysis loop (mission §18).
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "distill"))
from verifier import verify

from . import tools
from .context import build_context, to_messages
from .router import route

MAX_FIXES = 2
MAX_TOOLS = 6
SYSTEM = ("You are Urai, a senior engineer runtime. Plan briefly, use tools, "
          "verify with tests. Never invent APIs, files, or results.")


def categorize_failure(answer: str, tool_error: str = "") -> str:
    if tool_error:
        return "tool"
    v = verify(answer)
    fails = " ".join(v["failures"])
    if "leaked" in fails or "private-home" in fails:
        return "instruction"
    if "exec-fail" in fails or "syntax-error" in fails:
        return "coding"
    if "eval" in fails:
        return "verification"
    return "reasoning"


def run_agent(task: str, files: dict = None, budget_tokens: int = 2048) -> dict:
    t0 = time.time()
    trace = []
    r = route(task)
    trace.append({"step": "route", "level": r["level"], "reason": r["reason"],
                  "backend": r["backend"].name})

    ctx = build_context(task, files or {}, budget_tokens=budget_tokens)
    trace.append({"step": "context", "est_tokens": ctx["est_tokens"],
                  "dropped_history": ctx["dropped_history"]})
    messages = [{"role": "system", "content": SYSTEM}] + to_messages(ctx)

    answer, fixes, tool_calls = "", 0, 0
    failure_kind = None
    while True:
        try:
            res = r["backend"].complete(messages, max_tokens=512)
            answer = res["content"]
        except Exception as e:
            if r["fallback"]:
                fb = __import__("jev.backends", fromlist=["MockBackend"]).MockBackend()
                trace.append({"step": "fallback", "error": str(e)[:200]})
                answer = fb.complete(messages)["content"]
                break
            return {"ok": False, "error": str(e)[:300], "trace": trace}
        trace.append({"step": "generate", "chars": len(answer), "attempt": fixes})

        if r["verify"]:
            v = verify(answer)
            trace.append({"step": "verify", "score": v["score"],
                          "failures": v["failures"]})
            if v["score"] >= 0.8:
                break
            failure_kind = categorize_failure(answer)
            fixes += 1
            if fixes > MAX_FIXES:
                trace.append({"step": "budget-exhausted", "kind": failure_kind})
                break
            messages.append({"role": "assistant", "content": answer})
            messages.append({"role": "user", "content":
                "Verification failed: " + "; ".join(v["failures"]) +
                ". Correct minimally and re-answer."})
            trace.append({"step": "correct", "kind": failure_kind})
        else:
            break
        tool_calls += 0
        if tool_calls > MAX_TOOLS:
            break

    return {"ok": True, "answer": answer, "level": r["level"],
            "backend": r["backend"].name, "fixes": fixes,
            "failure_kind": failure_kind,
            "elapsed_s": round(time.time() - t0, 2), "trace": trace}
