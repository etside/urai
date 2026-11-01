# Running Urai Locally with Ollama (Option C)

This is the fastest path to a working local Urai model — no training, no
llama.cpp build, no Python environment required. It uses the existing
Qwen3-4B Q4_K_M GGUF and Ollama's standard model-management infrastructure.

## Why this is the fastest path

- Ollama handles all model loading, quantisation, and serving.
- The repo already declares the active GGUF and its ChatML template in
  `model/registry.json`.
- No distillation or fine-tuning is involved (Option A is skipped).
- No llama.cpp build is needed (Option B is the fallback, not the default).

## Prerequisites

- [Ollama](https://ollama.com/download) installed and in your `$PATH`
- ~3 GB free disk space (GGUF is ~2.3 GB)
- Linux or macOS

## Quick start

```bash
git clone https://github.com/etside/urai.git && cd urai
bash scripts/setup-ollama.sh
ollama run urai
```

That's it. The script downloads the GGUF if needed, builds the Ollama model,
and prints the run command.

## What the script does

1. Checks that Ollama is installed.
2. Determines `URAI_DIR` (defaults to `~/.local/share/urai`; override with the
   `URAI_DIR` environment variable).
3. Downloads the GGUF to `$URAI_DIR/model/base/Qwen3-4B-Q4_K_M.gguf` if not
   already present — via the `urai` CLI if available, otherwise `curl`/`wget`.
4. Resolves the template `Modelfile` (replacing the path placeholder with the
   real GGUF path) and writes it to `/tmp/urai_Modelfile`.
5. Runs `ollama create urai -f /tmp/urai_Modelfile`.
6. Prints success and usage instructions.

## Using the model

```bash
# Interactive chat
ollama run urai

# Single prompt
ollama run urai "Explain quantum entanglement in one sentence."

# REST API (Ollama must be running: ollama serve)
curl http://localhost:11434/api/generate \
  -d '{"model":"urai","prompt":"Hello!","stream":false}'
```

## Active model details

| Field | Value |
|---|---|
| Model name | Qwen3-4B Q4\_K\_M |
| Format | GGUF |
| Size | ~2.3 GB |
| Template | ChatML (`<\|im_start\|>` / `<\|im_end\|>`) |
| Context window | 4096 tokens (configurable in Modelfile) |
| HF source | `ggml-org/Qwen3-4B-GGUF` |

## Option C vs full Urai runtime

| | Option C (this doc) | Full Urai runtime |
|---|---|---|
| Setup | `bash scripts/setup-ollama.sh` | `pip install -e ".[local]"` + `urai serve` |
| Inference | Ollama | llama.cpp (via Urai server) |
| Agent harness | ✗ | ✓ |
| Skills / tools | ✗ | ✓ |
| API server | Ollama (`localhost:11434`) | Urai (`localhost:8777`) |
| Use case | Fast local chat / prototyping | Full Urai agent experience |

Option C is bare inference — you get the model, nothing else. If you need the
full agent harness, skills, and the Urai API, use the full runtime instead.

## Option B fallback (no Ollama)

If Ollama is not available, the repo ships a llama.cpp-based runner:

```bash
pip install -e ".[local]"
urai model download qwen3-4b
urai serve
```

This starts the Urai server at `http://localhost:8777`. See
[docs/CLI.md](CLI.md) for full CLI reference.
