# Urai documentation

## Start here

| I want to… | Go to |
|---|---|
| Install and run Urai | [README](../README.md) |
| Deploy to a VPS or Docker | [DEPLOYMENT.md](DEPLOYMENT.md) |
| Update the running server | [REPO_WORKFLOW.md](REPO_WORKFLOW.md) → §3 |
| Improve the model / train | [TRAINING.md](TRAINING.md) |
| Use the API from code | [API.md](API.md) · [OPENAI_API.md](OPENAI_API.md) |
| Connect an editor (VS Code, Cursor…) | [ide-integration.md](ide-integration.md) |

---

## Using Urai

| Document | What it covers |
|---|---|
| [README](../README.md) | What Urai is, quick install, Web Studio, CLI, configuration |
| [DEPLOYMENT.md](DEPLOYMENT.md) | VPS + systemd + Caddy, Docker, env vars, firewall, backups |
| [API.md](API.md) | Every HTTP route: auth, keys, chat, agents, wiki, routines, `/vibe` |
| [OPENAI_API.md](OPENAI_API.md) | Drop-in OpenAI client setup (`base_url`, keys, streaming) |
| [CLI.md](CLI.md) | `urai api`, `studio`, `tui`, `key`, `model`, `vibe`, `wiki`, `agents`, `routines` |
| [ide-integration.md](ide-integration.md) | VS Code, opencode, Cursor, anything OpenAI-compatible |
| [HARNESS.md](HARNESS.md) | The agent harness: tools, loops, sandbox rules |
| [SAFETY.md](SAFETY.md) | What the sandbox does and does not protect |
| [video-studios.md](video-studios.md) | Video generation backends wired into the Studio |
| [agent-swarm.md](agent-swarm.md) | Swarm, conductor, and browser computer-use agent |

---

## Architecture

| Document | What it covers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | The v3 system: server, router, backends, memory, tools |
| [JEV_ARCHITECTURE.md](JEV_ARCHITECTURE.md) | Runtime internals (Phase 2/3) |

---

## Models and training

| Document | What it covers |
|---|---|
| [TRAINING.md](TRAINING.md) | **Step-by-step** fine-tuning guide: distill → Kaggle T4 → deploy |
| [REPO_WORKFLOW.md](REPO_WORKFLOW.md) | How to update code, sync VPS, cut releases, CI overview |
| [INDEPENDENCE.md](INDEPENDENCE.md) | Roadmap: Qwen-dependent → Urai-owned weights (Laya) |
| [LAYA.md](LAYA.md) | Laya, the Urai-owned student model |
| [CYBERURAI.md](CYBERURAI.md) | CyberUrai security specialist tier |
| [DATASET_PIPELINE.md](DATASET_PIPELINE.md) | Generate → teacher → verify → distill internals |
| [BENCHMARKS.md](BENCHMARKS.md) | Measured tok/s, RAM and quality (reproducible) |
| [TRAINING_INFRA.md](TRAINING_INFRA.md) | Kaggle, Modal, HuggingFace — GPU options |
| [VISION_UPGRADE.md](VISION_UPGRADE.md) | Vision and image generation upgrade notes |
| [GPU_COMBINED_STRATEGY.md](GPU_COMBINED_STRATEGY.md) | Affordable GPU strategy |
| [KAGGLE_NOW.md](KAGGLE_NOW.md) | Kaggle free-tier T4 setup notes |

---

## Contributing

```bash
# Quick sanity check before any commit (~6s, no network):
python3 scripts/smoke_urai.py

# Compile-check all Python:
find . -name '*.py' -not -path './.git/*' | xargs python3 -m py_compile
```

CI runs automatically on every push to `main`:
- `ci.yml` — compile + offline smoke (~1 min)
- `urai-ci.yml` — full lint, import check, Python 3.10 compat (~3 min)

See [REPO_WORKFLOW.md](REPO_WORKFLOW.md) for the full dev → deploy → release loop.

---

## Historical snapshots

These record a point in time and are **not** a description of the current deployment:

- [PROD.md](PROD.md) — production readiness audit, 2026-10-15
- [AUDIT_2026-10-15.md](AUDIT_2026-10-15.md) — code audit, 2026-10-15
- [CLAWD_AUDIT.md](CLAWD_AUDIT.md) — feature audit
- [MODEL_BENCHMARK_BASELINE.md](MODEL_BENCHMARK_BASELINE.md) — Phase-1 baseline numbers
- [LEARN.md](LEARN.md) — early learning loop notes
