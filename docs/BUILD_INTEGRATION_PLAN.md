# Urai — Build & Integration Plan (DeepSeek-class, end-to-end)

Companion to `docs/PRODUCTION_SPEC.md` (what to build) and
`docs/DEPLOYMENT_PLAN.md` (how to run it). This document is the **integration
blueprint**: it binds every existing feature in this repo to a role in the
product, defines the three pillars — **JEV (runtime) · NLP · vibe-text** — and
specifies exactly how **webapp, frontend, backend, API, CLI and APK** become
one wired, production system. No prototype stubs remain.

---

## 0. How to read this

- §1 audit = ground truth of what exists today (so nothing is re-invented).
- §2–§3 = target architecture and the JEV/NLP/vibe pillars.
- §4 = **feature-adoption matrix**: every repo feature → its product role →
  the wiring work still required.
- §5–§8 = UI, LLM/media, and the four client surfaces (webapp+frontend, APK,
  API, CLI).
- §9–§11 = cross-cutting contracts, acceptance gates, phased delivery.

---

## 1. Current-state audit (ground truth)

### 1.1 What is already real and wired

| Area | Reality |
|---|---|
| Harness core | `agent.py` (verify-first loop), `conductor.py`, `swarm.py`, `browser.py`, `sched.py`, `sessions.py`, `memory.py`, `focus.py`, `context.py`, `fewshots.py`, `skills.py`, `tools.py`, `router.py` — all reachable from `server.py` + `cli.py`. |
| Two-brand surface | `brand.py` → public `("urai","cyberurai")`; `/v1/models`, `/v1/capabilities` correct. |
| API | ~45 routes in `server.py` (OpenAI-compat + extensions + superadmin) with API-key/master/guest auth, SSE, CORS. |
| CLI | `jev/cli.py` single argparse with ~24 subcommands; remote-first, keyless install. |
| APK | WebView shell + CyberUrai privacy-guard module; debug build in CI. |
| Web UI | `app.html` (chat SPA, sidebar, harness drawer, modals, aurora+3D tilt) + `landing.html` (marketing, scroll-reveal). |
| Training/media | Modal/GPU distill pipeline; `vision.py`, `imagine.py`, `video.py`, `analyze.py`, `mcp_*`, `plugins.py`. |

### 1.2 Critical gaps that block "end-to-end production" (from the audits)

| # | Gap | Impact | Fix in §|
|---|---|---|---|
| G1 | **No sentiment/NLP/intent/language analysis anywhere** (verified: zero matches repo-wide) | cannot "generate per user sentiment/input" | §3 |
| G2 | **No dark/light theme toggle** (hardcoded dark `:root`) | UI requirement unmet | §7 |
| G3 | **No separate navigation / no routed pages** (single chat screen w/ overlays) | DeepSeek-class IA missing | §7 |
| G4 | **APK ↔ webapp disconnected**: `MainActivity` injects `urai_ep`/`urai_key` + calls `boot()`, but `app.html` reads neither and `boot()` is undefined; API key never sent | keyed/remote deploys 401 from APK | §8.2 |
| G5 | **APK release-only-is-debug**, no `signingConfigs`, `dependencies{}` misplaced inside `android{}`, no wrapper, CyberUrai `"cyber"` prefs never written, `TrackerDB` scans `splitNames` (never fires), missing runtime perms | "APK fully done" unmet | §8.2 |
| G6 | **CLI local `ask` reuses full agent + prints JSON; local `agent --session/--no-remember` ignored; no `agent apply`; no remote for see/imagine/embed/evaluate; `skill` action ignored; config file not 0600** | "CLI fully done" unmet | §8.4 |
| G7 | **API: GET routes unauthenticated even with `URAI_API_KEY`; error shapes inconsistent (flat vs OpenAI vs structured); streaming is fake (post-hoc 64-char chunker); `/admin/*` absent** | "API fully done" unmet | §8.3 |
| G8 | `serve.py` broken imports + `cache.py` dead; memory/fewshots/skills are keyword-only (embeddings endpoint unused for recall) | quality/perf gaps | §4, §3.4 |
| G9 | Static/SSE responses skip security headers; no `Vary: Origin`; no request-id | hardening | §9 |
| G10 | `docs/LAYA.md` contradicts current `brand.py` | doc drift | §4 |

