# 🧠 Urai

**Production AI runtime — local + cloud, CLI + API + Web + Android.**

Urai is a single, self-contained AI runtime that runs on the cheapest VPS you can find. One model file, all capabilities: chat, vision, image generation, video generation, voice (TTS + STT), vibe coding, embeddings, agents, and MCP. Fully OpenAI API compatible — drop-in replacement. GPU unlocks full capability.

---

## ✨ Capabilities

| Capability | Local (CPU) | Local (GPU) | Cloud API |
|-----------|-------------|-------------|----------|
| Chat / LLM | qwen3-4b (Q4_K_M) | qwen3-8b (Q4_K_M) | GPT-4o, Claude Haiku, Kimi K2, DeepSeek R2, Muse Wonder |
| Vision | qwen25vl-3b | qwen25vl-7b | GPT-4o-mini, Gemini |
| Image Gen | sd-turbo (2-step, 512px) | HyperFlux-1 (1-step SDXL) | DALL-E 3, Stability |
| Video Gen | ❌ (needs 16GB+ VRAM) | HunyuanVideo | Veo 3, Wan 3.0 |
| Voice TTS | kokoro-onnx (80MB, CPU) | kokoro-onnx | ElevenLabs, OpenAI TTS |
| Voice STT | whisper-small (int8) | whisper-medium | OpenAI Whisper |
| Transcribe | Bengali + English | Bengali + English | All languages |
| Vibe Coding | local + tools | local + tools | Any cloud model |
| Embeddings | nomic-embed (768d) | nomic-embed | OpenAI ada-002 |
| Agent | plan → tool → verify | plan → tool → verify | Any backend |
| MCP | stdio server | stdio server | stdio server |

---

## 💻 Hardware Requirements

| Tier | Specs | What Works |
|------|-------|-----------|
| **Minimum** (VPS/CPU) | 2 vCPU, 4GB RAM | Chat (qwen3-4b), embeddings, sd-turbo, whisper-small |
| **Recommended** (GPU 6-8GB) | 4 vCPU, 8GB RAM, 6GB VRAM (RTX 3060/A2000) | All local models up to 8B, fast image gen, medium STT |
| **Production** (GPU 16GB+) | 8+ vCPU, 16GB+ RAM, 16GB VRAM (A100/RTX 4090) | All models, real-time video gen, multi-modal |

---

## 🚀 Quick Install

```bash
curl -fsSL https://raw.githubusercontent.com/etside/urai/main/install.sh | bash
```

Or clone and run:
```bash
git clone https://github.com/etside/urai.git
cd urai
pip install -r requirements.txt
urai model download qwen3-4b
urai serve start
```

---

## 🖥️ CLI Commands

```bash
urai chat                    # Interactive chat REPL
urai ask "question"           # One-shot question
urai agent "task"             # Plan → tool → verify agent loop
urai vibe "build a todo app"  # Vibe coding: NL → code → run → iterate
urai see image.jpg "describe" # Vision: analyze image
urai imagine "a sunset"       # Image generation (sd-turbo)
urai video "prompt"           # Video generation (cloud API)
urai speak "hello world"      # TTS — text to speech
urai transcribe audio.wav     # STT — speech to text
urai embed "text"             # Generate embeddings
urai mcp                      # Start MCP stdio server
urai api                      # Start OpenAI-compatible API server (:8777)
urai model list               # List available models
urai model download <name>    # Download a model
urai model add <name> <path>  # Register a local model
urai serve start              # Start local llama-server
urai gpu                      # Show GPU info
```

---

## 🔌 API Compatibility

Urai speaks the **OpenAI API protocol**. It's a drop-in replacement:

