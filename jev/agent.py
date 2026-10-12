#!/usr/bin/env python3
"""Agent loop: PLAN -> TOOL -> OBSERVE -> REASON -> VERIFY -> CORRECT.

Correction budget: MAX_FIXES=2 re-tries, MAX_TOOLS=6 tool calls per task.
Never loops forever. Every step is recorded in the trace; failures are
categorized (knowledge/reasoning/coding/context/tool/hallucination/
instruction/verification) for the failure-analysis loop (mission §18).
"""

import re
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
          "verify with tests. Never invent APIs, files, or results. "
          "To use a tool, emit exactly one fenced block per turn:\n"
          "```tool\n"
          '{"tool": "<name>", "args": {...}}\n'
          "```\n"
          "Tools: read_file {path}, run {argv:[...]}, "
          "see {image, question?}, imagine {prompt, out?}. "
          "After the tool result arrives, continue the task.")
TOOL_RE = re.compile(r"```tool\s*\n(.*?)```", re.DOTALL)


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


def run_tool_call(spec: dict) -> dict:
    """Execute one parsed {"tool", "args"} spec through jailed engines."""
    import json as _json
    name = spec.get("tool", "")
    args = spec.get("args", {}) or {}
    try:
        if name in tools.TOOLS:
            fn = tools.TOOLS[name]
            if name == "run" and isinstance(args, dict):
                return fn(args.get("argv", []))
            out = fn(**args) if isinstance(args, dict) else fn(args)
            return out if isinstance(out, dict) else {"ok": True, "output": out}
        if name == "see":
            from . import vision
            return vision.see(args.get("image", ""), args.get("question",
                             "Describe this image in detail."))
        if name == "imagine":
            from . import imagine
            return imagine.generate(args.get("prompt", ""), args.get("out"),
                                    args.get("steps"), args.get("width"),
                                    args.get("height"), args.get("seed", 7))
        return {"ok": False, "error": f"unknown tool: {name}"}
    except TypeError as e:
        return {"ok": False, "error": f"bad args for {name}: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def extract_tool_calls(answer: str) -> list:
    import json as _json
    calls = []
    for m in TOOL_RE.finditer(answer or ""):
        try:
            spec = _json.loads(m.group(1))
            if isinstance(spec, dict) and "tool" in spec:
                calls.append(spec)
        except Exception:
            continue
    return calls[:1]  # one tool per turn: observe before the next


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

        # ReAct tool pass: execute at most one requested tool per turn,
        # feed the observation back, and let the model continue.
        for spec in extract_tool_calls(answer):
            if tool_calls >= MAX_TOOLS:
                trace.append({"step": "budget-exhausted", "kind": "tools"})
                break
            tool_calls += 1
            out = run_tool_call(spec)
            import json as _json
            trace.append({"step": "tool", "tool": spec.get("tool"),
                          "ok": out.get("ok"), "n": tool_calls})
            messages.append({"role": "assistant", "content": answer})
            messages.append({"role": "user", "content":
                "Tool result:\n" + _json.dumps(out)[:4000] +
                "\nContinue the task using this observation."})
            answer = ""  # force another generation with the observation
            break
        if answer == "":
            continue

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

    return {"ok": True, "answer": answer, "level": r["level"],
            "backend": r["backend"].name, "fixes": fixes,
            "failure_kind": failure_kind, "tool_calls": tool_calls,
            "elapsed_s": round(time.time() - t0, 2), "trace": trace}
