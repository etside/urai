# Urai Harness Guide

Urai is an agent harness (OpenCode/OpenClaw-class), not just a model:
a verify-first agent loop, parallel swarm, tools, browser, skills, memory,
scheduler, sessions and plan-mode file editing — local-first, zero cost.

## Agent (`/agent`, `urai agent`)
PLAN → TOOL → OBSERVE → REASON → VERIFY → CORRECT. Budgets: 2 fixes,
6 tool calls. Every step lands in `trace`. Text answers verify clean;
code must compile (exec with `--exec` in distill).
- `plan: true` → file writes become proposals, nothing applied.
- `session_id` → turns persist server-side; history re-injected next call.
- `POST /agent/apply {proposals}` (master key) applies write/edit specs.

## Tools (`/tools`)
`read_file` (jailed) · `write_file` · `edit_file` (exact-match) ·
`run` (allowlisted binaries, read-only git) · `web_search` · `web_fetch` ·
`browse` (approval-safe) · `analyze` (evidence-first, redacted) ·
`mcp_servers` · `mcp` (external MCP servers via `mcp_clients.json`).

## Swarm (`/agent/swarm`, `urai swarm`)
Up to 8 tasks, 3 workers, isolated failures. Each task is a full agent run.

## Conductor (mode conductor, Fugu-style)
Thinker decomposes into subtasks, Workers execute shards in parallel, Verifier merges. One pool, one endpoint, no API keys. Roles are prompt-specialized runs of the local student (teacher-backed when TEACHER env is set).

## Tiers (one API, four behaviors, no keys)
urai-fast (quick, short), urai (balanced default), urai-ultra (consistency sampling plus verify), urai-cyber (security skills plus verify). Pass tier to /agent. Outcomes per level and backend accumulate in data/routing_scores.json (learning loop, stage 1: measure); pool opt-in and opt-out via the routing endpoint.

## Sessions (`/agent/sessions`: list/history/clear)
Server-side JSONL memory per session id. Web UI drawer opens/imports them;
Telegram keeps one session per chat (`/new` resets).

## Jobs (`/agent/jobs`: list/add/toggle/delete/run/runs)
Cron-style background agents (min 60s interval). Runs logged with status +
summary; `cron` plugin hook fires per run. Scheduler starts with the API.

## Memory + Focus (`/agent/memory`, `/agent/focus`)
- Memory: facts/preferences/decisions, keyword + recency + hits recall,
  auto-injected top-3 into every run. Dedup on write.
- Focus: stack of what is being worked on, top item injected every run.
  Set on real work, clear when done.

## Skills (`skills/*/SKILL.md`, `urai skill`)
Capability packs matched by keyword stems (10 built in: threat-analysis,
motion, mcp-builder, …). Agent loads top matches into context.

## Browser (`/browser/run|status|approve`, `urai browse`)
Human-like automation; auth fields pause for approval instead of failing.

## Channels
- Web UI (`/app`): chat, streaming, plan mode, harness drawer, superadmin.
- Telegram plugin: duplex polling, per-chat sessions, allowlist, splitting.
- CLI: `urai chat|ask|agent --plan --session|swarm|browse|video|plugin|mcp`.

## Eval loop (`/evaluate`, `jev/bench.py`, `URAI_BENCH`)
Every capability is measured; weight promotion requires no-regression.
Traces → `data/verified/*.jsonl` → LoRA (see `docs/INDEPENDENCE.md`).