```bash
# Point any OpenAI-compatible client at Urai
export OPENAI_API_KEY=any-value      # Urai ignores it for local
export OPENAI_BASE_URL=http://localhost:8777/v1
```

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/chat/completions` | POST | Chat completions (streaming supported) |
| `/v1/completions` | POST | Text completions |
| `/v1/models` | GET | List available models |
| `/v1/images/generations` | POST | Image generation |
| `/v1/audio/speech` | POST | Text-to-speech (TTS) |
| `/v1/audio/transcriptions` | POST | Speech-to-text (STT) |
| `/v1/embeddings` | POST | Text embeddings |
| `/v1/videos/generations` | POST | Video generation |
| `/health` | GET | Health check (includes voice status) |

---

## ☁️ Cloud Model Integrations

| Provider | Model | Role | Env Variable |
|----------|-------|------|-------------|
| Anthropic | Claude Haiku 4.5 | Chat (fast, cheap) | `ANTHROPIC_API_KEY` |
| OpenAI | GPT-4o Mini | Vision + fast chat | `OPENAI_API_KEY` |
| Google | Gemini / Veo 3 | Vision + Video gen | `GEMINI_API_KEY` |
| DeepSeek | DeepSeek R2 | Reasoning + coding | `DEEPSEEK_API_KEY` |
| Moonshot | Kimi K2 (1T MoE) | Coding + reasoning | `MOONSHOT_API_KEY` |
| OpenCode | Muse Wonder | Free-tier chat | `OPENCODE_API_KEY` |
| ElevenLabs | eleven_multilingual_v2 | TTS (cloud) | `ELEVENLABS_API_KEY` |
| FAL | HyperFlux-1 | Fast image gen | `FAL_API_KEY` |
| Wan | Wan Video 3.0 | Video gen | `WAN_API_KEY` |

---

## 📦 Local Models

| Model | Size | Role | Quant |
|-------|------|------|-------|
| qwen3-0.6b | 0.6B | Fast chat | Q8_0 |
| qwen3-1.7b | 1.7B | Primary chat | Q4_K_M |
| qwen3-4b | 4B | Primary chat (active) | Q4_K_M |
| qwen3-8b | 8B | Primary chat (GPU) | Q4_K_M |
| qwen25vl-3b | 3B | Vision | Q4_K_M |
| coder05-fast | 0.5B | Fast coding | Q4_K_M |
| deepseek-r1-1.5b | 1.5B | Reasoning | Q4_K_M |
| mimo25-3b | 3B | Primary chat | Q4_K_M |
| nemotron-mini-4b | 4B | Primary chat | Q4_K_M |
| embed-small | 137M | Embeddings (768d) | Q4_K_M |
| sd-turbo | 0.86B | Image gen (2-step) | fp16 |
| whisper-small | 244M | STT (Bengali+English) | int8 |
| whisper-medium | 769M | STT (higher accuracy) | int8 |
| kokoro-tts | 82M | TTS (ElevenLabs-quality) | fp32 |

---

## 🔧 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `URAI_PORT` | 8777 | API server port |
| `URAI_API_KEY` | (empty) | API key for remote access (empty = localhost only) |
| `URAI_MASTER_KEY` | 856777 | Master key (unlimited access) |
| `URAI_VOICE_BACKEND` | auto | Voice backend: auto, local, elevenlabs, openai |
| `URAI_WHISPER_MODEL` | small | Whisper model size: tiny, base, small, medium |
| `URAI_KOKORO_VOICE` | af_heart | Kokoro TTS voice ID |
| `ELEVENLABS_API_KEY` | (empty) | ElevenLabs API key for cloud TTS |
| `OPENAI_API_KEY` | (empty) | OpenAI API key for cloud TTS/STT/vision |
| `OPENAI_BASE_URL` | https://api.openai.com/v1 | OpenAI-compatible base URL |
| `GEMINI_API_KEY` | (empty) | Google Gemini / Veo 3 API key |
| `DEEPSEEK_API_KEY` | (empty) | DeepSeek API key |
| `MOONSHOT_API_KEY` | (empty) | Moonshot / Kimi K2 API key |
| `ANTHROPIC_API_KEY` | (empty) | Anthropic / Claude API key |
| `FAL_API_KEY` | (empty) | FAL API key for HyperFlux |
| `WAN_API_KEY` | (empty) | Wan Video API key |

---

## 🌐 Web UI

```bash
urai api                    # Starts server on http://localhost:8777
```

Open `http://localhost:8777/app` for the full web interface, or `http://localhost:8777/welcome` for the landing page.

---

## 📱 Android APK

Urai ships with an Android WebView shell:
- Points at your Urai API server
- Privacy guard: `PrivacyMonitorService` blocks trackers
- Configurable server URL + API key in settings
- Build: GitHub Actions → [etside/urai/releases](https://github.com/etside/urai/releases)

---

## 🎓 Training Your Own Model

Urai includes a distillation pipeline for custom models:

1. **Distillation**: `scripts/distill/` — generate → verify → filter training data
2. **QLoRA fine-tune**: Kaggle free GPU (`urai_kaggle_setup.txt`) or Modal cloud
3. **Base**: Qwen3-0.6B → your student model
4. **Gate**: must beat previous model on the benchmark suite
5. **Deploy**: download GGUF → `model/base/` → `urai model add`

See [docs/TRAINING_INFRA.md](docs/TRAINING_INFRA.md) for details.

---

## 📚 Documentation

- [Architecture](docs/ARCHITECTURE.md) — Full system architecture
- [Runtime Setup](deploy/RUNTIME.md) — VPS deployment guide
- [Separate VPS](deploy/vps-separate.md) — Multi-VPS setup
- [Clawd Audit](docs/CLAWD_AUDIT.md) — Code audit results
- [Training Infra](docs/TRAINING_INFRA.md) — Model training pipeline

---

## 📄 License

MIT

---

**Urai, developed by Tynio LTD**
