#!/usr/bin/env python3
"""Context manager: token budgeting + intelligent truncation (mission §13).

Never blindly cut from the front. Priority preserved:
  user requirements > active files/errors > API contracts > decisions >
  task state > old history (compressed first, dropped last).
Token estimate: ~4 chars/token (documented approximation).
"""

EST_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // EST_CHARS_PER_TOKEN)


def build_context(requirements: str, files: dict = None, errors: str = "",
                  contracts: str = "", decisions: str = "",
                  history: list = None, budget_tokens: int = 2048) -> dict:
    files = files or {}
    history = history or []
    # Fixed priority sections; history is the elastic one.
    sections = [
        ("requirements", requirements or ""),
        ("errors", errors or ""),
        ("contracts", contracts or ""),
        ("decisions", decisions or ""),
    ]
    file_text = "\n\n".join(f"--- {p} ---\n{c}" for p, c in files.items())
    if file_text:
        sections.insert(1, ("active_files", file_text))

    used = sum(estimate_tokens(s) for _, s in sections)
    hist_budget = max(0, budget_tokens - used)
    kept_history, dropped = [], 0
    # newest-first fill of the remaining budget (compress = keep head/tail)
    for msg in reversed(history):
        t = estimate_tokens(msg.get("content", ""))
        if t <= hist_budget:
            kept_history.append(msg)
            hist_budget -= t
        else:
            dropped += 1
    kept_history.reverse()

    total = used + sum(estimate_tokens(m.get("content", "")) for m in kept_history)
    return {"sections": [(k, v) for k, v in sections if v],
            "history": kept_history, "dropped_history": dropped,
            "est_tokens": total, "budget_tokens": budget_tokens,
            "over_budget": total > budget_tokens}


def to_messages(ctx: dict) -> list:
    parts = [f"[{name.upper()}]\n{body}" for name, body in ctx["sections"]]
    msgs = []
    for m in ctx["history"]:
        msgs.append({"role": m.get("role", "user"), "content": m["content"]})
    msgs.append({"role": "user",
                 "content": "\n\n".join(parts) or "(no context)"})
    return msgs
