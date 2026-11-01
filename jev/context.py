"""
jev/context.py — Context builder for Urai.

Upgraded to support RAG injection and history compression.

Env gate: set URAI_NEURO=1 to enable RAG retrieval on every build_context() call.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

EST_CHARS_PER_TOKEN: float = 3.5

# ---------------------------------------------------------------------------
# RAG injection (graceful degradation when URAI_NEURO is not set)
# ---------------------------------------------------------------------------

_NEURO_ENABLED = os.environ.get("URAI_NEURO", "0") == "1"


def _try_rag_context(query: str, max_chars: int = 2000) -> str:
    """Return RAG context string or empty string if unavailable."""
    if not _NEURO_ENABLED:
        return ""
    try:
        from jev import rag as _rag  # lazy import keeps startup fast
        return _rag.context_for(query, max_chars=max_chars)
    except Exception:  # pragma: no cover
        return ""


# ---------------------------------------------------------------------------
# History compression
# ---------------------------------------------------------------------------

def compress_history(
    messages: List[Dict[str, Any]],
    budget_chars: int,
) -> List[Dict[str, Any]]:
    """
    Reduce *messages* to fit within *budget_chars* (approximate).

    Strategy:
      1. Always keep the system message (if any) at index 0.
      2. Always keep the last N user/assistant pairs that fit.
      3. Summarise the middle by extracting the first sentence of each turn.

    Parameters
    ----------
    messages     : list of {role, content} dicts
    budget_chars : soft char budget

    Returns
    -------
    Possibly-shortened messages list.
    """
    if not messages:
        return messages

    total = sum(len(m.get("content", "")) for m in messages)
    if total <= budget_chars:
        return messages  # already fits

    system_msgs = [m for m in messages if m.get("role") == "system"]
    convo = [m for m in messages if m.get("role") != "system"]

    # Always keep last 4 messages (2 pairs) verbatim.
    keep_tail = convo[-4:] if len(convo) >= 4 else convo
    middle = convo[: max(0, len(convo) - 4)]

    # Summarise middle: first sentence of each turn.
    summarised: List[Dict[str, Any]] = []
    for msg in middle:
        content = msg.get("content", "")
        first_sent = _first_sentence(content)
        summarised.append({"role": msg["role"], "content": first_sent})

    rebuilt = system_msgs + summarised + keep_tail
    new_total = sum(len(m.get("content", "")) for m in rebuilt)

    # If still over budget, drop oldest summarised turns one by one.
    while new_total > budget_chars and summarised:
        dropped = summarised.pop(0)
        new_total -= len(dropped.get("content", ""))

    return system_msgs + summarised + keep_tail


def _first_sentence(text: str) -> str:
    """Return the first sentence of *text* (heuristic)."""
    import re
    m = re.search(r'[^.!?]*[.!?]', text)
    if m:
        return m.group(0).strip()
    # No sentence boundary found — return first 120 chars.
    return text[:120].strip()


# ---------------------------------------------------------------------------
# Core context builder
# ---------------------------------------------------------------------------

class ContextBuilder:
    """
    Accumulates context items and serialises them for LLM consumption.

    Existing callers use build_context() + to_messages(); both signatures
    are preserved. The `rag` parameter is new.
    """

    def __init__(self) -> None:
        self._sections: List[Dict[str, Any]] = []
        self._requirements: str = ""

    # ------------------------------------------------------------------
    # Builder methods
    # ------------------------------------------------------------------

    def add_section(
        self,
        title: str,
        content: str,
        role: str = "system",
    ) -> "ContextBuilder":
        self._sections.append({"title": title, "content": content, "role": role})
        return self

    def set_requirements(self, text: str) -> "ContextBuilder":
        """Store the user requirements so RAG can query against them."""
        self._requirements = text
        return self

    # ------------------------------------------------------------------
    # build_context — returns a flat string (backward-compatible)
    # ------------------------------------------------------------------

    def build_context(
        self,
        rag: bool = True,
        max_rag_chars: int = 2000,
    ) -> str:
        """
        Render all sections to a single string.

        When *rag* is True and URAI_NEURO=1 is set, prepends a [DOCUMENTS]
        block retrieved for the current requirements.
        """
        parts: List[str] = []

        if rag and self._requirements:
            rag_block = _try_rag_context(self._requirements, max_chars=max_rag_chars)
            if rag_block:
                parts.append(rag_block)

        for section in self._sections:
            header = f"## {section['title']}" if section.get("title") else ""
            body = section.get("content", "")
            parts.append(f"{header}\n{body}".strip())

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # to_messages — returns OpenAI-style messages list (backward-compatible)
    # ------------------------------------------------------------------

    def to_messages(
        self,
        history: Optional[List[Dict[str, Any]]] = None,
        rag: bool = True,
        max_rag_chars: int = 2000,
        budget_chars: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Build a messages list suitable for the LLM API.

        Parameters
        ----------
        history      : existing conversation messages to append
        rag          : inject RAG context into system prompt
        max_rag_chars: cap on RAG block size
        budget_chars : if > 0, compress history to fit
        """
        system_text = self.build_context(rag=rag, max_rag_chars=max_rag_chars)
        messages: List[Dict[str, Any]] = []
        if system_text:
            messages.append({"role": "system", "content": system_text})

        if history:
            messages.extend(history)

        if budget_chars > 0:
            messages = compress_history(messages, budget_chars)

        return messages


# ── Backward-compat shims (kept for agent.py, server.py, other callers) ──────

EST_CHARS_PER_TOKEN = 3.5

def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / EST_CHARS_PER_TOKEN))

def build_context(requirements: str = "", files: dict = None, errors: str = "",
                  contracts: str = "", decisions: str = "", history: list = None,
                  budget_tokens: int = 2048, rag: bool = False) -> dict:
    """Legacy dict-returning build_context — wraps ContextBuilder."""
    cb = ContextBuilder(requirements=requirements, files=files or {},
                        errors=errors, contracts=contracts, decisions=decisions)
    budget_chars = budget_tokens * int(EST_CHARS_PER_TOKEN)
    msgs = cb.to_messages(history=history or [], rag=rag, budget_chars=budget_chars)
    sections = []
    if requirements: sections.append(("requirements", requirements))
    if errors:       sections.append(("errors", errors))
    if contracts:    sections.append(("contracts", contracts))
    if decisions:    sections.append(("decisions", decisions))
    if files:
        ft = "\n\n".join(f"--- {p} ---\n{c}" for p, c in (files or {}).items())
        if ft: sections.insert(1, ("active_files", ft))
    return {"sections": sections, "history": msgs, "dropped_history": 0,
            "est_tokens": estimate_tokens(" ".join(m.get("content","") for m in msgs)),
            "budget_tokens": budget_tokens, "over_budget": False}

def to_messages(ctx: dict) -> list:
    """Legacy to_messages — converts build_context dict to message list."""
    parts = [f"[{name.upper()}]\n{body}" for name, body in ctx.get("sections", []) if body]
    msgs = list(ctx.get("history", []))
    if parts:
        content = "\n\n".join(parts)
        # inject as last user message if no system already
        if not any(m.get("role") == "system" for m in msgs):
            msgs = [{"role": "system", "content": content}] + msgs
    return msgs
