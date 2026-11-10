# Urai vs Muse Spark — Competitive Analysis Report

**Date:** 2026-10-27  
**Scope:** Urai v3 (etside/urai, commit `96f50b9`) vs Muse Spark (launch April 2026 through Muse Spark 1.3, September 2026)  
**Purpose:** Identify what Urai needs to implement to beat or match Muse Spark

---

## Summary Answer

Urai and Muse Spark are fundamentally different products competing on different axes. **Muse Spark is a hosted frontier model** from Meta Superintelligence Labs — closed weights, cloud-only, multimodal at scale, health-first, and deeply integrated with Meta's social graph. **Urai is a local-first AI runtime** — open-source, self-hosted, OpenAI-compatible, with a full desktop + CLI + web studio stack.

They overlap directly in: chat, agentic task execution, voice, vision, vibe/code generation, web research, and multi-agent orchestration. Muse Spark leads on raw model intelligence, multimodal depth, social-graph integration, and the "personal agent" story. Urai leads on privacy, local-first operation, zero cost at runtime, open weights, and full developer control.

**The gap to close is not about raw benchmark scores** — a 0.6B–8B local model will never beat a frontier-scale closed model on HLE. The gap is about product completeness, UX polish, and the specific features Muse Spark markets that Urai either lacks or has only partially implemented.

**Top 5 priorities to beat Muse Spark on its own claims:**
1. A polished "personal agent" that acts — not just answers — with proactive memory and goal-tracking
2. A code interpreter / sandboxed Python execution environment
3. A 1M-token (or maximum feasible) context window
4. A Contemplating-equivalent mode (parallel multi-agent reasoning)
5. Deep health reasoning module powered by curated medical training data

---

## What Each Product Is

### Urai v3

- **Source:** `/home/kp/urai-work/urai/README.md`, `CHANGELOG.md`, `docs/ARCHITECTURE.md`
- **Type:** Open-source AI runtime (Apache 2.0) by Tynio LTD
- **Core model:** Qwen3-4B Q4_K_M via llama.cpp; own fine-tuned weights (`urai-qwen3-06b`, `laya` pending)
- **Hardware target:** Runs on a 2 vCPU/4GB VPS (CPU-only minimum); GPU unlocks 8B+ models
- **Key features:**
  - OpenAI-compatible API at port 8777
  - Web Studio (PWA, installable) with Chat, Vibe Code, Wiki, Agents, API Keys panels
  - Desktop app (Electron, Windows + Linux)
  - Android APK (WebView shell)
  - CLI (`urai ask`, `urai agent`, `urai vibe`, `urai wiki`, `urai agents`, `urai routines`)
  - Voice: STT (faster-whisper) + TTS (kokoro-onnx), AWS fallback
  - Vision: Qwen2.5-VL-3B via llama.cpp multimodal (mtmd)
  - Image generation: sd-turbo via stable-diffusion.cpp
  - Video: animatic/slideshow (local) + Higgsfield/Runway proxy (cloud)
  - Browser: Playwright computer-use with human-like pauses
  - Knowledge Wiki: 3-tier memory, BM25 + vector search
  - Named Agents: persistent, scheduled, private memory
  - Vibe Code: NL → write → run → iterate loop
  - Deep Research: IterResearch with multi-hop web search
  - Multi-agent: Swarm + Conductor (PlanningFlow) + parallel fan-out
  - MCP server: 8 tools (`urai_ask`, `urai_agent`, `urai_see`, `urai_imagine`, `urai_video`, `urai_embed`, `urai_model_list`, `urai_evaluate`)
  - 18 skills including ports of Anthropic skills
  - Self-improvement: weekly distill → bench → promote pipeline
  - AWS free tier: S3, DynamoDB, Polly, Transcribe, CloudWatch
  - Router with 5 tiers (L0–L4): routes to local or cloud model by complexity
- **Benchmarks (as of 2026-10-14):** Knowledge 100%, Math 83.3%, Code 100% — but on Qwen3-4B, not frontier scale
- **Latest commits:** AWS GPU training launch, hardware-adaptive optimizer, v1.04 finetune config, vibe coding features

### Muse Spark (Meta Superintelligence Labs)

