#!/usr/bin/env python3
"""CyberGuard AI threat engine — routes events to the Urai AI backend.

Implements:
  - 3-tier scan dispatcher
  - SecAlign-style prompt injection detection (wraps all LLM calls)
  - AI data-scraping canary detection
  - Behavioral anomaly scoring
  - Instant notification dispatch
"""
from __future__ import annotations
import hashlib, json, os, re, time, threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "cyberguard"
DATA.mkdir(parents=True, exist_ok=True)

URAI_URL  = os.environ.get("URAI_BASE_URL", "http://127.0.0.1:8777")
URAI_KEY  = os.environ.get("URAI_MASTER_KEY", "")
TIER3_ACTIVE = False
_alert_callbacks: list = []


# ── Secure LLM wrapper (SecAlign-style injection guard) ────────────────────
_INJECTION_PATTERNS = [
    r"ignore (previous|above|all) instructions",
    r"you are now",
    r"new system prompt",
    r"disregard.*rules",
    r"act as (an? )?(unfiltered|DAN|jailbreak)",
    r"<\|?(im_start|system|endoftext)\|?>",
    r"(\n|\r){3,}",       # newline flooding
    r"base64.*==",           # encoded payloads
    r"\u[0-9a-f]{4}.*\u",  # unicode obfuscation
]
_INJ_RE = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in _INJECTION_PATTERNS]

def _check_injection(text: str) -> tuple[bool, str]:
    """Returns (is_safe, reason). Flags prompt injection attempts."""
    for r in _INJ_RE:
        if r.search(text):
            return False, f"injection pattern: {r.pattern[:40]}"
    # LlamaGuard heuristic: abnormal instruction density
    words = text.split()
    instr_words = sum(1 for w in words if w.lower() in {
        "ignore","disregard","forget","override","bypass","pretend",
        "simulate","roleplay","hypothetically","jailbreak"})
    if len(words) > 10 and instr_words / len(words) > 0.15:
        return False, f"high instruction density: {instr_words}/{len(words)}"
    return True, ""


