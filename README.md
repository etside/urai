# Urai — Open AI Model

[![CI](https://github.com/etside/urai/actions/workflows/urai-integration.yml/badge.svg)](https://github.com/etside/urai/actions/workflows/urai-integration.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/etside/urai)](https://github.com/etside/urai/releases)

| | |
|---|---|
| **Model** | Qwen3-0.6B fine-tuned (urai-qwen3-06b-v1-Q4_K_M) |
| **API** | http://52.66.18.45:8777 (OpenAI-compatible) |
| **Studio** | https://etside.github.io/urai/ |
| **APK** | [Download latest release](https://github.com/etside/urai/releases) |
| **CLI** | `pip install urai` or clone + `pip install -e .` |
| **License** | Apache 2.0 |
| **Version** | v1.1.1 |

## Quick Connect

```bash
export OPENAI_BASE_URL=http://52.66.18.45:8777/v1
export OPENAI_API_KEY=urai_e3sbJn3XztLzDS3nahrJPnYKdbDRiRpY

python3 -c "
from openai import OpenAI
client = OpenAI(base_url='http://52.66.18.45:8777/v1', api_key='urai_e3sbJn3XztLzDS3nahrJPnYKdbDRiRpY')
resp = client.chat.completions.create(model='urai', messages=[{'role':'user','content':'Hello'}])
print(resp.choices[0].message.content)
"
```

## Surfaces

| Surface | How to access |
|---|---|
| **Web Studio** | https://etside.github.io/urai/ · http://52.66.18.45:8777/app |
| **API** | http://52.66.18.45:8777/v1 (OpenAI-compatible) |
| **CLI** | `urai ask "..."` · `urai chat` · `urai tui` |
| **APK** | [GitHub Releases](https://github.com/etside/urai/releases) |
| **Python** | `from jev.agent import run_agent` |
| **MCP** | `urai mcp` (stdio, for Claude Code / opencode) |
| **ACP** | `python -m jev.acp` (voice/OpenLive protocol) |

See [docs/SURFACES.md](docs/SURFACES.md) for full details.

## Model

- **Base model:** Qwen3-0.6B
- **Quantization:** Q4_K_M (GGUF)
- **Registry:** [model/registry.json](model/registry.json)
- **GGUF download:** s3://urai-data-089737991855-ap-south-1/models/
- **Context window:** 32768 tokens
- **Skills:** 18 built-in skills (wiki, code, vibe, agents, memory, RAG, TTS, STT)

## Backends

See [docs/BACKENDS.md](docs/BACKENDS.md) for full backend documentation.

## Repository Layout

```
urai/
├── jev/          # Core runtime — 54 Python modules
├── studio/       # Web Studio (PWA)
├── model/        # Model registry and weights metadata
├── docs/         # BACKENDS.md, SURFACES.md, NEURO.md
├── skills/       # 18 built-in skills
└── .github/      # CI/CD workflows
```

## License

Apache 2.0 — see [LICENSE](LICENSE).
