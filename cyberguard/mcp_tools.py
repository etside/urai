#!/usr/bin/env python3
"""CyberGuard MCP tool definitions — plugs into Urai's existing MCP server."""

TOOLS = [
    {
        "name": "cyberguard_scan",
        "description": "Run a CyberGuard security scan. tier=1 (quick, <2s), "
                       "tier=2 (deep, ~60s), tier=3 (start continuous daemon). "
                       "Returns risk_score (0-100), findings list, AI verdict.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tier": {"type": "integer", "default": 1, "description": "1=quick 2=deep 3=continuous"},
                "target": {"type": "string", "default": "device", "description": "path, IP, or 'device'"},
            },
        },
    },
    {
        "name": "cyberguard_block",
        "description": "Immediately block an IP address at the kernel level (nftables/iptables).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ip": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["ip"],
        },
    },
    {
        "name": "cyberguard_alert_history",
        "description": "Get recent CyberGuard security alerts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20},
                "severity": {"type": "string", "default": "all",
                             "description": "all|critical|high|medium|low"},
            },
        },
    },
    {
        "name": "cyberguard_threat_intel",
        "description": "Query CyberGuard threat intelligence — check if an IP, domain, or hash is malicious.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "IP, domain, SHA256 hash, or CVE"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "cyberguard_analyze_packet",
        "description": "Analyze a network packet or flow for malicious content using AI + Suricata rules.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pcap_b64": {"type": "string", "description": "base64-encoded pcap bytes"},
                "flow_json": {"type": "object", "description": "flow metadata dict"},
            },
        },
    },
]


def handle_tool(name: str, args: dict) -> str:
    """Execute a CyberGuard MCP tool call."""
    import json
    from cyberguard.engine import scan, load_intel, _dispatch_alert, DATA

    if name == "cyberguard_scan":
        result = scan(
            target=args.get("target", "device"),
            tier=int(args.get("tier", 1)),
        )
        return json.dumps({
            "risk_score": result["risk_score"],
            "findings": result["findings"][:10],
            "ai_verdict": result.get("ai_verdict", ""),
            "elapsed_s": result.get("elapsed_s"),
        }, indent=2)[:6000]

    if name == "cyberguard_block":
        import subprocess
        ip = args.get("ip", "")
        try:
            subprocess.run(
                ["nft", "add", "element", "inet", "cyberguard",
                 "block_ipv4", f"{{ {ip} }}"],
                check=True, capture_output=True, timeout=10)
            _dispatch_alert({
                "type": "ip_blocked",
                "severity": "info",
                "title": f"IP blocked: {ip}",
                "detail": f"Reason: {args.get('reason', 'MCP request')}",
            })
            return json.dumps({"ok": True, "blocked": ip})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)[:200]})

    if name == "cyberguard_alert_history":
        log_file = DATA / "alerts.jsonl"
        if not log_file.exists():
            return json.dumps({"alerts": [], "total": 0})
        lines = log_file.read_text().splitlines()
        limit = int(args.get("limit", 20))
        sev_filter = args.get("severity", "all")
        alerts = []
        for line in reversed(lines):
            try:
                a = json.loads(line)
                if sev_filter == "all" or a.get("severity") == sev_filter:
                    alerts.append(a)
                    if len(alerts) >= limit:
                        break
            except Exception:
                pass
        return json.dumps({"alerts": alerts, "total": len(lines)}, indent=2)[:6000]

    if name == "cyberguard_threat_intel":
        query = args.get("query", "")
        intel = load_intel()
        result = {
            "query": query,
            "is_malicious": False,
            "matches": [],
        }
        if query in intel.get("ioc_ips", []):
            result["is_malicious"] = True
            result["matches"].append("ioc_ips feed")
        if query in intel.get("ioc_domains", []):
            result["is_malicious"] = True
            result["matches"].append("ioc_domains feed")
        if query in intel.get("ioc_hashes", []):
            result["is_malicious"] = True
            result["matches"].append("ioc_hashes feed")
        if query in intel.get("nation_state_ips", []):
            result["is_malicious"] = True
            result["matches"].append("nation_state feed (TraderTraitor/Lazarus)")
        if not result["matches"]:
            result["verdict"] = "Not found in local feeds — may still be malicious"
        return json.dumps(result, indent=2)

    if name == "cyberguard_analyze_packet":
        from cyberguard.engine import _urai_agent
        flow = args.get("flow_json", {})
        task = (
            f"Analyze this network flow for threats:\n{json.dumps(flow, indent=2)}\n\n"
            "Check for: C2 communication, data exfiltration, lateral movement, "
            "DGA domains, unusual ports, known attack patterns, EIP-7702 exploitation. "
            "Reply: THREAT level + specific finding. Under 300 chars.")
        result = _urai_agent(task, tier="urai-cyber")
        return result.get("answer", result.get("error", "Analysis failed"))[:1000]

    return json.dumps({"error": f"Unknown tool: {name}"})
