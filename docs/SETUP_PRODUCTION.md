# Urai — production setup (current)

This is the single setup path for a **production-ready** Urai: CPU or GPU,
LLM + vibe coding, human-like conversation, summarising and tool-calling skills,
Wan video / Seedream image, and the Kaggle T4 free-GPU training loop.

It reflects what is actually in the tree and on the VPS. **No credential value
is ever printed, stored in git, or fabricated.** A relay with no key reports
`configured:false` rather than returning invented media.

---

## 0. One-command audit / setup

```bash
cd /root/urai
bash scripts/setup/production_setup.sh            # report only — safe anywhere
bash scripts/setup/production_setup.sh --install  # pinned deps + Kaggle CLI (if creds exist)
bash scripts/setup/production_setup.sh --verify   # version / gpu / relays / health
```

The script detects CPU vs CUDA/ROCm/Metal, reports which credential **names**
are present (OpenAI / Anthropic / OpenRouter / Vercel AI Gateway / teacher /
DashScope / ARK / Kaggle), checks the three communication skills, and verifies
the optional HTTP media paths. Requires Python 3.12+. Core runtime is stdlib
first — `requirements.txt` pins only the optional FastAPI/media/browser paths.

---

## 1. Compute: CPU, GPU, and quant selection

`jev/gpu.py` probes `nvidia-smi` then `rocm-smi`. The launcher applies this
offload policy automatically:

| Free VRAM | Build flag | `-ngl` |
|---|---|---|
| ≥ 6 GB NVIDIA | `-DGGML_CUDA=ON` | 99 (full) |
| 3–6 GB | `-DGGML_CUDA=ON` | 20 |
| < 3 GB / AMD ROCm | `-DGGML_CUDA=ON` / `-DGGML_HIP=ON` | 10 |
| none | `-DGGML_NATIVE=ON` | 0 (CPU) |

```bash
git clone --depth 1 https://github.com/ggerganov/llama.cpp.git third_party/llama.cpp
cmake -S third_party/llama.cpp -B third_party/llama.cpp/build \
  -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON        # add -DGGML_CUDA=ON on NVIDIA
cmake --build third_party/llama.cpp/build -j"$(nproc)" \
  --target llama-server llama-cli llama-bench llama-quantize
./bin/urai model download qwen3-4b                  # active default, ~3 GB RAM
./bin/urai serve start
./bin/urai api --port 8777
```

For the 30B MoE target (`Qwen3-30B-A3B-GGUF`, Apache-2.0) use the quant ladder
in `docs/PRODUCTION_SPEC.md` §2.1. **Hard floor 16 GB RAM** for CPU-only MoE;
below that the runtime stays in clearly-labelled *lite mode* with Qwen3-4B.
Multi-expert offload uses `--n-cpu-moe N` (llama.cpp ≥ b5200). Training and big
benchmarks never run on the control box — they go to Kaggle/Modal (§6).

---

## 2. LLM, vibe coding, reasoning and human-like replies

`config/platform.json` is the non-secret source of truth; env overrides it.

- **Primary LLM:** Ollama cloud `deepseek-v4.1-flash` at `https://api.ollama.com/v1`.
- **Fast / reasoning / ultra** profiles: `glm-5.3-flash`, `kimi-k3`, `muse-spark-open`.
- **Local fallback:** `urai-ai-1.3` via `llama-server`, used when offline.
- **Additional providers** already present in the VPS env (names only):
  `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`,
  `VERCEL_AI_GATEWAY_API_KEY`, `TEACHER_API_KEY`. The setup script reports
  which are available; no new key is required to start.

**Production LLM routing (urai-router):** all keys are pooled in
`~/.config/urai-router/keys.txt` (0600) and served from an OpenAI-compatible
proxy. Verified providers: `bai` (paid, balance via `urai-router keys balance
--provider bai`), two `openrouter` keys, `vercel`, `cerebras` (very fast
`qwen-3.8-27b` / `gpt-oss-120b`; token bucket refills continuously, $5 trial
credits expire after 30 days — no perpetual daily-free tier), plus keyless
`opencode` and local `ollama`. A daily cron refreshes key health and catalogues.
The merged catalogue has ~1,146 models. Point Urai
at it with:

```bash
urai-router serve --port 8792
export OLLAMA_BASE_URL=http://127.0.0.1:8792/v1
export OLLAMA_API_KEY=router-local        # router proxy needs no real key
export OLLAMA_MODEL=deepseek-v4.1-flash   # or any qualified model id
```

`bai/deepseek-v4.1-flash` answered through this path end-to-end. Free
OpenCode models route without a key but may return 429 when rate-limited.

Per-request pipeline (`jev/nlp.py → jev/vibe.py → jev/router.py → cache/retrieval → backend`):

1. `nlp` extracts intent, language, sentiment, emotion, complexity and red flags.
2. `vibe` applies a sentiment-conditioned style contract — this is what makes
   replies sound human rather than templated.
