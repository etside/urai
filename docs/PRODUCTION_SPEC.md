# Urai — Production Build Spec

Status: **binding spec** (no prototype). Scope: standalone, production-grade AI
platform running **VPS-first with CPU fallback and CPU→GPU/ROCm acceleration**.
Owner: Tynio LTD. Supersedes the ad-hoc notes in `docs/PROD.md`,
`docs/VISION_UPGRADE.md`, `docs/GPU_COMBINED_STRATEGY.md` where they conflict.

> Deployment/provisioning/security runbook: `docs/DEPLOYMENT_PLAN.md`.

---

## 0. Principles

1. **One product, two public models.** Users only ever see `urai` and
   `cyberurai`. Everything else (backbones, teachers, adapters, embeddings,
   rerankers, vision/video relays) is internal and never appears as a
   selectable model id (enforced in `jev/brand.py`, `jev/server.py:_models`).
2. **One internal backbone.** A single MoE checkpoint family replaces a
   portfolio of separate frontier models. Capability is added by *skills,
   adapters, tools and retrieval on the same backbone* — not by shipping more
   models.
3. **VPS-first, GPU-optional.** The exact same weights run on a CPU VPS; when a
   CUDA/ROCm device is present, the same launcher offloads to it. No code fork,
   no second artifact.
4. **Verify-first.** Every agent answer passes the verifier gate; nothing is
   promoted (data, adapter, or weight) without the bench gate.
5. **Reproducible & remote-built.** All builds/installs/heavy compute run in CI
   or on the server, never on a developer laptop.

---

## 1. Architecture

```
                         ┌─────────────────────────────────────────┐
   clients               │  Cloudflare edge (DDoS/WAF/Bot/ZeroTrust)│
   app · APK · CLI ─────▶│  TLS1.3 + post-quantum, Access, Tunnel   │
   OpenAI SDK            └───────────────┬─────────────────────────┘
                                          │ (no origin public IP)
                        ┌─────────────────▼──────────────────────────┐
                        │  VPS  (always-on control plane)             │
                        │  Caddy/nginx → urai-api 127.0.0.1:8777      │
                        │  • auth (API keys), rate/token gates        │
                        │  • router (VPS-first, GPU-when-available)   │
                        │  • harness: agent/conductor/swarm/browser   │
                        │  • memory/focus/sessions/scheduler          │
                        │  • llama-server :8080 (MoE, CPU or GPU)     │
                        │  • llama-server :8081 (embeddings)          │
                        │  • media relay → Seedream 4.0 / Wan 3.0      │
                        └───────────┬───────────────────┬─────────────┘
                                    │                   │
                 ┌──────────────────▼───┐   ┌───────────▼─────────────┐
                 │ GPU node (optional)  │   │ Managed media APIs       │
                 │ CUDA or ROCm, same   │   │ Seedream 4.0 (image)     │
                 │ GGUF via --n-cpu-moe │   │ Wan 3.0 (+Prime) video   │
                 └──────────────────────┘   └─────────────────────────┘
```

- Control plane (API, auth, harness, memory, scheduler) is **always on the
  VPS** — it is cheap and always available.
- Inference plane (the MoE) runs **on the VPS CPU by default** and **offloads
  to a GPU node when one is attached/required**. The router decides per request.
- Media generation is **API-relayed** (Seedream/Wan) with an **offline local
  fallback** (SD-Turbo, Qwen2.5-VL) so the platform still works without egress.

---

## 2. Model strategy

### 2.1 The single MoE backbone — Qwen3-30B-A3B

| Property | Value |
|---|---|
| Architecture | Mixture-of-Experts, 128 experts, 8 active/token |
| Params | 30.5B total / **3.3B active** |
| Context | 32,768 native · **131,072 with YaRN** |
| License | Apache-2.0 (commercial OK) |
| Files | `Qwen/Qwen3-30B-A3B-GGUF` (q4_K_M…q8_0) |

Why this backbone: MoE gives frontier-class routing at ~3.3B active cost, so a
CPU VPS stays usable while a GPU makes it fast — from one artifact. Apache-2.0
removes legal friction. Native 32K + YaRN 128K satisfies "large context".

**Quant ladder (same model, selected by detected hardware — one file family):**

| Tier | File | ~Size | Target box | llama.cpp flags |
|---|---|---|---|---|
| `moe-q8`   | Q8_0   | 32.5 GB | GPU ≥48 GB | `-ngl 99 -fa` |
| `moe-q5`   | Q5_K_M | 21.7 GB | GPU 32 GB | `-ngl 99 -fa` |
| `moe-q4`   | Q4_K_M | 18.6 GB | GPU 16–24 GB / VPS 32 GB | `-ngl 99` or `--n-cpu-moe N` |
| `moe-q3`   | Q3_K_M | 14.9 GB | VPS 32 GB CPU | `--n-cpu-moe N -ctk q8_0 -ctv q8_0` |
| `moe-q2`   | Q2_K   | 12.8 GB | VPS 24 GB CPU (min) | `--n-cpu-moe N`, ctx ≤16k |

