# Urai production readiness — 2026-10-15

## Process supervision (Overmind pattern: Procfile + supervisor)
- `Procfile` declares every process: web API, 2 llama teachers, embed server, 2 grind workers.
- `deploy/urai-llama-4b.service` + `deploy/urai-llama-17b.service`: systemd units with
  `Restart=always` for the teachers. Created now, **enabled only after the current
  grind lands** (manual setsid processes hold the ports today; do not double-bind).
- `urai-api` already runs under systemd with `Restart=on-failure`.

## Secrets (fixed)
- `URAI_API_KEY` was inline in the world-readable service file → moved to
  `/etc/urai/env` (root:root 600) via `EnvironmentFile`. Rotate the value next.
- `DO_API_TOKEN` lives only in GitHub repo secrets; probes run via Actions.
- OpenCode/OpenClaude local logs contain pasted token material — rotate + clean.

## TLS (fixed)
- `urai.daddyai.online` resolves to the VPS but nginx served port 80 only.
- certbot TLS added for the urai site; nginx reload only (no grind impact).

## Backups
- `scripts/urai-backup.sh` snapshots data/verified, prompts, reports, registry + key docs.
- Cron daily 03:00 UTC, keeps 7. Models excluded (re-downloadable from HF).

## Eval-gated promotion (overmind-core pattern: winner is a git diff, bench-gated)
- Every landed chunk auto-promotes into few-shot behavior (no restart).
- Weight promotion (adapters) requires the bench gate: knowledge/math/code must not
  regress, else DISCARD. See `docs/GPU_COMBINED_STRATEGY.md`.

## Remaining before GPU spend
1. Let parallel grind bank rows; merge a+b via `scripts/distill/merge_parallel.py`.
2. Fire one-hour H100 (Kaggle T4 free preferred — DO is contract-only).
3. Bench-gate the adapter, merge → GGUF, register, cut over teachers to units.
