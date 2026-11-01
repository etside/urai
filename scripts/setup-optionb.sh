#!/usr/bin/env bash
# Urai Option B: llama.cpp direct runner (no Ollama required)
set -euo pipefail

STOP=0
for arg in "$@"; do
  if [ "$arg" = "--stop" ]; then STOP=1; fi
done

if [ "$STOP" -eq 1 ]; then
  echo "Stopping llama-server on port 8777..."
  pkill -f 'llama-server.*8777' || echo "No llama-server process found on port 8777."
  exit 0
fi

echo "============================================="
echo " Urai Option B: llama.cpp Direct Runner"
echo "============================================="
echo ""

# --- Check Python 3.8+ ---
echo "[1/6] Checking Python 3.8+..."
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo "")
if [ -z "$PY" ]; then
  echo "ERROR: Python 3 not found. Install Python 3.8+ and retry."
  exit 1
fi
PY_VER=$($PY -c 'import sys; print("%d%02d" % sys.version_info[:2])')
if [ "$PY_VER" -lt 308 ]; then
  echo "ERROR: Python 3.8+ required. Found: $($PY --version)"
  exit 1
fi
echo "Python OK: $($PY --version)"
echo ""

# --- URAI_DIR ---
echo "[2/6] Resolving URAI_DIR..."
URAI_DIR="${URAI_DIR:-$HOME/.local/share/urai}"
echo "URAI_DIR: $URAI_DIR"
GGUF_PATH="$URAI_DIR/model/base/Qwen3-4B-Q4_K_M.gguf"
mkdir -p "$(dirname "$GGUF_PATH")"
echo ""

# --- Download GGUF if missing ---
echo "[3/6] Checking GGUF..."
if [ ! -f "$GGUF_PATH" ]; then
  echo "GGUF not found at $GGUF_PATH. Downloading..."
  if command -v urai >/dev/null 2>&1; then
    urai model download qwen3-4b || true
  fi
  if [ ! -f "$GGUF_PATH" ]; then
    echo "Falling back to direct download via curl..."
    GGUF_URL="https://huggingface.co/ggml-org/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf"
    curl -L --progress-bar -o "$GGUF_PATH" "$GGUF_URL"
  fi
fi
echo "GGUF found: $GGUF_PATH"
echo ""

# --- Find llama-server ---
echo "[4/6] Locating llama-server..."
LLAMA_SERVER=""
if command -v llama-server >/dev/null 2>&1; then
  LLAMA_SERVER=$(which llama-server)
elif [ -f "$URAI_DIR/../third_party/llama.cpp/build/bin/llama-server" ]; then
  LLAMA_SERVER="$URAI_DIR/../third_party/llama.cpp/build/bin/llama-server"
elif [ -f "./third_party/llama.cpp/build/bin/llama-server" ]; then
  LLAMA_SERVER="./third_party/llama.cpp/build/bin/llama-server"
fi

if [ -z "$LLAMA_SERVER" ]; then
  echo "ERROR: llama-server binary not found."
  echo ""
  echo "To install:"
  echo "  Option 1 (via pip):  pip install -e \".[local]\"  (builds llama.cpp automatically)"
  echo "  Option 2 (via cmake): cd third_party/llama.cpp && mkdir build && cd build && cmake .. && cmake --build . --config Release -j4"
  exit 1
fi
echo "llama-server: $LLAMA_SERVER"
echo ""

# --- GPU flag detection ---
echo "[5/6] Detecting GPU for layer offload..."
GPU_FLAGS=""
if nvidia-smi >/dev/null 2>&1; then
  echo "NVIDIA GPU detected — enabling -ngl 35"
  GPU_FLAGS="-ngl 35"
else
  echo "No NVIDIA GPU detected — CPU-only mode"
fi
echo ""

# --- Launch llama-server ---
echo "[6/6] Launching llama-server..."
echo "Command: $LLAMA_SERVER -m $GGUF_PATH -c 4096 --host 0.0.0.0 --port 8777 $GPU_FLAGS"
# shellcheck disable=SC2086
"$LLAMA_SERVER" -m "$GGUF_PATH" -c 4096 --host 0.0.0.0 --port 8777 $GPU_FLAGS &
SERVER_PID=$!
echo "llama-server PID: $SERVER_PID"
echo ""

echo "Waiting for server to start..."
sleep 3

if curl -s http://localhost:8777/health >/dev/null 2>&1; then
  echo "Option B running at http://localhost:8777 — OpenAI-compatible API"
else
  echo "WARNING: Server may still be starting. Check: curl -s http://localhost:8777/health"
fi

echo ""
echo "--- Test with ---"
echo "curl -s http://localhost:8777/v1/chat/completions \\"
echo "  -H 'Content-Type: application/json' \\"
echo "  -d '{\"model\": \"urai\", \"messages\": [{\"role\": \"user\", \"content\": \"Hello!\"}]}' | jq ."
echo ""
echo "To stop: bash scripts/setup-optionb.sh --stop"
