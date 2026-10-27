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
from .reason import verify_answer as _verify_answer, chain_of_thought as _cot
from .skills import context_block as skills_block
from .skills import match as skills_match
from .evidence import EvidenceLedger
from .tool_guard import check_and_log as _guard_check

MAX_FIXES = 2
MAX_TOOLS = 6
SYSTEM = ("You are Urai, an AI developed by Tynio LTD. "
          "Plan briefly, use tools, verify with tests. Never invent APIs, files, or results.\n"
          "To use a tool, emit exactly one fenced block per turn:\n"
          "```tool\n"
          '{"tool": "<name>", "args": {...}}\n'
          "```\n"
          "Available tools:\n"
          "  read_file {path}  write_file {path, content}  edit_file {path, old, new}\n"
          "  run {argv:[...]}  run_code {source, language?}  analyze {target}\n"
          "  web_search {query}  web_fetch {url}  research {query, depth?}\n"
          "  see {image, question?}  imagine {prompt, out?}\n"
          "  artifact {kind, content, name?}  (kind: code|markdown|html|svg|csv|json)\n"
          "  remember {text, kind?}  recall {query, top?}\n"
          "  mcp {server, tool, args}  browse {goal, steps:[...]}\n"
          "Tiers: urai-fast (quick) urai (balanced) urai-ultra (deep reasoning+verify) urai-cyber (security)\n"
          "For hard questions use chain-of-thought: think step by step before answering.\n"
          "After every tool result, continue the task until done.")
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


def run_tool_call(spec: dict, plan: bool = False,
                  ledger: 'EvidenceLedger | None' = None) -> dict:
    """Execute one parsed {"tool", "args"} spec through jailed engines.
    plan=True: write/edit calls are recorded as proposals, NOT applied."""
    # Security guard
    _tname = spec.get('tool', '')
    _targs = spec.get('args', {}) or {}
    _guard = _guard_check(_tname, _targs if isinstance(_targs, dict) else {})
    if not _guard.get('allowed', True):
        return {'ok': False, 'error': f'Tool blocked ({_guard["risk"]}): {_guard["reason"]}',
                'blocked': True}
    # Record in evidence ledger if provided
    if ledger is not None:
        pass  # will record after execution below
    import json as _json
    name = spec.get("tool", "")
    args = spec.get("args", {}) or {}
    if plan and name in ("write_file", "edit_file"):
        return {"ok": True, "plan_only": True, "proposal": spec}
    try:
        if name == "run_code":
            return tools.TOOLS["run_code"](
                source=args.get("source", ""),
                language=args.get("language", "python"),
                stdin=args.get("stdin", ""),
            )
        if name == "research":
            return tools.TOOLS["research"](
                query=args.get("query", ""),
                depth=int(args.get("depth", 3)),
            )
        if name == "artifact":
            return tools.TOOLS["artifact"](
                kind=args.get("kind", "text"),
                content=args.get("content", ""),
                name=args.get("name", ""),
                language=args.get("language", ""),
            )
        if name == "remember":
            return tools.TOOLS["remember"](args.get("text",""), args.get("kind","fact"))
        if name == "recall":
            return tools.TOOLS["recall"](args.get("query",""), int(args.get("top",3)))
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