---

## 2. Target architecture (end-to-end)

```
   WEBAPP (browser)        FRONTEND (shared lib)       ANDROID APK         CLI (urai/jev)
        │                        │                        │                   │
        └────────────┬───────────┴───────────┬────────────┴───────────────────┘
                     ▼                       ▼
        ┌─────────────────────────  EDGE  ──────────────────────────┐
        │  Cloudflare: TLS1.3+PQ · WAF · rate-limit · Access · Tunnel │
        └───────────────────────────────┬──────────────────────────┘
                                         ▼
        ┌──────────────────────────  API LAYER (server.py)  ────────────────┐
        │ OpenAI-compat  ·  extensions  ·  auth (keys/master/guest)         │
        │ ONE error contract  ·  true token streaming  ·  request-id  · SSE │
        └───────────────┬─────────────────────────────────┬───────────────┘
                        ▼                                 ▼
        ┌──── REQUEST UNDERSTANDING (new) ────┐   ┌──── JEV HARNESS (existing) ────┐
        │ nlp.analyze (lang/intent/entity/…)  │   │ router L0–L4 · agent · conductor│
        │ sentiment.analyze (vibe/emotion)    │──▶│ swarm · browser · tools · mcp   │
        │ profile (per-user prefs, sticky)    │   │ memory · focus · sessions · sched│
        │ vibe.plan → STYLE CONTRACT          │   │ skills · fewshots · retrieval   │
        └─────────────────────────────────────┘   └───────────────┬────────────────┘
                                                                    ▼
        ┌──── LLM / MEDIA PLANE ──────────────────────────────────────────────┐
        │ MoE backbone (Qwen3-30B-A3B) quant ladder   ·   embeddings    ·      │
        │ reranker · vision · Seedream 4.0 (image) · Wan 3.0/Prime (video) ·   │
        │ local sd-turbo/qwen2.5-vl fallbacks                                  │
        └──────────────────────────────────────────────────────────────────────┘
```

**Contract rule:** *no user request reaches the LLM without first passing the
Request-Understanding layer*, and *every client talks to one API surface with
one auth model and one error contract*. That single rule is what makes the
system "connected" rather than a pile of features.

---

## 3. The three pillars: JEV · NLP · vibe-text

### 3.1 JEV — the runtime (already built; harden, don't rebuild)

JEV is the existing `jev/` package: routing + harness + tools + memory. Work:
- Close G8 (`serve.py` imports, wire `cache.py` or delete it, connect
  `EmbeddingBackend` to retrieval).
- Keep the public surface at exactly `urai` + `cyberurai` (§PRODUCTION_SPEC §2).

### 3.2 NLP — request understanding (NEW)

New module **`jev/nlp.py`** — pure-stdlib first, model/embedding-assisted when
available (no new hard deps):

```python
analyze(text, *, history=None) -> {
  "language": "en",            # detection + script hint
  "sentiment": {"label": "negative|neutral|positive",
                "score": -1.0..1.0, "confidence": 0.0..1.0},
  "emotion": "frustration|joy|curiosity|anger|neutral|…",
  "intensity": 0.0..1.0,        # strength of affect
  "urgency": 0.0..1.0,          # time-pressure words, "asap", "now"
  "intent": "ask|debug|build|refactor|explain|translate|summarize|audit|chitchat",
  "entities": [{"type": "file|lang|url|pkg|api|person", "value": "…"}],
  "topics": ["…"],
  "complexity": 0..1,           # feeds router.classify
  "redflags": ["self-harm","abuse",...]   # safety hand-off (§9)
}
```

