# Urai in your editor — VSCode, opencode, and any OpenAI-compatible client

Urai speaks the OpenAI API on a fixed base URL, so every tool that accepts a
“custom OpenAI-compatible provider” works with three values:

| Field | Value |
|---|---|
| Base URL | `https://urai.daddyai.online/v1` |
| API key | `856777` (master key — unlimited, cost 0) |
| Model | `jev-local-student` (routed: local Qwen3-4B first, cloud fallback) |

Token policy: guests get **5 free responses per device/IP**, then
`Free Token Expired / 0 available Token` until the master key is supplied.
With `856777` every call reports `usage.total_tokens = 0, cost = 0`.

Health check: `GET https://urai.daddyai.online/health`
Token status: `GET https://urai.daddyai.online/v1/token/status?device_id=YOUR_ID`

---

## 1. Minimal terminal install (coding + agent)

```bash
curl -fsSL https://raw.githubusercontent.com/etside/urai/main/install.sh | bash
urai login 856777
urai ask --remote "explain this repo layout"
urai agent --remote "write a Python retry helper with tests"
urai chat --remote          # interactive REPL against the VPS
urai whoami                 # remaining free tokens / approved / blocked
```

No model download is needed for `--remote` (VPS does the heavy work —
device-light rule). For fully offline coding, add a local model:

```bash
URAI_MODEL=coder05-fast bash install.sh   # ~469 MB, fastest local coder
urai serve start --model coder05-fast
urai ask "write a fibonacci function"      # local, no VPS
```

Env overrides (no config file needed):
`URAI_REMOTE_URL`, `URAI_MASTER_KEY`, `URAI_DEVICE_ID`, `URAI_REMOTE=1`.

---

## 2. VSCode — Continue extension

`~/.continue/config.yaml`:

```yaml
models:
  - name: Urai
    provider: openai
    model: jev-local-student
    apiBase: https://urai.daddyai.online/v1
    apiKey: "856777"
    roles: [chat, edit, apply]
tabAutocompleteModel:
  name: Urai
  provider: openai
  model: jev-local-student
  apiBase: https://urai.daddyai.online/v1
  apiKey: "856777"
```

## 3. VSCode — Cline / Roo Code

Settings → API Provider → **OpenAI Compatible**:

- Base URL: `https://urai.daddyai.online/v1`
- API Key: `856777`
- Model: `jev-local-student`

For agentic runs you can also point the agent endpoint directly:
`POST https://urai.daddyai.online/agent` with header
`Authorization: Bearer 856777` and body `{"task": "..."}`.

## 4. opencode

`opencode.json` (project root):

```json
{
  "providers": {
    "urai": {
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "https://urai.daddyai.online/v1",
        "apiKey": "856777"
      },
      "models": {
        "jev-local-student": { "name": "Urai (local-first)" }
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
c = OpenAI(base_url="https://urai.daddyai.online/v1", api_key="856777")
r = c.chat.completions.create(model="jev-local-student",
    messages=[{"role": "user", "content": "Write a retry helper"}])
print(r.choices[0].message.content)
```

```bash
curl -s https://urai.daddyai.online/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer 856777' \
  -H 'X-Device-Id: my-laptop' \
  -d '{"model":"jev-local-student","messages":[{"role":"user","content":"hi"}],"max_tokens":64}'
```

Aider: `aider --openai-api-base https://urai.daddyai.online/v1
--openai-api-key 856777 --model openai/jev-local-student`

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `Free Token Expired / 0 available Token` (403) | Supply the master key: header `Authorization: Bearer 856777`, or `urai login 856777`, or `POST /auth/unlock {"master_key":"856777"}` |
| `invalid API key` (401) | Same as above — the VPS also accepts its service key, but `856777` is the documented one |
| Approval flow | `POST /auth/request {"device_id":"…","whatsapp":"…","gmail":"…"}` → superadmin approves at `/superadmin` |
| Model seems generic | It routes local-first; pass `"model": "jev-local-student"` and check `urai.models` badge in the response |
