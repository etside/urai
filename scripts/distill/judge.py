#!/usr/bin/env python3
"""LLM-judge second signal for text-only tasks (mission: don't lose them).

Rule: execution/static checks stay the gatekeeper for code. The judge only
scores completions with NO executable artifacts (score would be neutral
0.5). If no judge teacher is configured, returns neutral with a tag so the
pipeline stays fully offline-capable.
"""

import json


def judge(task: dict, completion: str, teacher=None) -> dict:
    rubric = task.get("judge_rubric", "")
    if not rubric:
        return {"score": 0.5, "reasons": ["no-rubric"], "judge": "none"}
    if teacher is None or getattr(teacher, "name", "") == "mock-v1":
        return {"score": 0.5, "reasons": ["no-judge-available"], "judge": "none"}
    prompt = (
        "Score this completion 0.0-1.0 against the rubric. "
        "Reply ONLY as JSON {\"score\": <float>, \"reasons\": [<str>]}.\n\n"
        f"RUBRIC: {rubric}\n\nTASK: {task['prompt']}\n\nCOMPLETION:\n{completion}"
    )
    try:
        out = teacher.generate({"id": "judge", "prompt": prompt,
                                "system": "You are a strict evaluator. JSON only."})
        txt = out.content
        import re as _re
        txt = _re.sub(r"<think>.*?</think>", "", txt, flags=_re.DOTALL)
        txt = _re.sub(r"```think.*?```", "", txt, flags=_re.DOTALL)
        m = _re.search(r"\{[^{}]*\}", txt, _re.DOTALL)
        data = json.loads(m.group(0) if m else txt.strip().strip("`").replace("json\n", ""))
        s = max(0.0, min(1.0, float(data.get("score", 0.5))))
        return {"score": round(s, 3), "reasons": data.get("reasons", []),
                "judge": getattr(teacher, "name", "unknown")}
    except Exception as e:
        return {"score": 0.5, "reasons": [f"judge-error: {e}"], "judge": "error"}
