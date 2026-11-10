#!/usr/bin/env python3
"""Google Calendar + Gmail integration via OAuth2.

Uses google-auth-oauthlib (Apache 2.0) for the OAuth2 flow and
google-api-python-client (Apache 2.0) for API calls. Both are optional
deps; if missing, functions return a clear ImportError message.

Tokens are stored in data/integrations/google_token.json.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOKEN_DIR = ROOT / "data" / "integrations"
TOKEN_FILE = TOKEN_DIR / "google_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

CLIENT_SECRETS_FILE = os.environ.get(
    "URAI_GOOGLE_CLIENT_SECRETS",
    str(ROOT / "data" / "integrations" / "google_client_secrets.json"))


def _ensure_dir():
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)


def get_auth_url() -> dict:
    """Return OAuth2 consent URL. Requires google-auth-oauthlib."""
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        return {"ok": False,
                "error": "google-auth-oauthlib not installed; "
                         "pip install 'urai[integrations]'"}
    if not os.path.isfile(CLIENT_SECRETS_FILE):
        return {"ok": False,
                "error": f"client secrets not found at {CLIENT_SECRETS_FILE}; "
                         "download from Google Cloud Console"}
    try:
        flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES)
        flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
        auth_url, _ = flow.authorization_url(prompt="consent")
        return {"ok": True, "url": auth_url}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def handle_callback(code: str) -> dict:
    """Exchange authorization code for tokens and store them."""
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        return {"ok": False,
                "error": "google-auth-oauthlib not installed"}
    try:
        flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES)
        flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
        flow.fetch_token(code=code)
        creds = flow.credentials
        _ensure_dir()
        TOKEN_FILE.write_text(json.dumps({
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes),
        }, indent=2))
        return {"ok": True, "connected": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def _get_creds():
    if not TOKEN_FILE.exists():
        return None
    try:
        from google.oauth2.credentials import Credentials
        data = json.loads(TOKEN_FILE.read_text())
        return Credentials(**data)
    except ImportError:
        return None
    except Exception:
        return None


def calendar_list_events(days: int = 7) -> dict:
    """List upcoming calendar events."""
    creds = _get_creds()
    if creds is None:
        return {"ok": False, "error": "not connected; run get_auth_url() first"}
    try:
        from googleapiclient.discovery import build
        from datetime import datetime, timedelta, timezone
    except ImportError:
        return {"ok": False, "error": "google-api-python-client not installed"}
    try:
        service = build("calendar", "v3", credentials=creds)
        now = datetime.now(timezone.utc).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        events_result = service.events().list(
            calendarId="primary", timeMin=now, timeMax=end,
            maxResults=25, singleEvents=True, orderBy="startTime").execute()
        events = events_result.get("items", [])
        return {"ok": True, "events": [
            {"summary": e.get("summary", ""),
             "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date", "")),
             "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date", ""))}
            for e in events
        ]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def calendar_create_event(title: str, start: str, end: str,
                           description: str = "") -> dict:
    """Create a calendar event."""
    creds = _get_creds()
    if creds is None:
        return {"ok": False, "error": "not connected"}
    try:
        from googleapiclient.discovery import build
    except ImportError:
        return {"ok": False, "error": "google-api-python-client not installed"}
    try:
        service = build("calendar", "v3", credentials=creds)
        event = {
            "summary": title, "description": description,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
        }
        created = service.events().insert(calendarId="primary", body=event).execute()
        return {"ok": True, "event_id": created.get("id", "")}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def gmail_read(max: int = 10, query: str = "") -> dict:
    """Read recent Gmail messages."""
    creds = _get_creds()
    if creds is None:
        return {"ok": False, "error": "not connected"}
    try:
        from googleapiclient.discovery import build
    except ImportError:
        return {"ok": False, "error": "google-api-python-client not installed"}
    try:
        service = build("gmail", "v1", credentials=creds)
        results = service.users().messages().list(
            userId="me", maxResults=max, q=query).execute()
        messages = results.get("messages", [])
        out = []
        for msg in messages[:max]:
            detail = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["Subject", "From"]).execute()
            headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
            out.append({
                "id": msg["id"],
                "subject": headers.get("Subject", ""),
                "from": headers.get("From", ""),
                "snippet": detail.get("snippet", "")[:200],
            })
        return {"ok": True, "messages": out}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def gmail_send(to: str, subject: str, body: str) -> dict:
    """Send a Gmail message."""
    creds = _get_creds()
    if creds is None:
        return {"ok": False, "error": "not connected"}
    try:
        from googleapiclient.discovery import build
        import base64
    except ImportError:
        return {"ok": False, "error": "google-api-python-client not installed"}
    try:
        service = build("gmail", "v1", credentials=creds)
        raw = (f"To: {to}\r\nSubject: {subject}\r\n\r\n{body}")
        message = {"raw": base64.urlsafe_b64encode(raw.encode()).decode()}
        sent = service.users().messages().send(userId="me", body=message).execute()
        return {"ok": True, "message_id": sent.get("id", "")}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def disconnect() -> dict:
    """Remove stored Google tokens."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
    return {"ok": True}
