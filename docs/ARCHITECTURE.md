# Urai v3 Architecture

## Overview
Urai is a production AI runtime that combines the best of local open-source models
with seamless cloud API fallback. OpenAI API compatible. Runs on minimum hardware.
GPU unlocks full capability.

## Capability Map

| Capability | Local (CPU) | Local (GPU) | Cloud API |
|-----------|-------------|-------------|----------|
| Chat/LLM | qwen3-4b Q4_K_M | qwen3-8b Q4_K_M | GPT-4o, Claude, Kimi K2, DeepSeek |
| Vision | qwen25vl-3b | qwen25vl-7b | GPT-4o-mini, Gemini |
| Image Gen | sd-turbo (2-step) | HyperFlux-1 | DALL-E 3, Stability |
| Video Gen | ❌ (needs 16GB+) | HunyuanVideo | Veo 3, Wan 3 |
| Voice TTS | kokoro-onnx | kokoro-onnx | ElevenLabs, OpenAI TTS |
| Voice STT | whisper-small int8 | whisper-medium | OpenAI Whisper |
| Transcribe | Bengali+English | Bengali+English | All languages |
| Embed | nomic-embed | nomic-embed | OpenAI ada-002 |
| Vibe Code | local+tools | local+tools | Any cloud model |
| Agent | plan+tool+verify | plan+tool+verify | Any backend |
| MCP | stdio server | stdio server | stdio server |

## Hardware Tiers

### Minimum (VPS/CPU-only)
- 2 vCPU, 4GB RAM
- Models: qwen3-4b (chat), embed-small, sd-turbo (stop llama first), whisper-small
- Missing: video gen, large vision, reasoning models

### Recommended (GPU 6-8GB)
- 4 vCPU, 8GB RAM, 6GB VRAM (RTX 3060 / A2000)
- All local models up to 8B
- Fast image gen, video gen (HunyuanVideo lite)
- Full Bengali+English STT at medium accuracy

### Production GPU (16GB+)
- 8+ vCPU, 16GB+ RAM, 16GB VRAM (A100 / RTX 4090)
- All models including 14B, 30B MoE
- Real-time video gen
- Multi-modal in single pass

## Service Architecture (VPS)

```
nginx :443
  ├── daddyai.online → :3000 (PM2, Node, daddyai)
  └── urai.daddyai.online → :8777 (urai-api)

urai-api :8777 (Python, jev/server.py)
  ├── /v1/chat/completions → router → local llama :8080 or cloud
  ├── /v1/models
  ├── /v1/images/generations → sd-turbo or cloud
  ├── /v1/audio/speech → kokoro or ElevenLabs
  ├── /v1/audio/transcriptions → faster-whisper or OpenAI
  ├── /v1/embeddings → embed-server :8081
  ├── /v1/video/generations → API only (Veo3/Wan3)
  └── /health

urai-llama :8080 (llama-server, qwen3-4b)
urai-embed :8081 (llama-server --embedding, nomic-embed)
```

## Router Levels
- L0: simple questions → qwen3-06b (fast)
- L1: coding snippets → coder05-fast or deepseek-r1-1.5b
- L2: multi-file/long → qwen3-4b (resident)
- L3: architecture/debug → qwen3-4b + cloud teacher
- L4: explicit hard → DeepSeek R2 / Kimi K2 (cloud)
- Vision → qwen25vl-3b (local) or GPT-4o-mini (cloud)
- Image gen → sd-turbo (local) or HyperFlux/DALL-E (cloud)
- Video gen → Veo 3 / Wan 3 (cloud always)
- Voice TTS → kokoro (local) or ElevenLabs (cloud)
- Voice STT → whisper-small (local) or OpenAI Whisper (cloud)

## OpenAI API Compatibility
All endpoints speak OpenAI protocol. Drop-in replacement:
```bash
export OPENAI_API_KEY=any-value  # urai ignores it for local
export OPENAI_BASE_URL=http://localhost:8777/v1
```

## Android APK
- WebView shell pointing at urai-api
- Privacy guard: PrivacyMonitorService blocks trackers
- Settings: server URL + API key configurable
- Build: GitHub Actions → etside/urai/releases

## Training Pipeline
- Distillation: scripts/distill/ (generate → verify → filter)
- QLoRA: Kaggle free GPU (urai_kaggle_setup.txt) or Modal cloud
- Base: Qwen3-0.6B → student model
- Gate: must beat previous model on bench suite
- Deploy: download GGUF → model/base/ → urai model add