Hard floor: **16 GB RAM for CPU-only**. Below that the platform enters
**lite mode** (the only exception to "one backbone"): a dense Qwen3-4B
Q4_K_M served identically, clearly labelled `degraded` in `/health`. No
other model is ever user-visible.

MoE expert offload (`--n-cpu-moe`, llama.cpp ≥ b5200) is the key enabler: put
attention+shared experts on the GPU and routed experts in system RAM, so a
modest GPU (even 8–12 GB) meaningfully accelerates the same file used by the
CPU VPS.

### 2.2 Public surface — exactly two models

| id | Positioning | Internally |
|---|---|---|
| `urai` | fastest general LLM/agent for **vibe coding + agentic tasks** | MoE backbone + coding/agent skills + fast/balanced/ultra *modes* |
| `cyberurai` | **top latest cybersecurity knowledge & skills** | MoE backbone + cyber skill stack + threat-intel retrieval + cyber adapter |

Modelled in `jev/brand.py` (`BRANDS` = these two; all legacy ids — `urai-fast`,
`urai-ultra`, `urai-cyber`, `laya`, `cyberurai-v1`, `qwen*`, `coder*` — are
aliases folded in). `/v1/models` returns only these two.

### 2.3 Everything else is internal

Backbone quant tiers · embeddings (`embed-small`, nomic-embed) · reranker ·
local vision (`qwen25vl-3b`) · local image (`sd-turbo`) · TTS/STT · the MoE
teacher/distill stack · adapters. None are listed; some are addressable only
through internal tool paths.

### 2.4 Unified student (Laya) on the MoE

The "one unified model" is realised as **Laya**: a LoRA/imatrix lineage on the
MoE backbone, trained remotely (Modal/GPU) on the merged verified set
(`scripts/train/merge_verified.py` → `data/verified/unified.jsonl`). Promotion
is **bench-gated** (knowledge/math/code must not regress) and lands as a GGUF
quant in the ladder above — the public id stays `urai`.

### 2.5 CyberUrai = same backbone, cyber stack

CyberUrai is **not** a separate frontier model. It is the MoE backbone plus:
- skills `cyber-security`, `threat-analysis`, `android-privacy`;
- a retrieval layer over fresh advisories/CVEs/threat feeds (RAG, cached);
- a cyber adapter (LoRA) + verify-first, evidence-only verdict format
  (`RISK` + ≤3 bullets, ≤600 chars) per `docs/CYBERURAI.md`.
It retains "only two public models" while being a distinct brand/behaviour.

---

## 3. Compute & acceleration

### 3.1 Device auto-detection (extend `jev/gpu.py`)

Replace best-effort detection with a documented matrix:

| Vendor | Probe | Build | Runtime |
|---|---|---|---|
| NVIDIA | `nvidia-smi --query-gpu=name,memory.total,memory.free,compute_cap` | `-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=<cap>` | `-ngl`, `--n-cpu-moe`, `-fa` |
| AMD | `rocm-smi`, `amd-smi`, `rocminfo`, `/opt/rocm` | `-DGGML_HIP=ON -DAMDGPU_TARGETS=<gfx>` | `-ngl`, `--n-cpu-moe`, `-fa` |
| Apple | `system_profiler` (Metal) | default | `-ngl 99` |
| none | — | CPU build | `--n-cpu-moe`, small ctx, q8_0 KV |

`offload_policy()` returns `{vendor, engine, ngl, n_cpu_moe, ctx, kv}` derived
from **free** VRAM (not total) minus a safety margin. Multi-GPU uses `-ts`
(split) or vLLM tensor-parallel.

### 3.2 Serving engines

- **llama.cpp `llama-server`** — default everywhere (CPU, CUDA, ROCm; MoE
  offload; GGUF; OpenAI-compatible `/v1/*`). One binary per accel backend.
- **vLLM** — optional high-throughput GPU path for MoE (continuous batching),
  selected when `URAI_ENGINE=vllm` and a GPU is present. Same OpenAI contract.

### 3.3 Routing: VPS-first, GPU-when-available/required

`jev/router.py` decides per request:
1. classify difficulty (L0–L4) and mode (`fast|balanced|ultra|cyber`);
2. if a GPU node is healthy and the request is L≥2 or `ultra/cyber` → GPU;
3. else → VPS CPU (always available);
4. external teacher API only as a last-resort fallback when configured.
Verification (`verify`) is forced for L≥2 and all `cyberurai` traffic.

---

## 4. Media generation

### 4.1 Vision + image — Seedream 4.0 (unified access)

