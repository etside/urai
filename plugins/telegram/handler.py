"""Telegram channel plugin (stdlib only, urllib long-polling).

Hooks: on_hook("message", {text, chat_id}) -> answers via Urai remote API.
Daemon: serve_forever() polls getUpdates and replies (run: urai plugin serve telegram).
Needs TELEGRAM_BOT_TOKEN env. Urai side: URAI_REMOTE_URL + URAI_MASTER_KEY.
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


def _tg(method, payload):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    req = urllib.request.Request(
        f"{API}/bot{token}/{method}", json.dumps(payload).encode(),
        {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=70) as r:
        return json.load(r)


def _ask_urai(text):
    base = (os.environ.get("URAI_REMOTE_URL", "https://urai.daddyai.online")).rstrip("/")
    key = os.environ.get("URAI_MASTER_KEY", "")
    dev = os.environ.get("URAI_DEVICE_ID", "telegram-plugin")
    body = {"model": "jev-local-student",
            "messages": [{"role": "user", "content": text}],
            "max_tokens": 512, "device_id": dev}
    req = urllib.request.Request(
        base + "/v1/chat/completions", json.dumps(body).encode(),
        {"Content-Type": "application/json",
         "Authorization": "Bearer " + key, "X-Device-Id": dev})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.load(r)
    if isinstance(d, dict) and d.get("choices"):
        return d["choices"][0]["message"]["content"][:3500]
    return json.dumps(d)[:1000]


def on_hook(hook, payload):
    if hook != "message":
        return {"ok": False, "error": f"unsupported hook: {hook}"}
    try:
        answer = _ask_urai(payload.get("text", ""))
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    chat_id = payload.get("chat_id")
    if chat_id:
        try:
            _tg("sendMessage", {"chat_id": chat_id, "text": answer})
        except Exception as e:
            return {"ok": False, "error": f"send failed: {e}"}
    return {"ok": True, "answer": answer}


def serve_forever():
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
            print(f"<- {m.get('chat', {}).get('id')}: {text[:80]}")
            r = on_hook("message", {"text": text, "chat_id": m["chat"]["id"]})
            print(("-> sent" if r.get("ok") else f"-> failed: {r.get('error')}"))
