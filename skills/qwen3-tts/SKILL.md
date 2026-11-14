---
name: qwen3-tts
description: "Ultra-high-quality open-source TTS from Qwen team (Apache 2.0). Voice cloning, voice design, natural language-based voice control, 10 languages. 0.6B and 1.7B models run locally. Better than kokoro for expressive, multilingual speech."
source: https://github.com/QwenLM/Qwen3-TTS
license: Apache-2.0
---

# Qwen3-TTS (Urai)

Qwen3-TTS is an open-weight TTS model (Apache 2.0) by Alibaba Qwen team. 0.6B and 1.7B variants, runs locally.

## Why use Qwen3-TTS over kokoro

- Better multilingual quality (Chinese, English, Japanese, Korean, German, French, Russian, Portuguese, Spanish, Italian)
- Natural language voice control ("speak slowly and warmly")
- Voice cloning from a 3-30s sample
- Voice design from text description
- Stronger emotional expression and prosody

## Setup

```bash
urai model download qwen3-tts-0.6b  # lightweight
urai model download qwen3-tts-1.7b  # better quality
```

Or via pip:
```bash
pip install qwen-tts
```

## Usage

```python
from qwen_tts import Qwen3TTS

tts = Qwen3TTS.from_pretrained("Qwen/Qwen3-TTS-0.6B")

# Basic TTS
tts.generate("Hello, I am Urai.", output="speech.wav")

# Voice clone
tts.generate("Welcome to Urai.", reference_audio="sample.mp3", output="cloned.wav")

# Voice design
tts.generate("This is important.", voice_desc="calm, British, professor-like", output="designed.wav")

# Multilingual
tts.generate("नमस्ते, मैं ऊराई हूं।", language="hi", output="hindi.wav")
```

## Via Urai API

```bash
curl -X POST http://localhost:8777/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Hello from Urai",
    "model": "qwen3-tts-1.7b",
    "voice": "default",
    "language": "en"
  }'
```

## Model Sizes

| Model | Size | Quality | VRAM |
|-------|------|---------|------|
| Qwen3-TTS-0.6B | ~1.2GB | Good | 2GB |
| Qwen3-TTS-1.7B | ~3.4GB | Best | 4GB |
