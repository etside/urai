#!/usr/bin/env python3
"""jev/events.py — In-memory per-session event ring buffer + cancel set.

Used by agent.py, vibe.py, contemplate.py, goals.py to emit observable
events for the Studio's agent event log sidebar and SSE endpoint.

Thread-safe, stdlib only. Max 500 events per session (ring-buffer via deque).
"""
from __future__ import annotations
import collections
import threading
import time

# ── Storage ───────────────────────────────────────────────────────────────────

_MAX_EVENTS = 500
_store: dict[str, collections.deque] = {}
_lock = threading.RLock()

# ── Cancel set ────────────────────────────────────────────────────────────────

_cancelled: set[str] = set()
_cancel_lock = threading.RLock()


def cancel(session_id: str) -> None:
    """Mark a session as cancelled (checked by is_cancelled())."""
    with _cancel_lock:
        _cancelled.add(session_id)


def is_cancelled(session_id: str) -> bool:
    """Return True if cancel() was called for this session."""
    with _cancel_lock:
        return session_id in _cancelled


def clear_cancel(session_id: str) -> None:
    """Remove the cancellation flag (call when session restarts)."""
    with _cancel_lock:
        _cancelled.discard(session_id)


# ── Emit / get / clear ────────────────────────────────────────────────────────

def emit(session_id: str, type: str, agent_id: str = "",
         tool: str = "", input_summary: str = "",
         output_summary: str = "", status=None) -> dict:
    """Append an event to the session's ring buffer.

    Parameters
    ----------
    session_id:      session identifier (empty string = global/unnamed)
    type:            event type, e.g. 'tool_call', 'agent_start', 'goal_step'
    agent_id:        which agent / goal produced this event
    tool:            tool name (for tool_call events)
    input_summary:   truncated representation of the tool input
    output_summary:  truncated representation of the tool result
    status:          True/False or a string label ('ok', 'error', …)
    """
    ev = {
        "timestamp": time.time(),
        "type": type,
        "agent_id": agent_id,
        "tool": tool,
        "input_summary": str(input_summary)[:300],
        "output_summary": str(output_summary)[:300],
        "status": status,
    }
    with _lock:
        if session_id not in _store:
            _store[session_id] = collections.deque(maxlen=_MAX_EVENTS)
        _store[session_id].append(ev)
    return ev


def get_events(session_id: str, since_ts: float = 0) -> list:
    """Return all events for session_id newer than since_ts."""
    with _lock:
        dq = _store.get(session_id)
        if not dq:
            return []
        return [e for e in dq if e["timestamp"] > since_ts]


def clear(session_id: str) -> None:
    """Remove all events for a session."""
    with _lock:
        _store.pop(session_id, None)