def run_agent(task: str, files: dict = None, budget_tokens: int = 2048,
                consistency: int = 1, plan: bool = False,
                history: list = None, tier: str = "urai") -> dict:
    t0 = time.time()
    trace = []
    from .router import apply_tier as _apply_tier
    _tier = _apply_tier(tier)
    if tier and tier != "urai":
        consistency = max(int(consistency or 1), int(_tier["consistency"]))
        trace.append({"step": "tier", "tier": tier})
    r = route(task, tier=tier)
    trace.append({"step": "route", "level": r["level"], "reason": r["reason"],
                  "backend": r["backend"].name})

    ctx = build_context(task, files or {}, budget_tokens=budget_tokens,
                          history=history or [])
    trace.append({"step": "context", "est_tokens": ctx["est_tokens"],
                  "dropped_history": ctx["dropped_history"]})
    messages = [{"role": "system", "content": SYSTEM}] + to_messages(ctx)
    # Repo conventions: AGENTS.md auto-load (OpenCode-style).
    try:
        from .tools import WORKSPACE as _WS
        import os as _os
        _ag = _os.path.join(_WS, "AGENTS.md")
        if _os.path.isfile(_ag):
            with open(_ag) as _f:
                _txt = _f.read(4000)
            if _txt.strip():
                messages.append({"role": "system",
                                 "content": "Repo conventions (AGENTS.md):\n" + _txt})
                trace.append({"step": "agents-md", "chars": len(_txt)})
    except Exception as e:
        trace.append({"step": "agents-md-skip", "error": str(e)[:120]})
    loaded = skills_match(task)
    if loaded:
        messages.append({"role": "system",
                         "content": "Loaded skills (follow them):\n"
                         + skills_block(task)})
        trace.append({"step": "skills",
                      "loaded": [s["name"] for s in loaded]})
    # Active memory + focus (Wonder-style): recall relevant memories and the
    # current focus anchor into every run. Never fails the run.
    try:
        from .memory import recall as _recall
        _mems = _recall(task, top=3)
        if _mems:
            messages.append({"role": "system",
                             "content": "Active memory (use if relevant):\n" + "\n".join(
                                 f"- [{m['kind']}] {m['text']}" for m in _mems)})
            trace.append({"step": "memory", "recalled": len(_mems)})
    except Exception as e:
        trace.append({"step": "memory-skip", "error": str(e)[:120]})
    try:
        from .focus import context_block as _focus_block
        _fb = _focus_block()
        if _fb:
            messages.append({"role": "system", "content": _fb})
            trace.append({"step": "focus", "chars": len(_fb)})
    except Exception as e:
        trace.append({"step": "focus-skip", "error": str(e)[:120]})
    # Few-shot memory: solved examples promoted from landed distill chunks.
    # This is how each chunk immediately improves answers (no retraining).
    if r["level"] >= 1:
        try:
            from .fewshots import context_block as few_block
            fb = few_block(task)
            if fb:
                messages.append({"role": "system", "content": fb})
                trace.append({"step": "fewshots", "chars": len(fb)})
        except Exception as e:
            trace.append({"step": "fewshots-skip", "error": str(e)[:120]})

    answer, fixes, tool_calls = "", 0, 0
    failure_kind = None
    proposals = []
    if plan:
        trace.append({"step": "plan-mode",
                      "note": "writes recorded, not applied"})
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
            out = run_tool_call(spec, plan=plan)
            if out.get("plan_only"):
                proposals.append(spec)
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

    # Self-consistency re-rank (opt-in): extra samples at temp 0.7,
    # keep the highest verifier score. Default 1 = unchanged behavior.
    tried = 1
    if consistency and int(consistency) > 1 and r["verify"] and answer:
        try:
            best, best_score = answer, verify(answer)["score"]
            for _ in range(min(int(consistency) - 1, 4)):
                cand = r["backend"].complete(messages, max_tokens=512,
                                             temperature=0.7)["content"]
                tried += 1
                sc = verify(cand)["score"]
                if sc > best_score:
                    best, best_score = cand, sc
            answer = best
            trace.append({"step": "consistency", "tried": tried,
                          "best_score": best_score})
        except Exception as e:
            trace.append({"step": "consistency-skip",
                          "error": str(e)[:120]})

    try:
        from .router import record_outcome as _rec
        _rec(r["level"], getattr(r["backend"], "name", "?"), bool(answer))
    except Exception:
        pass
    return {"ok": True, "answer": answer, "proposals": proposals, "tier": r.get("tier", "urai"),
            "level": r["level"],
            "backend": r["backend"].name, "fixes": fixes,
            "failure_kind": failure_kind, "tool_calls": tool_calls,
            "elapsed_s": round(time.time() - t0, 2), "trace": trace}
