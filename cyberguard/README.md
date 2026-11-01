# CyberGuard — Urai Deep Security Module

Nation-state-grade, AI-driven endpoint + network security for Android, Windows, Linux/Ubuntu.
Built on eBPF (Tetragon/Tracee), Suricata 8, Zeek 9, Android VpnService, Windows WFP/ETW,
Urai AI threat engine, and real-time blockchain/crypto anomaly detection.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     CyberGuard v1                               │
│                                                                 │
│  ┌────────────┐  ┌────────────┐  ┌────────────────────────┐    │
│  │  Android   │  │  Windows   │  │    Linux / Ubuntu      │    │
│  │  APK       │  │  EXE       │  │    Daemon              │    │
│  │            │  │            │  │                        │    │
│  │ VpnService │  │ WFP/ETW    │  │ eBPF (Tetragon+Tracee) │    │
│  │ AppOps     │  │ minifilter │  │ Suricata 8 + Zeek 9    │    │
│  │ TrackerDB  │  │ kernel drv │  │ nftables IPS           │    │
│  └─────┬──────┘  └─────┬──────┘  └──────────┬─────────────┘    │
│        │               │                    │                  │
│        └───────────────┴────────────────────┘                  │
│                        │  JSON events                          │
│                ┌────────▼──────────┐                           │
│                │  Urai AI Engine   │  ← SecAlign + LlamaGuard │
│                │  Threat Analyzer  │    anomaly + ML IDS       │
│                │  /v1/threat/scan  │    EIP-7702 detector      │
│                └────────┬──────────┘    AI scraping detector   │
│                         │                                      │
│                ┌────────▼──────────┐                           │
│                │  Notification     │  instant alert (push,     │
│                │  + Auto-Block     │  SMS, desktop, APK notif) │
│                └───────────────────┘                           │
└─────────────────────────────────────────────────────────────────┘
```

## 3-Tier Scan System

### Tier 1 — Normal Scan (fast, < 2s)
- File/folder hash scan against known malware SHA256 DB (NSRL + VirusShare feeds)
- Installed app tracker/permission scoring (TrackerDB)
- Network connection snapshot (active ports, foreign IPs vs threat intel)
- Process list anomaly (unexpected high-priv processes)
- Quick AppOps audit (who used mic/camera/location in last 24h)

### Tier 2 — Deep Scan (30s–2min)
- Full APK DEX string pool scan for C2 signatures, cryptominers, spyware SDKs
- VpnService packet capture + Suricata rule match (ET Open rules + custom)
- DNS query analysis: DGA detection, known malware C2 domains (PDNS)
- TLS fingerprint (JA4) anomaly detection
- Foreground/background correlation: detect apps using mic/camera while locked
- Runtime memory snapshot comparison (root: /proc/pid/maps analysis)
- EIP-7702 / smart contract delegation transaction monitoring (Web3 wallets)
- Supply chain check: verify APK signing cert hasn't changed

### Tier 3 — Super Mode (continuous, AI-powered)
- eBPF kernel hooks: every syscall, network packet, file I/O (Linux)
- Behavioral ML baseline: learns normal app behavior, flags drift
- AI data exfiltration detection: detects silent data harvesting by any app
  including Google, Facebook, TikTok (VpnService level + DPI)
- AI training data scraping detection: canary tokens, output watermarking,
  query pattern anomaly (detects LLM scrapers and model extraction attacks)
- Self-protection: detects attempts to kill/disable CyberGuard itself
- Nation-state TTPs: TraderTraitor, Lazarus, Jade Sleet signatures
- Blockchain anomaly: EIP-7702 delegation monitoring, abnormal signing bursts
- Zero-day heuristics: process hollowing, DLL sideloading, LOLBins
- Kali Linux offensive technique signatures (2026 latest)
- Anti-AI-bypass: SecAlign-based prompt injection detection on all LLM calls

## Install

### Linux/Ubuntu
```bash
curl -fsSL https://raw.githubusercontent.com/etside/urai/cyberguard/cyberguard/install_linux.sh | sudo bash
cyberguard scan --tier 1   # quick scan
cyberguard scan --tier 2   # deep scan
cyberguard daemon start    # continuous Tier 3
cyberguard status
```

### Android APK
Download `cyberguard.apk` from Releases. Grant:
- VPN permission (for no-root packet capture)
- Usage Access (for AppOps monitoring)
- Notification permission
No root required for Tiers 1–2. Root unlocks full iptables IPS.

### Windows
Download `CyberGuard-Setup.exe` from Releases. Requires admin.
Installs WFP callout driver + ETW session for kernel-level monitoring.

### CLI / MCP
```bash
urai cyberguard scan --tier 2 --target /path/or/ip
urai cyberguard daemon start
# MCP: exposes cyberguard_scan, cyberguard_alert, cyberguard_block tools
```

## Threat Intelligence Sources (auto-updated daily)
- Emerging Threats Open rules (Suricata)
- Abuse.ch (MalwareBazaar, URLhaus, ThreatFox)
- AlienVault OTX community pulses
- CISA KEV (Known Exploited Vulnerabilities)
- TraderTraitor / Lazarus Group IOC feeds
- Blockchain threat intel (TRM Labs public feeds)
- EIP-7702 delegation monitoring (Ethereum mainnet)
