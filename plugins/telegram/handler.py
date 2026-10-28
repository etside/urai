"""Telegram channel plugin (stdlib only, urllib long-polling).

Full duplex: polls getUpdates, answers via Urai /agent with a per-chat
session (memory across turns), allowlist-gated, typing indicator,
>4096-char message splitting, /new + /help commands.

Daemon: serve_forever() (run: urai plugin serve telegram).
Env: TELEGRAM_BOT_TOKEN (required), URAI_REMOTE_URL (default http://127.0.0.1:8777),
     URAI_MASTER_KEY (required), TELEGRAM_ALLOW_CHAT_IDS (comma list, empty = deny all),
     URAI_DEVICE_ID (default telegram-plugin).
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

API = "https://api.telegram.org"
TG_LIMIT = 4000


def _allow() -> set:
    return {c.strip() for c in os.environ.get("TELEGRAM_ALLOW_CHAT_IDS", "").split(",") if c.strip()}


def _tg(method, payload):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    req = urllib.request.Request(
        f"{API}/bot{token}/{method}", json.dumps(payload).encode(),
        {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=70) as r:
        return json.load(r)


def _send_split(chat_id, text):
    text = text or "(empty reply)"
    parts = [text[i:i + TG_LIMIT] for i in range(0, len(text), TG_LIMIT)] or [text]
    for part in parts:
        _tg("sendMessage", {"chat_id": chat_id, "text": part})
    return len(parts)


def _urai(path, body):
    base = (os.environ.get("URAI_REMOTE_URL", "http://127.0.0.1:8777")).rstrip("/")
    key = os.environ.get("URAI_MASTER_KEY", "")
    dev = os.environ.get("URAI_DEVICE_ID", "telegram-plugin")
    req = urllib.request.Request(
        base + path, json.dumps(body).encode(),
        {"Content-Type": "application/json",
         "Authorization": "Bearer " + key, "X-Device-Id": dev})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def _sess_clear(session_id):
    try:
        _urai("/agent/sessions", {"action": "clear", "session_id": session_id})
    except Exception:
        pass


def _ask_urai(text, session_id):
    base = (os.environ.get("URAI_REMOTE_URL", "http://127.0.0.1:8777")).rstrip("/")
    key = os.environ.get("URAI_MASTER_KEY", "")
    dev = os.environ.get("URAI_DEVICE_ID", "telegram-plugin")
    body = {"task": text, "session_id": session_id, "budget_tokens": 2048}
    req = urllib.request.Request(
        base + "/agent", json.dumps(body).encode(),
        {"Content-Type": "application/json",
         "Authorization": "Bearer " + key, "X-Device-Id": dev})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.load(r)
    return (d.get("answer") or json.dumps(d)[:1000])[:12000]


def on_hook(hook, payload):
    if hook != "message":
        return {"ok": False, "error": f"unsupported hook: {hook}"}
    chat_id = str(payload.get("chat_id", ""))
    text = (payload.get("text", "") or "").strip()
    if not text:
        return {"ok": False, "error": "empty text"}
    if chat_id not in _allow():
        return {"ok": False, "error": "chat not allowlisted"}
    if text == "/new":
        _sess_clear(f"tg-{chat_id}")
        return {"ok": True, "answer": "fresh session started — send anything."}
    if text == "/help":
        return {"ok": True, "answer": "Urai harness bot. /new fresh session, /help this. All turns remembered per chat."}
    try:
        answer = _ask_urai(text, f"tg-{chat_id}")
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    if chat_id:
        try:
            _tg("sendChatAction", {"chat_id": payload.get("chat_id"), "action": "typing"})
            n = _send_split(payload.get("chat_id"), answer)
        except Exception as e:
            return {"ok": False, "error": f"send failed: {e}"}
        return {"ok": True, "answer": answer, "parts": n}
    return {"ok": True, "answer": answer}


def serve_forever():
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        raise SystemExit("TELEGRAM_BOT_TOKEN not set — create via @BotFather, then export it.")
    if not _allow():
        print("WARN: TELEGRAM_ALLOW_CHAT_IDS empty — all chats denied until set.")
    print("telegram plugin polling (Ctrl-C to stop)…")
    offset = 0
    while True:
        try:
            d = _tg("getUpdates", {"offset": offset, "timeout": 50,
                                   "allowed_updates": ["message"]})
        except Exception as e:
            print(f"poll error: {e}; retrying in 5s")
            time.sleep(5)
            continue
        for u in d.get("result", []):
            offset = u["update_id"] + 1
            m = u.get("message") or {}
            text = m.get("text", "")
            if not text:
                continue
            cid = m.get("chat", {}).get("id")
            print(f"<- {cid}: {text[:80]}")
            if text == "/new":
                _sess_clear(f"tg-{cid}")
                r = {"ok": True, "answer": "fresh session started."}
                try:
                    _send_split(cid, r["answer"])
                except Exception as e:
                    r = {"ok": False, "error": str(e)[:150]}
            else:
                r = on_hook("message", {"text": text, "chat_id": cid})
            print(("-> sent" if r.get("ok") else f"-> failed: {r.get('error')}"))
