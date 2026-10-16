# Urai — Deployment Plan

Companion to `docs/PRODUCTION_SPEC.md`. Everything here is executed **remotely**
(CI or on the server) — never as a local build/install.

---

## 0. Topology

| Plane | Where | Role |
|---|---|---|
| Edge | Cloudflare (proxy + Tunnel + Access + WAF + PQ TLS) | DDoS/WAF/bot, Zero Trust, hides origin |
| Control | VPS `urai-1` (currently DO 4 vCPU/8 GB, `blr1`) | API, auth, router, harness, memory, scheduler, media relay |
| Inference | same VPS CPU (default) → optional GPU node (CUDA/ROCm) | MoE backbone |
| Media | Seedream 4.0 / Wan 3.0 (managed APIs) | image/video, persisted |
| Train | Modal (default) / DO GPU (if ever) / Kaggle | Laya unified student |

Target domain: `urai.daddyai.online` (prod), `api.urai.daddyai.online`
(optional split), `admin.urai.daddyai.online` (Access-protected).

---

## 1. Prerequisites / accounts

- Cloudflare zone for `daddyai.online`; **API token** (Zone:DNS Edit,
  Zone:Zone Settings Edit, Account:Cloudflare Tunnel, Access, R2 optional).
- BytePlus ModelArk (Seedream) **`ARK_API_KEY`** + `ARK_BASE`.
- Alibaba Model Studio (Wan) **`DASHSCOPE_API_KEY`** + `WorkspaceId`/region.
- DigitalOcean token (VPS lifecycle); Modal + Kaggle tokens (training).
- Repo secrets already present (per operator): `DO_API_TOKEN`,
  `MODAL_TOKEN_ID/SECRET`, `KAGGLE_USERNAME/KEY`, `URAI_MASTER_KEY`.

---

## 2. VPS provisioning (server-only)

Ubuntu 24.04, non-root user `urai`, key-only SSH.

```bash
# on the box
adduser --disabled-password --gecos "" urai
install -d -m700 -o urai -g urai /etc/urai
printf 'URAI_API_KEY=...\nURAI_MASTER_KEY=...\nARK_API_KEY=...\nARK_BASE=https://ark.ap-southeast.bytepluses.com/api/v3\nDASHSCOPE_API_KEY=...\n' \
  | install -m600 -o urai -g urai /dev/stdin /etc/urai/env
# firewall: close 8777; allow only tunnel (no public 80/443 needed once tunnelled)
ufw default deny incoming; ufw allow 22/tcp; ufw enable

# deps (no compiler assumed): runtime libs only
apt-get update && apt-get install -y libgomp1 unzip ca-certificates
```

**Sizing:** CPU-only MoE needs **≥16 GB RAM (24–32 GB recommended)**. The
current 8 GB droplet cannot host Qwen3-30B-A3B → either **resize to 8 vCPU /
32 GB** (~$168/mo) or attach a GPU node (see §4). Until then the box runs
**lite mode** (dense Qwen3-4B) — flagged `degraded` in `/health`.

---

## 3. Code + service install

```bash
# deploy from the signed branch/tag, not by hand
git -C /opt/urai fetch --all --tags && git -C /opt/urai checkout <tag>
install -m644 /opt/urai/deploy/urai-api.service /etc/systemd/system/
systemctl daemon-reload && systemctl restart urai-api
```

systemd units (installed on box):
- `urai-api.service` → `python3 -m jev.server` on `127.0.0.1:8777`
  (`EnvironmentFile=/etc/urai/env`, `Restart=always`, `WorkingDirectory=/opt/urai`).
- `urai-llama.service` → `llama-server` MoE on `:8080` (CPU flags per §5).
- `urai-embed.service` → `llama-server --embedding` on `:8081`.

---

## 4. GPU node (optional accelerator)

Priority order:
1. **Attached GPU** on any cloud (DO GPU SKUs are contract-gated — `gpu_sizes_via_api: 0`
   on this account, so **DO self-service GPU is out**; use a provider that
   provisions, e.g. Lambda/RunPod/on-prem, or request a DO contract SKU).
2. **ROCm box** (AMD gfx) — same GGUF, `-DGGML_HIP=ON`.
3. If no GPU is procured, the platform stays on VPS CPU (spec-compliant, slower).

