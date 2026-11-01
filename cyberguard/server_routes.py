#!/usr/bin/env python3
"""
CyberGuard server-side routes — added to jev/server.py via plugin.

Exposes:
  GET  /v1/threat/intel          — current IOC feed (for Android/Windows agents)
  POST /v1/threat/scan           — AI-powered threat analysis
  GET  /v1/threat/status         — daemon status + alert counts
  POST /v1/threat/block          — add IP to block list
  POST /v1/threat/report         — receive alert from an agent
"""
from __future__ import annotations
import json, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "cyberguard"
DATA.mkdir(parents=True, exist_ok=True)

INTEL_FILE  = DATA / "threat_intel.json"
ALERTS_FILE = DATA / "alerts.jsonl"
BLOCKS_FILE = DATA / "blocked_ips.json"


def load_blocks() -> list:
    if BLOCKS_FILE.exists():
        try:
            return json.loads(BLOCKS_FILE.read_text())
        except Exception:
            pass
    return []

def save_blocks(blocks: list):
    BLOCKS_FILE.write_text(json.dumps(blocks))


def handle_get(path: str, query: dict) -> dict | None:
    if path == "/v1/threat/intel":
        if INTEL_FILE.exists():
            try:
                return json.loads(INTEL_FILE.read_text())
            except Exception:
                pass
        return {"ioc_ips": [], "ioc_domains": [], "ioc_hashes": [],
                "nation_state_ips": [], "updated": 0}

    if path == "/v1/threat/status":
        alerts = []
        if ALERTS_FILE.exists():
            try:
                alerts = ALERTS_FILE.read_text().splitlines()
            except Exception:
                pass
        from cyberguard.engine import TIER3_ACTIVE
        return {
            "tier3_running": TIER3_ACTIVE,
            "total_alerts": len(alerts),
            "blocked_ips": len(load_blocks()),
            "intel_updated": json.loads(INTEL_FILE.read_text()).get("updated", 0)
                             if INTEL_FILE.exists() else 0,
        }
    return None


def handle_post(path: str, body: dict) -> dict | None:
    if path == "/v1/threat/scan":
        from cyberguard.engine import scan, _check_injection
        target = body.get("target", "device")
        tier = int(body.get("tier", 1))
        # guard against injection via target field
        safe, reason = _check_injection(target)
        if not safe:
            return {"ok": False, "error": f"Input rejected: {reason}"}
        return scan(target=target, tier=tier)

    if path == "/v1/threat/block":
        ip = body.get("ip", "").strip()
        if not ip:
            return {"ok": False, "error": "ip required"}
        import re
        if not re.match(r"^[\d\.]{7,15}$|^[0-9a-f:]{3,39}$", ip):
            return {"ok": False, "error": "invalid IP"}
        blocks = load_blocks()
        if ip not in blocks:
            blocks.append(ip)
            save_blocks(blocks)
            # Apply to nftables if available
            try:
                import subprocess
                subprocess.run(
                    ["nft", "add", "element", "inet", "cyberguard",
                     "block_ipv4", f"{{ {ip} }}"],
                    capture_output=True, timeout=10)
            except Exception:
                pass
        return {"ok": True, "blocked": ip, "total_blocks": len(blocks)}

    if path == "/v1/threat/report":
        # Receive alert from Android/Windows agent
        alert = {
            "title": body.get("title", ""),
            "detail": body.get("detail", ""),
            "severity": body.get("severity", "info"),
            "source": body.get("source", "agent"),
            "timestamp": time.time(),
        }
        with open(ALERTS_FILE, "a") as f:
            f.write(json.dumps(alert) + "\n")
        # Feed to Urai AI for analysis if critical
        if alert["severity"] in ("critical", "high"):
            try:
                from cyberguard.engine import _urai_agent
                ai = _urai_agent(
                    f"Security alert from device:\nTitle: {alert['title']}\n"
                    f"Detail: {alert['detail']}\n"
                    "Give immediate recommended action in under 200 chars.",
                    tier="urai-cyber")
                alert["ai_response"] = ai.get("answer", "")
            except Exception:
                pass
        return {"ok": True, "alert_id": f"cg-{int(time.time())}"}

    return None
