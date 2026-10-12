# Urai v1-lite

Our own high-performance local AI model + intelligence runtime.
Mission: the best model we can realistically **own, run, distill, evaluate and
continuously improve** — NOT a giant foundation model from scratch.

- `urai chat` streams the local student · `urai agent` runs plan/tool/verify ·
  `urai api` serves OpenAI-compatible endpoints · `urai gpu` goes CUDA-aware on
  GPU boxes · `urai teacher` checks the external teacher backend.

## Status: runtime live, first distilled-data pipeline proven

- Active model: **Qwen2.5-Coder-0.5B Q4_K_M** (`coder05-fast`, 23.2 tok/s
  prompt, ~6.35 tok/s gen, ~569 MB RAM)
- Runner-up: Qwen2.5-0.5B Q4_K_M (`qwen05-fast`, 28.6/6.9 tok/s) — lost the
  code smoke test (wrong shape, vacuous tests, score 0.0)
- Primary candidate: Qwen2.5-Coder-1.5B Q4_K_M (`coder15-primary`) — bench
  never completed on the 3 GB dev box (killed by swap pressure); needs a
  bigger machine
- Distill v0.2: 228 generated tasks → **41 kept** (96 below threshold,
  91 dupes) across code-repair (20), code-generation (8), api-engineering (5),
  security (5), reasoning (3)

## Quickstart

Requirements: Python 3.12+, `cmake`, a C++ compiler, ~2 GB free disk
(per 0.5B GGUF). GPU optional (CPU works, CUDA auto-used when present).

```bash
# 1. Fetch a base student weight (public Qwen GGUFs)
./bin/urai model download coder05-fast
#  - qwen05-fast / coder05-fast / coder15-primary (see model/registry.json)

# 2. Build the llama.cpp runner (first time only, takes a while on small boxes)
git clone --depth 1 https://github.com/ggerganov/llama.cpp.git third_party/llama.cpp
cmake -S third_party/llama.cpp -B third_party/llama.cpp/build \
  -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON
cmake --build third_party/llama.cpp/build -j$(nproc) \
  --target llama-cli llama-bench llama-quantize llama-server

# 3. Start the local model server (GPU-aware, :8080) and use it
./bin/urai serve start
./bin/urai chat                       # streaming REPL (empty line quits)
./bin/urai agent "Write clamp(v,lo,hi) with a test"   # plan/tool/verify loop
./bin/urai api                        # OpenAI-compatible API on :8777
```

Add `./bin` to `PATH` to call `urai` from anywhere.

## CLI reference

```
urai chat                          interactive REPL, streams tokens
urai ask "question"                 one-shot answer
urai agent "multi-step task"        plan/tool/verify loop
urai model list                     registry + availability + bench numbers
urai model download <id>            fetch GGUF from HF into model/base
urai model use <id>                 set active model (restarts server)
urai model bench [--id ID]          llama-bench row for a model
urai serve start|stop|status        llama-server lifecycle (GPU-aware)
urai gpu                            detect GPU + offload policy
urai teacher status|test            external teacher backend (env) check
urai see <image> [question]          ask about a picture (vision model)
urai imagine <prompt> [-o out.png]   text-to-image (stable-diffusion.cpp)
urai evaluate "task" --expect a,b   scored check via running server
urai api [--port 8777]              start Urai OpenAI-compatible API
                                    (/v1/chat/completions, /v1/images/generations, ...)
urai version                        runtime version + active model
```

## Models

| id | kind | params | role | status |
|---|---|---|---|---|
| `qwen05-fast` | chat | 0.5B Q4_K_M | fast | benched 28.6/6.9 tok/s |
| `coder05-fast` | chat | 0.5B Q4_K_M | fast-coding, **active** | benched 23.2/6.35 tok/s |
| `coder15-primary` | chat | 1.5B Q4_K_M | primary | needs bigger box |
| `qwen25vl-3b` | vision | 3B Q4_K_M + Q8_0 mmproj | see pictures | `urai model download qwen25vl-3b` |
| `sd-turbo` | generate | SD-Turbo fp16 | make pictures | `urai model download sd-turbo` |

Vision: [Qwen2.5-VL-3B GGUF](https://huggingface.co/ggml-org/Qwen2.5-VL-3B-Instruct-GGUF)
via [llama.cpp](https://github.com/ggml-org/llama.cpp).
Generation: [SD-Turbo](https://huggingface.co/stabilityai/sd-turbo) via
[stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp).
Details + remaining work: [docs/VISION_UPGRADE.md](docs/VISION_UPGRADE.md).

Teacher (distillation source) is any OpenAI-compatible endpoint:

```bash
export TEACHER_BASE_URL="https://opencode.ai/zen/v1"   # or OpenRouter, etc.
export TEACHER_API_KEY="..."
export TEACHER_MODEL="opencode/muse-spark-1.3-contributor-free"
./bin/urai teacher test
```

## Distillation pipeline

```
scripts/distill/generate_tasks.py  -> data/raw_tasks/expanded   (task gen)
scripts/distill/teacher_client.py  -> data/teacher_out          (teacher answers)
scripts/distill/verifier.py        -> exec + judge checks       (exec_check, judge)
scripts/distill/filter.py          -> data/verified/*.jsonl     (keep/drop + why)
scripts/distill/run_distill.py     -> one-shot orchestration + report
scripts/hw_baseline.py             -> machine capability record
```

```bash
python3 scripts/hw_baseline.py --matmul-n 512 --matmul-iters 5
python3 scripts/distill/generate_tasks.py --out data/raw_tasks/expanded --seed 7
python3 scripts/distill/run_distill.py --tasks data/raw_tasks/expanded \
  --out data/verified/distill-v0.3.jsonl \
  --report eval/reports/distill-v0.3-summary.json --exec --judge
```

`data/raw_tasks/sample_tasks.jsonl` is the checked-in seed set. Full
`teacher_out` / `verified` sets regenerate via the commands above.

## Layout

```
jev/      runtime package (router/context/tools/agent/server/backends/registry)
bin/      urai + jev launchers
docs/     architecture, baselines, dataset pipeline
scripts/  hw baseline + distillation pipeline (teacher → verifier → filter)
data/     raw_tasks seeds (generated/verified sets are reproducible artifacts)
eval/     benchmarks + reports (all measured, nothing invented)
model/    registry.json + GGUF slots (binaries live here, NOT in git)
```

## Headline finding

The dev box (2-core Intel m3, ~3.2 GB RAM, no GPU) runs the runtime, data
pipeline and eval harness — but cannot train weights or bench 1.5B models.
Training/benching needs a GPU elsewhere; artifacts come back here as GGUF and
slot into `model/registry.json` via `urai model download`.

## Recovery note

This repo was reconstructed from the `ownai-distill-jev` build session after
the original `x3` work disk became unavailable. Source, docs, scripts, seed
data and registry are byte-faithful to the session's final state
(`urai v1-lite`, active `coder05-fast`). Regenerable artifacts (GGUF weights,
`third_party/llama.cpp` build, `teacher_out`/`verified` sets, bench logs)
are intentionally excluded — reproduce them with the commands above.
