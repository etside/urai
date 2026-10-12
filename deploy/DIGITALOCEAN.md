# Urai on DigitalOcean (live)

- **Droplet:** `urai-1` (ID 608481907) — 4 vCPU / 8 GB / 160 GB, `blr1`
  (Bangalore, closest to GMT+6), Ubuntu 24.04, **$48/mo**
- **IP:** `168.144.180.56` — API+web: `http://168.144.180.56:8777`
  (web playground at `/`, OpenAI-compatible `/v1/*`)
- **Project:** `urai` (Development, ML/AI purpose —
  ID 45246ec6-c8cf-46c1-81ba-d8964f70496a)
- **Firewall:** `urai-fw` — 22, 80, 443, 8777 open
- **SSH:** `ssh -i ~/.ssh/urai_do root@168.144.180.56`
  (key name `urai-deploy` in the DO account)
- **On-box layout:** `/opt/urai` (code, user `urai`), systemd
  `urai-api.service` (key via `Environment=URAI_API_KEY`), llama-server
  `:8080` (chat/vision) + `:8081` (embeddings) via `urai serve start`.
- **Models on disk:** coder05-fast (active), coder15, qwen25vl-3b + mmproj,
  sd-turbo, embed-small, qwen05-fast. Runners: prebuilt llama.cpp b11559 +
  sd-cli (no compiler on the image; `libgomp1` + `unzip` installed).

## Redeploy / destroy

```bash
# destroy everything (stops billing immediately):
curl -X DELETE -H "Authorization: Bearer $DO_TOKEN" \
  https://api.digitalocean.com/v2/droplets/608481907
# firewall cleanup:
curl -X DELETE -H "Authorization: Bearer $DO_TOKEN" \
  https://api.digitalocean.com/v2/firewalls/95eda2b5-756a-4df7-85eb-92abe57bd808
```

## Notes

- Never commit `URAI_API_KEY` or the DO API token — both live only in
  server env / the operator's shell.
- HTTPS: point DNS at the IP and apply `deploy/Caddyfile` on the droplet.
- Snapshot the droplet before risky upgrades (DO snapshots, ~$0.05/GB-mo).