Implementation: lexicon + regex + heuristics (deterministic, testable) with an
**optional** upgrade path that calls the embedding server / a small classifier
GGUF when present. Determinism keeps it CI-testable without a GPU.

### 3.3 vibe-text — sentiment-conditioned generation (NEW)

New module **`jev/vibe.py`** turns `nlp.analyze` + user profile into a **style
contract** injected into the system prompt (and reflected in the UI):

```python
plan(nlp, profile) -> {
  "formality": 0..1, "warmth": 0..1, "verbosity": 0..1,
  "humor": 0..1, "technical_depth": 0..1, "emoji": 0..1,
  "structure": "concise|balanced|structured|collapsible",
  "language": "en",           # reply in the user's language
  "de-escalate": true         # when sentiment negative/high-intensity
}
```

- Negative/high-intensity → de-escalate: shorter, calmer, no emoji, lead with
  the fix. Positive → warmer, a little more playful. Urgent → terse, action
  first. Curious/learning → more explanation + examples.
- "AI vibe-text" = the assistant's wording, length and structure **adapt per
  user sentiment/input** — and the UI surfaces *why* (a small "tone" chip) so
  it feels intentional, not random.
- Injected as a compact directive block; stored on the trace for audit.

### 3.4 Personalization & retrieval (connect the loose parts)

- **`jev/profile.py`** — per-identity profile (sticky prefs: language,
  formality, technical depth, verbosity) persisted next to `memory/facts.jsonl`;
  blended with transient sentiment (sticky ≠ transient).
- **`jev/retrieval.py`** — vector recall using the existing `EmbeddingBackend`
  (`:8081`) over memory/skills/fewshots, replacing keyword-only recall
  (`memory.recall`, `fewshots.best_for`, `skills.match`) with hybrid
  BM25+cosine, deterministic fallback to keyword when embed server is down.

### 3.5 End-to-end sentiment pipeline (the wiring)

```
client → API → nlp.analyze(text)
                 │
                 ├─► sentiment/vibe ─► profile.merge ─► vibe.plan ──┐
                 │                                                     ▼
                 ├─► retrieval.recall (memory/skills/fewshots) ─► context.build
                 │                                                     │
                 └─► router.classify (complexity/entities) ─► tier  ──┤
                                                                       ▼
                                     system = base + focus + skills + retrieval + STYLE CONTRACT
                                                                       ▼
                                             LLM (MoE) → verify-first agent loop
                                                                       ▼
                                   response (+ turai_metadata.vibe + trace)
                                                                       ▼
                                        client renders; UI shows tone chip (§7)
```

Call sites to insert (file:line from audit): `server.py` `/chat:786`,
`/v1/chat/completions:816`, `/generate:930`, `/v1/completions:941`, `/agent:963`;
`agent.py run_agent:103`. Add `nlp` + `vibe` JSON to responses and to
`/v1/capabilities` (methods).

---

## 4. Feature-adoption matrix (every repo feature → product role → work)

Legend — Status: **keep** (wired, fine) · **harden** (wired, needs fixes) ·
**wire** (exists, not connected) · **new**.

