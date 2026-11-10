# Urai Local Inference Guide

This guide covers all three local inference options for Urai, from fastest to most involved.

---

## 1. Quick Hardware Check

Run the audit script first to get a recommendation for your hardware:

```bash
bash scripts/audit-hardware.sh
```

The script detects CPU, RAM, NVIDIA/AMD GPU, Apple Silicon, disk space, and whether you are on an AWS EC2 instance, then prints a one-line recommendation.

---

## 2. Option C — Ollama (Fastest)

**Best for:** Most machines with 8 GB+ RAM. Requires [Ollama](https://ollama.com) installed.

```bash
bash scripts/setup-ollama.sh
ollama run urai
```

- Downloads `Qwen3-4B-Q4_K_M.gguf` (~2.5 GB) from Hugging Face on first run.
- Creates a custom Ollama model named `urai` using the repo Modelfile.
- Interactive chat in the terminal, or use Ollama's OpenAI-compatible API at `http://localhost:11434`.

See `docs/LOCAL_OLLAMA.md` for full details.

---

## 3. Option B — llama.cpp Direct (Fallback)

**Best for:** Machines without Ollama, AWS EC2 instances, or when you need the raw OpenAI-compatible API.

```bash
bash scripts/setup-optionb.sh
```

- Starts `llama-server` on `http://localhost:8777`.
- OpenAI-compatible REST API (`/v1/chat/completions`).
- Auto-detects NVIDIA GPU and adds `-ngl 35` for GPU layer offload.

Test it:

```bash
curl -s http://localhost:8777/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model": "urai", "messages": [{"role": "user", "content": "Hello!"}]}' | jq .
```

Stop it:

```bash
bash scripts/setup-optionb.sh --stop
```

**Prerequisite:** `llama-server` must be on your PATH or built via:

```bash
pip install -e ".[local]"
# or
cd third_party/llama.cpp && mkdir build && cd build && cmake .. && cmake --build . -j4
```

---

## 4. Option A — Distillation Pipeline (Advanced / Stub)

**Best for:** Researchers who want to train a custom student GGUF. Not needed for local inference.

```bash
bash scripts/setup-optiona.sh        # dry-run: prints steps only
bash scripts/setup-optiona.sh --run  # actually runs the pipeline
```

> **Warning:** Takes 2–8 hours, requires GPU with 16 GB+ VRAM and ~20 GB disk. Use Option C or B for immediate inference.

---

## 5. AWS Setup Notes

- The audit script auto-detects EC2 instance type via the instance metadata service (`169.254.169.254`).
- For GPU instances (p3, p4, g4, g5), Option B with `-ngl 35` or Option C are both recommended.
- Set `URAI_DIR` to an EBS mount path with enough space (the GGUF is ~2.5 GB):

```bash
export URAI_DIR=/mnt/urai-data
bash scripts/setup-optionb.sh
```

---

## 6. GPU Offload Notes

- Both Ollama (Option C) and llama.cpp (Option B) support NVIDIA/AMD GPU offload via `-ngl`.
- The audit script reads VRAM and prints the right recommendation.
- `scripts/setup-optionb.sh` auto-adds `-ngl 35` when `nvidia-smi` is available.
- For AMD ROCm, install the ROCm build of llama.cpp and Ollama's ROCm variant.

---

## Option Comparison

| Option | Tool | Speed | Setup effort | API |
|--------|------|-------|--------------|-----|
| C | Ollama | Fast | Minimal | `localhost:11434` |
| B | llama.cpp | Fast | Moderate | `localhost:8777` |
| A | Training pipeline | N/A | High | — |

---

*Active model: Qwen3-4B Q4\K\_M — declared in `model/registry.json`.*
