# Urai API Reference

Base URL: `http://127.0.0.1:8777` (local default). Start it with:

```bash
urai api                 # 127.0.0.1:8777
urai api --host 0.0.0.0 --port 8777   # LAN / VPS (set URAI_API_KEY!)
```

The API is OpenAI-compatible where it matters (`/v1/chat/completions`,
`/v1/completions`, `/v1/embeddings`, `/v1/models`), so existing SDKs work by
changing `base_url` only.

## Authentication

| Caller | Header | Notes |
|---|---|---|
| Master | `Authorization: Bearer $URAI_MASTER_KEY` | Full access, unlimited. Never ship this to clients. |
| API key | `Authorization: Bearer urai_…` | Created with `urai key create` or `POST /v1/keys/generate`. Optional quota. |
| Guest | none, optionally `X-Device-Id: <id>` | Limited free chats per device (`URAI_FREE_LIMIT`, default 5). |

`URAI_MASTER_KEY` **must** be set in the environment. If it is missing the
server starts with an insecure development fallback and prints a warning.

Guarded paths (`URAI_API_KEY` set ⇒ a valid key is required):

```
/v1/*  /chat  /generate  /agent  /tools  /evaluate  /see  /imagine
```

Master-only routes are marked **master** below. Key management and vibe coding
write files or mint credentials, so they are always master-only.

### Rate limiting

Per-IP sliding window, `URAI_RATE_LIMIT` requests per `URAI_RATE_WINDOW`
seconds (default `60 / 60`; `0` disables). Exceeding it returns:

```json
{ "error": "rate_limit_exceeded", "retry_after": 60 }
```

with HTTP `429`. Check your own budget with `GET /v1/rate-limit-status`:

```json
{ "limit": 60, "window_s": 60, "your_count": 3,
  "your_remaining": 57, "your_ip": "127.0.0.1" }
```

## Health & discovery

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | `{status, local_llama, voice, watchdog, identity, time}` |
| `GET` | `/v1/models` | Registry models with availability + active flag |
| `GET` | `/v1/info` | Strengths, endpoints, measured throughput |
| `GET` | `/metrics` | Counters, routing scores, cache size, budgets |
| `GET` | `/v1/tools` | Built-in tool schemas |
| `GET` | `/v1/integrations` | Configured MCP servers / plugins |
| `GET` | `/v1/docs` | Doc index (`/docs/<file>.md` serves the markdown) |
| `GET` | `/v1/notices` | Latest `data/notices.json` entries |
| `GET` | `/v1/benchmarks` | Latest benchmark report |
| `GET` | `/v1/repo/status` | Git revision / dirty state |
| `GET` | `/v1/cloud/usage?days=7` | Cloud spend report |
| `GET` | `/v1/token/status?device_id=` | Guest quota: `remaining`, `blocked_until`, `approved` |

## Chat (OpenAI-compatible)

```http
POST /v1/chat/completions
Content-Type: application/json

{
  "model": "urai",
  "messages": [{"role": "user", "content": "hello"}],
  "max_tokens": 512,
  "temperature": 0.7,
  "stream": true
}
```

- Streaming uses standard SSE `data:` frames ending with `data: [DONE]`.
- Vision: add an image content part (`{"type":"image_url", ...}`) to a message.
- Aliases: `POST /chat`, `POST /generate`, `POST /v1/completions`.
- `POST /v1/embeddings {"input": "text"}` → vectors.
- `POST /v1/reason` → reasoning-oriented completion.

Model IDs: `urai-fast`, `urai`, `urai-ultra`, `urai-cyber` (router aliases),
plus any model registered in `data/registry.json`.

## Vibe coding **master**

```http
POST /vibe
{ "task": "add a /healthz route and a test",
  "workspace": "/path/to/project",
  "plan_only": false,
  "max_steps": 20 }
```