| Feature (module/asset) | Product role | Status | Required work |
|---|---|---|---|
| `agent.py` verify-first loop | Core reasoning engine | harden | insert nlp/vibe at entry; real tool_calls |
| `conductor.py` | Long-task orchestration | keep | expose in web UI task mode |
| `swarm.py` | Parallel fan-out | keep | CLI `--mode conductor` |
| `router.py` (L0–L4) | Cost/latency policy | harden | feed `nlp.complexity`; log vibe |
| `backends.py` (llama/embed/teacher) | Completers | harden | embed server → `retrieval.py`; true streaming |
| `context.py` | Budget/truncation | keep | honor style `verbosity` |
| `memory.py` / `focus.py` / `fewshots.py` / `skills.py` | Personalization + knowledge | harden | `retrieval.py` hybrid recall |
| `sessions.py` / `sched.py` | Persistence + cron agents | keep | UI surfaces (sidebar “Tasks”) |
| `tools.py` (fs/terminal/git/web) | Action layer | harden | expose in “…/Tools” nav; audit log |
| `browser.py` (Playwright) | Web automation | keep | UI approvals panel; CLI `browse` remote |
| `mcp_server.py` / `mcp_client.py` | IDE/agent interop | keep/wire | document in UI Integrations |
| `plugins.py` (`browser`,`telegram`) | Channel plugins | wire | plugin gallery in Settings |
| `apitokens.py` | Metered keys | harden | surface in Settings → API keys |
| `analyze.py` (RE/ELF/PE) | Security tool | keep | CyberUrai tool card |
| `vision.py` / `imagine.py` / `video.py` | Media | harden | unify into `/v1/*` + media gallery UI |
| `gpu.py` / `serve.py`/`serve_ctl.py` | Accelerator + lifecycle | harden | fix `serve.py` imports; unify launcher |
| `models_registry.py` / `model/registry.json` | Model mgmt | harden | MoE entry; fix `qwen3-17b` mislabel |
| `cache.py` | Prompt cache | wire | connect to `agent`/`server` or delete |
| `bench.py` / `bench_harness.py` / `selfimprove.py` | Eval + self-improve | harden | gate in CI; surface in `/v1/benchmarks` UI |
| `integrations.py` / `/v1/integrations` | Capability report | keep | render in Settings |
| `skills/*` (11 packs) | Knowledge packs | keep | skill browser in sidebar |
| `scripts/distill/*`, `scripts/train/*`, `modal/`, `kaggle/` | Training pipeline | keep | Modal default (done) |
| `landing.html` | Public marketing | keep | dark/light + 3D polish |
| `app.html` | Product webapp | harden | §7 rewrite of IA + theme |
| `android/*` | APK shell + cyber guard | harden | §8.2 |
| `bin/urai`, `install.sh`, `jev/cli.py` | CLI | harden | §8.4 |
| `deploy/*`, `.github/workflows/*` | Ops + CI | keep | add deploy workflow (§11) |

---

## 5. LLM & media plane (see PRODUCTION_SPEC §2–§4)

- One MoE backbone **Qwen3-30B-A3B** (Apache-2.0), quant ladder, CPU→CUDA/ROCm.
- `urai` = general assistant; `cyberurai` = same backbone + cyber stack.
- Media: **Seedream 4.0** (image, unified relay, persist outputs) and
  **Wan 3.0 + Prime** (video, async poll, Prime opt-in) — full detail in the
  spec; here they are simply **capabilities exposed through the same API and
  the same media gallery UI**, never separate client integrations.

---

## 6. Design direction (frontend-design)

Not a ChatGPT clone and not a default shadcn theme. Direction: **"depth glass
over ink"** — a calm, spacious workspace with a restrained emerald accent, one
signature gradient (emerald → indigo → violet) used sparingly, and a soft
"3D rounded" object language: layered rounded surfaces with subtle inner light,
1px luminous borders and real elevation — depth used for hierarchy, never
decoration. Type: a humanist sans for prose (Söhne-class) with a mono for code;
tight tracking on headings, generous line-height on answers. Motion is
**stable and quiet** (transform/opacity only, 120–240 ms, no layout shift).
Everything is expressed as design tokens so dark/light is a token swap, not a
fork.

---

## 7. UI/UX plan — DeepSeek-class webapp (closes G2, G3)

All four surfaces share one **`frontend/` library** (tokens, components, API
client). The webapp is the reference implementation; APK embeds it; CLI mirrors
its actions.

### 7.1 Information architecture (separate navigation, routed)

