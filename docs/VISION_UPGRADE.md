# Urai vision + generation upgrade (v1-lite → v1.1)

Goal: Urai works like a normal LLM (roles, OpenAI `/v1/*` API) and gains
two new senses — **See** (analyze pictures) and **Imagine** (generate
pictures) — using only open-source models + runners.

## What was missing

| Gap | Fix |
|---|---|
| `/chat` space-joined all messages (roles/system lost) | roles preserved; `/v1/chat/completions` added |
| No OpenAI-compatible paths (only `/chat`, `/generate`) | `/v1/chat/completions`, `/v1/models`, `/v1/images/generations` |
| No image input anywhere | `urai see`, `POST /see`, vision parts passthrough |
| No image output anywhere | `urai imagine`, `POST /imagine`, `POST /v1/images/generations` |
| Registry knew only text GGUFs | `kind: chat\|vision\|generate` + multi-file download |
| `serve start` had no `--mmproj` | auto-passed for `kind=vision` models |

## Open-source references used

- **Runner (vision + chat):** llama.cpp `llama-server` multimodal (mtmd)
  — https://github.com/ggml-org/llama.cpp
- **Vision model:** Qwen2.5-VL-3B-Instruct Q4_K_M + Q8_0 mmproj
  (Apache-2.0) —
  https://huggingface.co/ggml-org/Qwen2.5-VL-3B-Instruct-GGUF
  (`Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf`,
  `mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf`)
- **Runner (generation):** stable-diffusion.cpp `sd` CLI (MIT, CPU-ok) —
  https://github.com/leejet/stable-diffusion.cpp
- **Generation checkpoint:** SD-Turbo (CreativeML Open RAIL++-M, 1–4 steps,
  512px) — https://huggingface.co/stabilityai/sd-turbo
  (`sd_turbo.safetensors`, ~3.4 GB fp16)
- Alternatives (same integration shape, bigger boxes): Llama-3.2-Vision,
  Mistral-Small-3.1, Gemma-3, MiniCPM-V (vision); SDXL-Turbo, FLUX.1-schnell
  (generation).

## Setup

```bash
# vision (∼2.6 GB: 3B Q4_K_M + Q8_0 projector)
./bin/urai model download qwen25vl-3b
./bin/urai model use qwen25vl-3b
./bin/urai serve start
./bin/urai see photo.jpg "What is in this picture?"

# generation: build runner once, fetch checkpoint (~3.4 GB)
git clone --depth 1 https://github.com/leejet/stable-diffusion.cpp.git \
    third_party/stable-diffusion.cpp
cmake -S third_party/stable-diffusion.cpp -B third_party/stable-diffusion.cpp/build \
    -DCMAKE_BUILD_TYPE=Release -DSD_CUBLAS=OFF
cmake --build third_party/stable-diffusion.cpp/build -j$(nproc) --target sd
./bin/urai model download sd-turbo
./bin/urai imagine "a robot reading a book" -o out.png
```

API equivalents: `POST /see {image, question}`, `POST /imagine {prompt, ...}`,
`POST /v1/chat/completions` with `image_url` parts (data: or http(s) URLs),
`POST /v1/images/generations {prompt}`.

## Remaining work (honest list)

1. **Weights not in git** (GitHub 100 MB/file cap): fetch via the commands
   above; `model/registry.json` pins exact URLs.
2. **Vision quality bench**: add a small labeled image set + `see` accuracy
   smoke test (mirrors `scripts/distill/verifier.py` for text).
3. **Generation eval**: fixed prompt/seed set, record time + output hashes in
   `eval/reports/` (see `MODEL_BENCHMARK_BASELINE.md` conventions).
4. **VRAM policy**: `gpu.offload_policy()` covers llama; SD-CUDA (`-DSD_CUDA=ON`)
   path untested — needs a CUDA box.
5. **Embeddings**: no `/v1/embeddings` yet (llama-server can serve one;
   wire through when retrieval is needed).
6. **Agent tool-use**: `agent.py` plans/verifies but never calls `tools.py`
   (`tool_calls += 0`); wire `see`/`imagine` as agent tools next.
