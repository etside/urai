---
name: voicestudio
description: "AI voice studio: clone any voice, design custom voices, dub videos, dictate, transcribe in 646 languages — all running locally. Use for voice cloning from a sample, dubbing a video into another language, designing a custom voice persona, or high-quality TTS. Based on VoiceStudio (110k stars, open-source local ElevenLabs alternative)."
source: https://github.com/debpalash/VoiceStudio
license: AGPL-3.0
---

# VoiceStudio (Urai)

Local voice AI: clone, design, dub, dictate, transcribe. 646 languages. No cloud needed.

## Capabilities

- **Voice Cloning**: 3-30s reference → cloned voice (any language)
- **Voice Design**: describe a voice in natural language → synthesize it
- **Video Dubbing**: translate + re-voice a video into another language
- **Transcription**: 646 languages, speaker diarization
- **TTS**: ultra-high-quality speech from text with emotion/speed control

## Usage via Urai

```bash
# Clone a voice from reference audio
urai agent "clone the voice from sample.mp3 and say 'Welcome to Urai'"

# Dub a video into Spanish
urai agent "dub this video into Spanish" --file video.mp4

# Design a custom voice
urai agent "create a voice that sounds like a calm British professor"

# Transcribe
urai agent "transcribe this audio in Hindi" --file audio.mp3
```

## Via Urai API

```bash
# Voice clone + TTS
curl -X POST http://localhost:8777/v1/audio/speech \
  -d '{"input":"Hello world","voice":"clone","reference_audio":"path/to/sample.mp3"}'

# Transcription
curl -X POST http://localhost:8777/v1/audio/transcriptions \
  -F "file=@audio.mp3" -F "language=hi"
```

## Supported Engines (all local, all free)

| Engine | Quality | Speed | Languages |
|--------|---------|-------|-----------|
| Kokoro (Urai default) | High | Fast | 8 |
| CosyVoice | High | Medium | 20+ |
| Qwen3-TTS | Best | Medium | 10 |
| faster-whisper | - | Fast | 100+ (transcription) |

## Install

Urai includes kokoro-onnx by default. For CosyVoice or Qwen3-TTS:
```bash
urai model download cosyvoice  # or qwen3-tts
```