Replace the single chat screen with a routed shell:

```
/shell
 ├── /            Chat            (streaming answers, tone chip, model picker)
 ├── /tasks       Agents & Jobs   (sessions, cron jobs, swarm/conductor runs)
 ├── /knowledge   Memory · Skills · Focus
 ├── /studio      Media gallery   (images/video, Seedream/Wan jobs)
 ├── /tools       Tools · Browser runs · MCP · Plugins
 ├── /settings    Profile · Theme · API keys · Integrations · Endpoint
 └── /admin       Superadmin (Access-gated)
```

- **Sidebar** (persistent, collapsible 260↔72↔0): logo, **New chat**, search,
  conversation list grouped by Today/Week/Earlier with pin + rename + delete
  (currently missing), Tasks entry, user/plan area at the bottom.
- **Top-level navigation** as a distinct rail/segmented control so pages are
  separate (fixes G3), not overlays.
- History routing via the History API (`pushState`) + deep links; `/superadmin`
  maps onto `/admin`.

### 7.2 Collapsible tabs

A reusable collapsible primitive used for: model-picker sections (Models/
Features/Skills/Methods/Plugins), Settings groups, the reasoning `<think>`
block, Jobs/Memory/Focus panels, and a right “Parameters” inspector
(temperature, max tokens, context, skills toggles). State persists per user.

### 7.3 Theme toggle (closes G2)

- `:root` = light tokens, `[data-theme="dark"]` = dark tokens; all colors via
  variables. A segmented **Light / Dark / System** control in the topbar +
  Settings; persisted (`localStorage` + profile); respects
  `prefers-color-scheme` when "System"; no flash (inline pre-paint script);
  meets AA contrast in both themes (verify the dim grays).

### 7.4 3D rounded shape language

- Token set: radii `--r-sm 10 / --r-md 16 / --r-lg 24 / --r-pill 999`;
  surfaces `--surface-1/2/3` with `box-shadow: 0 1px 0 rgba(255,255,255,.04)
  inset, 0 8px 30px rgba(0,0,0,.35)`; luminous `1px` borders; optional glass
  (`backdrop-filter: blur(12px)`) on drawers/modals only.
- Component upgrades: cards, message bubbles, buttons, inputs, sidebar items
  and modals get the rounded/depth treatment. The existing pointer-3D tilt on
  suggestion cards is generalised to a `data-tilt` directive (used sparingly).

### 7.5 Animations (stable)

- Keep aurora canvas + scroll-reveal; add route transitions (opacity+2px
  translate, 160 ms), sidebar/tab expand (height/transform, no reflow jank),
  and a **real streaming cursor** once server streaming is fixed (§8.3).
- Hard rules: transform/opacity only; no layout thrash; `will-change` limited;
  every animation disabled under `prefers-reduced-motion`; no animation longer
  than 240 ms in-app.

### 7.6 Webapp ↔ frontend ↔ backend connected

- One `frontend/api.js` client (shared by webapp + APK) that: injects auth
  headers, honors the injected `urai_ep`/`urai_key` (fixes G4), normalises the
  single error contract (§9), handles SSE, and opens the token modal on
  `403 free_token_expired`.
- Frontend build is bundled by CI and served same-origin by `server.py`
  (`/app`, `/assets/*`); no CDN, works offline behind the tunnel.

---

## 8. Client surfaces (fully done)

### 8.1 Webapp + frontend
Routed shell (§7), theme toggle, collapsible tabs, 3D tokens, media gallery,
tools/browser panels, settings (profile/keys/integrations), admin. Landing page
gets the same tokens + theme toggle.

### 8.2 APK — fully done (closes G4, G5)
- **Backend wiring:** `app.html`/`frontend/api.js` read `localStorage.urai_ep`
  and `urai_key`; define `boot()`; send the key. Write the CyberUrai `"cyber"`
  prefs from Settings (single source: endpoint + key).
