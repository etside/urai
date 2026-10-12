# Model Benchmark Baseline (Phase 1 — measured, not estimated)

Date: 2026-10-05 · Probe: `scripts/hw_baseline.py` (re-run anytime)
Machine: the box in front of us. All numbers below are measured here.

## 1. Hardware (measured 2026-10-05T21:49:49Z)

| Resource | Measurement |
|---|---|
| CPU | Intel Core m3-6Y30 @ 0.90 GHz, 2 cores / 4 threads, max 2.2 GHz |
| CPU FP32 throughput (numpy 512³ matmul proxy) | **~5.8 GFLOPS** |
| RAM total | **3.2 GB** |
| RAM available at probe time | **~0.63 GB** (system under load) |
| Swap | 5.3 GB (3.8 GB free) — swapping kills inference latency |
| GPU / VRAM | **none** |
| Disk free (/) | 67 GB |
| Disk free (project drive x3) | 45 GB |
| Network → huggingface.co | reachable (HTTP 200) |
| Python | 3.14.4, numpy 2.3.5, **no torch/transformers** |

## 2. What this hardware can and cannot do

| Task | Verdict |
|---|---|
| Full pretraining / SFT / DPO from scratch | **infeasible** — no GPU; CPU LoRA on 1B needs ~8–16 GB RAM |
| LoRA fine-tune even 0.5B on CPU | **infeasible** — <1 GB free RAM, would thrash swap for days |
| llama.cpp CPU inference, ≤1B Q4 | **feasible** — ~0.5–0.9 GB RAM, expect ~5–20 tok/s on this CPU |
| llama.cpp inference, 7–9B Q4 | **borderline/infeasible** — needs ~4–6 GB RAM > total 3.2 GB |
| 12–14B local | **no** |
| Distillation data pipeline (generate via API → filter → verify with pytest) | **yes** — this is CPU-light orchestration |
| Eval harness + benchmark suite | **yes** |
| JEV runtime (router/context/memory/tools/verifier) | **yes** — plain Python service |
| GGUF quantization (`llama-quantize`) | **yes** for small models, slow but one-shot |
| Teacher generation via API (OpenRouter/TypeSafe) | **yes** — needs API keys, no local compute |

## 3. Baseline model performance (local) — MEASURED 2026-10-05

llama.cpp built from source (commit `7049ff0`, `GGML_NATIVE=ON`, AVX2) +
Qwen2.5-0.5B-Instruct Q4_K_M (`model/base/`, 463 MB, 630M params).
Raw JSON: `eval/reports/bench-qwen05-q4km.json`.

| Model | pp512 | tg128 | Max RSS | Swap | Status |
|---|---|---|---|---|---|
| Qwen2.5-0.5B-Instruct Q4_K_M, 4 threads, CPU | **28.6 tok/s** | **6.9 tok/s** | 592 MB | 0 | ✅ runs comfortably |

Interactive (`llama-cli`, ctx 1024): prompt ~21–44 tok/s, generation
~6–13 tok/s (warm-cache variance). 150 tokens ≈ 24 s wall.

**Quality smoke test (retry-with-backoff prompt):** output looked
plausible but was BROKEN — `time.sleep` never called, `fn` not a
parameter, truncated mid-function. Verdict: this size class can draft,
never be trusted unverified. Textbook case for verifier-first
distillation (mission §8): beauty ≠ correctness.

## 3b. Second candidate + head-to-head (2026-10-06)

| Model | pp | tg | RSS | Code-smoke (retry task, verifier-scored) |
|---|---|---|---|---|
| Qwen2.5-0.5B-Instruct Q4_K_M (general) | 28.6 | 6.9 | 592 MB | **0.0** — wrong shape (decorator), vacuous tests, truncated repetition |
| Qwen2.5-Coder-0.5B-Instruct Q4_K_M (coding) | 23.2 | 6.35 | 569 MB | **better but flawed** — right signature, real asserts, runnable; backoff wrong (`sleep 2**tries`), swallows to `None`, exec flagged 20 s timeout from oversized sleeps |
| Qwen2.5-Coder-1.5B-Instruct Q4_K_M | — | — | ~1.2 GB est | **EXCLUDED on this box** — bench twice killed by swap pressure (only ~650 MB free); needs a ≥8 GB machine |

Decision (evidence-based, reversible): **active = coder05-fast**.
Same speed/RAM class as the general 0.5B, strictly better code shape on
the Priority-1 workload. 1.5B stays in the registry for GPU/bigger boxes.

## 4. Baseline: current "intelligence" path

| Metric | `jev_review.py` → TypeSafe endpoint |
|---|---|
| Local compute | ~0 (thin HTTP client) |
| Latency | network-bound, timeout 300 s, no streaming |
| Offline capable | no |
| Cost | per-call API cost |
| Quality on our coding tasks | **unmeasured** — needs the real-world benchmark (§17 of mission) before any claim |

## 5. Candidate student shortlist (to benchmark, NOT yet chosen)

Selection criteria: must fit ≤1 GB RAM for THIS box; larger sizes only if a
bigger machine joins. All open-weight, GGUF-available:

- ~0.3–0.5B: SmolLM2-360M, Qwen2.5-0.5B
- ~1–1.5B: SmolLM2-1.7B (tight), Qwen2.5-1.5B (tight, likely needs swap)
- 7–9B class: **only** if a ≥8 GB RAM machine is provided — excluded here until then

Teacher candidates (API, terms permitting): strongest available coding model
for code, strongest reasoning model for reasoning, cheapest adequate model
for general — exact picks deferred to Phase 2 after workload sampling.

## 6. Phase-gate recommendation

1. Do NOT attempt any training run on this machine.
2. Next cheap, high-information step: download ONE ~400 MB Q4 student
   candidate + build llama.cpp, record the first real tok/s row here.
3. In parallel: start Phase 2 dataset prototype (task collection + teacher
   generation via API + pytest verification using the existing game test
   suite as oracle).
4. Decide where weight training will run (cloud GPU / second machine), since
   it cannot run here.

## 7. Final-report fields (all TBD — Phase 1)

BASE STUDENT MODEL: TBD · BEST TEACHER: TBD · DATASET SIZE: 0 ·
TOKENS/SEC: unmeasured · All scores: unmeasured · No "best" claimed.

## Addendum 2026-10-12 — speed flags on this box (llama.cpp b11559, m3 CPU, -t 2)

coder05-fast, pp128/tg64, `llama-bench -o json`:

| flags | pp t/s | tg t/s | note |
|---|---|---|---|
| plain | 22.84 | 8.06 | `eval/reports/bench-coder05-plain.json` |
| `-ctk q8_0 -ctv q8_0 -fa on` | 21.69 | 8.02 | `eval/reports/bench-coder05-kv8fa.json` |

Finding: KV-cache quant + flash-attn do **not** speed up this CPU box
(slight prompt-processing slowdown). They still ship as server defaults
because q8_0 KV **saves RAM** (matters for 3B+ models in 3 GB). Next lever
here: `--spec ngram-mod` (free) and IQ quants — bench before claiming.