Provision/attach procedure:
```bash
# build llama.cpp for the vendor (in CI or on the GPU node — never locally)
cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=<cap> && cmake --build build -j
# or AMD:
cmake -B build -DGGML_HIP=ON -DAMDGPU_TARGETS=<gfx1100> && cmake --build build -j
# run the SAME quant the VPS uses, offloading experts:
./build/bin/llama-server -m Qwen3-30B-A3B-Q4_K_M.gguf -ngl 99 --n-cpu-moe <N> -fa -c 32768
```
Register the node in `config/platform.json` (`accelerator.hosts`) so the router
can target it; health-gate via `/health` + a canary prompt.

Training node (Modal): `gh workflow run urai-train.yml -f tag=unified` after
merge (spends ~$1) — or Actions → **Urai Train** → tag `unified`.

---

## 5. Inference launcher policy (`config/platform.json`)

```json
{
  "public_models": ["urai", "cyberurai"],
  "backbone": { "repo": "Qwen/Qwen3-30B-A3B-GGUF", "ladder": ["q8","q5","q4","q3","q2"] },
  "accelerator": { "policy": "auto", "min_ram_cpu_gb": 16, "ctx": 32768, "kv": "q8_0" },
  "media": {
    "image": { "ark_base": "https://ark.ap-southeast.bytepluses.com/api/v3",
               "model": "seedream-4-0-250828" },
    "video": { "model": "wan3.0-video", "fast_model": "wan3.0-video-prime",
               "region": "ap-southeast-1", "fast": false }
  }
}
```

Quant selection is automatic from detected free VRAM/RAM (see spec §3). Flags:
- CPU: `--n-cpu-moe N -ctk q8_0 -ctv q8_0 -c 16384`.
- GPU: `-ngl 99 --n-cpu-moe N -fa -c 32768` (raise ctx to 131072 + `--rope-scaling yarn` for long-context mode).

---

## 6. Cloudflare edge

### 6.1 DNS + proxy
- A/CNAME `urai` → Tunnel hostname (not the origin IP).
- Orange-cloud proxy on; SSL mode **Full (strict)**; Always Use HTTPS; min TLS **1.3**.

### 6.2 Tunnel (origin has no public IP)
```yaml
# /etc/cloudflared/config.yml
tunnel: urai-prod
credentials-file: /etc/cloudflared/urai-prod.json
ingress:
  - hostname: urai.daddyai.online
    service: http://127.0.0.1:8777
  - hostname: admin.urai.daddyai.online
    service: http://127.0.0.1:8777
  - service: http_status:404
```
```bash
cloudflared tunnel login && cloudflared tunnel create urai-prod
cloudflared tunnel route dns urai-prod urai.daddyai.online
systemctl enable --now cloudflared
# then remove public 80/443 from ufw — origin is tunnel-only
```

### 6.3 WAF + rate limiting
- Managed Ruleset + OWASP Core; block known-bad; custom rule: challenge
  `cf.threat_score > 10`.
- Rate limits (per IP, then per API key at origin):
  | Path | Limit |
  |---|---|
  | `/v1/chat*`, `/agent*` | 60/min, burst 20 |
  | `/v1/images*`, `/imagine*` | 10/min |
  | `/v1/videos*`, `/video*` | 3/min |
  | `/superadmin*`, `/status` | 20/min + Access required |
- Bot Management: allow verified bots (search), managed-challenge suspicious.

### 6.4 Zero Trust
- **Access applications**: `admin.urai.daddyai.online`, `urai.daddyai.online/superadmin*`,
  `/v1/repo/*`. Policies: service tokens for CI/CLI; SSO + device posture
  (WARP) for humans; mTLS for admin machines.
- **WARP** enrolled for operator devices; audit log streaming to R2 (optional).

### 6.5 Post-quantum
- TLS 1.3 with **hybrid PQ key agreement** (X25519MLKEM768) — verify via
  `openssl s_client -connect urai.daddyai.online:443` shows the hybrid group.
- Use PQ-capable origin certs via Tunnel; keep TLS1.3-only, disable legacy curves.

---

## 7. Secrets & rotation

- Server: `/etc/urai/env` (0600, user `urai`); never in git/logs.
- CI: GitHub Actions secrets (`DO_*`, `MODAL_*`, `KAGGLE_*`, `ARK_*`,
  `DASHSCOPE_*`, keystore). `.gitignore` blocks `**/env`, `*.key`, `*.jks`.
