#!/bin/bash
# Urai repo <-> VPS sync helper
# VPS pulls necessary code from repo when client requires it.
# Usage: scripts/repo_sync.sh [--check-only]
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
echo "== Urai repo sync =="
echo "root: $ROOT"
git remote -v | head -n 5 || true
echo "--- status ---"
git rev-parse --short HEAD || true
git status --porcelain | head -n 20 || true
if [ "$1" = "--check-only" ]; then exit 0; fi
echo "--- pull --ff-only ---"
git pull --ff-only || { echo "pull failed"; exit 1; }
echo "--- py_compile jev ---"
python3 -m py_compile jev/server.py jev/agent.py jev/router.py jev/backends.py || true
echo "OK sync done. Restart with: systemctl restart urai-api"
