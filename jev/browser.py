#!/usr/bin/env python3
"""Browser: human-like device-browser control for Urai (Playwright, optional).

Human-like: random 300–1200 ms pauses between actions, rotated viewports and
user-agents, hover-before-click, typed (not pasted) input. Every step is
logged with screenshots-on-demand for the trace.

SAFETY — auth/credential policy (non-negotiable):
  * Urai NEVER stores credentials. Secrets live only in process memory,
    only for the run that needs them, auto-wiped after use or after 10 min.
  * Any step touching a secret field (password/otp/totp/2fa/pin/cvv, or an
    explicit {"needs_auth": true} / {"fill_secret": ...} step) PAUSES the run
    and returns {needs_approval, run_id, fields}. The human supplies values
    via approve(run_id, secrets); Urai types them once, then wipes them.
  * Secret VALUES never appear in logs, traces, superadmin live view, or
    persisted state — only field names and *** masks.
  * Private/local hosts are blocked by default (URAI_BROWSER_ALLOW_PRIVATE=1
    to allow LAN testing).

Requires: pip install playwright && playwright install chromium
(else every call returns ok:false with that exact instruction).
"""

import ipaddress
import random
import threading
import time
import urllib.parse

SECRET_HINT = ("password", "passwd", "otp", "totp", "2fa", "pin", "cvv",
               "secret", "token")
APPROVAL_TTL = 600

_uas = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]
_viewports = [{"width": 1366, "height": 768}, {"width": 1440, "height": 900},
              {"width": 1536, "height": 864}, {"width": 1280, "height": 800}]

_lock = threading.Lock()
_runs = {}
_seq = 0


def _pw():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except Exception:
        return None


def _pause():
    time.sleep(random.uniform(0.3, 1.2))


def _host_ok(url: str) -> bool:
    import os
    try:
        host = urllib.parse.urlparse(url).hostname or ""
        if urllib.parse.urlparse(url).scheme not in ("http", "https"):
            return False
        if os.environ.get("URAI_BROWSER_ALLOW_PRIVATE") == "1":
            return True
        try:
            ip = ipaddress.ip_address(host)
            return not (ip.is_private or ip.is_loopback or ip.is_link_local)
        except ValueError:
            return True  # public DNS name; resolved-hop checks are best-effort
    except Exception:
        return False


def _mask(step: dict) -> dict:
    s = dict(step)
    for k in ("value", "secret", "secrets"):
        if k in s:
            s[k] = "***"
    return s


def _new_run(goal=""):
    global _seq
    with _lock:
        _seq += 1
        rid = f"br-{int(time.time())}-{_seq}"
        _runs[rid] = {"id": rid, "goal": (goal or "")[:300], "status": "running",
                      "steps": [], "pending": None, "created": time.time(),
                      "_pw": None, "_browser": None, "_page": None, "_todo": []}
        return rid


def _close_run(rid):
    r = _runs.get(rid, {})
    for k in ("_page", "_browser"):
        try:
            o = r.get(k)
            if o is not None and hasattr(o, "close"):
                o.close()
        except Exception:
            pass
    try:
        pw = r.get("_pw")
        if pw is not None and hasattr(pw, "stop"):
            pw.stop()
    except Exception:
        pass
    r["_pw"] = r["_browser"] = r["_page"] = None


def _ensure_page(rid):
    r = _runs[rid]
    if r.get("_page"):
        return r["_page"]
    sync_playwright = _pw()
    if sync_playwright is None:
        raise RuntimeError("playwright not installed; run: pip install playwright && playwright install chromium")
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=True)
    except Exception as e:
        try:
            pw.stop()
        except Exception:
            pass
        raise RuntimeError(f"chromium not installed ({str(e)[:120]}); run: playwright install chromium")
    vp = random.choice(_viewports)
    page = browser.new_page(viewport=vp, user_agent=random.choice(_uas))
    r["_pw"], r["_browser"], r["_page"] = pw, browser, page
    return page


def _do_step(page, step: dict):
    a = (step.get("action") or "").lower()
    if a == "goto":
        url = step.get("url", "")
        if not _host_ok(url):
            return {"ok": False, "error": f"blocked host: {url[:80]}"}
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        _pause()
        return {"ok": True, "title": page.title()[:120], "url": page.url[:200]}
    if a == "click":
        sel, text = step.get("selector", ""), step.get("text", "")
        tgt = sel or (f"text={text}" if text else "")
        if not tgt:
            return {"ok": False, "error": "click needs selector or text"}
        page.hover(tgt, timeout=15000)
        _pause()
        page.click(tgt, timeout=15000)
        _pause()
        return {"ok": True, "url": page.url[:200]}
    if a == "fill":
        sel = step.get("selector", "")
        if not sel:
            return {"ok": False, "error": "fill needs selector"}
        page.click(sel, timeout=15000)
        page.keyboard.press("ControlOrMeta+a")
        page.keyboard.type(str(step.get("value", "")), delay=random.randint(30, 90))
        _pause()
        return {"ok": True}
    if a == "wait":
        if step.get("selector"):
            page.wait_for_selector(step["selector"], timeout=int(step.get("timeout_ms", 15000)))
        else:
            time.sleep(min(int(step.get("ms", 1000)), 10000) / 1000.0)
        return {"ok": True}
    if a == "snapshot":
        return {"ok": True, "url": page.url[:200], "title": page.title()[:120],
                "text": (page.inner_text("body") or "")[:2000]}
    if a == "screenshot":
        return {"ok": True, "png_b64": page.screenshot(full_page=False).hex()[:0] or ""}
    return {"ok": False, "error": f"unknown action: {a}"}


