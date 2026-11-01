# Urai Studio

Unified web interface for the Urai AI model.

## Access

| Environment | URL |
|---|---|
| **GitHub Pages (public)** | https://etside.github.io/urai/ |
| **EC2 live (always-on)** | http://52.66.18.45:8777/app |

## Features

- Chat interface with full conversation history
- Model selector (local llama, EC2, cloud)
- Tool use / function calling UI
- Skills browser (18 skills)
- File upload and RAG context
- TTS/STT (via AWS Polly/Transcribe)
- Session memory (DynamoDB)
- Export conversation
- PWA — installable on mobile

## Self-hosted

```bash
git clone https://github.com/etside/urai
cd urai
pip install -e .
urai serve
```

See [docs/BACKENDS.md](../docs/BACKENDS.md) for configuration.
