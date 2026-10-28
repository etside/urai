# Urai in your editor — VSCode, opencode, and any OpenAI-compatible client

Urai speaks the OpenAI API, so every tool that accepts a “custom
OpenAI-compatible provider” works with three values:

| Field | Value |
|---|---|
| Base URL | `http://127.0.0.1:8777/v1` (or your host) |
| API key | `urai_…` from `urai key create`, or `$URAI_MASTER_KEY` |
| Model | `urai` (`urai-fast`, `urai-ultra`, `jev-local-student` also work) |

Start the server first:

```bash
urai api                       # 127.0.0.1:8777
urai key create my-editor      # prints the token once
```

For a shared or remote instance use `https://your-host/v1` and set
`URAI_API_KEY` on the server. The examples below use a local instance; swap in
your own host and key.

---

## 1. Terminal (coding + agent)

```bash
urai ask "explain this repo layout"
urai agent "write a Python retry helper with tests"
urai chat                      # interactive REPL
urai whoami                    # token state
```

No model download is needed when you point clients at a running server. For
fully offline use, download a model and serve it locally:

```bash
urai model download coder05-fast   # ~469 MB, fastest local coder
urai serve start --model coder05-fast --ctx 8192
```

---

## 2. VSCode — Continue extension

`~/.continue/config.yaml`:

```yaml
models:
  - name: Urai
    provider: openai
    model: urai
    apiBase: http://127.0.0.1:8777/v1
    apiKey: urai_REPLACE_ME
    roles: [chat, edit, apply]
tabAutocompleteModel:
  name: Urai
  provider: openai
  model: urai-fast
  apiBase: http://127.0.0.1:8777/v1
  apiKey: urai_REPLACE_ME
```

## 3. VSCode — Cline / Roo Code

Settings → API Provider → **OpenAI Compatible**:

- Base URL: `http://127.0.0.1:8777/v1`
- API Key: `urai_REPLACE_ME`
- Model: `urai`

For agentic runs you can also call the agent endpoint directly:
`POST /agent` with header `Authorization: Bearer urai_REPLACE_ME` and body
`{"task": "..."}`.

## 4. opencode

`opencode.json` (project root):

```json
{
  "providers": {
    "urai": {
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "http://127.0.0.1:8777/v1",
        "apiKey": "urai_REPLACE_ME"
      },
      "models": {
        "urai": { "name": "Urai (local-first)" }
      }
    }
  }
}
```

MCP tools instead (or as well) — stdio, no network:

```json
{
  "mcp": {
    "urai": {
      "type": "local",
      "command": ["python3", "/path/to/urai/jev/mcp_server.py"]
    }
  }
}
```

Tools exposed: `urai_ask`, `urai_agent`, `urai_see`, `urai_imagine`,
`urai_video`, `urai_embed`, `urai_model_list`, `urai_evaluate`.

## 5. Any OpenAI client (Python / curl / Aider / Cursor)

```python
from openai import OpenAI
c = OpenAI(base_url="http://127.0.0.1:8777/v1",
           api_key="urai_REPLACE_ME")
r = c.chat.completions.create(model="urai",
    messages=[{"role": "user", "content": "Write a retry helper"}])
print(r.choices[0].message.content)
```

```bash
curl -s http://127.0.0.1:8777/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer urai_REPLACE_ME' \
  -H 'X-Device-Id: my-laptop' \
  -d '{"model":"urai","messages":[{"role":"user","content":"hi"}],"max_tokens":64}'
```

Aider: `aider --openai-api-base http://127.0.0.1:8777/v1
--openai-api-key urai_REPLACE_ME --model openai/urai`

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `Free Token Expired / 0 available Token` (403) | Supply a key: `Authorization: Bearer urai_…`, `urai key create`, or `POST /auth/unlock {"master_key":"…"}` |
| `invalid API key` (401) | Check the token or set `URAI_MASTER_KEY` on the server |
| Connection refused | Start the server: `urai api` (and check the port) |
| CORS error in a browser app | Set `URAI_CORS_ORIGIN=https://your-app.example` |
| Model seems generic | Routing may have chosen a smaller student model; pass `"model": "urai-ultra"` and inspect `urai.models` in the response |
