# Urai OpenAI-compatible API

Base URL: `https://urai.daddyai.online` (local: `http://127.0.0.1:8777`).
Drop-in for OpenAI clients: same `/v1/chat/completions`, `/v1/completions`,
`/v1/embeddings`, `/v1/models` shapes. Auth via `Authorization: Bearer <key>`
(master `856777` or an issued `urai_…` token) plus `X-Device-Id` header.

## Python (openai package)

```python
from openai import OpenAI
c = OpenAI(base_url="https://urai.daddyai.online/v1", api_key="urai_YOUR_TOKEN",
           default_headers={"X-Device-Id": "my-app"})
r = c.chat.completions.create(model="urai",
    messages=[{"role": "user", "content": "Summarize distillation in one line."}])
print(r.choices[0].message.content)
```

## curl

```bash
curl https://urai.daddyai.online/v1/chat/completions \
  -H "Authorization: Bearer urai_YOUR_TOKEN" -H "X-Device-Id: my-app" \
  -H Content-Type:application/json -d '{
  "model": "urai-ultra",
  "messages": [{"role": "user", "content": "Review this for security issues."}],
  "temperature": 0.2, "max_tokens": 512}'
```

## Models (`GET /v1/models`)
`urai` (balanced) · `urai-fast` (quick) · `urai-ultra` (verified depth) ·
`urai-cyber` (security) · `laya` (owned student, landing soon).

## Agents (`POST /agent`)
`{task, files, budget_tokens, consistency, plan, session_id, remember,
tier}` → `{answer, proposals, session_id, trace, level, backend}`.
Swarm/conductor: `POST /agent/swarm {tasks[], max_workers, mode}`.

## Tokens
Guests: 5 free/device. Master `856777`: unlimited. Apps: superadmin issues
`urai_…` tokens with quotas; usage/last-used tracked, revocable. Pass as
Bearer or `api_token` field/query. Full route list: `docs/API.md`.