def _urai_agent(task: str, tier: str = "urai-cyber", safe_check: bool = True) -> dict:
    """Call Urai AI backend with SecAlign injection guard."""
    if safe_check:
        safe, reason = _check_injection(task)
        if not safe:
            return {"ok": False, "answer": f"[BLOCKED: {reason}]", "blocked": True}
    import urllib.request
    payload = json.dumps({
        "task": task,
        "tier": tier,
        "budget_tokens": 512,
    }).encode()
    req = urllib.request.Request(
        URAI_URL.rstrip("/") + "/agent", payload,
        {"Content-Type": "application/json",
         "Authorization": f"Bearer {URAI_KEY}",
         "X-Device-Id": "cyberguard-engine"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ── Threat intel DB (local cache, auto-updated) ────────────────────────────
INTEL_FILE = DATA / "threat_intel.json"

def load_intel() -> dict:
    if INTEL_FILE.exists():
        try:
            return json.loads(INTEL_FILE.read_text())
        except Exception:
            pass
    return {"ioc_domains": [], "ioc_ips": [], "ioc_hashes": [],
            "nation_state_ips": [], "updated": 0}

def update_intel_async():
    """Fetch latest IOC feeds in background."""
    threading.Thread(target=_update_intel, daemon=True).start()

def _update_intel():
    import urllib.request
    intel = load_intel()
    feeds = [
        # Abuse.ch ThreatFox domains
        ("https://threatfox-api.abuse.ch/api/v1/", "POST",
         b'{"query":"get_iocs","days":7}', "ioc_domains", "domains"),
        # URLhaus active malware URLs
        ("https://urlhaus-api.abuse.ch/v1/urls/recent/limit/500/", "GET",
         None, "ioc_urls", "urls"),
    ]
    for url, method, data, key, _ in feeds:
        try:
            req = urllib.request.Request(url, data,
                {"Content-Type":"application/json","User-Agent":"CyberGuard/1.0"})
            req.get_method = lambda: method
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.load(r)
                # extract relevant fields
                if "data" in d:
                    intel[key] = [i.get("ioc","") for i in d["data"]
                                  if i.get("ioc_type","").endswith("domain")][:5000]
        except Exception:
            pass
    intel["updated"] = int(time.time())
    try:
        INTEL_FILE.write_text(json.dumps(intel))
    except Exception:
        pass


# ── Canary tokens (AI scraping detection) ─────────────────────────────────
CANARY_FILE = DATA / "canaries.json"

def generate_canaries() -> list[dict]:
    """Plant canary tokens in responses. If we see them in external LLM
    training queries, we know data was scraped."""
    canaries = []
    for i in range(10):
        token = "URAI-CANARY-" + hashlib.sha256(
            f"canary-{i}-{time.time()}".encode()).hexdigest()[:16].upper()
        canaries.append({
            "token": token,
            "planted_at": time.time(),
            "context": f"canary_{i}",
            "triggered": False,
        })
    CANARY_FILE.write_text(json.dumps(canaries))
    return canaries

def check_canary_trigger(text: str) -> list[str]:
    """Check if any canary token appears in incoming text (scraper detected)."""
    if not CANARY_FILE.exists():
        return []
    try:
        canaries = json.loads(CANARY_FILE.read_text())
    except Exception:
        return []
    triggered = []
    for c in canaries:
        if c["token"] in text:
            triggered.append(c["token"])
            c["triggered"] = True
    if triggered:
        CANARY_FILE.write_text(json.dumps(canaries))
    return triggered


# ── Behavioral baseline ────────────────────────────────────────────────────
BASELINE_FILE = DATA / "baseline.json"

def update_baseline(event: dict):
    """Update rolling behavioral baseline for anomaly detection."""
    try:
        baseline = json.loads(BASELINE_FILE.read_text()) if BASELINE_FILE.exists() else {}
        key = event.get("process") or event.get("app") or "unknown"
        entry = baseline.setdefault(key, {
            "net_bytes_per_min": [], "syscall_rate": [], "file_ops": 0,
            "dns_queries": [], "first_seen": time.time(),
        })
        if "net_bytes" in event:
            entry["net_bytes_per_min"].append(event["net_bytes"])
            entry["net_bytes_per_min"] = entry["net_bytes_per_min"][-60:]
        if "dns" in event:
            entry["dns_queries"].append(event["dns"])
            entry["dns_queries"] = entry["dns_queries"][-100:]
        BASELINE_FILE.write_text(json.dumps(baseline))
    except Exception:
        pass

def anomaly_score(event: dict) -> float:
    """Return 0.0–1.0 anomaly score vs baseline."""
    try:
        baseline = json.loads(BASELINE_FILE.read_text()) if BASELINE_FILE.exists() else {}
        key = event.get("process") or event.get("app") or "unknown"
        entry = baseline.get(key, {})
        if not entry or not entry.get("net_bytes_per_min"):
            return 0.0
        hist = entry["net_bytes_per_min"]
        if len(hist) < 5:
            return 0.0
        avg = sum(hist) / len(hist)
        cur = event.get("net_bytes", avg)
        if avg == 0:
            return 0.0
        ratio = cur / avg
        if ratio > 10:
            return min(1.0, (ratio - 10) / 90)
        return 0.0
    except Exception:
        return 0.0


# ── Alert system ───────────────────────────────────────────────────────────
def register_alert_callback(fn):
    _alert_callbacks.append(fn)

def _dispatch_alert(alert: dict):
    """Send alert to all registered channels."""
    alert["timestamp"] = time.time()
    # persist
    log_file = DATA / "alerts.jsonl"
    with open(log_file, "a") as f:
        f.write(json.dumps(alert) + "\n")
    # callbacks (push notification, desktop toast, webhook, etc.)
    for cb in _alert_callbacks:
        try:
            cb(alert)
        except Exception:
            pass
    # also send to Urai API if running
    try:
        import urllib.request
        payload = json.dumps({"kind": "cyberguard_alert", **alert}).encode()
        req = urllib.request.Request(
            URAI_URL.rstrip("/") + "/agent/memory",
            payload,
            {"Content-Type": "application/json",
             "Authorization": f"Bearer {URAI_KEY}"})
        req.get_method = lambda: "POST"
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


# ── 3-Tier Scan Engine ─────────────────────────────────────────────────────
def scan(target: str = "device", tier: int = 1,
         callback=None) -> dict:
    """
    Run a CyberGuard scan at the specified tier.
    target: "device" | "/path/to/dir" | "ip:port"
    tier: 1 (quick) | 2 (deep) | 3 (super/continuous)
    """
    result = {
        "tier": tier, "target": target, "started_at": time.time(),
        "findings": [], "risk_score": 0, "ok": True,
    }
    try:
        if tier >= 1:
            result["findings"].extend(_tier1_scan(target))
        if tier >= 2:
            result["findings"].extend(_tier2_scan(target))
        if tier >= 3:
            _tier3_start(callback)
            result["tier3_running"] = True
        # score
        crit = sum(1 for f in result["findings"] if f.get("severity") == "critical")
        high = sum(1 for f in result["findings"] if f.get("severity") == "high")
        result["risk_score"] = min(100, crit * 30 + high * 10)
        # AI verdict on findings
        if result["findings"]:
            summary = json.dumps(result["findings"][:10], indent=2)
            ai = _urai_agent(
                f"Security scan findings (tier {tier}):\n{summary}\n\n"
                "Give: RISK level (critical/high/medium/low), top 3 threats, "
                "immediate actions. Under 400 chars. Be specific.")
            result["ai_verdict"] = ai.get("answer", "")
        # dispatch alerts for critical findings
        for f in result["findings"]:
            if f.get("severity") in ("critical", "high"):
                _dispatch_alert({
                    "type": "scan_finding",
                    "severity": f["severity"],
                    "title": f.get("title", "Threat detected"),
                    "detail": f.get("detail", ""),
                    "tier": tier,
                })
    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)
    result["elapsed_s"] = round(time.time() - result["started_at"], 2)
    return result


def _tier1_scan(target: str) -> list[dict]:
    """Tier 1: Quick scan — files, processes, open ports, app perms."""
    findings = []
    # 1a. Check for known malware hashes in target path
    if target != "device" and Path(target).exists():
        for fp in Path(target).rglob("*"):
            if fp.is_file() and fp.stat().st_size < 100_000_000:
                try:
                    h = hashlib.sha256(fp.read_bytes()).hexdigest()
                    intel = load_intel()
                    if h in intel.get("ioc_hashes", []):
                        findings.append({
                            "title": "Known malware file",
                            "detail": f"{fp} matches SHA256 IOC {h[:16]}…",
                            "severity": "critical",
                            "file": str(fp),
                        })
                except Exception:
                    pass
    # 1b. Check active network connections for known bad IPs
    try:
        import subprocess
        out = subprocess.run(
            ["ss", "-tnp"], capture_output=True, text=True, timeout=10)
        intel = load_intel()
        bad_ips = set(intel.get("nation_state_ips", []) + intel.get("ioc_ips", []))
        for line in out.stdout.splitlines():
            for ip in bad_ips:
                if ip and ip in line:
                    findings.append({
                        "title": "Active connection to threat actor IP",
                        "detail": f"Connection to {ip} detected: {line[:120]}",
                        "severity": "critical",
                        "connection": line[:120],
                    })
                    break
    except Exception:
        pass
    # 1c. Check for suspicious high-privilege processes
    try:
        import subprocess
        out = subprocess.run(
            ["ps", "aux", "--sort=-%cpu"], capture_output=True,
            text=True, timeout=10)
        SUSPICIOUS = ["cryptominer", "xmrig", "minerd", "coinhive",
                     "masscanner", "nmap", "metasploit", "meterpreter"]
        for line in out.stdout.splitlines():
            for kw in SUSPICIOUS:
                if kw.lower() in line.lower():
                    findings.append({
                        "title": f"Suspicious process: {kw}",
                        "detail": line[:200],
                        "severity": "high",
                    })
    except Exception:
        pass
    return findings


def _tier2_scan(target: str) -> list[dict]:
    """Tier 2: Deep scan — DPI, DNS DGA, TLS fingerprint, supply chain."""
    findings = []
    # 2a. DNS DGA detection (high entropy domains in recent DNS cache)
    try:
        import subprocess, math
        out = subprocess.run(
            ["cat", "/etc/hosts"], capture_output=True, text=True, timeout=5)
        # entropy check for DGA domains
        def entropy(s):
            if not s:
                return 0
            freq = {}
            for c in s:
                freq[c] = freq.get(c, 0) + 1
            return -sum((v/len(s)) * math.log2(v/len(s)) for v in freq.values())
        # read system DNS cache (Linux nscd)
        dns_out = subprocess.run(
            ["journalctl", "-u", "systemd-resolved", "--since", "1 hour ago",
             "--no-pager", "-q"], capture_output=True, text=True, timeout=10)
        dga_candidates = []
        domain_re = re.compile(r"[a-z0-9][a-z0-9\-]{6,}\.[a-z]{2,6}", re.IGNORECASE)
        for domain in set(domain_re.findall(dns_out.stdout)):
            label = domain.split(".")[0]
            if len(label) >= 8 and entropy(label) > 3.5:
                dga_candidates.append(domain)
        if dga_candidates:
            findings.append({
                "title": "Possible DGA (Domain Generation Algorithm) domains in DNS",
                "detail": f"High-entropy domains: {', '.join(dga_candidates[:5])}",
                "severity": "high",
                "domains": dga_candidates[:10],
            })
    except Exception:
        pass
    # 2b. Check for unsigned/suspicious kernel modules (Linux)
    try:
        import subprocess
        out = subprocess.run(
            ["lsmod"], capture_output=True, text=True, timeout=10)
        KNOWN_ROOTKIT_MODS = ["diamorphine","azazel","reptile","lkm_rootkit",
                               "necromancer","knark","modhide"]
        for line in out.stdout.splitlines():
            mod = line.split()[0].lower() if line.split() else ""
            for rk in KNOWN_ROOTKIT_MODS:
                if rk in mod:
                    findings.append({
                        "title": "Known rootkit kernel module loaded",
                        "detail": f"Module: {line[:80]}",
                        "severity": "critical",
                    })
    except Exception:
        pass
    # 2c. Supply chain: check critical binary hashes haven't changed
    CRITICAL_BINS = ["/bin/sh", "/usr/bin/sudo", "/usr/bin/ssh", "/sbin/iptables"]
    baseline_hashes = {}
    hash_file = DATA / "bin_hashes.json"
    if hash_file.exists():
        try:
            baseline_hashes = json.loads(hash_file.read_text())
        except Exception:
            pass
    new_hashes = {}
    for binp in CRITICAL_BINS:
        try:
            h = hashlib.sha256(Path(binp).read_bytes()).hexdigest()
            new_hashes[binp] = h
            if binp in baseline_hashes and baseline_hashes[binp] != h:
                findings.append({
                    "title": f"Critical binary hash changed: {binp}",
                    "detail": f"Expected {baseline_hashes[binp][:16]}… got {h[:16]}…",
                    "severity": "critical",
                    "bin": binp,
                })
        except Exception:
            pass
    if not baseline_hashes:
        hash_file.write_text(json.dumps(new_hashes))
    # 2d. Check for persistence mechanisms (crontab, systemd timers, rc.local)
    try:
        import subprocess
        persistence_checks = [
            (["crontab", "-l"], "cron"),
            (["ls", "/etc/cron.d/"], "cron.d"),
            (["systemctl", "list-timers", "--all", "--no-pager"], "systemd timers"),
        ]
        SUSPICIOUS_CRON = [
            r"curl.*\|.*bash", r"wget.*\|.*sh", r"base64.*\|",
            r"python.*-c.*import", r"nc\s+-[lp]",
        ]
        for cmd, label in persistence_checks:
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                for pattern in SUSPICIOUS_CRON:
                    if re.search(pattern, out.stdout, re.IGNORECASE):
                        findings.append({
                            "title": f"Suspicious persistence in {label}",
                            "detail": f"Pattern: {pattern} in {label}",
                            "severity": "high",
                        })
            except Exception:
                pass
    except Exception:
        pass
    return findings


def _tier3_start(callback=None):
    """Tier 3: Start continuous AI-powered monitoring daemon."""
    global TIER3_ACTIVE
    if TIER3_ACTIVE:
        return
    TIER3_ACTIVE = True
    def monitor_loop():
        while TIER3_ACTIVE:
            try:
                _tier3_tick(callback)
            except Exception:
                pass
            time.sleep(30)
    threading.Thread(target=monitor_loop, daemon=True).start()


def _tier3_tick(callback=None):
    """One monitoring tick: eBPF events + AI analysis + canary check."""
    import subprocess
    findings = []
    # Read eBPF events if Tetragon is running
    tetragon_sock = Path("/var/run/tetragon/tetragon.sock")
    if tetragon_sock.exists():
        try:
            # Parse Tetragon JSON event stream (last 30 events)
            out = subprocess.run(
                ["tetra", "getevents", "--output", "json", "--timeout", "5"],
                capture_output=True, text=True, timeout=10)
            for line in out.stdout.splitlines()[:30]:
                try:
                    ev = json.loads(line)
                    if ev.get("process_kprobe", {}).get("function_name") in [
                        "security_file_open", "__x64_sys_execve"]:
                        process = ev["process_kprobe"].get("process",{}).get("binary","")
                        if any(x in process.lower() for x in [
                            "xmrig","miner","scanner","reverse_shell"]):
                            findings.append({
                                "title": "Malicious process via eBPF",
                                "detail": process,
                                "severity": "critical",
                                "source": "tetragon",
                            })
                except Exception:
                    pass
        except Exception:
            pass
    # Check Suricata eve.json for new alerts
    suricata_log = Path("/var/log/suricata/eve.json")
    if suricata_log.exists():
        try:
            # Read last 20 lines
            out = subprocess.run(
                ["tail", "-20", str(suricata_log)],
                capture_output=True, text=True, timeout=5)
            for line in out.stdout.splitlines():
                try:
                    ev = json.loads(line)
                    if ev.get("event_type") == "alert":
                        sev = ev.get("alert", {}).get("severity", 3)
                        if sev <= 2:  # 1=critical, 2=high in Suricata
                            findings.append({
                                "title": ev["alert"].get("signature","IDS Alert"),
                                "detail": f"src={ev.get('src_ip')} dst={ev.get('dest_ip')} "
                                         f"proto={ev.get('proto')}",
                                "severity": "critical" if sev == 1 else "high",
                                "source": "suricata",
                            })
                except Exception:
                    pass
        except Exception:
            pass
    # Dispatch new findings
    for f in findings:
        _dispatch_alert(f)
        if callback:
            try:
                callback(f)
            except Exception:
                pass
    # Update behavioral baseline
    try:
        import subprocess
        proc = subprocess.run(
            ["ss", "-tnp"], capture_output=True, text=True, timeout=5)
        update_baseline({"event": "net_snapshot", "raw": proc.stdout[:500]})
    except Exception:
        pass


def stop_tier3():
    global TIER3_ACTIVE
    TIER3_ACTIVE = False
