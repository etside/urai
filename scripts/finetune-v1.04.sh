#!/usr/bin/env bash
# finetune-v1.04.sh — Urai v1.04 fine-tune orchestration pipeline
# Usage: bash scripts/finetune-v1.04.sh [--run]
#
# Without --run: prints a dry-run summary of steps and exits 0.
# With    --run: runs the full fine-tune pipeline.
set -euo pipefail

echo "=========================================="
echo "  Urai v1.04 Fine-tune Pipeline"
echo "=========================================="

# --------------------------------------------------------------------------
# Prerequisite checks
# --------------------------------------------------------------------------

check_python() {
  local PY
  PY=$(python3 --version 2>/dev/null | awk '{print $2}') || true
  if [ -z "$PY" ]; then
    echo "ERROR: python3 not found. Install Python 3.10+."
    exit 1
  fi
  local MAJOR MINOR
  MAJOR=$(echo "$PY" | cut -d. -f1)
  MINOR=$(echo "$PY" | cut -d. -f2)
  if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 10 ]; }; then
    echo "ERROR: Python 3.10+ required. Found $PY."
    exit 1
  fi
  echo "==> Python $PY OK"
}

check_pip() {
  if ! command -v pip &>/dev/null && ! command -v pip3 &>/dev/null; then
    echo "ERROR: pip not found."
    exit 1
  fi
  echo "==> pip OK"
}

check_disk() {
  local FREE_GB
  FREE_GB=$(df -BG . | awk 'NR==2{gsub(/G/,"",$4); print $4}')
  if [ "$FREE_GB" -lt 15 ]; then
    echo "ERROR: Need at least 15 GB free disk. Found ${FREE_GB}GB."
    exit 1
  fi
  echo "==> Disk: ${FREE_GB}GB free OK"
}

detect_gpu() {
  # Returns extra flags for the train command if NVIDIA GPU is available
  if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null 2>&1; then
    local GPU_NAME
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo 'unknown')
    echo "==> GPU detected: $GPU_NAME"
    echo "    Adding --mixed_precision bf16 --use_deepspeed flags"
    GPU_FLAGS="--mixed_precision bf16 --use_deepspeed"
  else
    echo "==> No NVIDIA GPU detected — running on CPU (slow)"
    GPU_FLAGS=""
  fi
}

# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------

RUN_MODE=false
for arg in "$@"; do
  case "$arg" in
    --run) RUN_MODE=true ;;
  esac
done

# --------------------------------------------------------------------------
# Dry-run summary
# --------------------------------------------------------------------------

if [ "$RUN_MODE" = false ]; then
  echo ""
  echo "DRY RUN — steps that would execute with --run:"
  echo ""
  echo "  1. pip install -e \".[train]\"  (installs training deps)"
  echo "  2. mkdir -p data/finetune/v1.04/"
  echo "  3. python scripts/distill/prepare_data.py --output data/finetune/v1.04/ \\"
  echo "         --tasks vibe-code,llm-tools,agent,memory,mcp"
  echo "  4. python scripts/train_pipeline.py --config configs/distill_qwen3_4b.yaml \\"
  echo "         --output-name urai-v1.04 \\"
  echo "         --tasks vibe-code,llm-tools,agent,memory,mcp \\"
  echo "         [+ GPU flags if NVIDIA detected]"
  echo "  5. python scripts/distill/export_gguf.py \\"
  echo "         --input model/base/urai-v1.04.bin \\"
  echo "         --output model/base/urai-v1.04.gguf \\"
  echo "         --quant Q4_K_M"
  echo ""
  echo "Capabilities trained: vibe-code, llm-tools, agent, memory, mcp"
  echo "Output GGUF: model/base/urai-v1.04.gguf"
  echo ""
  echo "Re-run with --run to execute."
  exit 0
fi

# --------------------------------------------------------------------------
# Run mode
# --------------------------------------------------------------------------

check_python
check_pip
check_disk
detect_gpu

# Resolve repo root relative to this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

# Step 1 — install training deps
echo ""
echo "==> Step 1/5: Installing training dependencies..."
pip install -e ".[train]"

# Step 2 — create data directory
echo ""
echo "==> Step 2/5: Creating training data directory..."
mkdir -p data/finetune/v1.04/

# Step 3 — prepare training data
echo ""
echo "==> Step 3/5: Preparing training data..."
python scripts/distill/prepare_data.py \
  --output data/finetune/v1.04/ \
  --tasks vibe-code,llm-tools,agent,memory,mcp

# Step 4 — fine-tune
echo ""
echo "==> Step 4/5: Running fine-tune (this will take a while)..."
# shellcheck disable=SC2086
python scripts/train_pipeline.py \
  --config configs/distill_qwen3_4b.yaml \
  --output-name urai-v1.04 \
  --tasks vibe-code,llm-tools,agent,memory,mcp \
  $GPU_FLAGS

# Step 5 — export GGUF
echo ""
echo "==> Step 5/5: Exporting GGUF..."
python scripts/distill/export_gguf.py \
  --input model/base/urai-v1.04.bin \
  --output model/base/urai-v1.04.gguf \
  --quant Q4_K_M

echo ""
echo "=========================================="
echo "  Fine-tune complete."
echo "  GGUF at model/base/urai-v1.04.gguf"
echo "=========================================="
echo "  Run: bash scripts/setup-ollama.sh to register urai:v1.04 in Ollama"
echo "=========================================="
