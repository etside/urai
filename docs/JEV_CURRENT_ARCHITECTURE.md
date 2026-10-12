# JEV — Current Architecture (audit, Phase 1)

Date: 2026-10-05 · Project audited: `/home/tjms` (Uradhura / Teen Patti backend)
New project location: `/run/media/tjms/x3` (this repo, `ownai-distill-jev`)

> Nothing below was replaced or modified. This is a read-only audit.

## 1. What "JEV" actually is today

There is **no local model, no runtime, and no router** today. "JEV" refers to
two separate pieces, both of which are thin clients of an **external,
third-party API (TypeSafe "Jev")** — not owned infrastructure:

### 1a. `tools/jev_review.py` — advisory review harness (own code)
- Path: `/home/tjms/tools/jev_review.py` (107 lines)
- What it does: builds a TypeSafe `/v1/systemone` payload from a review
  context + questions file, POSTs to `JEV_URL` (default
  `http://127.0.0.1:8080`), prints/stores the verdict to
  `tools/jev_reviews/<title>.result.json`.
- Contract: `{"model": "jev-latest", "state": ..., "questions": {...}}` →
  answers of type `noul` (probability), `choice`, `score`.
- Flag thresholds: `noul >= 0.65`, `score >= 1.5`.
- Auth: `Authorization: Bearer $JEV_API_KEY` (default `"local-dev"`).
- Design constraint (correct): **advisory only** — must never decide RNG,
  results, state, balances, or settlement. Every flag must be validated
  against BRD/SRS + code before acting.
- Failure mode: fails closed with
  `JEV review FAILED (JEV unavailable, not a code verdict)`.
- This is an **API adapter**, not a runtime. Keep it as-is.

### 1b. `tools/jev-ultrafast/` — third-party browser-agent demo (not own code)
- A clone of `browser-use/jev-ultrafast`: a browser agent with a dynamic
  indexed action space (page → element table → operation + target → execute).
- Loop: `jev_ultrafast/agent.py`; DOM snapshot: `snapshot.js`; browser glue:
  `browser.py`; policy heads: `model.py`; inspector: `demo.py`.
- Hard dependencies: `TYPESAFE_API_KEY` (TypeSafe Jev) + `TEXT_MODEL_API_KEY`
  (OpenRouter, demo uses `inception/mercury-2.5`). **Both are paid APIs.**
  Tests are offline; live examples cost money.
- Relevance to this mission: low. It demonstrates speculative fan-out
  (operation + target in one request) — a pattern worth stealing for our
  router — but it is not a model, not local, and not ours. Do not build on
  it directly.

### 1c. `veripc/backend/agent.py` — aspirational only
- Docstring claims jobs execute "using available models (vLLM/Ollama)", but
  line ~113 reads `# Phase 2: Integrate with vLLM/Ollama for actual model
  inference` — i.e. **not implemented**. No vLLM/Ollama code exists anywhere
  in the repo. Treat as a monitoring/telemetry daemon, not AI infra.

## 2. Local AI infrastructure inventory (all NEGATIVE unless noted)

| Capability | Status |
|---|---|
| llama.cpp integration | **none** — not installed, no bindings, no server |
| Local GGUF models | **none** — zero `.gguf` files on the system |
| Ollama / vLLM / TGI / MLX | **none installed** |
| PyTorch / Transformers / Accelerate / PEFT / TRL | **none** (`import torch` → ModuleNotFoundError) |
| Python ML stack | only `numpy 2.3.5`; system Python 3.14.4 |
| CUDA / GPU / VRAM | **none** (`nvidia-smi` absent) |
| Model routing | **none** |
| Fallback behavior | only `jev_review.py` fail-closed message |
| Context handling / compression / token budgeting | **none** (only raw context string in review harness) |
| Memory system (short-term / project / persistent) | **none** |
| Tool system for models (fs/terminal/git/HTTP) | **none** (repo has dev scripts, no model tool-calling) |
| Coding workflow automation | manual; `tools/claw-code` is docs/parity notes, not wired in |
| Streaming implementation | **none** (`urllib` blocking POST, 300 s timeout) |
| Benchmark scripts (models) | **none** |
| Prompt templates (training) | **none** |
| Datasets (training/SFT/DPO) | **none** |
| Evaluation scripts (models) | **none** (game-backend pytest suite only, unrelated) |
| Quantization tooling | **none** |
| Tokenizer tooling | **none** |

Existing `tests/` (24 files) cover the game backend (engine, wallet,
provider API, staging, RBAC, reliability) — valuable later as
**execution-based verifiers** for code-distillation data (Phase 5/8), but
they are not model evals today.

## 3. Current data flow (the whole "runtime")

```
reviewer → jev_review.py --title --context-file --questions-file
         → POST {model: jev-latest, state, questions} → $JEV_URL/v1/systemone
         → answers {noul|choice|score}
         → flags printed + stored as JSON (advisory)
```

No router, no context manager, no memory, no tools, no verifier, no
self-correction, no streaming, no local fallback. Any "intelligence" lives
behind the external TypeSafe endpoint.

## 4. Implications for the mission

1. **Greenfield runtime.** The JEV Intelligence Runtime (mission §10) must be
   built from scratch. Nothing to preserve except the `jev_review.py`
   advisory contract — keep its CLI + JSON output stable.
2. **No local inference baseline exists.** First tokens/sec numbers must come
   from a fresh llama.cpp + small-GGUF benchmark (see
   `MODEL_BENCHMARK_BASELINE.md`).
3. **No training stack exists.** torch/transformers/TRL/llama.cpp all need
   installing, and local training is infeasible on this box (see baseline).
4. **Do not fight the constraints.** The honest architecture is:
   runtime + data pipeline + eval harness built HERE; weight training done
   where a GPU exists (cloud/loaner/bigger box); artifacts deployed back
   here as GGUF.
