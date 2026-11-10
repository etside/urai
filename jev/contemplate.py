#!/usr/bin/env python3
"""Contemplating mode: parallel multi-agent reasoning with a judge merge.

Three agent branches (analytical, creative, skeptical) run concurrently
via swarm.run_swarm(), then a judge agent merges their answers into one.

Each branch uses a different system-prompt seed, and all emit events via
jev.events so the Studio event log can show progress in real time.

Stdlib only — relies on jev.swarm.run_swarm and jev.agent.run_agent.
"""
from __future__ import annotations
import time

from .swarm import run_swarm

SEEDS = {
    "analytical": (
        "You are Urai in analytical mode. Focus on facts, logic, and evidence. "
        "Break down the problem systematically. Cite specifics. "
        "Be precise and structured."
    ),
    "creative": (
        "You are Urai in creative mode. Explore novel angles, analogies, and "
        "unexpected connections. Think laterally. "
        "Offer fresh perspectives while staying grounded."
    ),
    "skeptical": (
        "You are Urai in skeptical mode. Challenge assumptions, identify "
        "weaknesses, and consider what could go wrong. "
        "Stress-test the reasoning. Be constructive but critical."
    ),
}

JUDGE_SYSTEM = (
    "You are Urai in judge mode. Three expert advisors have answered a "
    "question. Merge their answers into one best answer that captures "
    "the strongest insights and corrects any errors. "
    "Do not mention the advisors — present the merged answer directly."
)


def contemplate(messages, max_tokens: int = 1024, session_id: str = "") -> dict:
    """Run three parallel reasoning branches and merge via a judge.

    Args:
        messages: list of {role, content} dicts (OpenAI format)
        max_tokens: token budget per branch
        session_id: for event log correlation

    Returns:
        {ok, answer, thinking_traces, judge_trace, elapsed_s}
    """
    from .events import emit as _emit
    from .agent import run_agent as _run_agent

    t0 = time.time()

    # Extract the user's question text
    prompt_text = ""
    for m in reversed(messages or []):
        if m.get("role") == "user":
            prompt_text = m.get("content", "")
            break
    if not prompt_text:
        return {"ok": False, "error": "no user message found", "answer": ""}

    # Build three swarm tasks, one per seed
    tasks = [
        {"task": prompt_text, "system_override": seed, "budget_tokens": max_tokens}
        for seed in SEEDS.values()
    ]

    _emit(session_id, "contemplate_start", "contemplate",
          tool="swarm", input_summary=prompt_text[:200],
          output_summary="3 branches", status=True)

    swarm_result = run_swarm(tasks, max_workers=3)

    # Collect branch answers
    traces = []
    for i, r in enumerate(swarm_result.get("results", [])):
        if r is None:
            continue
        answer = r.get("answer", "")
        seed_name = list(SEEDS.keys())[i] if i < len(SEEDS) else f"branch_{i}"
        traces.append({"seed": seed_name, "answer": answer,
                       "ok": r.get("ok", False),
                       "elapsed_s": r.get("swarm_elapsed_s", 0)})
        _emit(session_id, "contemplate_branch", f"branch:{seed_name}",
              tool="run_agent", input_summary=prompt_text[:120],
              output_summary=answer[:200], status=r.get("ok", False))

    # Judge merge
    branch_texts = "\n".join(
        f"{i+1}. {t['answer']}" for i, t in enumerate(traces) if t.get("answer")
    )
    judge_task = (
        "Merge these three expert answers into one best answer.\n\n"
        f"{branch_texts}\n\n"
        f"Original question: {prompt_text}\n\n"
        "Provide the merged answer directly."
    )
    _emit(session_id, "contemplate_judge", "judge",
          tool="run_agent", input_summary=judge_task[:200],
          output_summary="merging", status=True)

    judge_result = _run_agent(judge_task, system_override=JUDGE_SYSTEM,
                              budget_tokens=max_tokens)
    merged = judge_result.get("answer", "")

    _emit(session_id, "contemplate_done", "contemplate",
          tool="judge", input_summary=judge_task[:120],
          output_summary=merged[:200], status=bool(merged))

    return {
        "ok": bool(merged),
        "answer": merged,
        "thinking_traces": traces,
        "judge_trace": {"answer": merged, "ok": judge_result.get("ok", False)},
        "elapsed_s": round(time.time() - t0, 2),
    }