- **Build:** move `dependencies{}` to project scope; add `signingConfigs`
  (upload keystore from CI secrets) + `release` signing; add Gradle wrapper;
  enable R8; add `mipmap` icons + `values/strings.xml`; fix
  `android:allowBackup=false` for key safety.
- **Cyber guard correctness:** replace `splitNames` scan with real dex/class
  library detection; score **granted** perms; replace nested weighted
  `ListView`-in-`ScrollView` with `RecyclerView`; request
  `POST_NOTIFICATIONS` + offer `ACTION_USAGE_ACCESS_SETTINGS`; add missing
  `RECORD_AUDIO`/location perms or drop the FGS types.
- **Distribution:** CI produces a **signed** APK + AAB; versioned release;
  optional Play internal track.
- **Navigation:** APK surfaces the routed pages via the WebView (hash routes)
  and the Cyber guard as a native entry.

### 8.3 API — fully done (closes G7, G9)
- **Auth unification:** apply `_auth_ok` to GET discovery routes too (config
  flag `URAI_AUTH_GET=1`, default on for prod); keep only `/health`,
  `/v1/models`, static public.
- **One error contract:** always
  `{"error":{"message":str,"type":str,"code":str}}` (+ HTTP status); keep the
  structured `free_token_expired` payload as a typed subtype; update the UI
  normaliser.
- **True streaming:** token-level SSE from `llama-server` (pass-through) instead
  of the post-hoc 64-char chunker (`server.py:1164`).
- **Route table + request-id:** add `X-Request-Id`, `Vary: Origin`,
  `Allow-Credentials` as configured; add the missing `/admin/*` aliases.
- **Capabilities:** advertise `nlp`, `vibe`, `retrieval` methods.

**Status (implemented):**
- `jev/config.py` central flags; `URAI_AUTH_GET` defaults on in prod
  (`URAI_ENV=prod`), `_PUBLIC_GET` keeps discovery public.
- `_normalize_error` gives every 4xx/5xx the one contract; `_expired_payload`
  stays a typed subtype.
- `_stream` now pass-through streams `Backend.stream()` (real SSE from
  `llama-server`; `MockBackend` streams in CI) with a chunked fallback when the
  backend can't stream or `URAI_STREAM=0`.
- Ops surface: `GET /metrics` (Prometheus text), `GET /admin/metrics` (JSON,
  master-gated), `POST /admin/cache/clear`, `GET /admin/trace` (JSON) and
  `GET /trace` (UI). `deploy/Caddyfile` serves `/admin/* /superadmin/* /trace
  /metrics` only on the admin host behind Cloudflare Access.
- Prompt cache + retrieval wired end to end (`/chat`, `/v1/chat/completions`,
  `/generate`, `/v1/completions`, `/agent`); responses expose `urai.cached`.

**Still open:** UI normaliser (`errText`) uses the new shape; CLI hardening
(§8.4) is tracked separately.

### 8.4 CLI — fully done (closes G6)
- Fix local `ask` (lightweight one-shot; not full agent JSON) and local
  `agent --session/--no-remember` pass-through.
- Add `urai agent apply` (land `--plan` proposals via `/agent/apply`).
- Add `--remote` to `see`, `imagine`, `embed`, `evaluate`; add
  `swarm --mode conductor`; add brand flag (`--model urai|cyberurai`).
- Implement `skill [add|enable|list]`; `serve stop --all` (stop embed too).
- Harden config: `~/.config/urai/config.json` written `0600`; prefer
  `$URAI_MASTER_KEY`; never echo the key.
- New commands matching the webapp: `urai profile`, `urai vibe on|off`,
  `urai studio` (media), `urai tasks` (jobs), `urai theme light|dark|system`
  (writes profile pref).
- One-line install already keyless/remote-first (keep); document full command
  set in `docs/CLI.md`.

---

## 9. Cross-cutting contracts

