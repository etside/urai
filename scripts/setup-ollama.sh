#!/usr/bin/env bash
# setup-ollama.sh — Create a local Urai model in Ollama (Option C)
# Usage: bash scripts/setup-ollama.sh [--run]
set -euo pipefail

RUN_AFTER=false
for arg in "$@"; do
  case "$arg" in
    --run) RUN_AFTER=true ;;
  esac
done

echo "==> Checking Ollama..."
if ! command -v ollama &>/dev/null; then
  echo "ERROR: Ollama is not installed."
  echo "Install it from https://ollama.com/download, then re-run this script."
  exit 1
fi
echo "    Ollama found: $(ollama --version 2>/dev/null || echo 'version unknown')"

# Determine base directory
URAI_DIR="${URAI_DIR:-$HOME/.local/share/urai}"
GGUF_PATH="$URAI_DIR/model/base/urai-v1.04.gguf"

echo "==> URAI_DIR: $URAI_DIR"
echo "==> GGUF path: $GGUF_PATH"

# Download GGUF if not present
if [ ! -f "$GGUF_PATH" ]; then
  echo "==> GGUF not found. Downloading..."
  mkdir -p "$(dirname "$GGUF_PATH")"

  if command -v urai &>/dev/null; then
    echo "    Using urai CLI: urai model download urai-v1.04"
    urai model download urai-v1.04
  elif command -v curl &>/dev/null; then
    echo "    Using curl to download from Hugging Face..."
    curl -L --progress-bar \
      -o "$GGUF_PATH" \
      "https://github.com/etside/urai/releases/download/urai-qwen3-06b-v1/urai-qwen3-06b-v1-Q4_K_M.gguf"
  elif command -v wget &>/dev/null; then
    echo "    Using wget to download from Hugging Face..."
    wget -q --show-progress \
      -O "$GGUF_PATH" \
      "https://github.com/etside/urai/releases/download/urai-qwen3-06b-v1/urai-qwen3-06b-v1-Q4_K_M.gguf"
  else
    echo "ERROR: Neither urai CLI, curl, nor wget found. Cannot download GGUF."
    echo "Manually download:"
    echo "  https://github.com/etside/urai/releases/download/urai-qwen3-06b-v1/urai-qwen3-06b-v1-Q4_K_M.gguf"
    echo "Place it at: $GGUF_PATH"
    exit 1
  fi
else
  echo "==> GGUF already present: $GGUF_PATH"
fi

# Locate Modelfile relative to this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
MODELFILE_TEMPLATE="$REPO_ROOT/Modelfile"

if [ ! -f "$MODELFILE_TEMPLATE" ]; then
  echo "ERROR: Modelfile template not found at $MODELFILE_TEMPLATE"
  exit 1
fi

# Write resolved Modelfile to /tmp
TMP_MODELFILE="/tmp/urai_Modelfile"
echo "==> Writing resolved Modelfile to $TMP_MODELFILE..."
sed "s|GGUF_PATH_PLACEHOLDER|$GGUF_PATH|g" "$MODELFILE_TEMPLATE" > "$TMP_MODELFILE"

# Create Ollama model
echo "==> Creating Ollama model 'urai:v1.04'..."
ollama create urai:v1.04 -f "$TMP_MODELFILE"

echo ""
echo "============================================================"
echo "  Urai model created successfully!"
echo "============================================================"
echo "  Run with:   ollama run urai:v1.04"
echo "  API:        curl http://localhost:11434/api/generate ..."
echo "  URAI_DIR:   $URAI_DIR"
echo "============================================================"

if [ "$RUN_AFTER" = true ]; then
  echo "==> Launching: ollama run urai:v1.04"
  exec ollama run urai:v1.04
fi
