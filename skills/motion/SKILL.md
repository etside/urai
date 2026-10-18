---
name: motion
description: 2D/3D motion and animation for web UI and generated media. Use for animated pages, transitions, canvas/WebGL scenes, video-animatic prompts.
---

# Motion & animation skill

## Web UI motion (append-only, never restyle existing features)
- Prefer CSS keyframes + `transform`/`opacity` (compositor-cheap). Avoid animating
  layout properties (width/height/top/left) on hot paths.
- 3D tilt: `perspective` on the parent, `rotateX/rotateY` from pointer position,
  clamp ±14deg, reset on `pointerleave`. Keep `transform-style: preserve-3d`.
- Ambient 2D: one fixed full-viewport `<canvas>` behind content (`z-index: 0`,
  `pointer-events: none`), DPR capped at 1.5, `requestAnimationFrame` paused on
  `document.hidden`. Radial-gradient blobs with `globalCompositeOperation =
  'lighter'` is enough for an aurora feel at near-zero cost.
- Text gradients: `background-clip: text` + animated `background-position`.
- Always honor `@media (prefers-reduced-motion: reduce)` — kill all motion.
- Wrap all motion init in try/catch: decoration must never break function.

## Generated media prompts (video/animatic)
- `/video` animatic: describe shot in motion terms — camera move (push-in,
  orbit, crane), subject action beats per second, lighting shift, loop point.
- Character motion (Mixamo-style): name the rig, the action clip, and the
  export (`.glb` + preview mp4). Single-person, well-lit source footage only.
- Scene-by-scene (flick-style): one paragraph per scene — setting, action,
  camera, duration. Keep beats ≤4s for preview renders.

## Verify
- No new network deps, no layout shift on load, 60fps on a cold CPU box.
- Keyboard/focus behavior unchanged; Escape still closes every modal.