Runs the propose → write → run loop inside `workspace` (defaults to the
server's cwd). Returns `{steps, files_written, summary}`. `plan_only: true`
returns proposed edits without touching disk. Bash calls are safety-checked and
paths are confined to the workspace.

## Agent harness

| Method | Path | Body / query |
|---|---|---|
| `POST` | `/agent` | `{task, files, plan, session_id, remember}` |
| `POST` | `/agent/swarm` | `{tasks: [...], workers}` |
| `POST` | `/agent/sessions` | `{action: list\|new\|history\|delete, session_id}` |
| `POST` | `/agent/jobs` | `{action: list\|add\|toggle\|delete\|run, task, every_s, id}` |
| `POST` | `/agent/memory` | `{action: list\|add, text, tag}` |
| `POST` | `/agent/routing` | `{action: get\|set, model, task_type}` |
| `POST` | `/agent/focus` | `{action: get\|set, text}` |
| `POST` | `/agent/apply` | `{action: apply\|reject, id}` |
| `POST` | `/v1/plan` | `{task, budget_tokens}` → plan + execution |

## Wiki (knowledge memory)

Tenant-free, file-backed markdown wiki with BM25 search and `[[wikilinks]]`.

| Method | Path | Body / query |
|---|---|---|
| `GET`/`POST` | `/v1/wiki/search` | `query`/`q`, `top` (default 5) |
| `GET` | `/v1/wiki/list` | `category` (optional) |
| `GET`/`POST` | `/v1/wiki/get` | `title` |
| `POST` | `/v1/wiki/add` | `{title, content, category}` (`concepts` default) |

`GET` mirrors exist so the Studio can read without a request body.

## Named agents

Persistent agents with private notes, history and an optional schedule.

| Method | Path | Body |
|---|---|---|
| `GET`/`POST` | `/v1/agents/list` | — |
| `POST` | `/v1/agents/create` | `{name, instructions, tools: [], schedule}` |
| `POST` | `/v1/agents/run` | `{agent_id, message, session_id}` |
| `DELETE` | `/v1/agents/<id>` | — |

## Routines

Recurring tasks executed by the server scheduler.

| Method | Path | Body |
|---|---|---|
| `GET`/`POST` | `/v1/routines/list` | — |
| `POST` | `/v1/routines/create` | `{name, prompt, schedule, tools}` |
| `POST` | `/v1/routines/run` | `{id}` |
| `DELETE` | `/v1/routines/<id>` | — |

Schedule strings: `manual`, `daily@08:00`, `every:3600` (seconds).

## API keys **master**

| Method | Path | Body |
|---|---|---|
| `GET` | `/v1/keys` | — → `{tokens: [...]}` (tokens masked) |
| `POST` | `/v1/keys/generate` | `{label, quota}` — `quota: 0` = unlimited |
| `DELETE` | `/v1/keys/<id-or-prefix>` | — |

`POST /v1/keys/generate` returns the **full token once**:

```json
{ "ok": true, "id": "urai_…", "token": "urai_…", "label": "laptop",
  "quota": 0, "used": 0, "created": 1793151921, "active": true }
```

Store it immediately; `GET /v1/keys` only returns a masked form.

`DELETE /v1/keys/<id-or-prefix>` needs at least 8 characters of the id
(shorter values, including an empty id, are rejected with `400`) and returns
`404` for an unknown id.

## Media

| Method | Path | Body |
|---|---|---|
| `POST` | `/imagine`, `/v1/images/generations` | `{prompt, ...}` |
| `POST` | `/video`, `/v1/videos/generations` | `{prompt, ...}` |
| `GET` | `/v1/videos/<job>` | job status |
| `POST` | `/see` | image + question (vision) |
| `POST` | `/v1/audio/speech` | `{input, voice}` |
| `POST` | `/v1/audio/transcriptions` | audio → text |
| `POST` | `/v1/chart` | `{data, kind, title, xlabel, ylabel}` |
| `POST` | `/v1/appshot` | `{region, question}` screen capture + vision |

## Browser (approval-safe)

| Method | Path | Body |
|---|---|---|
| `POST` | `/browser/run` | `{goal, steps}` |
| `POST` | `/browser/approve` | `{id, approve}` |
| `GET` | `/browser/status/<id>` | run status |

## Web shell & PWA

| Method | Path | Content |
|---|---|---|
| `GET` | `/` , `/app`, `/app.html` | Studio (`app.html`) |
| `GET` | `/welcome`, `/index.html` | Landing page |
| `GET` | `/superadmin` | Hidden admin view (same shell) |
| `GET` | `/manifest.webmanifest` | PWA manifest |
| `GET` | `/sw.js` | Service worker (shell-only cache) |
| `GET` | `/icon-192.png`, `/icon-512.png`, `/icon.svg` | Icons |
| `GET` | `/favicon.ico`, `/favicon.svg`, `/apple-touch-icon.png` | Favicons |

The service worker never caches `/v1/*`, `/health`, `/vibe`, `/agent` or
`/superadmin` — answers, keys and agent runs are always live.

## Admin (**master**)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/auth/unlock` | Unlock a device with an access code |
| `POST` | `/auth/request` | Guest requests approval |
| `GET`/`POST` | `/superadmin/tokens`, `/superadmin/approve`, `/superadmin/unblock` | Guest token administration |
| `GET` | `/superadmin/messages` | Live request log + state |
| `POST` | `/v1/repo/sync` | Pull + reload |
| `POST` | `/tools/reload` | Reload toolpacks/plugins |

## Errors

Errors are JSON with an `error` string and a meaningful status code:

```json
{ "error": "master key required" }        // 401
{ "error": "task required" }              // 400
{ "error": "unknown token" }              // 404 for DELETE of an unknown id
{ "error": "token id required" }          // 400 for DELETE with an empty id
{ "error": "rate_limit_exceeded", "retry_after": 60 }  // 429
{ "error": "not found" }                  // 404
```

## Examples

```bash
# health
curl -s localhost:8777/health | jq

# chat
curl -s localhost:8777/v1/chat/completions \
  -H "Authorization: Bearer $URAI_MASTER_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"urai","messages":[{"role":"user","content":"hi"}]}' | jq

# create an unlimited key
curl -s localhost:8777/v1/keys/generate \
  -H "Authorization: Bearer $URAI_MASTER_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"label":"laptop","quota":0}' | jq

# add + search a wiki page
curl -s localhost:8777/v1/wiki/add \
  -H "Authorization: Bearer $URAI_MASTER_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Deploy","content":"Caddy + systemd","category":"projects"}'
curl -s "localhost:8777/v1/wiki/search?query=deploy" \
  -H "Authorization: Bearer $URAI_MASTER_KEY" | jq
```