- **Sources:** [ai.meta.com/blog](https://ai.meta.com/blog/introducing-muse-spark-msl/), [verdent.ai](https://www.verdent.ai/zh-Hant/guides/what-is-muse-spark), [codersera.com](https://codersera.com/blog/muse-spark-1-3-complete-guide-2026/), [simonwillison.net](https://simonwillison.net/2026/Apr/8/muse-spark/), [about.fb.com](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/)
- **Type:** Closed-source proprietary frontier model (Meta Model API + consumer app)
- **Current version:** Muse Spark 1.3 (September 2, 2026)
- **Intelligence Index:** 48.09 on AA Intelligence Index v4.3.2 (1.3/Max); original 1.0 scored 52 on v4.0
- **Context window:** 1,048,576 tokens (1M); max completion 943,718 tokens
- **Pricing:** $1.25/$4.25 per 1M tokens (standard); $0.10/$0.20 (Contributor, trains on your data)
- **Reasoning modes:**
  - Instant (fast, conversational)
  - Thinking (extended step-by-step, CoT)
  - Contemplating (multiple agents in parallel — highest reasoning, comparable to Gemini Deep Think)
- **Input modalities:** Text, image, video, PDF (audio degraded in 1.3)
- **16 built-in tools in the chat harness:**
  - `browser.search`, `browser.open`, `browser.find` (web search + full-page fetch)
  - `meta_1p.content_search` (semantic search across Instagram/Threads/Facebook posts the user can see)
  - `meta_1p.meta_catalog_search` (product search / shopping)
  - `media.image_gen` (artistic/realistic, 3 aspect ratios)
  - `container.python_execution` (Code Interpreter: Python 3.9, pandas/numpy/matplotlib/sklearn/Pillow/OpenCV)
  - `container.create_web_artifact` (create HTML+JS apps rendered as sandboxed iframes)
  - `container.download_meta_1p_media` (pull Instagram/Facebook post media into sandbox)
  - `container.file_search` (search uploaded files/PDFs)
  - `container.view`, `container.insert`, `container.str_replace` (file editing in container)
  - `container.visual_grounding` (object detection/bbox/point/count on images — native model feature)
  - `subagents.spawn_agent` (delegate subtasks to independent sub-agents)
  - `third_party.link_third_party_account` (Google Calendar, Outlook, Gmail)
- **Health AI:** Trained with 1,000+ physicians; leads all models on HealthBench Hard (42.8 vs GPT-5.4 40.1)
- **Contemplating mode:** Multi-agent parallel reasoning; 50.2% on HLE, beats GPT-5.4 Pro (43.9%) and Gemini Deep Think (48.4%)
- **Muse (personal agent):** Launched September 8, 2026; runs on Muse Secure VM; proactively acts on goals; browser automation (fills forms, negotiates, buys); Link/Stripe payments built in; persistent memory; Sentinel approval agent; available on iOS/Android/muse.ai
- **Muse Code:** Coding agent (Muse Spark 1.2+); multi-agent, long-horizon coding; every subagent spawned is observable and replayable via event log
- **Muse Image / Muse Video:** Separate image and video generation products (web-search-grounded image generation)
- **Open-source posture:** Closed (first proprietary Meta model); Muse Glimmer 30B is the open-weights sibling (Apache 2.0)
- **Availability:** Free tier at meta.ai and Meta AI app (Meta account required); paid API at api.meta.ai/v1 (public since July 9, 2026); also on WhatsApp, Facebook, Instagram, Messenger, Ray-Ban glasses

---

## Feature Gap Analysis

| Capability | Urai v3 | Muse Spark 1.3 | Gap |
|---|---|---|---|
| **Model intelligence** | Qwen3-4B local (83% math, 100% knowledge on own bench) | Frontier scale (48.09 AA Index v4.3.2, top 23 of 224 models) | Large — closed by cloud fallback (L4 router) |
| **Context window** | 8,192 tokens default; configurable up to ~32K with Qwen3 | 1,048,576 tokens (1M) | **Critical gap** — 128x smaller |
| **Reasoning modes** | Chat / agent (plan-tool-verify) / thinking opt-in (`urai_thinking: true`) | Instant / Thinking / Contemplating | Missing "Contemplating" parallel multi-agent mode |
| **Code interpreter** | Vibe Code (write + run loop, file-guarded) — executes on the host | `container.python_execution` (sandboxed, Python 3.9 + full science stack) | **Gap** — Urai's vibe runs on the real FS; no isolated sandbox |
| **Web artifacts** | Not present (Studio renders static HTML only) | `container.create_web_artifact` — full HTML+JS apps as sandboxed iframes | **Gap** — no in-chat interactive artifact creation |
| **Visual grounding** | Vision via Qwen2.5-VL-3B (see + describe) | `container.visual_grounding` — bbox/point/count on images, native model feature | **Gap** — Urai can describe, not localize/count objects |
| **Sub-agent spawning** | Swarm + Conductor multi-agent | `subagents.spawn_agent` in tool call; Muse Code multi-agent event log | Partial — Urai has swarm but lacks live observability/event log |
| **Personal agent (acts proactively)** | Named agents with schedule + memory | Muse: browser fills forms, negotiates, buys, acts when app is closed | **Gap** — Urai agents respond; they don't proactively act toward goals |
| **Health reasoning** | No health-specific training or tools | #1 on HealthBench Hard; trained with 1,000+ physicians | **Gap** — no health data or specialized health module |
| **Social graph integration** | None | `meta_1p.content_search` — query your Instagram/Facebook/Threads | N/A — Urai is not a social platform; not applicable |
| **Shopping/payments** | None | `meta_1p.meta_catalog_search` + Link/Stripe payment in Muse agent | Lower priority — optional product direction |
| **Third-party integrations** | None built-in (MCP extensible) | Google Calendar, Outlook, Gmail via `third_party.link_third_party_account` | **Gap** — calendar/email integration missing |
| **Voice** | STT (faster-whisper) + TTS (kokoro) | Native voice input; Ray-Ban glasses audio | Partial — Urai has voice, lacks native integration quality |
| **Image generation** | sd-turbo (local, 512px) + cloud proxy | `media.image_gen` (artistic/realistic, 3 ratios, meta.ai CDN) | Quality gap — sd-turbo is low-res; needs HyperFlux/FLUX.1 |
| **Video generation** | Animatic slideshow (local) + Higgsfield/Runway proxy | Muse Video product (separate, launched May 2026) | Partially addressed via proxy |
| **PDF/document input** | File upload via `/agent`, wiki ingest | Native PDF input in API | Gap — PDF is not a first-class input modality |
| **Multiplatform** | Web, CLI, Desktop (Electron), Android APK, PWA | iOS, Android, web (meta.ai), WhatsApp, Facebook, Instagram, Messenger, Ray-Ban | Gap — iOS app missing; social channel presence |
| **Security architecture** | Filesystem jail + command allowlist | Muse Secure VM (dedicated cloud VM per user); Sentinel approval agent | Different model — Urai is self-hosted, inherently isolated by deployment |
| **Privacy** | 100% local — data never leaves the machine | Muse Secure VM with opt-out of training; Confidential VM coming | Urai wins here — local = maximal privacy |
| **Open weights** | Apache 2.0 open-source; own fine-tuned GGUF | Closed (Muse Glimmer 30B is open-weights sibling) | Urai wins here |
| **Pricing** | Free to run (own hardware); cloud fallback costs only if used | $1.25/$4.25 per 1M tokens standard; free consumer tier | Urai wins at scale for local use |
| **API compatibility** | OpenAI-compatible drop-in | OpenAI SDK + Anthropic Messages format compatible | Parity |
| **IDE integration** | VSCode Continue, Cline, opencode, Aider, Cursor | No standalone IDE integration documented | Urai wins here |
| **Self-improvement** | Weekly distill → bench → promote pipeline | Contributor tier trains on user data (not autonomous self-improvement) | Urai wins in concept; execution still immature |
| **MCP** | Full MCP server (8 tools) | Not documented | Urai wins here |

---

## Evidence Citations

- Urai feature set: `README.md` feature table; `docs/ARCHITECTURE.md` capability map; `CHANGELOG.md` v3.0.0
- Urai model state: `docs/LAYA.md` (urai-qwen3-06b shipped; laya pending bench gate); `docs/AUDIT_2026-10-15.md` (performance on VPS)
- Urai benchmarks: `docs/BENCHMARKS.md` — 100% knowledge, 83.3% math, 100% code on Qwen3-4B
- Urai agentic loop: `jev/agent.py`, `jev/vibe.py`, `jev/research.py`, `jev/swarm.py`, `jev/conductor.py`
- Muse Spark 16 tools: simonwillison.net/2026/Apr/8/muse-spark — tool names and descriptions from meta.ai chat harness
- Muse Spark benchmarks: verdent.ai/zh-Hant/guides/what-is-muse-spark (HLE 50.2%, Terminal-Bench 59.0, ARC-AGI-2 42.5)
- Muse Spark 1.3 details: codersera.com/blog/muse-spark-1-3-complete-guide-2026 (1M context, pricing, contributor tier, latency)
- Muse personal agent: about.fb.com/news/2026/09/introducing-muse-personal-ai-agent (Secure VM, Sentinel, browser actions, payments)
- Muse Spark health: ai.meta.com/blog/introducing-muse-spark-msl (physician collaboration, HealthBench #1)
- Muse Code: dev.meta.ai/resources/blog/build-with-muse-code (multi-agent coding, event log observability)

---

## Top 10 Actionable Recommendations (Prioritized by Impact)

### P1 — High Impact, Directly Competitive

**1. Code Interpreter: Sandboxed Python Execution**
- Muse Spark's `container.python_execution` is its most viral feature (pandas, matplotlib, numpy, sklearn in a sandboxed environment).
- Urai's Vibe Code executes on the real filesystem, which is powerful but not safe for untrusted prompts and not "magical" in the way ChatGPT/Claude/Muse Spark sandbox execution is.
- **What to build:** A lightweight Docker or gVisor-based sandbox behind `/v1/code/execute`. Expose it in Studio as a "Code" panel where users can write Python, run it, see outputs + generated charts inline. Wire it as an agent tool. Bonus: persist files per session at `/mnt/data/` to match the Muse Spark UX.
- **Files to touch:** `jev/server.py`, `jev/tools.py`, `jev/agent.py` (add `code_execute` tool), Studio `app.html`

**2. Context Window: Scale to Maximum Feasible Size**
- Muse Spark's 1M context is its headline differentiator for long-document work.
- Urai defaults to 8,192 tokens. Qwen3-8B with llama.cpp can serve 32K–128K with enough VRAM; Qwen3 models natively support 32K.
- **What to build:** Set the default context to 32,768 for GPU deployments. Expose a `--ctx` config for operators. On the Studio chat, show "Context: 32K / 128K" as a live indicator. Document and test long-context performance.
- **Files to touch:** `docs/ARCHITECTURE.md`, `urai serve start --ctx`, `install.sh` defaults, Studio settings panel

**3. Contemplating Mode: Parallel Multi-Agent Reasoning**
- Muse Spark's Contemplating mode (multiple agents reasoning in parallel, then merging) is its frontier-reasoning story.
- Urai has `Swarm` (parallel tasks) and `Conductor` (PlanningFlow), but these are not exposed as a "thinking tier" from the UI.
- **What to build:** A `/v1/chat/completions` extension param `"reasoning": "contemplating"` (or `x-urai-reasoning`) that fans out N parallel reasoning agents, combines via a verifier/judge, and streams the merged answer. Expose in Studio as a "mode selector" (Instant / Thinking / Contemplating). N=3 parallel with majority vote is a good first cut.
- **Files to touch:** `jev/reason.py`, `jev/swarm.py`, `jev/server.py`, Studio `app.html`

**4. Proactive Personal Agent (Acts, Not Just Answers)**
- Muse's core pitch: "once you share a goal, Muse works while the app is closed, comes back when something changes."
- Urai has scheduled routines and named agents but they respond to requests — they don't proactively advance toward a goal across multiple sessions.
- **What to build:** A "Goals" layer on top of Routines. User sets a goal ("sell my car for max price"). Urai creates a plan (multi-step), stores it in `data/`, and the scheduler runs plan steps autonomously — web research, draft emails, notify the user before taking external action. This is a direct upgrade to `jev/routines.py` + `jev/sched.py` + `jev/agent.py`. Add an approval queue in the Studio dashboard.
- **Files to touch:** `jev/routines.py`, `jev/sched.py`, `jev/agent.py`, Studio `app.html` (Goals panel)

**5. Muse Code-Equivalent: Observable Multi-Agent Coding with Event Log**
- Muse Code's differentiator vs Urai's Vibe Code: every spawned sub-agent, tool call, and steer is observable and replayable via an event log in the UI.
- Urai's vibe coding runs but has no live observability stream for the human to watch/interrupt.
- **What to build:** Add a `GET /v1/vibe/<session_id>/events` streaming endpoint (SSE) that emits a structured event per tool call/plan step/subtask. Render this in Studio's Vibe panel as a live "agent trace" sidebar. Allow cancel/steer mid-run. This is what separates a tool from a product.
- **Files to touch:** `jev/vibe.py`, `jev/server.py`, Studio Vibe panel in `app.html`

### P2 — Medium Impact, Fills Visible Gaps

**6. Web Artifacts: In-Chat HTML+JS App Generation**
- Muse Spark's `container.create_web_artifact` creates interactive apps (HTML+JS) rendered in sandboxed iframes inside the chat. This is the "Claude Artifacts" pattern.
- Urai Studio renders static markdown. There is no artifact canvas.
- **What to build:** When the model outputs an HTML code block tagged `artifact`, Studio renders it in a sandboxed `<iframe>` with a "fullscreen" / "copy" / "download" button. The backend just needs to return an artifact field in the streaming response. The frontend does the heavy lifting.
- **Files to touch:** `jev/server.py` (add `artifact` field to stream chunks), Studio `app.html`

**7. Health Reasoning Module**
- Muse Spark is #1 on HealthBench Hard, trained with 1,000+ physicians. Health is its highest-signal differentiator for consumer trust.
- Urai has no health-specific capability.
- **What to build:** Curate a health Q&A distillation set (use medical Q&A datasets: MedQA, PubMedQA, HealthBench public questions). Run through the existing distill pipeline (`scripts/distill/run_distill.py`) and fine-tune the next model checkpoint. Add a "Health mode" system prompt in the router that injects "cite sources, note limitations, recommend professional consultation." Measure on a held-out HealthBench slice.
- **Files to touch:** `scripts/distill/run_distill.py`, `data/raw_tasks/`, `jev/router.py`, `jev/fewshots.py`

**8. PDF as First-Class Input Modality**
- Muse Spark 1.3 accepts PDF natively in the API.
- Urai has no PDF input path — users must manually extract and paste text.
- **What to build:** Add `POST /v1/files` (OpenAI Files API pattern). Accept PDF uploads, extract text with PyMuPDF (already in Muse Spark's Python sandbox), chunk and index into the Wiki or a per-session context. Expose as a drag-drop in Studio chat.
- **Files to touch:** `jev/server.py`, `jev/wiki.py` or new `jev/files.py`, Studio `app.html`

**9. Calendar / Email Third-Party Integrations**
- Muse Spark links Google Calendar, Outlook, Gmail as built-in tools.
- Urai has MCP (which can connect to anything) but no pre-built calendar/email connectors.
- **What to build:** Add `jev/integrations/google_calendar.py` and `jev/integrations/gmail.py` as MCP tools (OAuth2 flow, minimal scopes). Expose in Studio as a "Connect" settings page. This is a 2-day integration per service using existing Python OAuth2 libraries.
- **Files to touch:** `jev/integrations.py`, `jev/mcp_server.py`, Studio settings panel

**10. iOS App (PWA Promotion / Native Shell)**
- Muse Spark is on iOS native. Urai has Android APK and PWA but no iOS presence.
- **What to build:** The Studio is already a PWA. Promote "Add to Home Screen" on iOS Safari in the Studio UI (the install prompt currently only shows for Chromium). For a native feel, a minimal WKWebView-based iOS app shell (mirrors the Android APK pattern) would give App Store presence. This is a one-time 2–3 day build following `android/` as the pattern.
- **Files to touch:** `jev/static/` (iOS meta tags), new `ios/` directory mirroring `android/`

---

## What Urai Already Beats Muse Spark On

| Area | Urai Advantage |
|---|---|
| **Privacy** | 100% local — data never leaves user's machine. No Meta account required. No training on user data by default. |
| **Cost at scale** | Zero marginal cost for local inference. No per-token billing. |
| **Open source** | Apache 2.0. Full weights, full code, self-hostable, forkable. |
| **Developer control** | OpenAI-compatible API, MCP server, VS Code/Cursor/Aider integration, full CLI |
| **Self-improvement pipeline** | Weekly distill → bench → promote is unique; Muse Spark has no equivalent |
| **Desktop app** | Native Electron app for Windows + Linux; Muse is mobile/web only |
| **No vendor lock-in** | Works offline, no internet required for core path |
| **IDE integration** | VSCode Continue, Cline, opencode, Aider documented; Muse Spark has none |

---

## Conclusions

Muse Spark is a more capable model at the frontier scale — but it is a hosted API product with Meta's social graph as its moat. Urai's moat is privacy, local-first, and full developer ownership.

The five highest-ROI investments for Urai to become genuinely competitive for the users who currently choose Muse Spark are:

1. **Code interpreter sandbox** — this is the single feature most likely to change a user's choice
2. **Context window to 32K–128K** — cheap config change, immediate user impact
3. **Contemplating mode** — the "wow" reasoning tier that drives demo shareability
4. **Proactive agent goals** — transforms Urai from a Q&A tool to an agent that works for you
5. **Muse Code-style event log observability** — makes the coding agent trustworthy and debuggable

None of these require frontier-scale model weights. All five are architectural/product decisions that play to Urai's existing codebase strengths.

---

*Report generated by Kiro investigation agent from first-party Urai source files and public Muse Spark documentation. All Muse Spark data is from publicly available sources as of October 2026.*
