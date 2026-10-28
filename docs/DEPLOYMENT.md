# Urai Deployment Guide

The canonical guide for getting Urai running in production.
For local/dev setup see the [main README](../README.md).

---

## Quick decision: which setup fits you?

| Setup | When to use |
|---|---|
| **VPS + systemd + Caddy** | Recommended. Stable, restarts on crash, HTTPS automatic. |
| **Docker Compose** | Good for isolated environments or if you prefer containers. |
| **Local only** | Dev/personal use. No HTTPS, no process supervisor needed. |

---

## 1. VPS deploy (recommended)

### 1.1 Provision a server

Minimum: 2 vCPU, 4 GB RAM, Ubuntu 22.04/24.04.
Recommended: 4 vCPU, 8 GB RAM (runs qwen3-4b comfortably).

```bash
# On the VPS — one-time setup
adduser urai --disabled-password --gecos ""
usermod -aG sudo urai
mkdir -p /opt/urai
chown urai:urai /opt/urai
```

### 1.2 Install Urai

```bash
su - urai
cd /opt/urai
git clone https://github.com/etside/urai.git .
pip install -e ".[local]"
urai model download qwen3-4b      # ~2.3 GB, one-time
```

### 1.3 Create the secrets file

```bash
# As root (never commit this file)
mkdir -p /opt/urai
cat > /opt/urai/.env <<EOF
URAI_MASTER_KEY=$(openssl rand -hex 32)
URAI_MODEL=qwen3-4b
URAI_PORT=8777
URAI_HOST=127.0.0.1
URAI_RATE_LIMIT=60
EOF
chmod 600 /opt/urai/.env
chown urai:urai /opt/urai/.env
```

### 1.4 Install the systemd service

```bash
# Copy the service file from the repo
cp /opt/urai/deploy/urai-api.service /etc/systemd/system/

systemctl daemon-reload
systemctl enable urai-api
systemctl start urai-api

# Verify it's running
systemctl status urai-api
journalctl -u urai-api -f          # live logs
```

The service file (`deploy/urai-api.service`) already handles:
- Auto-restart on failure (5s delay, max 5 restarts/minute)
- Memory cap: 3 GB
- Security hardening (no new privileges, private tmp, etc.)
- Reads `/opt/urai/.env` automatically

### 1.5 HTTPS with Caddy

```bash
# Install Caddy (Ubuntu)
apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | tee /etc/apt/sources.list.d/caddy-stable.list
apt update && apt install caddy

# Deploy the Caddyfile — edit your domain first
cp /opt/urai/deploy/Caddyfile /etc/caddy/Caddyfile
# Replace urai.example.com and admin@example.com with your values
nano /etc/caddy/Caddyfile

systemctl enable caddy
systemctl start caddy
```

Caddy automatically obtains and renews Let's Encrypt TLS — no certbot needed.
Point your DNS A record at the server IP before starting Caddy.

### 1.6 Verify end-to-end

```bash
curl https://your-domain.com/health
# {"status":"ok","model":"qwen3-4b"}

curl https://your-domain.com/v1/chat/completions \
  -H "Authorization: Bearer $URAI_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"urai","messages":[{"role":"user","content":"hi"}]}'
```

---

## 2. Docker Compose deploy

```bash
git clone https://github.com/etside/urai.git && cd urai
cp .env.example .env
# Edit .env: set URAI_MASTER_KEY (required in production)
nano .env

# HTTP only
docker compose up -d

# With automatic HTTPS (needs DOMAIN set in .env)
docker compose --profile https up -d
```

Logs: `docker compose logs -f`
Stop: `docker compose down`

---

## 3. Updating a running VPS

```bash
# Pull latest code
cd /opt/urai
sudo -u urai git pull --ff-only

# Install any new Python deps
sudo -u urai pip install -e ".[local]" -q

# Restart the service
sudo systemctl restart urai-api

# Confirm it came back up
systemctl status urai-api
curl http://127.0.0.1:8777/health
```

Or use the helper script (checks, pulls, restarts in one line):
```bash
sudo -u urai bash /opt/urai/scripts/repo_sync.sh
sudo systemctl restart urai-api
```

---

## 4. Useful operations

