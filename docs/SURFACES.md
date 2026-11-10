# Urai Surfaces

Every way to access and use Urai.

## Web Studio

| URL | Environment |
|---|---|
| https://etside.github.io/urai/ | GitHub Pages (public) |
| http://52.66.18.45:8777/app | EC2 (always-on) |

## API (OpenAI-compatible)

```bash
curl http://52.66.18.45:8777/v1/chat/completions \
  -H "Authorization: Bearer urai_e3sbJn3XztLzDS3nahrJPnYKdbDRiRpY" \
  -H "Content-Type: application/json" \
  -d '{"model":"urai","messages":[{"role":"user","content":"Hello"}]}'
```

## CLI

```bash
pip install urai

urai ask "What is the capital of France?"
urai chat
urai tui
urai vibe
urai wiki <topic>
urai agents
urai mcp
urai serve
```

## APK (Android)

1. Download the latest APK from [GitHub Releases](https://github.com/etside/urai/releases)
2. Install on Android
3. App is pre-configured to EC2 API (http://52.66.18.45:8777)

## Python SDK

```python
from jev.agent import run_agent
response = run_agent("Summarize this document", context="...")
print(response)
```

## MCP

```bash
urai mcp
```

Add to Claude Code:
```json
{"mcpServers": {"urai": {"command": "urai", "args": ["mcp"]}}}
```

## ACP (Voice)

```bash
python -m jev.acp
```

## TUI

```bash
urai tui
```