3. `router` selects the tier; complexity can only *raise* it.
4. Safety refusal happens **before** any model call on red flags.

```bash
./bin/urai ask "Explain MoE offload in two sentences"       # direct answer
./bin/urai agent "Add clamp() with a test, then verify"      # verify-first loop
./bin/urai vibe status                                       # style contract on/off
./bin/urai chat                                              # streaming REPL
```

### Skills that support this (all auto-discovered from `skills/*/SKILL.md`)

| Skill | Purpose |
|---|---|
| `zen-coder` | pragmatic minimal-diff coding with tests |
| **`summarize`** | TL;DR + key points + open items; preserves exact facts |
| **`tool-calling`** | choose → call → verify tool discipline; safe MCP use |
| **`human-conversation`** | natural Bengali/English, decision-first, specific, honest uncertainty |
| `urai-router` | route work to the right Urai tier/agent |
| `cyber-security`, `threat-analysis`, `android-privacy` | CyberUrai stack |
| `mcp-builder`, `self-audit`, `skill-creator`, `motion`, `mimo-v26`, `data-protection`, `webapp-testing`, `jev-optim` | extended harness |

`jev/skills.py` matches at most **2 skills per task** by keyword overlap, so
skill descriptions intentionally contain the trigger words ("summary", "tool",
"conversation", "Bengali", etc.). Use `./bin/urai skill list|show|enable` to
inspect. To add one, copy the frontmatter format from `skills/summarize/SKILL.md`.

---

## 3. Image — Seedream 4.0 (+ local fallback)

```bash
export ARK_API_KEY=...                    # from your provider account
./bin/urai imagine "gold and black premium bottle on marble" -o out/images/demo.png
```

- Model id `seedream-4-0-250828` is in `config/platform.json` (never hardcode).
- Endpoint base `https://ark.ap-southeast.bytepluses.com`, OpenAI-images shape,
  up to 14 reference images, `1K|2K|4K`, default 2K, ~$0.03/image.
- Returned URLs expire in **24 h** — `jev/relays.py` persists every result to
  `out/images` and serves a stable Urai URL.
- Without `ARK_API_KEY`, `urai imagine` falls back to local `sd-turbo`
  (`stable-diffusion.cpp`, ~4 GB RAM, slow on CPU) and reports the provider used.
- `POST /v1/images/generations` and `/imagine` share the same relay.

---

## 4. Video — Wan 3.0 / Prime (+ local fallback)

```bash
export DASHSCOPE_API_KEY=...
./bin/urai video "slow dolly across a gold bottle, studio light" --provider wan3
./bin/urai video "..." --provider wan3 --prime        # wan3.0-video-prime (opt-in)
```

- Model ids: `wan3.0-video` (default) and `wan3.0-video-prime` (fast, costlier).
  Both use the **same** DashScope async submit/poll lifecycle; Prime is only a
  model-id switch and is never enabled by default.
- Endpoint/poll paths and region come from `config/platform.json` →
  `jev/platform.py` → `jev/relays.py`; the relay sends
  `X-DashScope-Async: enable` and `Authorization: Bearer $DASHSCOPE_API_KEY`,
  polls `GET /api/v1/tasks/{task_id}`, then persists the MP4 to `out/videos`.
- Params: `resolution` 480P/720P/1080P, `ratio`, `duration` 2–30 s, `audio`,
  `seed`, `prompt_extend`; media inputs `first_frame`, `last_frame`,
  `reference_image|video|audio`, `file`, `link`.
- **No key → `configured:false`**, never a fabricated video. Local fallback is
  an sd-turbo + ffmpeg animatic (`--provider local`). The SOTA local path is
  H3 Ref2VA + VSA via ComfyUI (`--provider ref2va`, CUDA 12.1+, ~24 GB VRAM —
  see `docs/VIDEO_REF2VA.md`).

---

## 5. Verify the media plane

```bash
curl -s https://urai.daddyai.online/v1/capabilities | python3 -m json.tool
python3 -c 'from jev.relays import status; import json; print(json.dumps(status(), indent=2))'
```

Expected: `seedream4.configured` true only when `ARK_API_KEY` is set,
`wan3.configured` true only when `DASHSCOPE_API_KEY` is set. Both may honestly
be false today on the VPS — that is a configuration gap, not a bug.

---

### Optional DeepLake data plane

For persistent, searchable agent memory and versioned training datasets:
`python3 -m pip install -r requirements-deeplake.txt`, then `urai deeplake status`.
Local `file://` datasets need no credentials. See [DEEPLAKE.md](DEEPLAKE.md) —
it also explains how a saved `file://` or cloud dataset streams into
Kaggle/Modal GPU dataloaders without copying files.

### Google Colab CLI (on-demand GPU/TPU)

