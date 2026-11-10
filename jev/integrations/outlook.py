#!/usr/bin/env python3
"""Outlook Calendar + Mail integration via Microsoft Graph (OAuth2).

Uses msal (MIT license) for the OAuth2 device/authorization code flow.
All functions handle ImportError for missing msal with a clear message.

Tokens are stored in data/integrations/outlook_token.json.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOKEN_DIR = ROOT / "data" / "integrations"
TOKEN_FILE = TOKEN_DIR / "outlook_token.json"

SCOPES = ["Calendars.ReadWrite", "Mail.ReadWrite", "Mail.Send"]

CLIENT_ID = os.environ.get("URAI_OUTLOOK_CLIENT_ID", "")
AUTHORITY = os.environ.get("URAI_OUTLOOK_AUTHORITY",
                            "https://login.microsoftonline.com/common")
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _ensure_dir():
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)


def get_auth_url() -> dict:
    """Return Microsoft OAuth2 authorization URL."""
    try:
        import msal
    except ImportError:
        return {"ok": False,
                "error": "msal not installed; pip install 'urai[integrations]'"}
    if not CLIENT_ID:
        return {"ok": False,
                "error": "URAI_OUTLOOK_CLIENT_ID env var not set; "
                         "register an app in Azure AD"}
    try:
        app = msal.ConfidentialClientApplication(
            CLIENT_ID, authority=AUTHORITY)
        auth_url = app.get_authorization_request_url(
            SCOPES, redirect_uri="urn:ietf:wg:oauth:2.0:oob")
        return {"ok": True, "url": auth_url}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def handle_callback(code: str) -> dict:
    """Exchange authorization code for tokens and store them."""
    try:
        import msal
    except ImportError:
        return {"ok": False, "error": "msal not installed"}
    try:
        app = msal.ConfidentialClientApplication(CLIENT_ID, authority=AUTHORITY)
        result = app.acquire_token_by_authorization_code(
            code, scopes=SCOPES, redirect_uri="urn:ietf:wg:oauth:2.0:oob")
        if "access_token" in result:
            _ensure_dir()
            TOKEN_FILE.write_text(json.dumps(result, indent=2))
            return {"ok": True, "connected": True}
        return {"ok": False, "error": result.get("error_description",
                                                  result.get("error", "unknown"))}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def _get_token() -> str | None:
    if not TOKEN_FILE.exists():
        return None
    try:
        data = json.loads(TOKEN_FILE.read_text())
        return data.get("access_token")
    except Exception:
        return None


def _graph_get(endpoint: str) -> dict:
    import urllib.request
    token = _get_token()
    if not token:
        return {"ok": False, "error": "not connected; run get_auth_url() first"}
    try:
        req = urllib.request.Request(
            f"{GRAPH_BASE}{endpoint}",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return {"ok": True, "data": json.loads(resp.read())}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def _graph_post(endpoint: str, body: dict) -> dict:
    import urllib.request
    token = _get_token()
    if not token:
        return {"ok": False, "error": "not connected"}
    try:
        req = urllib.request.Request(
            f"{GRAPH_BASE}{endpoint}",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return {"ok": True, "data": json.loads(resp.read())}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def calendar_list_events(days: int = 7) -> dict:
    """List upcoming Outlook calendar events."""
    from datetime import datetime, timedelta, timezone
    start = datetime.now(timezone.utc).isoformat()
    end = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    res = _graph_get(
        f"/me/calendarview?startDateTime={start}&endDateTime={end}"
        f"&$top=25&$select=subject,start,end")
    if not res.get("ok"):
        return res
    events = res["data"].get("value", [])
    return {"ok": True, "events": [
        {"summary": e.get("subject", ""),
         "start": e.get("start", {}).get("dateTime", ""),
         "end": e.get("end", {}).get("dateTime", "")}
        for e in events
    ]}


def calendar_create_event(title: str, start: str, end: str,
                           description: str = "") -> dict:
    """Create an Outlook calendar event."""
    return _graph_post("/me/events", {
        "subject": title, "body": {"contentType": "Text", "content": description},
        "start": {"dateTime": start, "timeZone": "UTC"},
        "end": {"dateTime": end, "timeZone": "UTC"},
    })


def mail_read(max: int = 10) -> dict:
    """Read recent Outlook mail messages."""
    res = _graph_get(f"/me/messages?$top={max}&$select=subject,from,bodyPreview")
    if not res.get("ok"):
        return res
    messages = res["data"].get("value", [])
    return {"ok": True, "messages": [
        {"id": m.get("id", ""),
         "subject": m.get("subject", ""),
         "from": m.get("from", {}).get("emailAddress", {}).get("address", ""),
         "snippet": m.get("bodyPreview", "")[:200]}
        for m in messages
    ]}


def mail_send(to: str, subject: str, body: str) -> dict:
    """Send an Outlook mail message."""
    return _graph_post("/me/sendMail", {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to}}],
        }
    })


def disconnect() -> dict:
    """Remove stored Outlook tokens."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
    return {"ok": True}
