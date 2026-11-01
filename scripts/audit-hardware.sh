#!/usr/bin/env bash
# Urai Hardware Audit — detects CPU, RAM, GPU, AWS, disk and prints a recommendation.
set -euo pipefail

echo "============================================="
echo " Urai Hardware Audit"
echo "============================================="
echo ""

# --- CPU ---
echo "--- CPU ---"
lscpu | grep -E "Model name|Socket|Core|Thread|MHz" || true
echo ""

# --- RAM ---
echo "--- RAM ---"
free -h || true
echo ""

# --- GPU ---
echo "--- GPU ---"
NVIDIA_FOUND=0
NVIDIA_VRAM=0
AMD_FOUND=0
AWS_INSTANCE=""

if nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null; then
  NVIDIA_FOUND=1
  # Extract VRAM in MiB from the first GPU
  VRAM_LINE=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader 2>/dev/null | head -1 || echo "0 MiB")
  NVIDIA_VRAM=$(echo "$VRAM_LINE" | grep -oE '[0-9]+' | head -1 || echo "0")
else
  echo "NVIDIA: not found or nvidia-smi not available" || true
fi

if rocm-smi --showproductname 2>/dev/null; then
  AMD_FOUND=1
else
  echo "AMD ROCm: not found or rocm-smi not available" || true
fi

system_profiler SPDisplaysDataType 2>/dev/null | grep -E "Chipset|VRAM" || true
lspci 2>/dev/null | grep -i vga || true
echo ""

# --- AWS detection ---
echo "--- AWS ---"
AWS_INSTANCE=$(curl -s --connect-timeout 1 http://169.254.169.254/latest/meta-data/instance-type 2>/dev/null || echo "")
if [ -n "$AWS_INSTANCE" ]; then
  echo "AWS EC2 instance type: $AWS_INSTANCE"
else
  echo "not AWS (or metadata service unreachable)"
fi
echo ""

# --- Disk ---
echo "--- Disk ---"
df -h / || true
URAI_MODEL_DIR="${URAI_DIR:-$HOME/.local/share/urai}/model/base"
echo "Model dir: $URAI_MODEL_DIR"
if [ -d "$URAI_MODEL_DIR" ]; then
  df -h "$URAI_MODEL_DIR" || true
else
  echo "Model dir does not exist yet."
fi
echo ""

# --- Recommendation ---
echo "--- Recommendation ---"

# AWS GPU instance families: p3, p4, g4, g5
if echo "$AWS_INSTANCE" | grep -qE '^(p3|p4|g4|g5)'; then
  echo "Recommendation: AWS GPU instance detected. Use Option B (llama.cpp) or Option C (Ollama). Run: bash scripts/setup-optionb.sh"
elif [ -n "$AWS_INSTANCE" ]; then
  echo "Recommendation: AWS CPU instance. Use Option B with quantized model. Run: bash scripts/setup-optionb.sh"
elif [ "$NVIDIA_FOUND" -eq 1 ]; then
  if [ "$NVIDIA_VRAM" -ge 8192 ]; then
    echo "Recommendation: Use Ollama with GPU (Option C). Run: bash scripts/setup-ollama.sh"
  else
    echo "Recommendation: Use Ollama with partial GPU offload (Option C). Run: bash scripts/setup-ollama.sh"
  fi
elif [ "$AMD_FOUND" -eq 1 ]; then
  echo "Recommendation: Use Ollama with partial GPU offload (Option C). Run: bash scripts/setup-ollama.sh"
else
  echo "Recommendation: CPU-only detected. Option C (Ollama) or Option B (llama.cpp) both work. ~2-4 tokens/sec expected."
fi

echo ""
echo "============================================="
echo " Audit complete."
echo "============================================="
