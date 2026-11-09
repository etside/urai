# Urai — Tools & GPU reference

Compiled directly from the tree (no invented numbers). Use this as the
single map of **what the runtime is made of** and **where compute runs**.
Everything heavy (builds, training, benches, APK) runs in CI or on a remote
GPU — never on the local box.

---

## 1. Runtime tools (in-process)

| Area | Module | What it does |
|---|---|---|
| Router / tiers | `jev/router.py` | picks `urai-fast` / `urai` / `urai-ultra` / `urai-cyber`; `nlp.complexity` only *raises* the level |
| Agent loop | `jev/agent.py` | verify-first plan → tool → verify; consistency self-checks; `agent apply` lands proposals |
| Backends | `jev/backends.py` | `LlamaServerBackend` (chat :8080, embed :8081), `EmbeddingBackend`, `MockBackend` (`URAI_FORCE_MOCK=1`) |
| NLP | `jev/nlp.py` | intent, entities, topics, language, sentiment, emotion, complexity, **redflags** (safety) |
| vibe-text | `jev/vibe.py` | sentiment-conditioned style contract injected before generation |
| Retrieval / cache | `jev/retrieval.py`, `jev/cache.py` | prompt cache + retrieval wired through every chat path (`urai.cached`, `urai.cache_hit`) |
| Conductor / swarm | `jev/conductor.py`, `jev/swarm.py` | split hard tasks; parallel sub-agents |
| Tools engine | `jev/tools.py` | `read_file`, `write_file`, `edit_file`, `run` (allow-listed argv), git (read-only), `web_search`, `web_fetch`, `browse`, `analyze` (compile/lint), `mcp_servers`, `mcp` — jailed under `JEV_WORKSPACE`, `policy.json` allow-list |
| Browser | `jev/browser.py` | headless goal-driven browse; pauses (never fails) on auth fields |
| MCP | `jev/mcp_client.py`, `jev/mcp_server.py` (`mcp_clients.json`) | call external MCP servers; expose Urai as a server |
| Plugins | `plugins/{browser,telegram,opencode-urai}` | drop-in handlers (`plugin.json`) |
| Skills | `skills/*` (`jev/skills.py`) | `skill list/show/add/enable/disable`; e.g. `android-privacy`, `cyber-security`, `jev-optim`, `mcp-builder`, `motion`, `self-audit`, `skill-creator`, `threat-analysis` |
| Memory / sessions / scheduler | `jev/memory.py`, `jev/sessions.py`, `jev/sched.py` | cross-session memory, focus anchor, cron jobs |
| Self-improve | `jev/selfimprove.py` | traces → datasets (safe) |

## 2. Model & media plane

| Kind | Path | Detail |
|---|---|---|
| Chat (active) | `model/registry.json` | **Qwen3-4B Q4_K_M** (`active: qwen3-4b`), plus 0.5B / 1.5B / 1.7B / 0.6B picks |
| Vision | `jev/vision.py` | Qwen2.5-VL-3B GGUF + `mmproj` Q8_0 |
| Image (local) | `jev/imagine.py` | stable-diffusion.cpp, `sd-turbo` fp16 |
| Image (relay) | `jev/relays.py` + `jev/platform.py` + `config/platform.json` | **Seedream 4.0** `seedream-4-0-250828` (ARK), url/b64, ≤14 refs, persisted to `out/images` |
| Video (local) | `jev/video.py` | sd-turbo frames + ffmpeg animatic |
| Video (relay) | `jev/relays.py` | **Wan 3.0** `wan3.0-video` (DashScope async submit+poll), persisted to `out/videos` |
| Video (SOTA local) | `jev/ref2va.py` | H3 Ref2VA + VSA via ComfyUI (see §4) |

Relays fail **honestly** (`configured:false`) when `ARK_API_KEY` /
`DASHSCOPE_API_KEY` are absent — never a fabricated result.

## 3. GPU detection & offload policy (`jev/gpu.py`)

- **NVIDIA:** `nvidia-smi` → name, VRAM total/free, `cuda=true`.
- **AMD:** `rocm-smi` (best-effort).
- **None:** CPU-only policy.

Offload (`--n-gpu-layers`):

| VRAM | policy |
|---|---|
| ≥ 6 GB (NVIDIA) | `ngl=99` — full offload |
| 3–6 GB | `ngl=20` — partial, watch VRAM |
| < 3 GB / AMD | `ngl=10` — minimal |
| no GPU | `ngl=0` — CPU only, keep ≤1B Q4 |

