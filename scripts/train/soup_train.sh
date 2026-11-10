#!/usr/bin/env bash
# Urai unified-student training with Soup — replaces modal_train.sh.
#
# Trains on the merged verified set, exports a GGUF, and publishes the
# LoRA adapter to the urai-deps release. No Modal, no DO, no local compute
# required beyond the GitHub Actions GPU runner.
#
# Required env: (none — GH_TOKEN is optional for publish)
# Optional:     URAI_TRAIN_TAG  (default unified; only "unified" supported)
#               MAX_TRAIN_STEPS (default 300, overrides config)
#               GH_TOKEN        (to publish adapter asset)
set -euo pipefail

TAG="${URAI_TRAIN_TAG:-unified}"
MAX_STEPS="${MAX_TRAIN_STEPS:-300}"

# Build (or reuse) the unified dataset
echo "== merging verified dataset: tag=$TAG =="
python3 scripts/train/merge_verified.py
rows=$(wc -l < data/verified/unified.jsonl)
echo "unified dataset: $rows rows"
if [ "$rows" -lt 50 ]; then
  echo "::error::unified.jsonl has only $rows rows — need at least 50 to train."
  exit 1
fi

# Install Soup training stack (pinned for reproducibility)
echo "== installing soup-cli[train]>=0.73.0 =="
python3 -m pip install -q "soup-cli[train]>=0.73.0"

# Patch MAX_STEPS into the YAML config (soup train does not support --set)
echo "== patching config: max_steps=${MAX_STEPS} =="
sed -i "s/max_steps:.*$/max_steps: ${MAX_STEPS}/" config/soup_train.yaml

# Train
echo "== soup train: tag=$TAG max_steps=$MAX_STEPS =="
soup train --config config/soup_train.yaml --yes

# Export GGUF for the llama.cpp / registry serving stack
echo "== exporting GGUF (q4_k_m) =="
mkdir -p model
soup export --format gguf --quant q4_k_m --out model/urai-latest.gguf

echo "== packaging adapter =="
tar -czf "/tmp/adapters-${TAG}-soup.tgz" "adapters/unified-soup"

# Publish to urai-deps release (optional, requires GH_TOKEN)
if [ -n "${GH_TOKEN:-}" ]; then
  gh release view urai-deps --repo tukitattu/urai >/dev/null 2>&1 || \
    gh release create urai-deps --repo tukitattu/urai \
      --title "Urai vendored deps" --notes "Binaries + adapters." --prerelease
  gh release upload urai-deps "/tmp/adapters-${TAG}-soup.tgz" \
    --repo tukitattu/urai --clobber
  echo "published: adapters-${TAG}-soup.tgz"
fi

echo "SOUP_DONE ${TAG}"
