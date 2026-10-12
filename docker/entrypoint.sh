#!/usr/bin/env bash
# Container entrypoint: fetch model (if missing), start llama-server, serve API+web.
set -euo pipefail
MODEL="${URAI_MODEL:-coder05-fast}"
PORT="${URAI_PORT:-8777}"

if [ ! -f "model/registry.json" ]; then
  echo "no registry? creating defaults"; python3 -c "import sys; sys.path.insert(0,'.'); from jev import models_registry as r; r.save(r.load())"
fi
./bin/urai model download "$MODEL"
./bin/urai model use "$MODEL" >/dev/null || true
./bin/urai serve start --model "$MODEL" || {
  echo "NOTE: llama-server failed to start (weights present but runner issue?) — API still serves teacher/mock paths"; }
exec python3 -m jev.cli api --host 0.0.0.0 --port "$PORT"