CUDA rebuild (same CLI, zero code changes):

```bash
cmake -S third_party/llama.cpp -B third_party/llama.cpp/build \
  -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release
cmake --build third_party/llama.cpp/build -j \
  --target llama-server llama-cli llama-bench
```

`jev serve start` then auto-applies the policy. ROCm uses the same shape with
`-DGGML_HIP=ON`.

## 4. Ref2VA-VSA profile (local SOTA video)

`jev/ref2va.py` drives the installed ComfyUI custom node + bundled weights.
Profile gates: **CUDA 12.1+, ~24 GB VRAM**, ComfyUI reachable at
`URAI_COMFY_URL` (default `http://127.0.0.1:8188`), `comfy-kitchen` sol_attn.
Reference tokens stay **dense**; video tiles get VSA sparsity
(`URAI_REF2VA_SPARSITY`). `status()` reports per-file integrity and returns
"not installed" honestly. Details: [VIDEO_REF2VA.md](VIDEO_REF2VA.md).

## 5. Training / GPU job paths

| Path | Where | Notes |
|---|---|---|
| **Kaggle T4 (path used)** | `kaggle/train_qlora.py`, `scripts/train/sft_unsloth.py`, [KAGGLE_NOW.md](KAGGLE_NOW.md) | free single-GPU QLoRA (rank 16, 4-bit); run the notebook with `distill-now.jsonl` as an input dataset. No repo secrets needed. |
| **Soup (primary CI)** | `scripts/train/soup_train.sh`, `config/soup_train.yaml`, workflow `urai-train-soup.yml` | weekly cron + manual dispatch; QLoRA rank 16, stream_layers, publishes adapter to the `urai-deps` release. No extra secrets beyond `GITHUB_TOKEN`. |
| DigitalOcean H100 | `scripts/train/gpu_train.sh`, workflow `urai-gpu-run.yml` | **contract-only**: DO account GPU limit is 0 (`docs/GPU_LIMIT_REQUEST.md`); script destroys droplets at the time cap |
| GPU probe | workflow `urai-gpu-check.yml` | token-safe capability probe |

Base student `unsloth/Qwen3-4B-bnb-4bit`, Unsloth QLoRA rank 16, `adamw_8bit`,
seq-len 2048, 300 steps default. Strategy: [GPU_COMBINED_STRATEGY.md](GPU_COMBINED_STRATEGY.md).

## 6. CI workflows (`.github/workflows/`)

| Workflow | Trigger | What |
|---|---|---|
| `urai-integration.yml` | push/PR to the feature branch | **unit tests (nlp/vibe/pipeline/safety/relays), CLI, API contract, self-test** |
| `urai-video-ref2va.yml` | push/PR | prompt compiler + VSA patcher (no GPU needed) |
| `android.yml` | push/PR (`android/**`), tags `v*` | builds **APK + AAB** (signed when `URAI_KEYSTORE_*` set), publishes to `urai-deps` |
| `build.yml` | manual | builds llama.cpp + stable-diffusion.cpp, downloads weights, smoke + release bundle |
| `ci.yml` / `urai-ci.yml` | push | fast compile + offline smoke |
| `urai-train-soup.yml` | `schedule: 0 2 * * 1` + manual | **Soup training (primary)** — weekly cron, manual dispatch |
| `urai-gpu-check.yml` | manual | DO GPU capability probe |
| `urai-bench.yml`, `urai-selfimprove.yml`, `urai-distill-free.yml`, `distill-vps.yml` | manual | benches, self-improve, distill |

## 7. Artifacts & registry

Binaries, adapters and the APK/AAB are **not in git**. They live on the
`urai-deps` GitHub Release (runners, weights, `adapters-*.tgz`, `urai-app.apk`,
`urai-app.aab`) and are referenced by `model/registry.json` / `bin/urai model
download`.

## 8. Deploy targets

- **API + webapp:** `urai api` → `/` (playground) + `/v1/*` (OpenAI-compatible).
- **VPS:** systemd unit `deploy/urai-api.service` in `/opt/urai`, llama-server
  on `:8080` (chat) + `:8081` (embed), API on `:8777` — see
  [DEPLOYMENT_PLAN.md](DEPLOYMENT_PLAN.md) and [PROD.md](PROD.md).
- **Edge:** Caddy + Cloudflare Tunnel/Access (`deploy/Caddyfile`,
  `deploy/cloudflared.yml`); `/admin/*`, `/superadmin/*`, `/trace`, `/metrics`
  only on the admin host.
- **Android:** [android/README.md](../android/README.md).
