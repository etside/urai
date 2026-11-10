# Self-audit prompt 01 — runtime health (run weekly)

Audit Urai runtime health right now. For EACH item, run the check and quote evidence:
1. API: `GET /health` — status ok AND local_llama true?
2. Teachers: `:8080`, `:8081` `/health` — which are up? Any OOM kills in `dmesg`?
3. Site: public URL (`$URAI_PUBLIC_URL`) returns 200 over TLS? Cert expiry?
4. CI: latest `gh run list` all success? Any failing workflow?
5. Disk: `df -h /` under 80%? Backups in `/var/backups/urai/` fresh (<48h)?
6. Tokens: guest flow intact? (`/v1/token/status` for a fresh device)

Output: PASS/FAIL per item with evidence. Fix reds smallest-diff-first,
re-verify, commit. Store durable findings via `/agent/memory remember`.
