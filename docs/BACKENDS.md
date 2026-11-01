# Urai Backends

All backend systems that power Urai.

## Local llama-server

- **Binary:** llama-server (llama.cpp)
- **Model:** Qwen3-0.6B-Q4_K_M.gguf
- **Port:** 127.0.0.1:8080
- **Config:** `local_llama=true` in urai config

## EC2 API Server (primary)

- **URL:** http://52.66.18.45:8777
- **Instance:** t3.small, ap-south-1
- **Model:** Qwen3-0.6B (local_llama=true)
- **OpenAI-compatible:** Yes
- **API key:** urai_e3sbJn3XztLzDS3nahrJPnYKdbDRiRpY

## S3 Storage

- **Bucket:** urai-data-089737991855-ap-south-1
- **Region:** ap-south-1
- **models/**: GGUF weight files
- **memory/**: memory snapshots
- **sessions/**: session archives
- **IAM Role:** urai-ec2-role

## DynamoDB Tables

| Table | Purpose |
|---|---|
| `urai-sessions` | Conversation sessions |
| `urai-memory` | Long-term memory store |
| `urai-token-state` | Token/quota tracking |

## CloudWatch

| Log Group | Purpose |
|---|---|
| `/urai/server` | API server logs |
| `/urai/watchdog` | Watchdog / health check logs |

## AWS Polly (TTS)

- **Region:** ap-south-1
- **Trigger:** `urai speak` or Studio voice button

## AWS Transcribe (STT)

- **Region:** ap-south-1
- **Trigger:** Studio microphone button or `urai listen`

## GitHub Pages (Studio PWA)

- **URL:** https://etside.github.io/urai/
- **Deploy:** Automatic on push to main

## Cloud LLMs (optional)

| Provider | Env var |
|---|---|
| Kimi K2 | `MOONSHOT_API_KEY` |
| DeepSeek | `DEEPSEEK_API_KEY` |
| Claude Haiku | `ANTHROPIC_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
