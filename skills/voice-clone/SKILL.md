---
name: voice-clone
description: "Instant voice cloning from an audio sample using OpenVoice (MIT/MyShell). Clone any voice in seconds with a 3-30 second reference clip. Supports 50+ languages, emotion control, speed/pitch adjustment. Use for TTS with custom voices, dubbing, narration, digital humans."
source: https://github.com/myshell-ai/OpenVoice
---

# Voice Cloning (Urai + OpenVoice)

Urai integrates OpenVoice for instant, high-quality voice cloning.

## Capabilities

- **Zero-shot cloning**: 3-30 second reference audio → cloned voice
- **50+ languages**: English, Chinese, Spanish, French, Japanese, Korean, and more
- **Emotion control**: neutral, happy, sad, angry, surprised, whispering
- **Speed/pitch**: 0.5x–2.0x speed, ±12 semitones pitch
- **Local model**: runs on CPU (slow) or GPU (fast), no API key needed

## Setup

```bash
pip install openvoice torch
# Download model weights
urai model download openvoice
```

## Usage via Urai CLI

```bash
# Clone voice from reference
urai voice clone --reference /path/to/sample.mp3 --text "Hello, I am Urai" --output out.mp3

# With emotion
urai voice clone --reference sample.mp3 --text "This is amazing!" --emotion happy

# Multi-language
urai voice clone --reference sample.mp3 --text "Hola, soy Urai" --language es
```

## Usage via API

```bash
curl -X POST http://localhost:8777/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Hello, this is a cloned voice",
    "voice": "clone",
    "reference_audio": "base64_encoded_audio_or_path",
    "emotion": "neutral",
    "speed": 1.0
  }'
```

## Best Practices (from OpenVoice)

- Reference clip: 10-30 seconds, clean audio, minimal background noise
- Speaker should be alone (no other voices in reference)
- Emotion in reference clip affects quality — neutral reference is most versatile
- For best results, use 24kHz+ audio
- Voice cloning consent: always obtain permission before cloning a real person's voice

## Privacy

- All processing runs locally (no data sent to cloud)
- Cloned voice models stored in `data/voices/`
- Delete with `urai voice delete <voice-id>`