- Rotation runbook: issue new key → add to env/CI → reload service → revoke old
  (`/admin/keys`); rotate API tokens quarterly; rotate DO/Modal on team change.

---

## 8. CI/CD (no local builds)

Workflows (existing): `urai-ci.yml`, `ci.yml` (v2), `android.yml`,
`urai-train.yml`, `urai-gpu-run.yml`, `urai-gpu-check.yml`, `distill-vps.yml`.
Add a **deploy** workflow:
- Trigger: tag `v*` or manual.
- Steps (on GitHub runners): lint + tests → build llama.cpp (matrix: cpu/cuda/hip)
  → package → `rsync`/SSH to VPS → `systemctl restart` → smoke `/health`,
  `/v1/models` (assert exactly 2 ids), `/v1/capabilities`.
- Rollback: keep last N releases under `/opt/urai-releases`; symlink swap.

Android release: sign with upload keystore from secrets, attach APK to a GitHub
Release, publish artifact.

---

## 9. Data, media persistence, backups

- **Seedream/Wan outputs** expire (~24h) → relay downloads to object storage
  (DO Spaces / R2) and serves stable `/files/<id>` URLs. Retention policy:
  user media 30d default (configurable), logs 14d.
- **Backups:** nightly VPS snapshot + DB dump (`sqlite`/state) to Spaces;
  verified restore monthly. Registry + verified dataset versioned in git.

---

## 10. Observability

- `/health` (incl. `local_llama`, `accelerator`, `degraded`), `/v1/info`.
- Metrics: requests, tokens, TTFT, tok/s, GPU util/VRAM, queue depth, 4xx/5xx,
  media API latency/cost. Prometheus + Grafana (or DO monitoring) + uptime probe.
- Alerts: API down, 5xx >0.5%, TTFT SLO breach, disk >85%, VRAM OOM, media
  relay failures, cert/Tunnel health.

---

## 11. Scaling & HA

- Vertical first (RAM for CPU MoE; VRAM on GPU).
- Horizontal: stateless `urai-api` behind Caddy/Tunnel; sessions/memory in DB.
- Multiple GPU nodes → least-loaded routing; vLLM for batching at scale.
- Read-only status/landing served from edge cache.

---

## 12. Cost model (indicative)

| Item | Monthly |
|---|---|
| VPS 8 vCPU/32 GB (MoE-capable) | ~$168 |
| VPS 4 vCPU/8 GB (lite mode, current) | $48 |
| GPU node (on-demand, e.g. T4/A10 per hour) | variable |
| Cloudflare (Pro/Business + Access) | $0–25 + Access seats |
| Seedream 4.0 | ~$0.03 / image |
| Wan 3.0 | per-second, per resolution (Prime = faster, higher rate) |
| Modal training | ~$1 / run (T4) |

---

## 13. Rollout phases + rollback

| Phase | Deliverable | Exit check |
|---|---|---|
| P0 | Two-brand surface, capabilities, error/mobile/APK fixes | `/v1/models`==2, CI green |
| P1 | MoE on VPS + accel detect + local media fallback | CPU run + CUDA/ROCm CI logs |
| P2 | Seedream + Wan relays + persistence | E2E image/video, Prime toggle |
| P3 | Cloudflare Tunnel/Access/WAF/PQC + signed APK | origin tunnel-only, PQ handshake |
| P4 | GPU node + vLLM + Laya promotion | SLOs met, bench no-regression |
| P5 | CyberUrai retrieval/adapter + SLO burn-in | cyber evals pass |

Rollback: symlink swap to previous release + `systemctl restart`; edge config
rolled back via Terraform/API; DB from last snapshot.

---

## 14. Runbooks (quick)

- **API 5xx spike:** check `journalctl -u urai-api`, llama-server health,
  VRAM/RAM, then edge rate limits.
- **OOM on llama:** lower quant tier, reduce `-c`, increase `--n-cpu-moe`.
- **Media relay failing:** verify `ARK_API_KEY`/`DASHSCOPE_API_KEY`, region,
  fallback to local SD-Turbo; confirm persistence target reachable.
- **Tunnel down:** `systemctl status cloudflared`, re-auth tunnel, verify DNS.
- **Leaked key:** rotate (§7), revoke, rotate Cloudflare Access tokens.
