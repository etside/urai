#!/usr/bin/env bash
# Urai public deploy — both hosts, API exposed publicly (free until release).
#
# Hosts:
#   1. Tailscale VPS  (wearimpressive-vps, 100.124.118.90)
#   2. AWS EC2        (urai-v3, 52.66.18.45, ap-south-1)
#
# No custom domain yet? sslip.io gives a free HTTPS name for a public IP
# (52.66.18.45 → 52-66-18-45.sslip.io) and Caddy gets a Let's Encrypt cert.
# Set URAI_DOMAIN to use your own domain instead.
#
# Usage:
#   export OPENROUTER_API_KEY=sk-or-...
#   export URAI_MASTER_KEY=$(openssl rand -hex 32)   # save it
#   export URAI_DOMAIN=urai.example.com              # optional
#   export URAI_BRANCH=feat/muse-spark-open          # optional (default main)
#   bash deploy/deploy-public.sh --tailscale|--aws|--both
#
# Prereqs per host: sudo, git, python3>=3.10, ports 80+443 reachable.
set -euo pipefail

DOMAIN="${URAI_DOMAIN:-}"
BRANCH="${URAI_BRANCH:-main}"
REPO="${URAI_REPO:-https://github.com/etside/urai.git}"
SSH_KEY="${URAI_SSH_KEY:-}"

: "${OPENROUTER_API_KEY:?Set OPENROUTER_API_KEY}"
: "${URAI_MASTER_KEY:?Set URAI_MASTER_KEY (openssl rand -hex 32)}"

SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)
[ -n "$SSH_KEY" ] && SSH_OPTS+=(-i "$SSH_KEY")
SCP_OPTS=("${SSH_OPTS[@]}")

sshx() { ssh "${SSH_OPTS[@]}" "$@"; }
scpx() { scp "${SCP_OPTS[@]}" "$@"; }

public_ip() {
  sshx "$1" "curl -s --max-time 5 https://api.ipify.org || curl -s --max-time 5 https://ifconfig.me" \
    | tr -d '[:space:]'
}

