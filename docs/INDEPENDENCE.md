# Urai independence roadmap — from Qwen-dependent to Qwen-free

Goal: Urai answers from **its own weights**, Qwen kept only as a teacher
until the student surpasses it on Urai's own benchmarks. No step breaks
serving; each stage is gated by measured scores, never by hope.

## Stage 0 — Behavior distillation (LIVE NOW)

Every landed distill chunk auto-promotes verified completions into
`data/prompts/fewshots.jsonl` (`scripts/distill/promote_chunk.py`, hooked
into `run_free_grind.sh`). The agent injects top-matching solved examples
(`jev/fewshots.py`) for level ≥ 1 tasks. Effect: each chunk immediately
improves answers with **zero retraining, zero downtime**.

## Stage 1 — Dataset scale (IN PROGRESS)

`data/verified/distill-now.jsonl` grows every grind + every weekly
self-improve run. Promotion gate: bench math/code must not regress
(`eval/reports/regression-*.json`, advisory). Target: ≥2,000 verified
examples with think traces before Stage 2.

## Stage 2 — LoRA fine-tune (three routes, pick one)

`scripts/train/lora_urai.py` + `urai-train.yml` (dispatch): LoRA on the
Qwen3-4B base with the verified set, eval-gated (bench must improve or the
run is discarded).

Route A — free Kaggle T4 (recommended, $0): new Notebook → GPU T4 x2 →
`!pip install torch transformers peft trl datasets accelerate` → upload
`data/verified/<tag>.jsonl` as an input dataset → run this script
(it auto-uses CUDA) → download `adapters/<tag>/` → send the folder back
for GGUF export. ~30 free GPU-hours/week is enough for the full set.

Route B — this droplet, capped CPU demo: add `--allow-cpu` (<=300 examples,
r=8, 1 epoch, hours of runtime, demonstration-grade adapter only). Proves
the pipeline end-to-end; does not replace GPU training.

Route C — commissioned GPU box / Modal / RunPod: full run, then Stage 3.

## Stage 3 — GGUF export + shadow serve

Export LoRA-merged model to GGUF (`scripts/train/export_gguf.sh`), serve it
as `urai-student` on a second llama-server port, route 10% of traffic,
compare win-rate vs Qwen3-4B for a week. Promote on measured wins only.

## Stage 4 — Qwen-free

`urai model use urai-student`. Qwen remains a *teacher backend* for future
grinds until the student beats it 3 benches running — then teacher keys can
lapse and Urai stands alone.

## What "not depend on Qwen" honestly requires

Weights, not prompts. Stages 0–1 squeeze the teacher's knowledge into
behavior; only Stage 2+ moves it into Urai-owned weights. The CPU path
exists and is honest about being demo-grade — anyone promising a
competitive CPU-trained 4B model in an afternoon is selling something.