### Rotate the master key
```bash
# 1. Generate a new key
NEW_KEY=$(openssl rand -hex 32)

# 2. Update /opt/urai/.env
sed -i "s/^URAI_MASTER_KEY=.*/URAI_MASTER_KEY=$NEW_KEY/" /opt/urai/.env

# 3. Restart
systemctl restart urai-api

# 4. Save the new key somewhere safe — it won't appear in logs
echo "New master key: $NEW_KEY"
```

### Create an API key for a client app
```bash
# From any machine with the master key:
curl -s http://127.0.0.1:8777/v1/keys/generate \
  -H "Authorization: Bearer $URAI_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"label":"my-app","quota":0}' | python3 -m json.tool
# "token": "urai_xxx..."   ← copy this, shown once
```

### Check logs
```bash
journalctl -u urai-api -n 100          # last 100 lines
journalctl -u urai-api --since "1 hour ago" -f   # follow
```

### Backup data
```bash
# Run manually or add to cron
bash /opt/urai/scripts/urai-backup.sh
# Backs up: data/verified, prompts, reports, registry, key docs
# Keeps 7 daily snapshots; excludes model weights (re-downloadable)
```

Add to cron (daily 03:00 UTC):
```bash
echo "0 3 * * * urai bash /opt/urai/scripts/urai-backup.sh" >> /etc/crontab
```

---

## 5. Serving additional models (llama / embed)

The API server manages llama-server automatically. To pre-start or manage
model servers explicitly:

```bash
# Start chat model on :8080
urai serve start --model qwen3-4b --ctx 8192

# Start embedding server on :8081
urai serve start --model embed-small --embedding

# Stop all
urai serve stop
```

For GPU boxes, add llama-server flags via the service environment:
```bash
# /opt/urai/.env
LLAMA_ARGS=--n-gpu-layers 40 --flash-attn
```

---

## 6. Environment variables reference

| Variable | Default | Description |
|---|---|---|
| `URAI_MASTER_KEY` | *(required)* | Admin key — never commit, never log |
| `URAI_MODEL` | `qwen3-4b` | Default chat model id |
| `URAI_PORT` | `8777` | API listen port |
| `URAI_HOST` | `127.0.0.1` | Bind address (`0.0.0.0` for Docker) |
| `URAI_RATE_LIMIT` | `60` | Requests/minute/IP for free (no-key) traffic |
| `URAI_RATE_WINDOW` | `60` | Rate-limit window in seconds |
| `URAI_CACHE_TTL` | `60` | Response cache TTL in seconds |
| `URAI_REQUEST_TIMEOUT` | `120` | Upstream request timeout in seconds |
| `URAI_LOG_FILE` | *(stdout)* | Path for structured JSON log file |
| `URAI_FREE_LIMIT` | `5` | Free requests per device before block |
| `URAI_CORS_ORIGIN` | `*` | CORS allowed origin for browser clients |
| `URAI_BROWSER_ALLOW_PRIVATE` | `0` | Set to `1` to allow LAN URLs in browser agent |
| `OPENAI_API_KEY` | *(optional)* | Cloud fallback for L4 tasks |
| `ANTHROPIC_API_KEY` | *(optional)* | Claude cloud fallback |
| `AWS_DEFAULT_REGION` | `ap-south-1` | AWS free-tier services (Polly, Transcribe, S3) |

All variables documented in `.env.example` in the repo root.

---

## 7. Firewall

```bash
# Minimum open ports (ufw example)
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP (redirect to HTTPS)
ufw allow 443/tcp   # HTTPS (Caddy)
ufw deny 8777       # Keep :8777 internal — Caddy proxies it
ufw enable
```

---

## Troubleshooting

| Symptom | Check |
|---|---|
| `systemctl status urai-api` shows failed | `journalctl -u urai-api -n 50` |
| 403 on API calls | Missing `Authorization: Bearer <key>` header |
| 401 invalid key | Key mismatch — check `URAI_MASTER_KEY` in `/opt/urai/.env` |
| Port already in use | `ss -tlnp | grep 8777` — another process owns it |
| Model not found | Run `urai model download qwen3-4b` as the `urai` user |
| Caddy no HTTPS | DNS A record not pointing at this IP yet, or port 443 blocked |
| OOM / killed | Increase `MemoryMax` in the service file or use a smaller model |
