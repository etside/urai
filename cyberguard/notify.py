#!/usr/bin/env python3
"""CyberGuard notification dispatcher — desktop, Urai push, webhook."""
import json, os, subprocess, threading, urllib.request


def desktop_notify(title: str, body: str, severity: str = "info"):
    """Send desktop notification (Linux: notify-send, macOS: osascript)."""
    icon = {
        "critical": "dialog-error",
        "high": "dialog-warning",
        "info": "dialog-information",
    }.get(severity, "dialog-information")
    # Linux
    try:
        subprocess.run(
            ["notify-send", "-u",
             "critical" if severity == "critical" else "normal",
             "-i", icon,
             f"CyberGuard: {title}", body[:200]],
            check=False, timeout=5, capture_output=True)
        return
    except FileNotFoundError:
        pass
    # macOS
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{body[:100]}" with title "CyberGuard: {title}"'],
            check=False, timeout=5, capture_output=True)
    except FileNotFoundError:
        pass


def webhook_notify(url: str, alert: dict):
    """POST alert JSON to a webhook (Slack, Discord, custom)."""
    payload = json.dumps({
        "text": f"[CyberGuard {alert.get('severity','info').upper()}] "
                f"{alert.get('title','Alert')}: {alert.get('detail','')[:200]}",
        "alert": alert,
    }).encode()
    try:
        req = urllib.request.Request(
            url, payload,
            {"Content-Type": "application/json", "User-Agent": "CyberGuard/1.0"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        pass  # notification failure must not affect security logic


def push_to_urai_studio(base_url: str, api_key: str, alert: dict):
    """Push alert to Urai Studio live log (/superadmin or /agent/memory)."""
    payload = json.dumps({
        "action": "remember",
        "text": f"[CYBERGUARD {alert.get('severity','info').upper()}] "
               f"{alert.get('title')}: {alert.get('detail','')[:300]}",
        "kind": "cyberguard_alert",
    }).encode()
    try:
        req = urllib.request.Request(
            base_url.rstrip("/") + "/agent/memory", payload,
            {"Content-Type": "application/json",
             "Authorization": f"Bearer {api_key}"})
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass
