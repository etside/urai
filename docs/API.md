# Urai API Reference

Base: `https://urai.daddyai.online` (local: `http://127.0.0.1:8777`).
Auth: `Authorization: Bearer 856777` (master, unlimited, cost 0) or guest
(5 free/chat per device, then `Free Token Expired` until approved).
Header `X-Device-Id: <id>` tracks guest usage.

## Health & discovery
-  → key-need evidence per capability (integrated-as-Urai proof)
- `GET /health` → `{status, local_llama, identity, time}`
- `GET /v1/models` → registry models + active
- `GET /v1/info` → strengths, endpoints, measured throughput
- `GET /v1/docs` → doc index · `GET /docs/<file>` → markdown
- `GET /v1/notices` → `data/notices.json`
- `GET /v1/benchmarks` → latest bench report
- `GET /v1/token/status?device_id=` → remaining/blocked_until

## Chat (OpenAI-compatible)
- `POST /v1/chat/completions {model, messages, max_tokens, temperature, stream, device_id}`
- `POST /v1/completions` · `POST /chat` · `POST /generate`
- Vision: include image content parts → describes/analyses.
- `POST /v1/embeddings {input}` → vectors.

## Agent harness
- `POST /agent {task, files, budget_tokens, consistency, plan, session_id, remember, tier: urai|urai-fast|urai-ultra|urai-cyber}`
  → `{ok, answer, proposals, session_id, trace, level, backend, usage}`
- `POST /agent/apply {proposals}` *(master)* → applies write/edit specs.
- `POST /agent/swarm {tasks[], max_workers, mode: parallel|conductor}`
- `POST /agent/routing {action: scores|pool|pool_set}` → parallel runs + stats.
- `POST /agent/sessions {action: list|history|clear, session_id}`
- `POST /agent/jobs {action: list|add|toggle|delete|run|runs, id?, task?, every_s?}`
- `POST /agent/memory {action: remember|recall|forget|list, text?, kind?, query?, top?, id?}`
- `POST /agent/focus {action: set|current|clear, label?, detail?}`
- `POST /evaluate {task, expected_contains[]}` → score + agent result.
- `POST /tools {tool, args}` → runs any registered tool.

## Browser (approval-safe)
- `POST /browser/run {goal, steps[]}` → `{ok|needs_approval, run_id, fields?}`
- `GET /browser/status/<run_id>` · `POST /browser/approve {run_id, secrets}`

## Media
- `POST /imagine|/v1/images/generations {prompt, out?, steps?, w?, h?, seed?}`
- `POST /video|/v1/videos/generations {prompt, duration?, w?, h?, fps?}`
- `POST /see {image, question?}`

## Auth & admin *(master unless noted)*
- `POST /auth/unlock {master_key, device_id}` · `POST /auth/request {device_id, whatsapp, gmail}`
- `GET /superadmin/messages?key=` · `POST /superadmin/approve|unblock {key, ...}`
- `GET /v1/repo/status` · `POST /v1/repo/sync` → git pull + status

## Errors
`{error}` + HTTP code: 400 bad input · 403 `free_token_expired`/`forbidden`
· 502 backend failure. Usage is always `{total_tokens: 0, cost: 0}` on
local backends (real token counts pass through where measured).