Installed on this box in an isolated venv with a `colab` launcher
(`requirements-colab.txt` pins `google-colab-cli==0.8.0`). One-time Google
OAuth sign-in is required by the user; Urai stores no Google credentials.
`urai colab status` reports availability, and `urai colab new TRAIN --gpu T4`
/ `urai colab run train.py --gpu T4` provision remote hardware explicitly.
See [COLAB_GPU.md](COLAB_GPU.md) for the full workflow, including running the
same `kaggle/train_qlora.py` on Colab with `URAI_*` path overrides.

## 6. Kaggle T4 GPU (free) — using existing credentials

Kaggle is the GPU path actually used (~30 free GPU-hours/week). DigitalOcean
cannot supply a GPU on this account (GPU limit 0 — `docs/GPU_LIMIT_REQUEST.md`).

**Credentials — either method works:**

```bash
# A) token file
mkdir -p ~/.kaggle
cp /path/to/kaggle.json ~/.kaggle/kaggle.json
chmod 600 ~/.kaggle/kaggle.json

# B) environment (useful on headless/CI hosts)
export KAGGLE_USERNAME=...
export KAGGLE_KEY=...
python3 -m pip install kaggle
kaggle competitions list -s image-classification | head -3   # verify auth
```

Never commit `kaggle.json` or the env values. The setup script checks the file
mode and reports presence only.

**Training run** (no CLI keys are needed inside the notebook itself):

1. kaggle.com → Create → **Notebook**, turn **GPU T4 x2 ON** and **Internet ON**.
2. Add input → Upload `data/verified/distill-now.jsonl` (current set: 245 rows).
   Add `kaggle/train_qlora.py` as a second input (the repo is private).
3. First cell:
   ```python
   !pip install -q unsloth trl peft accelerate bitsandbytes datasets
   ```
4. Run `!python3 train_qlora.py` with `MAX_TRAIN_STEPS=300` (≈1 h) and
   `URAI_BASE=unsloth/Qwen3-4B-bnb-4bit` (rank 16, 4-bit, seq-len 2048, adamw_8bit).
5. Download `/kaggle/working/urai-adapter` → merge → GGUF export → **bench gate**
   (no knowledge/math/code regression or DISCARD). See `docs/TRAINING.md`.

Scripted alternative (needs `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`):
`bash scripts/train/modal_train.sh` with `URAI_MODAL_GPU=T4|A100|L40S`.

---

## 7. Production hardening checklist

- [ ] `URAI_API_KEY` required on all data routes; `URAI_AUTH_GET=1` in prod.
- [ ] `URAI_MASTER_KEY` rotated from any default; never the SSH password.
- [ ] Secrets in `/etc/urai/env` mode **0600**, or env-only; never in git/logs.
- [ ] `URAI_CORS_ORIGIN=https://urai.daddyai.online` (no `*`).
- [ ] TLS via Caddy/Cloudflare; origin bound to `127.0.0.1:8777`.
- [ ] Cloudflare Access on `/admin`, `/superadmin`, `/trace`, `/v1/repo/*`.
- [ ] Rate limits on `/v1/chat*`, `/v1/images*`, `/v1/videos*`, `/browser/*`.
- [ ] Public `/v1/models` returns exactly `urai` and `cyberurai` (`jev/brand.py`).
- [ ] `/health` shows the quant tier and degraded/lite state honestly.
- [ ] Backups of `out/images`, `out/videos`, sessions and token state.

## Public API gate (Cloudflare Worker)

`urai.daddyai.online` is no longer anonymous. A Cloudflare Worker `urai-gate`
requires `Authorization: Bearer <token>` on every request and proxies to a
secret-protected origin (`urai-origin.daddyai.online`, which rejects requests
without `X-Urai-Gate` at nginx). The token is stored only mode-600 at
`~/.config/urai/gate-token` on each host (never in git or the APK).

Clients must set this token as their Urai API key:
- CLI: `urai login "$(cat ~/.config/urai/gate-token)" --url https://urai.daddyai.online/`
- APK/web app: Settings → API key field.
- The CLI sends a browser-like `User-Agent` because Cloudflare error 1010
  rejects the default `Python-urllib` agent.

> Security status: `ollama.daddyai.online` is **closed** — its DNS record and
> tunnel ingress were removed (was unauthenticated); Ollama now runs only on
> loopback/Tailscale via the router's keyless local provider. Still open:
> `urai.daddyai.online` is public with no auth at the edge, and Caddy binds
> `*:8778` to the Urai proxy. Both should be restricted before calling the
> deployment fully hardened.

---

## 8. Acceptance smoke test

```bash
bash scripts/setup/production_setup.sh --verify
curl -fsS https://urai.daddyai.online/health
curl -fsS https://urai.daddyai.online/v1/models          # exactly urai, cyberurai
./bin/urai ask "one sentence on why the sky is blue"
./bin/urai agent "summarize docs/PRODUCTION_SPEC.md into 5 bullets"
./bin/urai skill list | grep -E 'summarize|tool-calling|human-conversation'
```

All eight production gates are listed in `docs/PRODUCTION_SPEC.md` §13.
