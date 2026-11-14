---
name: video-gen
description: "AI video generation via ChatCut (Seedance 2.5, Kling 4, MiniMax H3, Gemini Omni), local sd-turbo+ffmpeg slideshow, or provider APIs (Higgsfield, Runway). Use for text-to-video, image-to-video, first/last-frame transitions, and reference-guided generation."
source: https://github.com/ChatCut-Inc/agent-plugin
---

# Video Generation (Urai)

Urai supports multiple video generation backends. The best available backend is selected automatically.

## Models Available

| Model | Provider | Duration | Resolution | Best For |
|-------|----------|----------|------------|---------|
| `seedance-2-5` | ChatCut | 4-30s | 480p/720p/1080p | Default; multimodal refs, audio sync |
| `seedance2fast` | ChatCut | 4-15s | 720p | Fast drafts, iteration |
| `seedance2mini` | ChatCut | 4-15s | 720p | Cheap bulk generation |
| `kling` | ChatCut | 1-10s | 1080p (pro) | Character shots, fine emotional control |
| `kling-4` | ChatCut | 3-30s | 720p/1080p | Long clips, firstFrame/lastFrame |
| `minimax-h3` | ChatCut | 4-15s | 768p/2K | Multimodal (9img+3vid+3audio refs) |
| `minimax-h3-max` | ChatCut | 5-15s | 480p/768p | High-fidelity text/frame gen |
| `omni` | ChatCut (Gemini) | 3-10s | 360p-4K | Targeted edits, cheap drafts |
| `local` | sd-turbo+ffmpeg | 2-12s | 512p | Offline animatic (no API key needed) |

## Usage via Urai API

```bash
# Text-to-video
curl -X POST http://localhost:8777/video \
  -H "Content-Type: application/json" \
  -d '{"prompt": "a sunset over the ocean", "duration": 5, "provider": "chatcut-seedance", "ratio": "16:9"}'

# With first frame image
curl -X POST http://localhost:8777/video \
  -d '{"prompt": "zoom out to reveal a city", "provider": "chatcut-kling4", "first_frame": "asset-id", "duration": 8}'
```

## Setup

Set `CHATCUT_API_KEY` in `.env` to enable ChatCut providers (Seedance, Kling, MiniMax, Omni).

```bash
CHATCUT_API_KEY=your_key_here
```

## Prompt Engineering

For Seedance 2.5 (8-element structure):
```
[Subject] [Action] [Environment] [Camera motion] [Lighting] [Mood] [Style] [Audio description]
Example: "A red sports car accelerating through rain-slicked streets. Tracking shot. Neon reflections. Cinematic tension. Realistic. Engine roar and rain."
```

For Kling: use `@first_frame`, `@last_frame`, `@image_1` to reference inputs in prompt.

## Ratios
- `16:9` — landscape/YouTube
- `9:16` — vertical/mobile/Reels
- `1:1` — square/Instagram
- `21:9` — cinematic widescreen
