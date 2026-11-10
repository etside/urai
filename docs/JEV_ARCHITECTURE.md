# JEV Architecture (runtime as built — Phase 2/3)

```
┌─────────────────────────────────────────────────────┐
│ jev CLI (chat stream / ask / agent / model / serve / gpu / evaluate) │
├─────────────────────────────────────────────────────┤
│ JEV API :8777  /health /models /chat(+SSE) /generate /agent /tools /evaluate │
├──────────┬──────────────┬────────────┬───────────────┤
│ router   │ context mgr  │ tool eng.  │ agent loop    │
│ L0-L4    │ budget+trunc │ jail+allow │ verify+fix≤2  │
├──────────┴──────────────┴────────────┴───────────────┤
│ backends: llama-local (llama-server :8080) → teacher-api → mock │
│ models: coder05-fast [active] · qwen05-fast · coder15-primary (big-box) │
│ verifier: scripts/distill/verifier.py (compile/json/secrets/exec) │
└─────────────────────────────────────────────────────┘
```

## Files (`jev/`)

| File | Job |
|---|---|
| `cli.py` | all commands; `chat` streams SSE tokens live |
| `server.py` | OpenAI-compatible API, stdlib only |
| `router.py` | L0–L4 classifier → backend; local-first, API only at L3+ |
| `backends.py` | Mock / LlamaServer / TeacherAPI |
| `context.py` | token budget, priority truncation, history compression |
| `tools.py` | workspace jail, binary allowlist, read-only git |
| `agent.py` | plan→generate→verify→correct, budget MAX_FIXES=2 |
| `models_registry.py` | `model/registry.json`: ids, paths, bench numbers, active |
| `serve_ctl.py` | llama-server lifecycle (threads/ctx/ngl auto) |
| `gpu.py` | nvidia/rocm detect → `--n-gpu-layers` policy; CUDA rebuild hint |

## GPU story (honest)

- This box: no GPU → `ngl=0`, ≤1B Q4 only. Detected automatically.
- CUDA box: rebuild llama.cpp with `-DGGML_CUDA=ON`, same CLI auto-offloads
  (99 layers ≥6 GB VRAM, partial 3–6 GB). Zero code changes.
- Bigger VRAM unlocks `coder15-primary` already in the registry.

## Proven runs

- `jev serve start` → coder05 on :8080 (ngl=0, 3 threads, ctx 2048)
- `POST /agent {clamp task}` → L1 → llama-local → correct clamp + tests, fixes=0
- `jev chat` streams tokens; `jev model list/bench`, `jev gpu` all live.

## What's NOT yet built (roadmap)

SFT/DPO weight training (needs GPU box) · learned router · persistent
memory · speculative decoding · 7B+ tier · auth/multi-user on the API.
