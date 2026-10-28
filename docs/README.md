# Urai documentation

Start here if you are running Urai, and follow the *Building* section if you
are changing it.

## Using Urai

| Document | What it covers |
|---|---|
| [README](../README.md) | What Urai is, install, Web Studio, CLI, configuration |
| [API.md](API.md) | Every HTTP route: auth, keys, chat, agents, wiki, routines, `/vibe` |
| [OPENAI_API.md](OPENAI_API.md) | Drop-in OpenAI client setup (`base_url`, keys, streaming) |
| [CLI.md](CLI.md) | `urai api`, `studio`, `tui`, `key`, `model`, `vibe`, `wiki`, `agents`, `routines` |
| [ide-integration.md](ide-integration.md) | VS Code, opencode, Cursor, anything OpenAI-compatible |
| [HARNESS.md](HARNESS.md) | The agent harness: tools, loops, sandbox rules |
| [SAFETY.md](SAFETY.md) | What the sandbox does and does not protect |
| [video-studios.md](video-studios.md) | Video generation backends wired into the Studio |

## Architecture

| Document | What it covers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | The v3 system: server, router, backends, memory, tools |
| [JEV_ARCHITECTURE.md](JEV_ARCHITECTURE.md) | Runtime internals as built (Phase 2/3) |
| [agent-swarm.md](agent-swarm.md) | Swarm, conductor and browser-automation design |

## Models and training

| Document | What it covers |
|---|---|
| [BENCHMARKS.md](BENCHMARKS.md) | Measured tok/s, RAM and quality — reproducible |
| [MODEL_BENCHMARK_BASELINE.md](MODEL_BENCHMARK_BASELINE.md) | Phase-1 baseline numbers |
| [DATASET_PIPELINE.md](DATASET_PIPELINE.md) | Generate → teacher → verify → distill |
| [TRAINING.md](TRAINING.md) | Fine-tuning guide (SFT/DPO) |
| [TRAINING_INFRA.md](TRAINING_INFRA.md) | GPU infrastructure used for training |
| [LEARN.md](LEARN.md) | The learning loop |
| [INDEPENDENCE.md](INDEPENDENCE.md) | Roadmap away from Qwen |
| [LAYA.md](LAYA.md) | Laya, the Urai-owned student model |
| [CYBERURAI.md](CYBERURAI.md) | CyberUrai security specialist |
| [VISION_UPGRADE.md](VISION_UPGRADE.md) | Vision and image generation upgrade notes |
| [GPU_COMBINED_STRATEGY.md](GPU_COMBINED_STRATEGY.md) · [GPU_LIMIT_REQUEST.md](GPU_LIMIT_REQUEST.md) · [KAGGLE_NOW.md](KAGGLE_NOW.md) | Affordable GPU options |

## Historical snapshots

These record a point in time and are **not** a description of the current
deployment (they mention hosts and shared keys that no longer exist):

- [PROD.md](PROD.md) — production readiness, 2026-10-15
- [AUDIT_2026-10-15.md](AUDIT_2026-10-15.md) — audit, 2026-10-15
- [CLAWD_AUDIT.md](CLAWD_AUDIT.md) — feature audit

## Contributing

- `python3 scripts/smoke_urai.py` — fast local sanity check (no network)
- `python3 scripts/smoke_urai.py --offline` — fully offline variant
- CI: `.github/workflows/ci.yml` and `urai-ci.yml`; packaging in
  `desktop.yml`, the weight bundle in `build.yml`.
