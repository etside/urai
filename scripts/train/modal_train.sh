#!/usr/bin/env bash
# Urai unified-student training on Modal — the DEFAULT GPU path.
#
# Ephemeral, remote, cost-capped (T4 by default). Trains the single unified
# student on the merged verified set (tag=unified) and publishes the LoRA
# adapter to the urai-deps release. No local compute.
#
# Required env: MODAL_TOKEN_ID, MODAL_TOKEN_SECRET
# Optional:     URAI_TRAIN_TAG (default unified), MAX_TRAIN_STEPS (300),
#               URAI_MODAL_GPU (T4|A100|L40S), GH_TOKEN (to publish)
set -euo pipefail
: "${MODAL_TOKEN_ID:?set MODAL_TOKEN_ID}"
: "${MODAL_TOKEN_SECRET:?set MODAL_TOKEN_SECRET}"
TAG="${URAI_TRAIN_TAG:-unified}"
MAX_STEPS="${MAX_TRAIN_STEPS:-300}"
GPU="${URAI_MODAL_GPU:-T4}"

# unified merges every verified row; other tags need an explicit file
if [ "$TAG" = "unified" ]; then
  python3 scripts/train/merge_verified.py
else
  [ -f "data/verified/${TAG}.jsonl" ] || { echo "MISSING dataset tag: $TAG"; exit 1; }
fi

echo "== modal train: tag=$TAG gpu=$GPU max_steps=$MAX_STEPS =="
python3 -m pip install -q modal
URAI_TRAIN_TAG="$TAG" URAI_MODAL_GPU="$GPU" \
  modal run modal/modal_train.py --tag "$TAG" --max-steps "$MAX_STEPS"

echo "== fetching adapter from volume =="
modal volume get urai-adapters "${TAG}-modal" "./adapters/${TAG}-modal"
tar -czf "/tmp/adapters-${TAG}-modal.tgz" "adapters/${TAG}-modal"

if [ -n "${GH_TOKEN:-}" ]; then
  gh release view urai-deps --repo etside/urai >/dev/null 2>&1 || \
    gh release create urai-deps --repo etside/urai \
      --title "Urai vendored deps" --notes "Binaries + adapters." --prerelease
  gh release upload urai-deps "/tmp/adapters-${TAG}-modal.tgz" \
    --repo etside/urai --clobber
  echo "published: adapters-${TAG}-modal.tgz"
fi
echo "MODAL_DONE ${TAG}"
