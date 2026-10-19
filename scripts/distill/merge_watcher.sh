#!/usr/bin/env bash
# Watches both parallel CPU grinds; when both finish, merges everything
# into data/verified/distill-now.jsonl and validates the trainer loader.
# Read-only w.r.t. running workers. Logs to /tmp/urai-merge-done.log.
set -u
cd /opt/urai
while pgrep -f "run_distill\.py" >/dev/null 2>&1; do sleep 120; done
sleep 30
{
  echo "both grinds finished at $(date -u +%FT%TZ)"
  for f in data/verified/distill-now-a.jsonl data/verified/distill-now-b.jsonl; do
    [ -f "$f" ] && wc -l "$f" || echo "MISSING $f"
  done
  python3 scripts/distill/merge_parallel.py data/verified/distill-now.jsonl \
    data/verified/distill-now.jsonl \
    data/verified/distill-now-a.jsonl data/verified/distill-now-b.jsonl \
    data/verified/chunks-distill-now-a/*.jsonl data/verified/chunks-distill-now-b/*.jsonl
  python3 /tmp/verify_loader.py
} >> /tmp/urai-merge-done.log 2>&1
echo "merge watcher done" >> /tmp/urai-merge-done.log