- **Auth:** one model — `urai_…` scoped keys (quotas) for apps/CLI, master for
  admin, guest free tier. `_auth_ok` + `_check_access` become the single gate
  for GET and POST. Cloudflare Access in front of `/admin`.
- **Error contract:** §8.3 shape everywhere; UI `errText()` updated.
- **Trace:** every request records `{request_id, nlp, vibe, route, tier,
  backend, usage, latency}`; `/agent/routing` and a new `/v1/trace` UI surface.
- **Safety:** `nlp.redflags` → refusal/de-escalation path (extend
  `docs/SAFETY.md`); no secret logging (already in `_log`).
- **Observability:** request-id logs, Prometheus metrics, dashboards (§DEPLOY).

---

## 10. Acceptance gates (no-prototype)

1. `/v1/models` = exactly `urai`,`cyberurai`; no internal ids.
2. `nlp.analyze` + `vibe.plan` run on **every** chat/agent request; unit-tested
   deterministically; output present in response metadata + trace.
3. UI: sidebar + separate routed navigation + collapsible tabs + functional
   Light/Dark/System toggle (AA contrast) + 3D rounded tokens; 360→1440 px and
   reduced-motion verified.
4. APK: signed release builds in CI; loads configured endpoint **with key**
   (no 401); Cyber guard detects a known tracker app and blocks via Shizuku/root
   or deep-link fallback.
5. API: GET auth enforced in prod; single error contract; **real** token
   streaming (TTFT < full-generation time for long answers).
6. CLI: local `ask` is a one-shot; remote parity for see/imagine/embed/evaluate;
   `agent apply` lands proposals; config `0600`.
7. Same GGUF runs CPU + auto-offloads CUDA + ROCm (CI matrix logs).
8. Bench gate green before any weight promotion.

---

## 11. Phased delivery (all builds in CI / on server — never local)

| Phase | Deliverable | Exit gate |
|---|---|---|
| **P0 Wiring truth** | fix G4/G8, `frontend/` lib skeleton, one API client | APK authenticates to keyed API; `serve.py` imports fixed |
| **P1 Understanding** | `jev/nlp.py`, `jev/vibe.py`, `jev/profile.py`, `jev/retrieval.py`; wired into API+agent | gates 2, and unit tests in CI |
| **P2 API done** | auth-on-GET, error contract, true streaming, `/admin`, request-id | gates 5 |
| **P3 UI done** | routed shell, sidebar, collapsible tabs, theme toggle, 3D tokens, gallery/tools/settings | gates 3 |
| **P4 APK done** | backend wiring, signing, R8, cyber fixes, signed release | gate 4 |
| **P5 CLI done** | commands + flags + config hardening + docs | gate 6 |
| **P6 LLM/media** | MoE backbone + accel detect; Seedream/Wan relays + persistence | gates 7 |
| **P7 Edge + burn-in** | Cloudflare Tunnel/Access/WAF/PQC; SLO dashboards | DEPLOYMENT_PLAN gates |

Verification is always remote: GitHub Actions matrices (cpu/cuda/hip), APK
build+sign job, API/CLI integration tests, and CI logs as evidence.

---

## 12. Decisions & risks

- **NLP without heavy deps:** stdlib-first, optional model upgrade — keeps CI
  deterministic and CPU-safe; risk = lexical sentiment limits → mitigate with
  profile feedback + optional classifier GGUF.
- **Theme toggle** must not regress the aurora canvas/contrast → token-driven,
  AA-tested both modes.
- **Real streaming** depends on `llama-server` passthrough; if a backend can't
  stream, fall back to chunked but mark `"streaming":"chunked"`.
- **Scope:** P0–P5 deliver the "fully done" APK/API/CLI + connected webapp; P6–P7
  make it DeepSeek-class at the model/edge layer. Sequence P0 first so every
  later phase builds on a truly connected baseline.
