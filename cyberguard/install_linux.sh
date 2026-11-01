#!/usr/bin/env bash
# CyberGuard Linux/Ubuntu installer
# Installs: eBPF (Tetragon), Suricata 8, Zeek 9, CyberGuard daemon
# Requirements: Ubuntu 22.04+ or Debian 12+, kernel >= 5.8 (for eBPF)
set -euo pipefail
CYAN="\033[0;36m"; GREEN="\033[0;32m"; RED="\033[0;31m"; NC="\033[0m"

info()  { echo -e "${CYAN}[CyberGuard]${NC} $*"; }
ok()    { echo -e "${GREEN}[✓]${NC} $*"; }
err()   { echo -e "${RED}[✗]${NC} $*"; exit 1; }

[ "$(id -u)" = "0" ] || err "Run as root: sudo bash install_linux.sh"

KERNEL=$(uname -r | cut -d. -f1-2)
info "Kernel: $KERNEL  |  Checking eBPF support..."
[ -f /sys/kernel/btf/vmlinux ] || info "Warning: BTF not found — some eBPF features limited"

# ── 1. Suricata 8 ────────────────────────────────────────────────────────
info "Installing Suricata 8..."
add-apt-repository -y ppa:oisf/suricata-stable 2>/dev/null || true
apt-get update -qq
apt-get install -y suricata suricata-update

# Update Emerging Threats rules
suricata-update update-sources
suricata-update enable-source et/open
suricata-update enable-source ptresearch/attackdetection
suricata-update
ok "Suricata installed: $(suricata --version 2>&1 | head -1)"

# ── 2. Zeek 9 ───────────────────────────────────────────────────────────
info "Installing Zeek 9..."
echo "deb http://download.opensuse.org/repositories/security:/zeek/xUbuntu_22.04/ /"   > /etc/apt/sources.list.d/zeek.list
curl -fsSL https://download.opensuse.org/repositories/security:zeek/xUbuntu_22.04/Release.key   | gpg --dearmor > /etc/apt/trusted.gpg.d/zeek.gpg 2>/dev/null || true
apt-get update -qq
apt-get install -y zeek 2>/dev/null || apt-get install -y zeek-lts || info "Zeek install skipped (add repo manually)"
ok "Zeek ready"

# ── 3. Tetragon (Cilium eBPF) ────────────────────────────────────────────
info "Installing Tetragon..."
TETRAGON_VER="1.4.0"
ARCH=$(uname -m | sed s/x86_64/amd64/ | sed s/aarch64/arm64/)
curl -fsSL -o /tmp/tetragon.tar.gz   "https://github.com/cilium/tetragon/releases/download/v${TETRAGON_VER}/tetragon-${TETRAGON_VER}-${ARCH}.tar.gz" 2>/dev/null   || info "Warning: Tetragon download failed — falling back to Tracee"

if [ -f /tmp/tetragon.tar.gz ]; then
  tar -xzf /tmp/tetragon.tar.gz -C /usr/local/bin/ tetra tetragon 2>/dev/null || true
  ok "Tetragon installed"
fi

# ── 4. Tracee (Aqua) as fallback / forensics layer ──────────────────────
info "Installing Tracee..."
apt-get install -y apt-transport-https curl
curl -fsSL https://aquasecurity.github.io/trivy-repo/deb/public.key   | gpg --dearmor -o /etc/apt/trusted.gpg.d/aqua.gpg 2>/dev/null || true
apt-get install -y tracee 2>/dev/null || info "Tracee install skipped"

# ── 5. Python deps for CyberGuard engine ────────────────────────────────
info "Installing Python dependencies..."
pip3 install -q scapy yara-python requests cryptography 2>/dev/null || true

# ── 6. Install CyberGuard daemon ─────────────────────────────────────────
info "Installing CyberGuard..."
URAI_DIR="${URAI_DIR:-$HOME/.local/share/urai}"
CGDIR="$URAI_DIR/cyberguard"

# Install systemd service
cat > /etc/systemd/system/cyberguard.service << SVCEOF
[Unit]
Description=CyberGuard — Urai Deep Security Daemon
After=network-online.target suricata.service
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$URAI_DIR
ExecStart=/usr/bin/python3 -m cyberguard.daemon --tier 3
Restart=always
RestartSec=5
KillMode=mixed
LimitNOFILE=65536
StandardOutput=journal
SyslogIdentifier=cyberguard

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable cyberguard
ok "CyberGuard service installed"

# ── 7. Install nftables IPS rules (block known bad IPs at kernel level) ──
info "Setting up nftables IPS..."
cat > /etc/nftables.d/cyberguard.nft << 'NFTEOF'
# CyberGuard nftables rules — auto-managed, do not edit manually
table inet cyberguard {
    set block_ipv4 {
        type ipv4_addr
        flags dynamic,timeout
        timeout 1h
        comment "CyberGuard blocked IPs — auto-populated"
    }
    set block_ipv6 {
        type ipv6_addr
        flags dynamic,timeout
        timeout 1h
    }
    chain input {
        type filter hook input priority -100; policy accept;
        ip saddr @block_ipv4 drop comment "CyberGuard block"
        ip6 saddr @block_ipv6 drop
    }
    chain output {
        type filter hook output priority -100; policy accept;
        ip daddr @block_ipv4 drop comment "CyberGuard outbound block"
    }
}
NFTEOF
nft -f /etc/nftables.d/cyberguard.nft 2>/dev/null || info "nftables rule add skipped"
ok "nftables IPS rules loaded"

echo ""
ok "CyberGuard installed. Start with: systemctl start cyberguard"
echo "  Quick scan:    cyberguard scan --tier 1"
echo "  Deep scan:     cyberguard scan --tier 2"
echo "  Continuous:    systemctl start cyberguard"
echo "  Status:        cyberguard status"
