# Urai video — studio integration (Higgsfield & others)

## Honest capability statement

Urai ships **two** video paths. They are not equal, and we do not pretend
otherwise:

1. **Local CPU path (built in, zero cost).** `urai video "prompt"` renders up
   to 16 still frames with the on-disk image checkpoint (sd-turbo) and
   stitches them into an MP4 slideshow with ffmpeg. Grade: **animatic /
   previz** — fine for storyboards and drafts. It is **not** Veo3 / Wan /
   Seedance class motion, and no CPU slideshow can honestly claim to be.

2. **SOTA provider proxy (recommended for production).** Urai forwards the
   job to a provider you configure (Higgsfield, Runway, or any generic
   `provider_url`) and returns the provider result transparently, still
   behind Urai auth, token accounting (`cost: 0` with master key), logging,
   and the superadmin panel. **This** is how Urai “performs” at Veo3 level:
   by routing to Veo3-class models instead of pretending to be one.

## Local usage

```bash
urai video "a robot reading a book, slow push-in" -o out.mp4
urai video "city timelapse" --duration 6 --remote   # render on the VPS
```

Requirements for the local path: sd-turbo checkpoint
(`urai model download sd-turbo`) **and** `ffmpeg` on PATH. Without either,
the API returns `ok: false` with the exact install step — never a silent
fake video.

## API

```bash
# Local animatic on the VPS (needs ffmpeg + checkpoint there)
curl -s http://127.0.0.1:8777/v1/videos/generations \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $URAI_MASTER_KEY" \
  -d '{"prompt":"a lighthouse at dusk","duration":4,"fps":4}'

# Job lookup
curl -s "http://127.0.0.1:8777/v1/videos/<job-id>" \
  -H "Authorization: Bearer $URAI_MASTER_KEY"

# Small clips straight back as base64
# ... -d '{"prompt":"...","response_format":"b64_json"}'
```

Token policy is the same as chat: the master key is unlimited; guests get
`URAI_FREE_LIMIT` free requests (default 5) before the device is blocked.

## Higgsfield / studio integration

Studios get three integration surfaces — use any or all:

**A. Chat/direction model (OpenAI-compatible).**
Point the studio’s “custom model” fields at Urai exactly like
[ide-integration](ide-integration.md): base
`http://127.0.0.1:8777/v1`, key `$URAI_MASTER_KEY` (or a `urai_…` key),
model `urai`. Use it for prompt expansion, shot lists, and direction
notes; send the final render prompt to the video endpoint or the studio’s
native pipeline.

**B. Video endpoint as a render service.**
`POST /v1/videos/generations` with `provider: "higgsfield"` (server env
`HIGGSFIELD_API_KEY` / `HIGGSFIELD_BASE_URL`) or a per-request
`provider_url` + `provider_key`. Urai returns the provider payload
unmodified under `result`, so studio-side parsing stays identical to a
direct provider call — with Urai auth and audit logging in front.

**C. MCP tool for agentic pipelines.**
`urai_video` (prompt, duration, width, height, fps, provider) alongside
`urai_ask` / `urai_agent` / `urai_imagine`, over stdio:
`python3 /path/to/urai/jev/mcp_server.py`.

## Recommended setup

1. Keep Urai as director + audit layer (auth, logging, approvals).
2. Set `HIGGSFIELD_API_KEY` (or Runway) in the server env for SOTA renders.
3. Use the local path only for previz/animatics.
4. Track every render in `/superadmin` → live log (`kind: video`).
