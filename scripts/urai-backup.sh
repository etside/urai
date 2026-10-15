#!/usr/bin/env bash
# Urai nightly backup: code is in git; this snapshots data + config.
# Models (13GB) are re-downloadable from HF — excluded by design.
set -euo pipefail
DEST="${URAI_BACKUP_DIR:-/var/backups/urai}"
mkdir -p "$DEST"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
cd /opt/urai
tar -czf "$DEST/urai-data-$STAMP.tgz" \
  data/verified data/prompts eval/reports model/registry.json \
  docs/GPU_COMBINED_STRATEGY.md docs/AUDIT_2026-10-15.md docs/PROD.md 2>/dev/null || true
ls -t "$DEST"/urai-data-*.tgz | tail -n +8 | xargs -r rm -f
echo "backup -> $DEST/urai-data-$STAMP.tgz"
