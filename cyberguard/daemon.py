#!/usr/bin/env python3
"""CyberGuard daemon — continuous Tier 3 monitoring + notification server."""
import argparse, json, os, signal, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cyberguard.engine import scan, stop_tier3, update_intel_async, _dispatch_alert
from cyberguard.notify import desktop_notify


def alert_handler(alert: dict):
    """Print + desktop notify on critical/high alerts."""
    sev = alert.get("severity", "info")
    title = alert.get("title", "Security Alert")
    detail = alert.get("detail", "")
    print(f"[{sev.upper()}] {title}: {detail[:120]}", flush=True)
    if sev in ("critical", "high"):
        desktop_notify(title, detail[:200], sev)


def main():
    ap = argparse.ArgumentParser(prog="cyberguard")
    sub = ap.add_subparsers(dest="cmd")

    p_scan = sub.add_parser("scan")
    p_scan.add_argument("--tier", type=int, default=1, choices=[1, 2, 3])
    p_scan.add_argument("--target", default="device")
    p_scan.add_argument("--json", action="store_true")

    sub.add_parser("status")
    p_daemon = sub.add_parser("daemon")
    p_daemon.add_argument("action", choices=["start", "stop"])

    p_block = sub.add_parser("block")
    p_block.add_argument("ip")

    p_intel = sub.add_parser("update-intel")

    args = ap.parse_args()

    if args.cmd == "scan" or args.cmd is None:
        tier = getattr(args, "tier", 1)
        target = getattr(args, "target", "device")
        as_json = getattr(args, "json", False)
        print(f"CyberGuard Tier {tier} scan — target: {target}")
        from cyberguard.engine import register_alert_callback
        register_alert_callback(alert_handler)
        result = scan(target=target, tier=tier, callback=alert_handler)
        if as_json:
            print(json.dumps(result, indent=2))
        else:
            print(f"\nRisk score: {result['risk_score']}/100")
            print(f"Findings: {len(result['findings'])}")
            for f in result["findings"]:
                print(f"  [{f['severity'].upper()}] {f['title']}: {f['detail'][:80]}")
            if result.get("ai_verdict"):
                print(f"\nAI verdict: {result['ai_verdict']}")
        return

    if args.cmd == "status":
        from cyberguard.engine import TIER3_ACTIVE, DATA
        print(f"Tier 3 daemon: {'running' if TIER3_ACTIVE else 'stopped'}")
        log = DATA / "alerts.jsonl"
        if log.exists():
            lines = log.read_text().splitlines()
            print(f"Total alerts logged: {len(lines)}")
            if lines:
                last = json.loads(lines[-1])
                print(f"Last alert: [{last.get('severity')}] {last.get('title')}")
        return

    if args.cmd == "daemon":
        if args.action == "start":
            print("Starting CyberGuard daemon (Tier 3)…")
            update_intel_async()
            from cyberguard.engine import register_alert_callback
            register_alert_callback(alert_handler)
            scan(tier=3, callback=alert_handler)
            # block until signal
            def _stop(s, f):
                stop_tier3()
                sys.exit(0)
            signal.signal(signal.SIGTERM, _stop)
            signal.signal(signal.SIGINT, _stop)
            while True:
                time.sleep(60)
        elif args.action == "stop":
            stop_tier3()
            print("Tier 3 stopped.")
        return

    if args.cmd == "block":
        # Block an IP via nftables immediately
        import subprocess
        ip = args.ip
        try:
            subprocess.run(
                ["nft", "add", "element", "inet", "cyberguard", "block_ipv4",
                 f"{{ {ip} }}"],
                check=True, capture_output=True)
            print(f"Blocked: {ip}")
            _dispatch_alert({
                "type": "manual_block",
                "severity": "info",
                "title": f"IP blocked: {ip}",
                "detail": "Manually blocked via cyberguard CLI",
            })
        except Exception as e:
            print(f"Block failed: {e}")
        return

    if args.cmd == "update-intel":
        print("Updating threat intelligence feeds…")
        from cyberguard.engine import _update_intel
        _update_intel()
        print("Done.")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
