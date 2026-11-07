#!/usr/bin/env bash
# Publish the distill shards to Kaggle and start QLoRA training on a free GPU.
#
#   bash kaggle/publish_and_train.sh                # pull shards from S3
#   bash kaggle/publish_and_train.sh path/train.jsonl
#
# Requires: kaggle CLI authenticated (kaggle config view) and AWS read access
# to the shard bucket. The kernel trains the student that ships on the EC2 host
# (Qwen3-1.7B) and writes /kaggle/working/urai-adapter.
set -euo pipefail
cd "$(dirname "$0")/.."

KAGGLE_USER="${KAGGLE_USER:-sherikhtj}"
DS_SLUG="${DS_SLUG:-urai-distill-muse-spark}"
KERNEL_SLUG="${KERNEL_SLUG:-urai-qlora-distill}"
BUCKET="${URAI_S3_BUCKET:-urai-data-089737991855-ap-south-1}"
PREFIX="s3://$BUCKET/distill/muse-spark-open"
WORK="${WORK:-/tmp/urai-kaggle}"
DATA_IN="${1:-}"

rm -rf "$WORK"
mkdir -p "$WORK/dataset" "$WORK/kernel"

# ── data: local file, else all S3 shards concatenated ───────────────────────
if [ -n "$DATA_IN" ] && [ -f "$DATA_IN" ]; then
  cp "$DATA_IN" "$WORK/dataset/train.jsonl"
else
  mkdir -p "$WORK/shards"
  aws s3 cp --recursive "$PREFIX/" "$WORK/shards/" \
    --exclude "*" --include "train-*.jsonl" >/dev/null 2>&1 || true
  cat "$WORK"/shards/train-*.jsonl > "$WORK/dataset/train.jsonl" 2>/dev/null || true
fi

rows=$(wc -l < "$WORK/dataset/train.jsonl" 2>/dev/null || echo 0)
if [ "$rows" -lt 5 ]; then
  echo "need >= 5 rows to train (have $rows)"
  exit 1
fi
echo "dataset rows: $rows"

cat > "$WORK/dataset/dataset-metadata.json" <<EOF
{
  "title": "Urai distill (Muse Spark / free teacher)",
  "id": "$KAGGLE_USER/$DS_SLUG",
  "licenses": [{"name": "CC0-1.0"}]
}
EOF

if kaggle datasets list --user "$KAGGLE_USER" 2>/dev/null \
     | awk 'NR>1 {print $1}' | grep -qx "$KAGGLE_USER/$DS_SLUG"; then
  kaggle datasets version -p "$WORK/dataset" -r zip \
    -m "refresh $(date -u +%FT%TZ) rows=$rows"
else
  kaggle datasets create -p "$WORK/dataset" -r zip
fi

# ── kernel: notebook (script kernels fail on Kaggle — see v1 ERROR) ─────────
# The live student is Qwen3-1.7B; MAX_STEPS 400 for the small dataset.
python3 - <<PYEOF
import json
src = open("kaggle/train_qlora.py").read()
nb = {
  "cells": [{"cell_type": "code", "execution_count": None, "metadata": {},
             "outputs": [], "source": src.splitlines(True)}],
  "metadata": {"kernelspec": {"display_name": "Python 3",
                              "language": "python", "name": "python3"},
               "language_info": {"name": "python", "version": "3"}},
  "nbformat": 4, "nbformat_minor": 4,
}
json.dump(nb, open("$WORK/kernel/train_kernel.ipynb", "w"), indent=1)
print("notebook built:", len(src.splitlines()), "lines")
PYEOF

cat > "$WORK/kernel/kernel-metadata.json" <<EOF
{
  "id": "$KAGGLE_USER/$KERNEL_SLUG",
  "title": "Urai QLoRA distill",
  "code_file": "train_kernel.ipynb",
  "language": "python",
  "kernel_type": "notebook",
  "is_private": true,
  "enable_gpu": true,
  "enable_internet": true,
  "dataset_sources": ["$KAGGLE_USER/$DS_SLUG"],
  "competition_sources": [],
  "kernel_sources": []
}
EOF

PUSH_ARGS=()
if [ "${NO_RUN:-0}" = "1" ]; then
  PUSH_ARGS+=(--no-run)
fi
kaggle kernels push -p "$WORK/kernel" "${PUSH_ARGS[@]}"
echo "kernel: https://www.kaggle.com/code/$KAGGLE_USER/$KERNEL_SLUG"
echo "status: kaggle kernels status $KAGGLE_USER/$KERNEL_SLUG"
