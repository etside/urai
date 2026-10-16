---
name: self-audit
description: Urai audits itself — find issues, fix them, verify, upgrade. Use for self-audit prompts, health reviews, and continuous self-improvement runs.
---

# Self-audit skill

You are auditing Urai itself. Rules:

1. **Evidence first.** Never claim an issue without a command, log line, file
   path, or endpoint response proving it. Quote the evidence.
2. **Scope in order:** health → correctness → security → performance →
   docs/drift. Fix in that order; stop at the first red item.
3. **Fix protocol:** smallest diff that resolves the evidence. Compile check
   (`py_compile`, `bash -n`, `node --check`), live-verify the exact failing
   call, commit with evidence in the message.
4. **Never:** invent APIs, fake benchmark numbers, touch secrets/keys,
   restart teachers mid-grind, or claim parity with frontier models.
5. **Upgrade rule:** new capability = code + live verification + docs +
   report. If any link is missing, it is not done.
6. Record durable findings as memory facts (`/agent/memory remember`) and
   anything over 5 minutes as focus (`/agent/focus set`).

## Audit loop (run top to bottom)
- `GET /health`, `/v1/models`, `/v1/integrations` — all green?
- `GET /v1/benchmarks` + `eval/reports/bench-harness-*.json` — regressed?
- `git status --short` — unexpected drift? `gh run list` — CI green?
- OOM/dead teachers? `ps`, `dmesg | grep oom-kill`, port health.
- Disk: `df -h` (models + backups). Cert: expiry date. Cron: backup ran?
- Prompt pack: `data/prompts/self_audit/*.md` — run each, file reports to
  `eval/reports/selfaudit-<area>-<date>.json`.
