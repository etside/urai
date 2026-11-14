---
name: motion-video
description: "HTML-rendered video and motion graphics for agents. Write HTML+CSS+JS animations that render as video. Use for changelog videos, product demos, explainers, and data visualizations. Based on HyperFrames (heygen-com/hyperframes) motion doctrine."
source: https://github.com/heygen-com/hyperframes
---

# Motion Video (Urai HyperFrames)

Urai can generate motion graphics and animated videos by writing HTML/CSS/JS that gets rendered to MP4.

## The Vector Law (Motion Doctrine)

> How Scene A exits determines how Scene B enters: same axis, same direction, matched speed, cut mid-motion on both sides.

**Core rules:**
1. Exit → Entry: same axis, same direction
2. Z-axis: scale-up exit → scale-up entry (never reverse)
3. Motion must PERFORM — no idle wobble or breathing
4. Stillness before climax: freeze 200ms before the key moment
5. Carrier elements persist across scenes for visual continuity

## Usage

### Generate a Motion Video
```bash
urai agent "create a 30-second product demo video for Urai v1.3 with animated features list"

urai agent "make a changelog video showing: 1) image gen fixed 2) vibe coding works 3) v1.3 released"
```

### Via Vibe Code
```bash
urai vibe "create an animated HTML presentation with smooth slide transitions for a startup pitch deck"
```

## Output Formats

- **HTML artifact**: rendered in Studio browser as interactive animation
- **MP4**: exported via headless browser (requires ffmpeg)
- **GIF**: for sharing in chat

## Scene Structure

```html
<!-- Each scene is a div with data-duration -->
<div class="scene" data-duration="3000" data-exit="slide-left">
  <h1 class="enter-from-right">Feature Title</h1>
  <p class="enter-from-bottom delay-200">Description text</p>
</div>
```

## Motion Primitives

| Effect | CSS Class | Duration |
|--------|-----------|----------|
| Slide in from right | `enter-right` | 400ms |
| Slide in from bottom | `enter-bottom` | 400ms |
| Scale up | `enter-scale` | 300ms |
| Fade in | `enter-fade` | 500ms |
| Stagger children | `stagger-children` | 50ms per child |

## Caption Overlay

```html
<!-- Auto-caption from transcript -->
<div class="caption-overlay" data-transcript="captions.vtt">
  <!-- captions rendered automatically -->
</div>
```

## Best Practices

- Keep scenes 2-5 seconds each
- Use brand colors consistently (define CSS variables)
- Typography: max 3 font sizes per video
- Motion: one primary motion per scene, secondary motions at 50% speed
- Always test at target ratio (16:9, 9:16, 1:1) before final render
