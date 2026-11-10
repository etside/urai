#!/usr/bin/env bash
# Urai Option A: Distillation Pipeline (STUB — documentation only by default)
set -euo pipefail

RUN_PIPELINE=0
for arg in "$@"; do
  if [ "$arg" = "--run" ]; then RUN_PIPELINE=1; fi
done

echo "============================================="
echo " Option A: Urai Distillation Pipeline (Advanced)"
echo "============================================="
echo ""

# --- Prerequisites check ---
echo "--- Prerequisites ---"
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo "")
if [ -z "$PY" ]; then
  echo "MISSING: Python 3.10+ required"
else
  PY_VER=$($PY -c 'import sys; print("%d%02d" % sys.version_info[:2])')
  if [ "$PY_VER" -ge 310 ]; then
    echo "OK: $($PY --version)"
  else
    echo "WARNING: Python 3.10+ recommended. Found: $($PY --version)"
  fi
fi

if command -v pip >/dev/null 2>&1; then
  echo "OK: pip found"
else
  echo "MISSING: pip required"
fi

echo "Disk: ~20GB free space required for training data and checkpoints."
df -h / || true

if nvidia-smi >/dev/null 2>&1; then
  echo "GPU: NVIDIA detected (16GB+ VRAM recommended for distillation)"
  nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || true
else
  echo "WARNING: No NVIDIA GPU detected. Distillation without GPU will be extremely slow."
fi
echo ""

# --- Pipeline steps (documentation) ---
echo "--- Distillation Pipeline Steps ---"
echo ""
echo "Step 1: Install training dependencies"
echo "  pip install -e \".[train]\""
echo ""
echo "Step 2: Prepare training data"
echo "  python scripts/distill/prepare_data.py"
echo ""
echo "Step 3: Run distillation"
echo "  python scripts/train_pipeline.py --config configs/distill_qwen3_4b.yaml"
echo ""
echo "Step 4: Convert to GGUF"
echo "  python scripts/distill/export_gguf.py --output model/base/urai-custom.gguf"
echo ""
echo "Step 5: Register and use the custom model"
echo "  - Update model/registry.json: set \"active\" to your new GGUF filename"
echo "  - Then run: bash scripts/setup-ollama.sh"
echo ""

# --- Warning ---
echo "============================================="
echo " WARNING"
echo "============================================="
echo "This pipeline takes 2-8 hours and requires significant GPU resources."
echo "Use Option C (scripts/setup-ollama.sh) or Option B (scripts/setup-optionb.sh)"
echo "for immediate local inference without training."
echo ""

if [ "$RUN_PIPELINE" -eq 0 ]; then
  echo "This was a dry-run (documentation only). Pass --run to actually execute the pipeline."
  echo "Example: bash scripts/setup-optiona.sh --run"
  exit 0
fi

# --- Actual execution (only if --run passed) ---
echo "--run flag detected. Starting distillation pipeline..."
echo ""

echo "[Step 1] Installing training dependencies..."
pip install -e ".[train]"

echo "[Step 2] Preparing training data..."
python scripts/distill/prepare_data.py

echo "[Step 3] Running distillation..."
python scripts/train_pipeline.py --config configs/distill_qwen3_4b.yaml

echo "[Step 4] Converting to GGUF..."
python scripts/distill/export_gguf.py --output model/base/urai-custom.gguf

echo "[Step 5] Done. Update model/registry.json to point to model/base/urai-custom.gguf, then run:"
echo "  bash scripts/setup-ollama.sh"
