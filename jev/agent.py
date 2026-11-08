#!/usr/bin/env python3
"""Agent loop: PLAN -> TOOL -> OBSERVE -> REASON -> VERIFY -> CORRECT.

Correction budget: MAX_FIXES=2 re-tries, MAX_TOOLS=6 tool calls per task.
Never loops forever. Every step is recorded in the trace; failures are
categorized (knowledge/reasoning/coding/context/tool/hallucination/
instruction/verification) for the failure-analysis loop (mission §18).
"""

import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "distill"))
from verifier import verify

from . import tools
from .context import build_context, to_messages
from .router import route
from .skills import context_block as skills_block
from .skills import match as skills_match

MAX_FIXES = 2
MAX_TOOLS = 6
SYSTEM = ("You are Urai, developed by Tynio LTD, a senior engineer runtime. Plan briefly, use tools, "
          "verify with tests. Never invent APIs, files, or results. "
          "To use a tool, emit exactly one fenced block per turn:\n"
          "```tool\n"
          '{"tool": "<name>", "args": {...}}\n'
          "```\n"
          "Tiers: urai-fast (quick), urai (balanced), urai-ultra (quality), "
          "urai-cyber (security). Conductor splits hard tasks automatically. "
          "Tools: read_file {path}, write_file {path, content}, "
          "edit_file {path, old, new, replace_all?}, run {argv:[...]}, analyze {target}, "
          "mcp_servers {server?}, mcp {server, tool, args}, "
          "web_search {query, top?}, web_fetch {url}, "
          "see {image, question?}, imagine {prompt, out?}, "
          "browse {goal, steps:[{action: goto|click|fill|wait|snapshot|screenshot, url?, selector?, text?, value?}]}. "
          "browse pauses (never fails) on auth fields so the human can input them. "
          "After the tool result arrives, continue the task.")
TOOL_RE = re.compile(r"```tool\s*\n(.*?)```", re.DOTALL)


def _tools_schema() -> list:
    """Return OpenAI function-calling tool objects for all available work tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read the contents of a file at the given path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path to read"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write content to a file, creating or overwriting it.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path to write"},
                        "content": {"type": "string", "description": "Content to write"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "edit_file",
                "description": "Edit a file by replacing old text with new text.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path to edit"},
                        "old": {"type": "string", "description": "Text to replace"},
                        "new": {"type": "string", "description": "Replacement text"},
                        "replace_all": {"type": "boolean", "description": "Replace all occurrences"},
                    },
                    "required": ["path", "old", "new"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run",
                "description": "Run a shell command specified as an argument vector.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "argv": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Command and arguments as a list",
                        },
                    },
                    "required": ["argv"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web for information.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "top": {"type": "integer", "description": "Number of top results to return"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "web_fetch",
                "description": "Fetch and extract text content from a URL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to fetch"},
                    },
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "browse",
                "description": "Control a browser to accomplish a goal via a sequence of steps.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "goal": {"type": "string", "description": "The browsing goal"},
                        "steps": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "action": {"type": "string", "enum": ["goto", "click", "fill", "wait", "snapshot", "screenshot"]},
                                    "url": {"type": "string"},
                                    "selector": {"type": "string"},
                                    "text": {"type": "string"},
                                    "value": {"type": "string"},
                                },
                                "required": ["action"],
                            },
                            "description": "List of browser actions",
                        },
                    },
                    "required": ["goal", "steps"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "see",
                "description": "Analyze or describe an image.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "image": {"type": "string", "description": "Image path or URL"},
                        "question": {"type": "string", "description": "Question about the image"},
                    },
                    "required": ["image"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "imagine",
                "description": "Generate an image from a text prompt.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Image generation prompt"},
                        "out": {"type": "string", "description": "Output file path"},
                    },
                    "required": ["prompt"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "mcp",
                "description": "Call a tool on an MCP server.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "server": {"type": "string", "description": "MCP server name"},
                        "tool": {"type": "string", "description": "Tool name on the server"},
                        "args": {"type": "object", "description": "Arguments for the tool"},
                    },
                    "required": ["server", "tool", "args"],
                },
            },
        },
    ]


def _plan_schema() -> list:
    """Return OpenAI function-calling tool objects for plan management tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": "create_plan",
                "description": "Create a structured plan with a title, goal, and ordered steps.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Short plan title"},
                        "goal": {"type": "string", "description": "Overall goal of the plan"},
                        "steps": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string", "description": "Unique step identifier"},
                                    "description": {"type": "string", "description": "What this step does"},
                                },
                                "required": ["id", "description"],
                            },
                            "description": "Ordered list of plan steps",
                        },
                    },
                    "required": ["title", "goal", "steps"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "complete_step",
                "description": "Mark a plan step as completed or failed.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "step_id": {"type": "string", "description": "ID of the step to complete"},
                        "success": {"type": "boolean", "description": "Whether the step succeeded"},
                        "result": {"type": "string", "description": "Result or error message"},
                    },
                    "required": ["step_id", "success", "result"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "deliver_result",
                "description": "Deliver the final answer and end the agent loop.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "answer": {"type": "string", "description": "The final answer to deliver"},
                    },
                    "required": ["answer"],
                },
            },
        },
    ]

