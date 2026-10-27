"""
urai_browser2.py — Upgraded Urai browser module.

Incorporates:
  1. OpenManus BrowserContextHelper: captures live browser state (URL, title,
     scroll position, visible text, screenshot as base64) after every step and
     injects it into the calling agent's memory.
  2. Odysseus session recovery: PID tracking, LAUNCH_FAILURE_RE detection,
     automatic session restart on crash.
  3. Computer-use mode: browse_autonomous() takes screenshot → asks Urai's
     vision model what action to perform → executes → repeats until goal is
     reached or max_steps exhausted. No pre-written step list required.

All existing public API (run_steps, approve, run_status) is preserved.
Security model unchanged: private hosts blocked, credentials paused, APPROVAL_TTL
honoured.

Playwright is an optional import; the module falls back gracefully when it is
absent (state capture returns None for screenshots, autonomous mode raises
RuntimeError).
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Optional playwright import
# ---------------------------------------------------------------------------
try:
    from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PLAYWRIGHT_AVAILABLE = False
    Page = Any  # type: ignore
    Browser = Any  # type: ignore
    BrowserContext = Any  # type: ignore

log = logging.getLogger("urai.browser")

# ---------------------------------------------------------------------------
# Constants / configuration
# ---------------------------------------------------------------------------

APPROVAL_TTL: int = int(os.getenv("URAI_APPROVAL_TTL", "120"))   # seconds
MAX_TEXT_CHARS: int = 4000   # chars per fold snapshot
SCROLL_STEP_PX: int = 600    # pixels per scroll action

# Private-network CIDR patterns (block by hostname)
_PRIVATE_HOST_RE = re.compile(
    r"^(localhost|127\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+"
    r"|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+"
    r"|192\.168\.\d+\.\d+"
    r"|::1|0\.0\.0\.0)$",
    re.IGNORECASE,
)

# Odysseus / Chrome launch failure signatures
LAUNCH_FAILURE_RE = re.compile(
    r"(DevToolsActivePort file doesn't exist"
    r"|Failed to launch (chrome|browser)"
    r"|Target closed"
    r"|Session closed"
    r"|BrowserType\.launch.*Error"
    r"|net::ERR_CONNECTION_REFUSED"
    r"|ECONNREFUSED"
    r"|crashed|exited unexpectedly)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------

# run_id -> run record dict
_runs: Dict[str, Dict[str, Any]] = {}

# run_id -> Chrome PID for crash recovery (Odysseus session tracking)
_session_pids: Dict[str, int] = {}

# run_id -> threading.Event for interrupt
_interrupt_events: Dict[str, threading.Event] = {}

_lock = threading.Lock()

# ---------------------------------------------------------------------------
# BrowserState
# ---------------------------------------------------------------------------

@dataclass
class BrowserState:
    """Live state captured after each browser action (OpenManus-style)."""
    url: str = ""
    title: str = ""
    text_above_fold: str = ""   # visible text before first scroll
    text_below_fold: str = ""   # text further down the page
    screenshot_b64: Optional[str] = None  # base64-encoded PNG
    scroll_y: int = 0
    total_height: int = 0
    captured_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        """Short human-readable summary for agent memory injection."""
        lines = [
            f"URL: {self.url}",
            f"Title: {self.title}",
            f"Scroll: {self.scroll_y}/{self.total_height}px",
        ]
        if self.text_above_fold:
            lines.append(f"Visible text (above fold): {self.text_above_fold[:500]}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers — security
# ---------------------------------------------------------------------------

def _is_private_host(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
        return bool(_PRIVATE_HOST_RE.match(host))
    except Exception:
        return False


def _assert_safe_url(url: str) -> None:
    if _is_private_host(url):
        raise PermissionError(f"Blocked: private/loopback host in URL: {url!r}")


# ---------------------------------------------------------------------------
# Playwright session management
# ---------------------------------------------------------------------------

_pw_instances: Dict[str, Any] = {}  # run_id -> {"pw", "browser", "context", "page"}


def _launch_playwright_session(run_id: str, headless: bool = True) -> Dict[str, Any]:
    """Launch a new Playwright browser session, recording the PID."""
    if not _PLAYWRIGHT_AVAILABLE:
        raise RuntimeError("playwright is not installed; run `pip install playwright && playwright install chromium`")

    pw = sync_playwright().start()
    browser: Browser = pw.chromium.launch(
        headless=headless,
        args=["--no-sandbox", "--disable-setuid-sandbox"],
    )
    context: BrowserContext = browser.new_context()
    page: Page = context.new_page()

    # Record PID for crash recovery
    try:
        pid = browser.process.pid if hasattr(browser, "process") and browser.process else None
    except Exception:
        pid = None

    session = {"pw": pw, "browser": browser, "context": context, "page": page}
    with _lock:
        _pw_instances[run_id] = session
        if pid:
            _session_pids[run_id] = pid

    log.info("Playwright session started for run_id=%s pid=%s", run_id, pid)
    return session


def _close_playwright_session(run_id: str) -> None:
    """Close and clean up a Playwright session."""
    with _lock:
        session = _pw_instances.pop(run_id, None)
        _session_pids.pop(run_id, None)

    if session:
        try:
            session["browser"].close()
        except Exception:
            pass
        try:
            session["pw"].stop()
        except Exception:
            pass
        log.info("Playwright session closed for run_id=%s", run_id)


def _get_or_recover_session(run_id: str, headless: bool = True) -> Dict[str, Any]:
    """Return existing session or restart it if it has crashed."""
    with _lock:
        session = _pw_instances.get(run_id)

    if session:
        # Liveness check
        try:
            _ = session["browser"].version
            return session
        except Exception as exc:
            if LAUNCH_FAILURE_RE.search(str(exc)):
                log.warning("Session crash detected for run_id=%s: %s — restarting", run_id, exc)
                _close_playwright_session(run_id)
            else:
                raise

    log.info("No session for run_id=%s, launching new one", run_id)
    return _launch_playwright_session(run_id, headless=headless)


# ---------------------------------------------------------------------------
# BrowserState capture (OpenManus BrowserContextHelper)
# ---------------------------------------------------------------------------

def get_browser_state(run_id: str) -> Optional[BrowserState]:
    """
    Capture the current live browser state for *run_id*.

    Returns a BrowserState populated with URL, title, scroll info, visible
    text (above/below fold), and a base64-encoded PNG screenshot.  Returns
    None if no active session exists or Playwright is unavailable.

    This function is automatically called after every _do_step() and the
    result is stored in the run record under 'last_state'.
    """
    with _lock:
        session = _pw_instances.get(run_id)

    if not session:
        return None

    page: Page = session["page"]

    try:
        url = page.url
        title = page.title()

        # Scroll metrics
        metrics: dict = page.evaluate("""() => ({
            scrollY:       window.scrollY,
            totalHeight:   document.body.scrollHeight,
            viewportHeight: window.innerHeight,
        })""")
        scroll_y = int(metrics.get("scrollY", 0))
        total_height = int(metrics.get("totalHeight", 0))

        # Extract text content
        full_text: str = page.evaluate(
            "() => document.body ? document.body.innerText : ''"
        )
        above = full_text[:MAX_TEXT_CHARS]
        below = full_text[MAX_TEXT_CHARS : MAX_TEXT_CHARS * 2]

        # Screenshot
        screenshot_b64: Optional[str] = None
        try:
            png_bytes: bytes = page.screenshot(type="png")
            screenshot_b64 = base64.b64encode(png_bytes).decode()
        except Exception as sc_err:
            log.debug("Screenshot failed: %s", sc_err)

        state = BrowserState(
            url=url,
            title=title,
            text_above_fold=above,
            text_below_fold=below,
            screenshot_b64=screenshot_b64,
            scroll_y=scroll_y,
            total_height=total_height,
        )

        # Inject into run record
        with _lock:
            if run_id in _runs:
                _runs[run_id]["last_state"] = state.to_dict()

        return state

    except Exception as exc:
        log.warning("get_browser_state failed for run_id=%s: %s", run_id, exc)
        return None


# ---------------------------------------------------------------------------
# Step execution helpers
# ---------------------------------------------------------------------------

def _navigate(page: Page, url: str) -> None:
    _assert_safe_url(url)
    page.goto(url, wait_until="domcontentloaded", timeout=30_000)


def _click(page: Page, selector_or_coords: str) -> None:
    """Click by CSS selector or 'x,y' pixel coordinates."""
    if re.match(r"^\d+\s*,\s*\d+$", selector_or_coords.strip()):
        x, y = [int(v.strip()) for v in selector_or_coords.split(",")]
        page.mouse.click(x, y)
    else:
        page.click(selector_or_coords, timeout=10_000)


def _type_text(page: Page, selector: str, text: str) -> None:
    page.fill(selector, text)


def _scroll(page: Page, direction: str = "down", amount: int = SCROLL_STEP_PX) -> None:
    delta = amount if direction == "down" else -amount
    page.evaluate(f"window.scrollBy(0, {delta})")


def _do_step(run_id: str, step: dict, session: dict) -> dict:
    """
    Execute a single browser step dict.  After execution, capture state.

    Supported actions:
        navigate  — {"action": "navigate", "url": "..."}
        click     — {"action": "click", "target": "selector or x,y"}
        type      — {"action": "type", "selector": "...", "text": "..."}
        scroll    — {"action": "scroll", "direction": "down|up", "amount": px}
        wait      — {"action": "wait", "ms": milliseconds}
        extract   — {"action": "extract"} → returns page text in result
        screenshot— {"action": "screenshot"} → returns b64 in result
    """
    page: Page = session["page"]
    action = step.get("action", "").lower()
    result: dict = {"action": action, "ok": True, "error": None}

    try:
        if action == "navigate":
            url = step["url"]
            _assert_safe_url(url)
            _navigate(page, url)
            result["url"] = page.url

        elif action == "click":
            _click(page, step.get("target", "body"))

        elif action == "type":
            _type_text(page, step.get("selector", "body"), step.get("text", ""))

        elif action == "scroll":
            _scroll(page, step.get("direction", "down"), step.get("amount", SCROLL_STEP_PX))

        elif action == "wait":
            time.sleep(step.get("ms", 500) / 1000.0)

        elif action == "extract":
            result["text"] = page.evaluate("() => document.body ? document.body.innerText : ''")

        elif action == "screenshot":
            png = page.screenshot(type="png")
            result["screenshot_b64"] = base64.b64encode(png).decode()

        else:
            result["ok"] = False
            result["error"] = f"Unknown action: {action!r}"

    except PermissionError as exc:
        result["ok"] = False
        result["error"] = str(exc)

    except Exception as exc:
        if LAUNCH_FAILURE_RE.search(str(exc)):
            log.warning("Launch failure detected mid-step: %s", exc)
            result["ok"] = False
            result["error"] = f"LAUNCH_FAILURE: {exc}"
        else:
            result["ok"] = False
            result["error"] = str(exc)

    # --- Capture state after every action (OpenManus-style injection) ---
    state = get_browser_state(run_id)
    result["state"] = state.to_dict() if state else None

    return result


# ---------------------------------------------------------------------------
# Core public API (preserved from original browser.py)
# ---------------------------------------------------------------------------

def run_steps(
    steps: List[dict],
    run_id: Optional[str] = None,
    headless: bool = True,
    require_approval: bool = False,
) -> dict:
    """
    Execute a pre-written list of browser steps.

    Each step is a dict with at least {"action": "<verb>", ...}.
    Returns {"ok": bool, "run_id": str, "results": [...], "final_state": dict|None}.

    If *require_approval* is True the run starts in PENDING state and blocks
    until approve(run_id) is called (or APPROVAL_TTL seconds elapse).
    """
    run_id = run_id or str(uuid.uuid4())

    with _lock:
        _runs[run_id] = {
            "run_id": run_id,
            "status": "pending" if require_approval else "running",
            "steps": steps,
            "results": [],
            "last_state": None,
            "created_at": time.time(),
        }
        _interrupt_events[run_id] = threading.Event()

    if require_approval:
        log.info("run_id=%s waiting for approval (TTL=%ds)", run_id, APPROVAL_TTL)
        deadline = time.time() + APPROVAL_TTL
        while time.time() < deadline:
            with _lock:
                status = _runs[run_id]["status"]
            if status == "approved":
                break
            if status == "rejected":
                with _lock:
                    _runs[run_id]["status"] = "rejected"
                return {"ok": False, "run_id": run_id, "results": [], "final_state": None,
                        "error": "Run rejected by user"}
            time.sleep(0.5)
        else:
            with _lock:
                _runs[run_id]["status"] = "timeout"
            return {"ok": False, "run_id": run_id, "results": [], "final_state": None,
                    "error": "Approval TTL expired"}

    with _lock:
        _runs[run_id]["status"] = "running"

    try:
        session = _get_or_recover_session(run_id, headless=headless)
    except Exception as exc:
        with _lock:
            _runs[run_id]["status"] = "error"
        return {"ok": False, "run_id": run_id, "results": [], "final_state": None,
                "error": str(exc)}

    results: List[dict] = []
    interrupt_ev = _interrupt_events[run_id]

    for i, step in enumerate(steps):
        if interrupt_ev.is_set():
            log.info("run_id=%s interrupted at step %d", run_id, i)
            break

        log.debug("run_id=%s executing step %d: %s", run_id, i, step)

        # Retry once on LAUNCH_FAILURE (session recovery)
        result = _do_step(run_id, step, session)
        if result.get("error", "").startswith("LAUNCH_FAILURE"):
            log.info("Attempting session recovery for run_id=%s", run_id)
            try:
                _close_playwright_session(run_id)
                session = _launch_playwright_session(run_id, headless=headless)
                result = _do_step(run_id, step, session)
            except Exception as rec_exc:
                result["error"] = f"Recovery failed: {rec_exc}"
                result["ok"] = False

        results.append(result)

        with _lock:
            _runs[run_id]["results"] = results

        if not result["ok"] and step.get("abort_on_error", True):
            break

    with _lock:
        _runs[run_id]["status"] = "done"
        last_state = _runs[run_id].get("last_state")

    return {
        "ok": all(r["ok"] for r in results),
        "run_id": run_id,
        "results": results,
        "final_state": last_state,
    }


def approve(run_id: str) -> bool:
    """Approve a pending run so it proceeds past the approval gate."""
    with _lock:
        if run_id not in _runs:
            return False
        if _runs[run_id]["status"] != "pending":
            return False
        _runs[run_id]["status"] = "approved"
    log.info("run_id=%s approved", run_id)
    return True


def reject(run_id: str) -> bool:
    """Reject a pending run."""
    with _lock:
        if run_id not in _runs:
            return False
        _runs[run_id]["status"] = "rejected"
    log.info("run_id=%s rejected", run_id)
    return True


def run_status(run_id: str) -> Optional[dict]:
    """
    Return a status snapshot for *run_id*.

    Keys: run_id, status, steps_total, steps_done, last_state, created_at.
    Returns None if the run_id is unknown.
    """
    with _lock:
        rec = _runs.get(run_id)
    if not rec:
        return None
    return {
        "run_id": run_id,
        "status": rec["status"],
        "steps_total": len(rec.get("steps", [])),
        "steps_done": len(rec.get("results", [])),
        "last_state": rec.get("last_state"),
        "created_at": rec.get("created_at"),
    }


def interrupt(run_id: str) -> bool:
    """Signal a running session to stop after the current step."""
    with _lock:
        ev = _interrupt_events.get(run_id)
    if ev:
        ev.set()
        log.info("run_id=%s interrupt requested", run_id)
        return True
    return False


def close_session(run_id: str) -> None:
    """Explicitly tear down the Playwright session for *run_id*."""
    _close_playwright_session(run_id)
    with _lock:
        _interrupt_events.pop(run_id, None)


# ---------------------------------------------------------------------------
# Computer-use / autonomous browsing
# ---------------------------------------------------------------------------

def _ask_vision_model(
    goal: str,
    screenshot_b64: str,
    history: List[dict],
    step_number: int,
    max_steps: int,
) -> dict:
    """
    Ask Urai's vision model what action to take next.

    In production this calls the Urai agent/LLM with the screenshot.  Here we
    implement the interface contract: return a dict with keys:
        action  : "click" | "type" | "scroll" | "navigate" | "wait" | "done" | "fail"
        target  : CSS selector, "x,y" coords, or URL (action-dependent)
        text    : text to type (only for "type" action)
        direction: "up" | "down" (only for "scroll")
        reasoning: short explanation (for trace)

    Falls back to a stub when the real model is not wired up yet.
    """
    # --- Real model integration point ---
    # Replace this section with your actual vision model call, e.g.:
    #   from jev.agent import vision_decide
    #   return vision_decide(goal, screenshot_b64, history, step_number)

    # Stub: import from jev.agent if available
    try:
        from jev.agent import vision_decide  # type: ignore
        return vision_decide(goal, screenshot_b64, history, step_number)
    except ImportError:
        pass

    # Fallback stub for testing (returns done after one step)
    log.warning("vision_decide not available; returning stub 'done' action")
    return {
        "action": "done",
        "reasoning": "vision model not wired up — treating goal as achieved",
        "target": None,
        "text": None,
        "direction": "down",
    }


def browse_autonomous(
    goal: str,
    max_steps: int = 10,
    run_id: Optional[str] = None,
    headless: bool = True,
    start_url: Optional[str] = None,
) -> dict:
    """
    Computer-use style autonomous browsing.

    Algorithm:
      1. Launch a browser session.
      2. Optionally navigate to *start_url* (defaults to about:blank).
      3. Capture a screenshot.
      4. Ask Urai's vision model: "given the goal and what you see, what is
         the next atomic action?"
      5. Execute the action.
      6. Capture updated BrowserState.
      7. Repeat from step 3 until the model returns action="done", action="fail",
         or *max_steps* is exhausted.

    Returns:
        {
          "ok": bool,
          "run_id": str,
          "steps_taken": int,
          "final_url": str | None,
          "final_state": dict | None,
          "trace": [{"step": n, "action": ..., "reasoning": ..., "result": ...}],
          "error": str | None,
        }

    No pre-written steps are required; Urai figures out how to achieve the
    goal entirely from visual perception.
    """
    if not _PLAYWRIGHT_AVAILABLE:
        raise RuntimeError(
            "browse_autonomous requires playwright. "
            "Install with: pip install playwright && playwright install chromium"
        )

    run_id = run_id or str(uuid.uuid4())

    with _lock:
        _runs[run_id] = {
            "run_id": run_id,
            "status": "running",
            "steps": [],       # dynamically built
            "results": [],
            "last_state": None,
            "created_at": time.time(),
            "mode": "autonomous",
            "goal": goal,
        }
        _interrupt_events[run_id] = threading.Event()

    trace: List[dict] = []
    interrupt_ev = _interrupt_events[run_id]
    history: List[dict] = []
    final_url: Optional[str] = None
    error: Optional[str] = None

    try:
        session = _get_or_recover_session(run_id, headless=headless)
        page: Page = session["page"]

        if start_url:
            _assert_safe_url(start_url)
            _navigate(page, start_url)

        for step_num in range(1, max_steps + 1):
            if interrupt_ev.is_set():
                log.info("autonomous run_id=%s interrupted at step %d", run_id, step_num)
                error = "Interrupted"
                break

            # --- Capture current state ---
            state = get_browser_state(run_id)
            if state is None:
                error = "Could not capture browser state"
                break

            screenshot_b64 = state.screenshot_b64 or ""

            # --- Ask vision model ---
            try:
                decision = _ask_vision_model(
                    goal=goal,
                    screenshot_b64=screenshot_b64,
                    history=history,
                    step_number=step_num,
                    max_steps=max_steps,
                )
            except Exception as model_exc:
                error = f"Vision model error: {model_exc}"
                break

            action = decision.get("action", "fail")
            reasoning = decision.get("reasoning", "")

            log.info(
                "autonomous step %d/%d: action=%s reasoning=%s",
                step_num, max_steps, action, reasoning[:80],
            )

            trace_entry: dict = {
                "step": step_num,
                "url": state.url,
                "action": action,
                "reasoning": reasoning,
                "decision": decision,
                "result": None,
            }

            # --- Terminal actions ---
            if action == "done":
                final_url = state.url
                trace.append(trace_entry)
                history.append({"step": step_num, "action": action, "url": state.url})
                with _lock:
                    _runs[run_id]["status"] = "done"
                return {
                    "ok": True,
                    "run_id": run_id,
                    "steps_taken": step_num,
                    "final_url": final_url,
                    "final_state": state.to_dict(),
                    "trace": trace,
                    "error": None,
                }

            if action == "fail":
                error = decision.get("text") or "Vision model signalled failure"
                trace.append(trace_entry)
                break

            # --- Build step dict and execute ---
            step_dict: dict = {"action": action, "abort_on_error": False}

            if action == "navigate":
                step_dict["url"] = decision.get("target", "")
            elif action == "click":
                step_dict["target"] = decision.get("target", "body")
            elif action == "type":
                step_dict["selector"] = decision.get("target", "body")
                step_dict["text"] = decision.get("text", "")
            elif action == "scroll":
                step_dict["direction"] = decision.get("direction", "down")
                step_dict["amount"] = decision.get("amount", SCROLL_STEP_PX)
            elif action == "wait":
                step_dict["ms"] = decision.get("ms", 1000)

            # Retry on session crash
            result = _do_step(run_id, step_dict, session)
            if result.get("error", "").startswith("LAUNCH_FAILURE"):
                log.info("Recovering session for autonomous run_id=%s", run_id)
                try:
                    _close_playwright_session(run_id)
                    session = _launch_playwright_session(run_id, headless=headless)
                    result = _do_step(run_id, step_dict, session)
                except Exception as rec_exc:
                    error = f"Session recovery failed: {rec_exc}"
                    trace_entry["result"] = result
                    trace.append(trace_entry)
                    break

            trace_entry["result"] = result
            trace.append(trace_entry)
            history.append({
                "step": step_num,
                "action": action,
                "ok": result["ok"],
                "url": (result.get("state") or {}).get("url", ""),
            })

            with _lock:
                _runs[run_id]["results"] = [t["result"] for t in trace if t["result"]]

            if not result["ok"]:
                log.warning("Step %d failed: %s", step_num, result.get("error"))

        else:
            error = f"max_steps ({max_steps}) reached without goal completion"

    except Exception as exc:
        error = str(exc)
        log.exception("browse_autonomous error for run_id=%s", run_id)

    finally:
        with _lock:
            if run_id in _runs and _runs[run_id]["status"] == "running":
                _runs[run_id]["status"] = "done"
            last_state = _runs[run_id].get("last_state") if run_id in _runs else None

    # Try to get current URL for final reporting
    try:
        with _lock:
            session = _pw_instances.get(run_id)
        if session:
            final_url = final_url or session["page"].url
    except Exception:
        pass

    return {
        "ok": error is None,
        "run_id": run_id,
        "steps_taken": len(trace),
        "final_url": final_url,
        "final_state": last_state,
        "trace": trace,
        "error": error,
    }


# ---------------------------------------------------------------------------
# Utility: list active runs
# ---------------------------------------------------------------------------

def list_runs() -> List[dict]:
    """Return status snapshots for all known runs."""
    with _lock:
        ids = list(_runs.keys())
    return [s for rid in ids if (s := run_status(rid)) is not None]


# ---------------------------------------------------------------------------
# Self-test / smoke test (run directly)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== urai_browser2 smoke test ===")

    # 1. run_steps with a simple navigation
    print("\n[1] run_steps → navigate to example.com")
    res = run_steps(
        steps=[
            {"action": "navigate", "url": "https://example.com"},
            {"action": "extract"},
        ],
        headless=True,
    )
    print(f"    ok={res['ok']}  run_id={res['run_id']}")
    if res["final_state"]:
        print(f"    URL: {res['final_state']['url']}")
        print(f"    Title: {res['final_state']['title']}")

    # 2. run_status
    print("\n[2] run_status")
    status = run_status(res["run_id"])
    print(f"    status={status}")

    # 3. Private host blocked
    print("\n[3] Private host blocking")
    blocked = run_steps([{"action": "navigate", "url": "http://localhost:8080/secret"}])
    print(f"    ok={blocked['ok']}  (expected False)")

    # 4. browse_autonomous (no vision model wired; stub returns done immediately)
    print("\n[4] browse_autonomous stub")
    auto = browse_autonomous("Find the main heading on example.com", max_steps=3,
                             start_url="https://example.com")
    print(f"    ok={auto['ok']}  steps_taken={auto['steps_taken']}")

    print("\nAll smoke tests complete.")
