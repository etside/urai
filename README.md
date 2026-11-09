# Urai — unified agent harness + local AI runtime

Urai is an OpenCode/OpenClaw-class **agent harness** (verify-first agent loop,
parallel swarm, jailed tools, browser, skills, memory, scheduler, sessions,
plan-mode editing) served behind an **OpenAI-compatible API and a DeepSeek-class
web app** — plus the program to grow its own weights: distill → eval-gate → LoRA.

- Live: `https://urai.daddyai.online` (TLS) · master key `856777` = unlimited,
  guests = 5 free responses per device.
- Public model surface is **exactly two** ids: `urai` and `cyberurai`
  (internal ids never leak — `jev/brand.py`). Active weight: **Qwen3-4B Q4_K_M**.
- One request pipeline: **NLP → vibe-text → router → backend**, with prompt
  cache + retrieval wired through every chat path.
- GPU-aware (CUDA/ROCm auto-offload); heavy work (builds, training, benches,
  APK) always runs in CI or on a remote GPU — never on the local box.

New here? → [docs/BUILD_INTEGRATION_PLAN.md](docs/BUILD_INTEGRATION_PLAN.md)
(build/status), [docs/TOOLS_AND_GPU.md](docs/TOOLS_AND_GPU.md) (tools + GPU map),
[docs/CLI.md](docs/CLI.md) (full command set), [docs/API.md](docs/API.md).

## Quickstart

Requirements: Python 3.12+, `cmake`, a C++ compiler, ~2 GB free disk per 0.5B
GGUF. GPU optional (CPU works; CUDA/ROCm auto-used when present).

```bash
# 1. Fetch a base student weight (public Qwen GGUFs)
./bin/urai model download coder05-fast
#  - qwen05-fast / coder05-fast / coder15-primary / qwen3-06b ...
#    (see model/registry.json; active default is qwen3-4b)

# 2. Build the llama.cpp runner (first time only, takes a while on small boxes)
git clone --depth 1 https://github.com/ggerganov/llama.cpp.git third_party/llama.cpp
cmake -S third_party/llama.cpp -B third_party/llama.cpp/build \
  -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON
cmake --build third_party/llama.cpp/build -j$(nproc) \
  --target llama-cli llama-bench llama-quantize llama-server

# 3. Start the local model server (GPU-aware, :8080) and use it
./bin/urai serve start
./bin/urai chat                       # streaming REPL (empty line quits)
./bin/urai agent "Write clamp(v,lo,hi) with a test"
./bin/urai api                        # OpenAI-compatible API + web app on :8777
```

Add `./bin` to `PATH` to call `urai` from anywhere. CUDA box? Rebuild with
`-DGGML_CUDA=ON` and `urai serve start` applies the offload policy — see
[docs/TOOLS_AND_GPU.md](docs/TOOLS_AND_GPU.md).

## What the runtime does with every request

```
prompt ─▶ jev/nlp.py        intent · language · sentiment · emotion · complexity · redflags
        ▶ jev/vibe.py       sentiment-conditioned style contract (fallback: "");
        ▶ jev/router.py     tier (urai-fast|urai|urai-ultra|urai-cyber) — complexity only raises
        ▶ jev/cache.py      prompt cache  (response carries urai.cached / urai.cache_hit)
        ▶ jev/retrieval.py  context augmentation
        ▶ backend           LlamaServerBackend (:8080) · EmbeddingBackend (:8081) · MockBackend
```

- **Safety gate:** `nlp.redflags` (self-harm / weapon / csam) → refusal before
  any model call, on `/chat`, `/v1/chat/completions`, `/generate`,
  `/v1/completions` and inside the agent (`urai.refused=true`).