SAFETY_REPLY = {
    "self-harm": (
        "I can't help with that. If you're thinking about harming yourself, "
        "please reach out to a local crisis line or emergency services right "
        "now — you deserve support."),
    "weapon": (
        "I can't help build weapons or explosives. I can help with chemistry, "
        "engineering, or safety topics in a constructive way."),
    "csam": (
        "I can't help with that request."),
}
_SAFETY_DEFAULT = "I can't help with that request."



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


def run_tool_call(spec: dict, plan: bool = False) -> dict:
    """Execute one parsed {"tool", "args"} spec through jailed engines.
    plan=True: write/edit calls are recorded as proposals, NOT applied."""
    import json as _json
    name = spec.get("tool", "")
    args = spec.get("args", {}) or {}
    if plan and name in ("write_file", "edit_file"):
        return {"ok": True, "plan_only": True, "proposal": spec}
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


def run_agent(task: str, files: dict = None, budget_tokens: int = 2048,
                consistency: int = 1, plan: bool = False,
                history: list = None, tier: str = "urai",
                event_queue=None) -> dict:
    t0 = time.time()
    trace = []
    from .router import apply_tier as _apply_tier
    _tier = _apply_tier(tier)
    if tier and tier != "urai":
        consistency = max(int(consistency or 1), int(_tier["consistency"]))
        trace.append({"step": "tier", "tier": tier})

    # ── NLP + vibe (Phase 2): understand the request and fix a style contract
    # BEFORE generation. Deterministic; never fails the run.
    nlp_out, vibe_out = {}, {}
    try:
        from . import nlp as _nlp
        nlp_out = _nlp.analyze(task, history=history)
        trace.append({"step": "nlp", "language": nlp_out.get("language"),
                      "intent": nlp_out.get("intent"),
                      "sentiment": (nlp_out.get("sentiment") or {}).get("label"),
                      "emotion": nlp_out.get("emotion"),
                      "complexity": nlp_out.get("complexity"),
                      "redflags": nlp_out.get("redflags")})
    except Exception as e:
        trace.append({"step": "nlp-skip", "error": str(e)[:120]})
    try:
        from . import vibe as _vibe
        if _vibe.enabled():
            vibe_out = _vibe.plan(nlp_out)
            if vibe_out:
                vibe_out["nlp"] = nlp_out
                vibe_out["directive"] = _vibe.directive(vibe_out)
                trace.append({"step": "vibe",
                              "structure": vibe_out.get("structure"),
                              "formatting": vibe_out.get("formatting"),
                              "language": vibe_out.get("language"),
                              "de-escalate": vibe_out.get("de-escalate")})
    except Exception as e:
        trace.append({"step": "vibe-skip", "error": str(e)[:120]})

    # ── Safety gate: refuse clearly-harmful intents without calling a model.
    _flags = nlp_out.get("redflags") or []
    if _flags:
        trace.append({"step": "safety", "redflags": _flags, "action": "refuse"})
        if isinstance(vibe_out, dict):
            vibe_out.setdefault("de-escalate", True)
        msg = SAFETY_REPLY.get(_flags[0], _SAFETY_DEFAULT)
        if "self-harm" in _flags:
            msg = SAFETY_REPLY["self-harm"]
        return {"ok": True, "answer": msg, "proposals": [], "tier": tier or "urai",
                "level": 0, "backend": "safety", "fixes": [], "failure_kind": None,
                "tool_calls": [], "elapsed_s": round(time.time() - t0, 2),
                "trace": trace, "refused": True,
                "urai": {"nlp": nlp_out, "vibe": vibe_out}}

    r = route(task, tier=tier, complexity=nlp_out.get("complexity"))
    trace.append({"step": "route", "level": r["level"], "reason": r["reason"],
                  "backend": r["backend"].name})

    ctx = build_context(task, files or {}, budget_tokens=budget_tokens,
                          history=history or [])
    trace.append({"step": "context", "est_tokens": ctx["est_tokens"],
                  "dropped_history": ctx["dropped_history"]})
    messages = [{"role": "system", "content": SYSTEM}] + to_messages(ctx)
    if vibe_out.get("directive"):
        messages.append({"role": "system", "content": vibe_out["directive"]})
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
    # Active memory + focus (Wonder-style): hybrid semantic recall over the
    # memory/focus index (retrieval.query combines relevance + recency) and the
    # current focus anchor into every run. Never fails the run.
    try:
        from . import config as _config
        _cfg = _config.get()
    except Exception:
        _cfg = None
    _mem_enabled = _cfg.MEMORY_ENABLED if _cfg is not None else True
    if _mem_enabled:
        try:
            from . import retrieval as _retrieval
            _mems = _retrieval.query(task, top_k=(_cfg.RETRIEVAL_TOP_K
                                                  if _cfg is not None else 5))
            if _mems:
                messages.append({"role": "system",
                                 "content": "Retrieved memory (use if relevant):\n"
                                 + "\n".join(
                                     f"- [{m['kind']}/{m['source']}] {m['text']}"
                                     for m in _mems)})
                trace.append({"step": "retrieval", "recalled": len(_mems),
                              "top_score": _mems[0]["score"],
                              "top_relevance": _mems[0]["relevance"],
                              "top_recency": _mems[0]["recency"]})
        except Exception as e:
            try:
                from .memory import recall as _recall
                _mems = _recall(task, top=3)
                if _mems:
                    messages.append({"role": "system",
                                     "content": "Active memory (use if relevant):\n"
                                     + "\n".join(f"- [{m['kind']}] {m['text']}"
                                                 for m in _mems)})
                    trace.append({"step": "memory", "recalled": len(_mems)})
            except Exception as e2:
                trace.append({"step": "retrieval-skip", "error": str(e2)[:120]})
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
    _plan_state = {}  # local plan state for native tools path
    _native = os.environ.get("URAI_NATIVE_TOOLS", "0") == "1"
    if plan:
        trace.append({"step": "plan-mode",
                      "note": "writes recorded, not applied"})
    while True:
        try:
            from . import cache as _cache
            if _native:
                _all_tools = _tools_schema() + _plan_schema()
                res = _cache.cached_complete(r["backend"], messages,
                                             max_tokens=512,
                                             tools=_all_tools)
            else:
                res = _cache.cached_complete(r["backend"], messages, max_tokens=512)
            answer = res["content"]
        except Exception as e:
            if r["fallback"]:
                fb = __import__("jev.backends", fromlist=["MockBackend"]).MockBackend()
                trace.append({"step": "fallback", "error": str(e)[:200]})
                answer = fb.complete(messages)["content"]
                break
            return {"ok": False, "error": str(e)[:300], "trace": trace}
        trace.append({"step": "generate", "chars": len(answer),
                      "attempt": fixes, "cached": bool(res.get("cached")),
                      "cache_hit": res.get("cache_hit")})

        # ── Native function-calling path (URAI_NATIVE_TOOLS=1)
        import json as _json
        if _native and res.get("tool_calls"):
            tc = res["tool_calls"][0]
            fn_name = tc.get("function", {}).get("name", "")
            raw_args = tc.get("function", {}).get("arguments", "{}")
            tool_call_id = tc.get("id", "")
            try:
                fn_args = _json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except Exception:
                fn_args = {}
            spec = {"tool": fn_name, "args": fn_args}

            # Emit pre-call tool event
            if event_queue is not None:
                try:
                    event_queue.put_nowait({
                        "type": "tool",
                        "tool_call_id": tool_call_id,
                        "function_name": fn_name,
                        "args_brief": str(fn_args)[:120],
                        "status": "calling",
                        "brief": "",
                    })
                except Exception:
                    pass

            # Handle plan tools inline
            if fn_name == "create_plan":
                steps_data = fn_args.get("steps", [])
                _plan_state = {
                    "title": fn_args.get("title", ""),
                    "goal": fn_args.get("goal", ""),
                    "steps": [{"id": s.get("id", ""), "description": s.get("description", ""),
                               "status": "pending"} for s in steps_data],
                }
                if event_queue is not None:
                    try:
                        event_queue.put_nowait({
                            "type": "plan",
                            "title": _plan_state["title"],
                            "goal": _plan_state["goal"],
                            "steps": list(_plan_state["steps"]),
                        })
                    except Exception:
                        pass
                out = {"ok": True, "plan": _plan_state}
                trace.append({"step": "plan-create", "title": _plan_state.get("title"),
                               "n_steps": len(_plan_state.get("steps", []))})
            elif fn_name == "complete_step":
                step_id = fn_args.get("step_id", "")
                success = bool(fn_args.get("success", True))
                result_txt = fn_args.get("result", "")
                status = "completed" if success else "failed"
                for s in _plan_state.get("steps", []):
                    if s["id"] == step_id:
                        s["status"] = status
                        break
                if event_queue is not None:
                    try:
                        event_queue.put_nowait({
                            "type": "step",
                            "step_id": step_id,
                            "status": status,
                            "result": result_txt,
                        })
                    except Exception:
                        pass
                out = {"ok": True, "step_id": step_id, "status": status}
                trace.append({"step": "plan-complete-step", "step_id": step_id, "success": success})
            elif fn_name == "deliver_result":
                answer = fn_args.get("answer", "")
                if event_queue is not None:
                    try:
                        event_queue.put_nowait({
                            "type": "tool",
                            "tool_call_id": tool_call_id,
                            "function_name": fn_name,
                            "args_brief": str(fn_args)[:120],
                            "status": "called",
                            "brief": str(answer)[:200],
                        })
                    except Exception:
                        pass
                trace.append({"step": "deliver-result", "chars": len(answer)})
                break
            else:
                # Regular tool call
                if tool_calls >= MAX_TOOLS:
                    trace.append({"step": "budget-exhausted", "kind": "tools"})
                    break
                tool_calls += 1
                out = run_tool_call(spec, plan=plan)
                if out.get("plan_only"):
                    proposals.append(spec)
                trace.append({"step": "tool", "tool": spec.get("tool"),
                              "ok": out.get("ok"), "n": tool_calls})
                if event_queue is not None:
                    try:
                        event_queue.put_nowait({
                            "type": "tool",
                            "tool_call_id": tool_call_id,
                            "function_name": fn_name,
                            "args_brief": str(fn_args)[:120],
                            "status": "called",
                            "brief": str(out)[:200],
                        })
                    except Exception:
                        pass

            messages.append({"role": "assistant", "content": answer,
                             "tool_calls": res.get("tool_calls", [])})
            messages.append({"role": "tool", "tool_call_id": tool_call_id,
                             "content": _json.dumps(out)[:4000]})
            answer = ""
            continue

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
            if event_queue is not None:
                try:
                    event_queue.put_nowait({
                        "type": "tool",
                        "tool_call_id": "",
                        "function_name": spec.get("tool", ""),
                        "args_brief": str(spec.get("args", {}))[:120],
                        "status": "called",
                        "brief": str(out)[:200],
                    })
                except Exception:
                    pass
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
            from . import cache as _cache2
            for _ in range(min(int(consistency) - 1, 4)):
                cand = _cache2.cached_complete(r["backend"], messages,
                                               max_tokens=512,
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
            "elapsed_s": round(time.time() - t0, 2), "trace": trace,
            "urai": {"nlp": nlp_out, "vibe": vibe_out}}