- **Endpoint:** `POST {ARK_BASE}/api/v3/images/generations`
  (e.g. `https://ark.ap-southeast.bytepluses.com/api/v3`).
- **Model id:** `seedream-4-0-250828` (read from config; the date suffix
  changes on model updates — never hardcode in code, only in `platform.json`).
- **Contract:** OpenAI-Images shape `{model, prompt, size, response_format}` +
  extensions `image` (image-to-image / multi-reference, up to 14 refs),
  `size` ∈ `1K|2K|4K` or explicit px (1280×720 … 4096×4096, default 2048²),
  `sequential_image_generation:auto` (sets), `stream`, `watermark`.
- **Cost:** ~$0.03 / successful image (flat across resolutions).
- **Critical:** returned URLs **expire in 24h** → the relay **persists outputs
  to object storage** immediately and re-serves a stable Urai URL.
- **Unified access:** Urai exposes one `/v1/images/generations` and one
  `/imagine` tool; the relay normalises OpenAI ↔ Seedream params. Local
  SD-Turbo is the offline fallback when egress/keys are unavailable.

### 4.2 Video — Wan 3.0 (+ Prime)

- **Endpoint:** DashScope asynchronous
  `POST https://{WorkspaceId}.{region}.maas.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis`
  with `X-DashScope-Async: enable`, `Authorization: Bearer $DASHSCOPE_API_KEY`;
  poll `GET /api/v1/tasks/{task_id}`.
- **Default model:** `wan3.0-video` (standard).
- **Prime decision (per requirement):** `wan3.0-video-prime` uses the **same
  endpoint, same schema, same task/poll lifecycle** — only the model id
  differs (Alibaba documents both under one reference; the model auto-routes
  by `input.media` + prompt). Integration is therefore **clean → Prime is
  included** as an opt-in *fast* profile (`URAI_VIDEO_FAST=1` or
  `model:"wan3.0-video-prime"`). Prime is never enabled by default (cost).
- Params: `resolution` 480P/720P/1080P, `ratio` adaptive/16:9/…, `duration`
  2–30s or `-1`, `audio`, `seed`, `prompt_extend`; media types `first_frame`,
  `last_frame`, `reference_image|video|audio`, `file`, `link`.
- Async tasks are tracked by the job store; signed result URLs are pulled and
  persisted (same retention discipline as Seedream).

---

## 5. Agent harness (verify-first)

Reuse and harden the existing modules; they are part of the product surface:

- **Verify-first agent** (`jev/agent.py`) — plan→tool→observe→verify→correct,
  budgets, full traces. Tool-use must actually dispatch (`tool_calls` wired).
- **Conductor** (`jev/conductor.py`) — thinker splits → parallel workers →
  verifier merges.
- **Swarm** (`jev/swarm.py`) — fan-out ≤8, isolated failures.
- **Browser** (`jev/browser.py`) — Playwright, credential-approval safety.
- **Active focus** (`jev/focus.py`) + **active memory** (`jev/memory.py`) —
  recency-scored memory + focus anchor injected each run.
- **Context** — MoE 32K native / 128K YaRN; q8_0 KV; server-side truncation
  policy + rolling summary for long sessions.
- **Sessions/scheduler** (`jev/sessions.py`, `jev/sched.py`) — survive restarts.

---

## 6. API & auth

- **OpenAI-compatible:** `/v1/models`, `/v1/chat/completions` (stream + non),
  `/v1/completions`, `/v1/embeddings`, `/v1/images/generations`.
- **Extensions:** `/agent`, `/agent/swarm`, `/agent/sessions|jobs`, `/tools`,
  `/evaluate`, `/see`, `/imagine`, `/video`, `/v1/videos/*`, `/browser/*`,
  `/v1/capabilities`, `/v1/info`, `/v1/docs`, `/health`.
- **Auth:** OpenAI-style `Authorization: Bearer urai_…` API keys with quotas
  (`jev/apitokens.py`, revocable, usage-tracked, never logged). Master key for
  admin. Guest free tier limited per device.
- **Errors** are always `{error: <string>}` or `{error:{message:<string>}}` —
  the UI normalises both (`errText()`), never `[object Object]`.

---

## 7. CLI — one-line install

```
curl -fsSL https://urai.daddyai.online/install.sh | sh
```

`install.sh` (already present) installs the CLI, symlinks `urai`/`jev` on PATH,
is **remote-first** (no heavy local download unless `URAI_MODEL` is set), and
supports `urai login`, `urai ask --remote`, `urai agent`, `urai swarm`.

---

## 8. Android APK — stable

- WebView shell with **configurable endpoint**, load-error screen (never a
  blank white page), settings, and the CyberUrai privacy guard module.
- **Release signing** (upload-keystore in CI secrets) → signed APK, not just
  debug; versioned via GitHub Release (`urai-deps`).