- **Streaming:** real token-level SSE passed through from `llama-server`
  (chunked fallback if a backend can't stream).
- **One error contract everywhere:** `{"error":{"message","type","code"}}`
  (+ `X-Request-Id` on every response).

## CLI reference (highlights)

```
urai chat                          interactive REPL, streams tokens
urai ask "question"                 one-shot answer (lightweight, no agent JSON)
urai agent "multi-step task"        plan/tool/verify loop
urai agent --session S | --no-remember
urai agent apply FILE | urai apply FILE   land a plan's proposals via /agent/apply
urai model list|download|use|bench  registry + availability + bench numbers
urai serve start|stop|restart [--all]      llama-server lifecycle (GPU-aware)
urai gpu                            detect GPU + offload policy
urai see <image> [question]         vision (--remote)
urai imagine <prompt> [-o out.png]  local sd-turbo or Seedream relay (provider)
urai video <prompt> [--provider wan3|ref2va|local]
urai studio [status|image|video|see]        media actions
urai embed / evaluate / browse / swarm [--mode conductor]
urai skill list|show|add|enable|disable
urai plugin / mcp / tasks / profile / vibe on|off|status / theme light|dark|system
urai login|logout|whoami             scoped API keys (quotas) for apps/CLI
urai api [--port 8777]              OpenAI-compatible API + web playground
urai version                        runtime version + active model
```

Full list: [docs/CLI.md](docs/CLI.md).

## API surface

```
Public (no key):   /health  /v1/models  /models  /v1/capabilities  /v1/info
                   /status  /v1/docs  /v1/media/profiles  /v1/integrations
Data (key):        /v1/chat/completions  /v1/completions  /v1/embeddings
                   /v1/images/generations  /imagine  /video  /agent  /tools ...
Ops:               /metrics (Prometheus)   /admin/metrics (JSON, master)
                   /admin/cache/clear     /admin/trace (JSON)   /v1/trace (alias)
                   /trace (UI page)       /assets/* + /frontend/* (ETag/304)
```

Set `URAI_API_KEY` to require `Bearer` on data routes; `URAI_AUTH_GET=1`
(default in prod) hardens GET discovery too. Webapp: `http://localhost:8777` —
set endpoint + key in the header; keys stay in browser `localStorage`.

### Options

| Where | How | Notes |
|---|---|---|
| Localhost | `./bin/urai api` | default, no key, safest |
| LAN | `--host 0.0.0.0` + `URAI_API_KEY` | `/v1/*` + tool routes need `Bearer` |
| VPS (systemd) | `deploy/urai-api.service` | repo in `/opt/urai`, `urai` user |
| VPS + HTTPS | Caddy: `deploy/Caddyfile` | auto TLS, `reverse_proxy 127.0.0.1:8777` |
| Docker | `docker build -t urai .` + `docker/docker-compose.yml` | `cp docker/.env.example docker/.env` |
| Edge | `deploy/cloudflared.yml` | Cloudflare Tunnel/Access in front of `/admin` |

### Sizing (measured where noted, rest estimated)

| Model | RAM needed | Notes |
|---|---|---|
| 0.5B Q4 (`coder05-fast`/`qwen05-fast`) | ~0.6 GB | measured 569/592 MB; smallest VPS OK |
| 1.5B / 1.7B Q4 | ~1.5 GB | needs 2 GB+ box |
| 3B vision (`qwen25vl-3b`) | ~3 GB | Q4_K_M + Q8_0 projector |
| 4B Q4 (`qwen3-4b`, active) | ~3 GB | primary; CPU or GPU |
| `sd-turbo` generate | ~4 GB | fp16 UNet; CPU slow but works |

Rule of thumb: 2 vCPU + model RAM + 1 GB headroom. CPU-only is fine;
GPU just makes it faster ([docs/TOOLS_AND_GPU.md](docs/TOOLS_AND_GPU.md)).

### Security checklist

- Never bind `0.0.0.0` without `URAI_API_KEY` (the CLI prints `auth=off` as a reminder).
- All data routes need the key when set; `/health` + `/v1/models` stay public.
- Prod: `URAI_CORS_ORIGIN=https://your.domain`; put Caddy/Cloudflare in front for TLS.
- Secrets are env-only (`URAI_MASTER_KEY`, `DO_API_TOKEN`, `ARK_API_KEY`,
  `DASHSCOPE_API_KEY`, ...) — never logged.
- `urai model download` URLs are pinned in `model/registry.json`; weights live
  outside git (and on the `urai-deps` release).

## Media (image + video)

- **Image:** local `sd-turbo` (`urai imagine`) or the **Seedream 4.0** relay
  (`provider=seedream`, model `seedream-4-0-250828`, ≤14 refs, persisted to
  `out/images`) when `ARK_API_KEY` is set.
- **Video:** local animatic, **Wan 3.0** relay (`provider=wan3`, DashScope async,
  persisted to `out/videos`) when `DASHSCOPE_API_KEY` is set, or the local
  **H3 Ref2VA + VSA** path via ComfyUI (`provider=ref2va`, ~24 GB VRAM).
- Relays never fabricate: with no key they return `configured:false`.

## Android app

Signed **APK + AAB** build in CI (`android.yml`), published to the `urai-deps`
release and version-tag Releases. The app is a WebView shell (endpoint + key in
Settings) plus the **CyberUrai** privacy guard (AppOps monitor, tracker scoring,
Shizuku/root blocking). See [android/README.md](android/README.md).

## Training & distillation

```
scripts/distill/generate_tasks.py  -> data/raw_tasks/expanded   (task gen)
scripts/distill/teacher_client.py  -> data/teacher_out          (teacher answers)
scripts/distill/verifier.py        -> exec + judge checks       (exec_check, judge)
scripts/distill/filter.py          -> data/verified/*.jsonl     (keep/drop + why)
scripts/distill/run_distill.py     -> one-shot orchestration + report
```

Train the unified student on the merged verified set (remote GPU only). The
free path actually used is a **Kaggle T4** kernel (Unsloth QLoRA, rank 16,
4-bit) — see [docs/KAGGLE_NOW.md](docs/KAGGLE_NOW.md):

```bash
# kaggle.com -> Notebook -> GPU T4 x2 + Internet ON
# add data/verified/distill-now.jsonl as an input dataset, then:
python3 kaggle/train_qlora.py            # MAX_TRAIN_STEPS=300, URAI_BASE=...
```

Soup is the automated training path (weekly CI + manual dispatch):

```bash
# Trigger via CI (recommended):
gh workflow run urai-train-soup.yml --repo tukitattu/urai
# Or run locally on a GPU box:
bash scripts/train/soup_train.sh         # soup-cli[train]>=0.73.0
```

Config: `config/soup_train.yaml`. Training runs automatically every Monday
at 02:00 UTC via `.github/workflows/urai-train-soup.yml`.

Merged adapters land on the `urai-deps` release. Details: [docs/TRAINING.md](docs/TRAINING.md),
[docs/GPU_COMBINED_STRATEGY.md](docs/GPU_COMBINED_STRATEGY.md),
[docs/VIDEO_REF2VA.md](docs/VIDEO_REF2VA.md).

## Docs index

| Doc | Contents |
|---|---|
| [BUILD_INTEGRATION_PLAN.md](docs/BUILD_INTEGRATION_PLAN.md) | end-to-end build plan + phase status (P0–P7) |
| [TOOLS_AND_GPU.md](docs/TOOLS_AND_GPU.md) | tools inventory + GPU/offload/training map |
| [PRODUCTION_SPEC.md](docs/PRODUCTION_SPEC.md) | LLM & media plane spec |
| [DEPLOYMENT_PLAN.md](docs/DEPLOYMENT_PLAN.md) · [PROD.md](docs/PROD.md) | edge, Cloudflare, VPS |
| [CLI.md](docs/CLI.md) · [API.md](docs/API.md) · [OPENAI_API.md](docs/OPENAI_API.md) | surfaces |
| [JEV_ARCHITECTURE.md](docs/JEV_ARCHITECTURE.md) · [HARNESS.md](docs/HARNESS.md) | runtime internals |
| [SAFETY.md](docs/SAFETY.md) · [CYBERURAI.md](docs/CYBERURAI.md) | safety gate + cyber guard |
| [TRAINING.md](docs/TRAINING.md) · [GPU_COMBINED_STRATEGY.md](docs/GPU_COMBINED_STRATEGY.md) | training |
| [VIDEO_REF2VA.md](docs/VIDEO_REF2VA.md) · [video-studios.md](docs/video-studios.md) | video |
| [VISION_UPGRADE.md](docs/VISION_UPGRADE.md) | vision |
| [BENCHMARKS.md](docs/BENCHMARKS.md) · [MODEL_BENCHMARK_BASELINE.md](docs/MODEL_BENCHMARK_BASELINE.md) | measured results |

## Automated build (no manual downloads)

`.github/workflows/build.yml` builds llama.cpp (pinned) + stable-diffusion.cpp,
downloads every pinned weight, runs the smoke test, regenerates the distill
datasets, and bundles runners + weights (+ `SHA256SUMS`) as artifacts — and as a
**GitHub Release** on a version tag:

```bash
git tag v1.1 && git push origin v1.1
# files over ~1.9GB are split (2GB Release cap) — rejoin with:
python3 scripts/assemble_release.py <download-dir>
```

Every push also runs fast CI (`ci.yml`) and the integration matrix
(`urai-integration.yml`: unit tests + CLI + API contract + self-test).

## Layout

```
jev/      runtime package (nlp/vibe/router/context/tools/agent/server/backends/cache/retrieval/relays)
bin/      urai + jev launchers
docs/     architecture, plans, baselines, GPU/tools, dataset pipeline
scripts/  hw baseline, distillation pipeline, training (soup/gpu)
data/     raw_tasks seeds + verified sets (generated sets are reproducible)
eval/     benchmarks + reports (all measured, nothing invented)
model/    registry.json + GGUF slots (binaries live on the urai-deps release)
plugins/  browser · telegram · opencode-urai
skills/   agent skills
android/  WebView shell + CyberUrai guard
deploy/   Caddyfile · cloudflared · systemd
```

## Headline finding

The dev box (2-core Intel m3, ~3.2 GB RAM, no GPU) runs the runtime, data
pipeline and eval harness — but cannot train weights and only lightly benches
large models. Training/benching runs on remote GPUs (free Kaggle T4; Soup CI is
the automated weekly alternative) and artifacts return as GGUF/adapter files recorded in `model/registry.json` and the
`urai-deps` release. Verification is always remote: GitHub Actions matrices
(cpu/cuda/hip), the APK build+sign job, and the API/CLI integration tests.

## Recovery note

This repo was reconstructed from the `ownai-distill-jev` build session after the
original `x3` work disk became unavailable. Source, docs, scripts, seed data and
registry are byte-faithful to the session's final state (`urai v2`). Regenerable
artifacts (GGUF weights, `third_party/llama.cpp` build, `teacher_out`/`verified`
sets, bench logs) are intentionally excluded — reproduce them with the commands
above.