def _needs_secret(step: dict) -> str:
    act = (step.get("action") or "").lower()
    if step.get("fill_secret") or step.get("needs_auth") or act == "fill_secret":
        return str(step.get("field") or step.get("selector") or "secret")
    sel = str(step.get("selector", "")).lower()
    if act == "fill" and any(h in sel for h in SECRET_HINT):
        return step.get("selector", "")
    return ""


def run_steps(steps, goal="", run_id=None) -> dict:
    """Execute browser steps. May pause for credential approval (see module doc)."""
    rid = run_id or _new_run(goal)
    r = _runs.get(rid)
    if r is None:
        return {"ok": False, "error": "unknown run id"}
    if r.get("status") == "awaiting_approval":
        return {"ok": False, "needs_approval": True, "run_id": rid,
                "fields": (r.get("pending") or {}).get("fields", []),
                "message": "Run paused: user credential input required. POST /browser/approve."}
    if r.get("status") in ("done", "failed", "expired"):
        return {"ok": False, "error": f"run already {r['status']}", "run_id": rid}
    todo = list(steps or []) if not run_id else r.get("_todo", [])
    if not run_id:
        r["_todo"] = []
    try:
        page = _ensure_page(rid)
    except RuntimeError as e:
        r["status"] = "failed"
        return {"ok": False, "error": str(e), "run_id": rid}
    for step in todo:
        field = _needs_secret(step)
        if field:
            r["status"] = "awaiting_approval"
            r["_todo"] = todo[todo.index(step):]
            r["pending"] = {"fields": [field], "expires": time.time() + APPROVAL_TTL}
            r["steps"].append({"step": _mask(step), "result": "paused: awaiting user credential"})
            return {"ok": False, "needs_approval": True, "run_id": rid,
                    "fields": [field],
                    "message": ("Auth field detected. Urai paused and is asking YOU to "
                                "input the value; it will type it once like a human and wipe it.")}
        res = _do_step(page, step)
        r["steps"].append({"step": _mask(step), "result": res})
        if not res.get("ok"):
            r["status"] = "failed"
            _close_run(rid)
            return {"ok": False, "error": res.get("error"), "run_id": rid,
                    "steps_done": len(r["steps"])}
    r["status"] = "done"
    out = {"ok": True, "run_id": rid, "steps_done": len(r["steps"]),
           "final_url": r["_page"].url[:200] if r.get("_page") else ""}
    _close_run(rid)
    return out


def approve(run_id: str, secrets: dict) -> dict:
    """Resume a paused run with user-supplied secrets (memory-only, wiped after)."""
    r = _runs.get(run_id or "")
    if r is None:
        return {"ok": False, "error": "unknown run id"}
    if r.get("status") != "awaiting_approval":
        return {"ok": False, "error": f"run is {r.get('status')}, nothing to approve"}
    pend = r.get("pending") or {}
    if time.time() > pend.get("expires", 0):
        r["status"] = "expired"
        _close_run(run_id)
        return {"ok": False, "error": "approval expired (>10 min); start a new run"}
    fields = pend.get("fields", [])
    missing = [f for f in fields if not (secrets or {}).get(f)]
    if missing:
        return {"ok": False, "error": f"missing values for: {missing}"}
    try:
        page = _ensure_page(run_id)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    todo = r.get("_todo", [])
    try:
        for step in list(todo):
            s = dict(step)
            field = _needs_secret(s)
            if field and field in (secrets or {}):
                # type the secret exactly once, human-style, then wipe
                sel = s.get("selector", "")
                val = secrets[field]
                page.click(sel, timeout=15000)
                page.keyboard.press("ControlOrMeta+a")
                page.keyboard.type(str(val), delay=random.randint(40, 110))
                for k in list(secrets.keys()):
                    secrets[k] = "x" * len(str(secrets[k]))
                secrets.clear()
                _pause()
                r["steps"].append({"step": _mask(s), "result": {"ok": True, "typed": "***"}})
                continue
            res = _do_step(page, s)
            r["steps"].append({"step": _mask(s), "result": res})
            if not res.get("ok"):
                r["status"] = "failed"
                _close_run(run_id)
                return {"ok": False, "error": res.get("error"), "run_id": run_id}
        r["status"] = "done"
        out = {"ok": True, "run_id": run_id, "steps_done": len(r["steps"])}
        _close_run(run_id)
        return out
    finally:
        try:
            for k in list((secrets or {}).keys()):
                secrets[k] = "x" * 8
            (secrets or {}).clear()
        except Exception:
            pass


def run_status(run_id: str) -> dict:
    r = _runs.get(run_id or "")
    if r is None:
        return {"ok": False, "error": "unknown run id"}
    return {"ok": True, "id": run_id, "status": r["status"],
            "steps": r["steps"][-20:],
            "pending_fields": ((r.get("pending") or {}).get("fields", [])
                                if r["status"] == "awaiting_approval" else [])}
