---
name: video-gen
description: "AI video generation using open-source, self-hosted models. No API keys or payment required. Backends: WAN 2.1 (best quality), LTX-Video (fast), AnimateDiff (SD-based), or Animatic preview (sd-turbo + ffmpeg). Patterns from Seedance/Kling/LTX open research. Use for text-to-video, image-to-video, first/last-frame transitions."
sources:
  - https://github.com/Wan-Video/Wan2.1
  - https://github.com/Lightricks/LTX-Video
  - https://github.com/guoyww/AnimateDiff
---

# Video Generation (Urai — 100% Open Source)

No API keys. No payment. All models run locally on your hardware.

## Backends

| Backend | Quality | Speed | VRAM | Setup |
|---------|---------|-------|------|-------|
| `wan21` | Best | Slow | 8GB+ GPU | `urai model download wan2.1` |
| `ltx` | Great | Fast | 8GB+ GPU | `urai model download ltx-video` |
| `animatediff` | Good | Medium | 6GB+ GPU | `urai model download animatediff` |
| `animatic` | Preview | Fast | CPU-ok | `urai model download sd-turbo` |

## Usage

```bash
# Text-to-video (auto-picks best available backend)
urai agent "generate a 5 second video of a sunset over the ocean"

# Via API
curl -X POST http://localhost:8777/video \
  -d '{"prompt": "a waterfall in a forest", "duration": 5, "ratio": "16:9"}'

# Specify backend
curl -X POST http://localhost:8777/video \
  -d '{"prompt": "...", "backend": "wan21", "ratio": "9:16", "resolution": "720p"}'
```

## Prompt Structure (from open research)

Best results use 8 elements:
```
[Subject] [Action] [Environment] [Camera] [Lighting] [Mood] [Style] [Audio description]

Example: "A red fox running through autumn forest. Tracking shot. Golden hour light. Peaceful. Cinematic. Rustling leaves and distant birdsong."
```

## Parameters

| Param | Options | Default |
|-------|---------|---------|
| `backend` | wan21, ltx, animatediff, animatic, auto | auto |
| `ratio` | 16:9, 9:16, 1:1, 4:3, 21:9 | 16:9 |
| `resolution` | 480p, 720p, 1080p | 720p |
| `duration` | 1-30 seconds | 4 |
| `first_frame` | image path | — |
| `last_frame` | image path | — |
| `style` | cinematic, anime, realistic, etc. | cinematic |
| `camera` | tracking shot, drone, handheld, etc. | — |

## Image-to-Video (WAN 2.1 / LTX)

Pass a `first_frame` image to animate from it:
```bash
curl -X POST http://localhost:8777/video \
  -d '{"prompt": "zoom out slowly", "first_frame": "/path/to/image.png", "backend": "wan21"}'
```

## Model Sources

- **WAN 2.1** (Apache 2.0): github.com/Wan-Video/Wan2.1
- **LTX-Video** (Apache 2.0): github.com/Lightricks/LTX-Video
- **AnimateDiff** (Apache 2.0): github.com/guoyww/AnimateDiff