deploy_one() {
  local ssh_target="$1" label="$2" domain="$3"
  echo "=== $label ($ssh_target) → https://$domain ==="

  local envfile; envfile="$(mktemp)"
  cat > "$envfile" <<ENV
URAI_PORT=8777
URAI_HOST=127.0.0.1
URAI_MODEL=${URAI_MODEL:-urai-qwen3-06b}
URAI_MASTER_KEY=$URAI_MASTER_KEY
URAI_PUBLIC=1
URAI_FREE_MODE=1
URAI_CLOUD_FALLBACK=1
URAI_CLOUD_PRIMARY=${URAI_CLOUD_PRIMARY:-1}
URAI_CORS_ORIGIN=https://etside.github.io
URAI_RATE_LIMIT=${URAI_RATE_LIMIT:-120}
URAI_CLOUD_CONSULT=1
URAI_CLOUD_1M=1
URAI_REASONING_EFFORT=${URAI_REASONING_EFFORT:-medium}
OPENROUTER_API_KEY=$OPENROUTER_API_KEY
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=meta/muse-spark-open
${VERCEL_AI_GATEWAY_API_KEY:+VERCEL_AI_GATEWAY_API_KEY=$VERCEL_AI_GATEWAY_API_KEY}
VERCEL_AI_GATEWAY_BASE_URL=${VERCEL_AI_GATEWAY_BASE_URL:-https://ai-gateway.vercel.sh/v1}
VERCEL_AI_GATEWAY_MODEL=${VERCEL_AI_GATEWAY_MODEL:-humansand/ampersand-v0.1}
URAI_PUBLIC_URL=https://$domain/
${URAI_LOCAL_URL:+JEV_LLAMA_URL=$URAI_LOCAL_URL}
${URAI_LOCAL_URL:+JEV_LLAMA_MODEL=$URAI_MODEL}
ENV

  # Ship the env file out-of-band so the key never appears in a shell history
  # or a remote process list.
  scpx -q "$envfile" "$ssh_target:/tmp/urai.env.new"
  rm -f "$envfile"

  sshx "$ssh_target" "BRANCH='$BRANCH' REPO='$REPO' DOMAIN='$domain' bash -s" <<'REMOTE'
set -euo pipefail

# ── code ────────────────────────────────────────────────────────────────────
if [ -d /opt/urai/.git ]; then
  cd /opt/urai
  sudo git fetch --depth 1 origin "$BRANCH"
  sudo git checkout -f -B deploy-muse FETCH_HEAD
else
  sudo mkdir -p /opt/urai
  sudo chown "$USER": /opt/urai
  sudo git clone --depth 1 --branch "$BRANCH" "$REPO" /opt/urai
  sudo chown -R "$USER": /opt/urai
  cd /opt/urai
fi
cd /opt/urai

# ── env ─────────────────────────────────────────────────────────────────────
sudo mv /tmp/urai.env.new /opt/urai/.env
sudo chown root:root /opt/urai/.env
sudo chmod 600 /opt/urai/.env

# ── systemd ─────────────────────────────────────────────────────────────────
sudo tee /etc/systemd/system/urai-api.service >/dev/null <<UNIT
[Unit]
Description=Urai API (public, Muse Spark Open teacher)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/opt/urai
EnvironmentFile=/opt/urai/.env
Environment=PYTHONPATH=/opt/urai
ExecStart=/usr/bin/python3 -m jev.cli api --host 127.0.0.1 --port 8777
Restart=always
RestartSec=5
NoNewPrivileges=true
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
UNIT

# ── caddy (automatic HTTPS) ─────────────────────────────────────────────────
if ! command -v caddy >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl gnupg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | sudo gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -qq
  sudo apt-get install -y -qq caddy
fi
sudo tee /etc/caddy/Caddyfile >/dev/null <<CADDY
$DOMAIN {
    encode gzip zstd
    reverse_proxy 127.0.0.1:8777 {
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        flush_interval -1
    }
    header {
        Strict-Transport-Security "max-age=31536000"
        X-Content-Type-Options "nosniff"
        -Server
    }
}
CADDY

sudo systemctl disable --now urai 2>/dev/null || true
sudo systemctl daemon-reload
sudo systemctl enable --now urai-api
sudo systemctl restart urai-api
sudo systemctl enable --now caddy
sudo systemctl reload caddy || sudo systemctl restart caddy

sleep 3
echo "local health: $(curl -s --max-time 5 http://127.0.0.1:8777/health | head -c 80)"
echo "public url:   https://$DOMAIN"
REMOTE
}

case "${1:-}" in
  --tailscale)
    t=wearimpressive-vps
    deploy_one "$t" "Tailscale VPS" "${DOMAIN:-$(public_ip "$t" | sed 's/\./-/g').sslip.io}" ;;
  --aws)
    t=ubuntu@52.66.18.45
    deploy_one "$t" "AWS EC2 urai-v3" "${DOMAIN:-$(public_ip "$t" | sed 's/\./-/g').sslip.io}" ;;
  --both)
    t=ubuntu@52.66.18.45
    deploy_one "$t" "AWS EC2 urai-v3" "${DOMAIN:-$(public_ip "$t" | sed 's/\./-/g').sslip.io}"
    t=wearimpressive-vps
    deploy_one "$t" "Tailscale VPS" "${DOMAIN:-$(public_ip "$t" | sed 's/\./-/g').sslip.io}" ;;
  *) echo "usage: bash deploy/deploy-public.sh --tailscale|--aws|--both"; exit 1 ;;
esac

echo
echo "Verify:"
echo "  curl https://<domain>/health"
echo "  curl https://<domain>/v1/models"
echo "  curl https://<domain>/v1/chat/completions \\"
echo "    -H 'Authorization: Bearer \$URAI_MASTER_KEY' -H 'Content-Type: application/json' \\"
echo "    -d '{\"model\":\"urai\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}'"
echo
echo "Pricing: Muse Spark Open \$1.25/M in + \$4.25/M out (OpenRouter)."