- Distribution: signed APK + (optional) Play internal track / enterprise.
- CI: `Urai Android` workflow builds and publishes the APK artifact.

---

## 9. Security — Cloudflare-grade + app-layer

**Edge (Cloudflare):**
- **DDoS** L3/4 automatic + L7 managed; **WAF** managed ruleset + OWASP core.
- **Bot Management** — verified bots allowlist, ML score challenge on abuse.
- **Rate limiting** rules per route class: `/v1/chat*` , `/v1/images*`,
  `/v1/videos*`, `/browser/*`, `/superadmin*` (tight), plus per-API-key limits
  at origin.
- **Zero Trust** — Cloudflare **Tunnel** (origin has **no public IP**),
  **Access** policies (service tokens / mTLS / device posture via WARP) on
  `/superadmin`, `/status`, `/v1/repo/*`, and admin APIs.
- **PQC** — TLS 1.3 with **hybrid post-quantum key agreement**
  (X25519MLKEM768 default) and PQ-capable certs; Tunnel/WARP on PQ where
  offered. CDN↔origin stays tunnelled + TLS.

**Origin/app-layer (already present, keep):** `X-Content-Type-Options`,
`X-Frame-Options: DENY`, `Referrer-Policy`, strict JSON 400s, body-size cap,
path-traversal guards, secrets in `/etc/urai/env` (0600), API-key quotas,
last-resort per-IP/device gates.

---

## 10. Frontend — responsive + animated (all live pages)

Live pages: **`/` (app.html)**, **`/welcome` (landing.html)**, **`/status`**.
Requirements (binding):
- Fluid layout from **360 px to ultrawide**; breakpoints at 1024 / 640 / 400.
- Safe-area insets for notched devices; `dvh` units; no horizontal scroll.
- Animated aurora background (canvas) with **`prefers-reduced-motion`** off-switch;
  micro-interactions (hover lift, focus glow, streaming cursor, toast/skeleton).
- Landing: scroll-reveal sections, animated nav, gradient headline.
- Accessibility: keyboard nav, focus-visible, colour contrast AA, `aria-*`.

---

## 11. Config & secrets

Single source of truth `config/platform.json` (non-secret) declares: public
model ids, backbone repo/quant, Seedream model id + `ARK_BASE`, Wan model ids +
region, Accelerator policy, feature flags. Secrets live only in env
(`/etc/urai/env`, GH secrets): `URAI_API_KEY`, `URAI_MASTER_KEY`,
`ARK_API_KEY`, `DASHSCOPE_API_KEY`, `DO_API_TOKEN`, `MODAL_TOKEN_*`,
`KAGGLE_*`, signing keystore.

---

## 12. Non-functional targets

| Area | Target |
|---|---|
| API availability | ≥99.9% (edge + single control plane) |
| Chat TTFT (VPS CPU, q3) | ≤3 s typical @ ≤8k ctx |
| Chat TTFT (GPU q4, 24 GB) | ≤0.7 s |
| Throughput (GPU q4) | ≥40 tok/s gen, ≥400 tok/s prefill |
| Image (Seedream 4.0) | p95 ≤12 s, 2K |
| Video (Wan 3.0) | async, p95 ≤5 min @1080p/5s |
| Context | 32K default, 128K YaRN opt-in |
| Error budget | <0.5% 5xx; all 4xx actionable strings |

---

## 13. Acceptance criteria (no-prototype gates)

A build is production-acceptable only when **all** hold:
1. `/v1/models` returns exactly `urai` and `cyberurai`; no internal ids leak.
2. Same GGUF runs CPU-only **and** auto-offloads on CUDA **and** ROCm boxes
   (proven by CI matrix logs, not local builds).
3. `urai` and `cyberurai` answer through the MoE with verify-first on L≥2.
4. Seedream 4.0 image + Wan 3.0 video relay works end-to-end with persistence;
   Prime toggle verified; offline fallback verified.
5. Cloudflare Tunnel + Access + WAF + rate limits + PQC active; origin has no
   public port 443.
6. All live pages pass a 360/400/768/1024/1440 px responsive check and the
   reduced-motion path.
7. Signed APK loads a configured endpoint with no blank-screen failure.
8. Bench gate green (knowledge/math/code no-regression) before any weight
   promotion.

---

## 14. Phases (summary; detail in deployment plan)

- **P0** Surface + bug hardening (done: two-brand surface, capabilities,
  error/mobile/APK).
- **P1** MoE backbone + accel detect + local media fallback.
- **P2** Seedream/Wan relays + persistence.
- **P3** Cloudflare edge (Tunnel/Access/WAF/PQC) + signed APK.
- **P4** GPU node + vLLM path + Laya unified-student promotion.
- **P5** CyberUrai retrieval/adapter + SLO burn-in.
