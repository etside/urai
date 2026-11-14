---
name: openmontage
description: "Agentic video production system — 12 production pipelines for creating full videos from a prompt or reference. Covers text-to-video, image-to-video, talking head, character animation, lip sync, background removal, video dubbing, motion graphics, B-roll gen, and social-ready export. Based on OpenMontage (80k stars, AGPLv3 open-source)."
source: https://github.com/OpenMontageInc/OpenMontage
license: AGPLv3
---

# OpenMontage (Urai)

Agentic video production: 12 pipelines, all orchestrated through natural language.

## What it does

OpenMontage is a full video production system that chains together open-source AI tools into production pipelines. Urai integrates its patterns for end-to-end video creation.

## Pipelines available in Urai

| Pipeline | Description |
|----------|-------------|
| `text-to-video` | Prompt → full video (WAN 2.1 / LTX-Video) |
| `image-to-video` | Image + prompt → animated video |
| `talking-head` | Photo + script → avatar speaking video |
| `lip-sync` | Video + audio → lip-synced output |
| `background-removal` | Remove/replace video background |
| `motion-graphics` | HTML/Remotion → rendered video |
| `video-dub` | Video → dubbed in another language |
| `b-roll-gen` | Script → B-roll video clips |
| `character-rig` | 2D character + motion → animation |
| `faceswap` | Face replacement (consented use only) |
| `comfyui-render` | Custom ComfyUI workflow → video |
| `social-export` | Video → Reels/TikTok/YouTube-ready format |

## Usage

```bash
# Start a production pipeline
urai agent "create a 30-second product demo for Urai v1.3"

urai agent "make a talking-head video: use photo.jpg and say 'Welcome to Urai'"

urai agent "dub this video into Urdu" --file product_video.mp4

urai agent "add motion graphics with Remotion: title reveal, features list, CTA"
```

## Best practices (from OpenMontage)

- Always start with a **storyboard** before generating video
- Use **reference images** to anchor style/character consistency across shots
- For social: 9:16, 60fps, captions baked in
- Lip sync quality depends on face visibility — ensure clean, front-facing frames
- Background removal works best with solid or uniform backgrounds

## Setup

Most pipelines use Urai's existing tools (WAN 2.1, LTX-Video, Kokoro, browser).
For ComfyUI pipeline:
```bash
urai model download comfyui
```
