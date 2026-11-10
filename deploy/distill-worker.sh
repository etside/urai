#!/usr/bin/env bash
# Urai distillation worker — teacher generation on a small host.
#
# Runs the Muse -> free-teacher chain over data/raw_tasks/all.jsonl, appends to
# data/finetune/muse-spark-open/train.jsonl, and uploads the shard to S3 after
# every pass. Safe to restart: --resume skips prompts already answered.
#
# Sharding: SHARD=i/n splits tasks by index, so AWS + Tailscale VPS + any
# other worker can run in parallel without duplicating work.
set -uo pipefail

cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

SHARD="${SHARD:-0/1}"
OUT="data/finetune/muse-spark-open/train.jsonl"
LOG="${URAI_DISTILL_LOG:-/tmp/urai-distill.log}"
BUCKET="${URAI_S3_BUCKET:-urai-data-089737991855-ap-south-1}"
HOST="$(hostname -s)"

mkdir -p "$(dirname "$OUT")"
touch "$OUT"

while true; do
  before=$(wc -l < "$OUT" 2>/dev/null || echo 0)
  python3 kaggle/teacher_muse_spark.py \
    --tasks data/raw_tasks/all.jsonl \
    --out "$OUT" \
    --reasoning "${URAI_DISTILL_REASONING:-low}" \
    --max-tokens "${URAI_DISTILL_MAX_TOKENS:-4096}" \
    --retries 2 \
    --resume \
    --shard "$SHARD" \
    --s3-uri "s3://$BUCKET/distill/muse-spark-open/train-$HOST.jsonl" \
    --sync-every 5 >> "$LOG" 2>&1
  after=$(wc -l < "$OUT" 2>/dev/null || echo 0)
  echo "$(date -u +%FT%TZ) shard=$SHARD rows=$after (+$((after-before)))" >> "$LOG"

  aws s3 cp "$OUT" "s3://$BUCKET/distill/muse-spark-open/train-$HOST.jsonl" \
    >> "$LOG" 2>&1 || true

  if [ "$after" -eq "$before" ]; then
    # Nothing new: either the daily free-tier cap or all tasks are done.
    sleep 900
  else
    sleep 60
  fi
done
