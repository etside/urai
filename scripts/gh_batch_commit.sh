#!/usr/bin/env bash
# gh_batch_commit.sh — Commit multiple files to GitHub in ONE atomic commit
# using the Git Data API (no 409 conflicts from parallel commits).
#
# Usage:
#   gh_batch_commit.sh REPO BRANCH MESSAGE FILE1:REMOTE_PATH1 [FILE2:REMOTE_PATH2 ...]
#
# Example:
#   gh_batch_commit.sh etside/urai main "feat: add voice and vibe" \
#     /tmp/voice.py:jev/voice.py \
#     /tmp/vibe.py:jev/vibe.py \
#     /tmp/registry.json:model/registry.json
#
# Requires: gh CLI (authenticated), jq, base64
# Parallel-safe: blobs are created in parallel; tree+commit is one atomic op.

set -euo pipefail

REPO="${1:?Usage: $0 REPO BRANCH MESSAGE file:path ...}"
BRANCH="${2:?}"
MESSAGE="${3:?}"
shift 3

if [[ $# -eq 0 ]]; then
  echo "Error: no files specified" >&2
  exit 1
fi

# ── helpers ───────────────────────────────────────────────────────────────────

api() {
  # Thin wrapper: gh api with JSON output
  gh api "$@"
}

log() { echo "  $*" >&2; }

# ── 1. Get current HEAD commit + tree SHA ─────────────────────────────────────

log "Fetching HEAD of $REPO@$BRANCH..."
HEAD_SHA=$(api "repos/$REPO/git/ref/heads/$BRANCH" --jq '.object.sha')
BASE_TREE=$(api "repos/$REPO/git/commits/$HEAD_SHA" --jq '.tree.sha')
log "HEAD: $HEAD_SHA  tree: $BASE_TREE"

# ── 2. Create blobs in parallel ───────────────────────────────────────────────
# Each pair is "local_path:remote_path"
# We'll collect results as JSON fragments: {"path":"...","sha":"..."}

BLOB_DIR=$(mktemp -d)
PIDS=()

for pair in "$@"; do
  LOCAL="${pair%%:*}"
  REMOTE="${pair#*:}"

  (
    CONTENT=$(base64 -w0 < "$LOCAL")
    BLOB_SHA=$(api "repos/$REPO/git/blobs" \
      --method POST \
      --field encoding=base64 \
      --field content="$CONTENT" \
      --jq '.sha')
    echo "{\"path\":\"$REMOTE\",\"mode\":\"100644\",\"type\":\"blob\",\"sha\":\"$BLOB_SHA\"}" \
      > "$BLOB_DIR/$(echo "$REMOTE" | tr '/' '_').json"
    log "blob $REMOTE → $BLOB_SHA"
  ) &
  PIDS+=($!)
done

# Wait for all blob uploads
for pid in "${PIDS[@]}"; do
  wait "$pid"
done

# ── 3. Build tree entries JSON array ─────────────────────────────────────────

TREE_ENTRIES="["
sep=""
for f in "$BLOB_DIR"/*.json; do
  TREE_ENTRIES+="${sep}$(cat "$f")"
  sep=","
done
TREE_ENTRIES+="]"

rm -rf "$BLOB_DIR"

# ── 4. Create new tree ────────────────────────────────────────────────────────
# Use --input (stdin JSON) because --field can't handle JSON array values.

log "Creating tree..."
NEW_TREE=$(printf '{"base_tree":"%s","tree":%s}' "$BASE_TREE" "$TREE_ENTRIES" \
  | api "repos/$REPO/git/trees" --method POST --input - --jq '.sha')
log "new tree: $NEW_TREE"

# ── 5. Create commit ──────────────────────────────────────────────────────────

log "Creating commit..."
NEW_COMMIT=$(printf '{"message":%s,"tree":"%s","parents":["%s"]}' \
    "$(echo "$MESSAGE" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read().rstrip()))')" \
    "$NEW_TREE" "$HEAD_SHA" \
  | api "repos/$REPO/git/commits" --method POST --input - --jq '.sha')
log "new commit: $NEW_COMMIT"

# ── 6. Update ref ─────────────────────────────────────────────────────────────

log "Updating refs/heads/$BRANCH..."
api "repos/$REPO/git/refs/heads/$BRANCH" \
  --method PATCH \
  --field sha="$NEW_COMMIT" \
  --field force=false \
  --jq '.object.sha' > /dev/null

echo ""
echo "✓ Committed ${#@} files to $REPO@$BRANCH"
echo "  commit: $NEW_COMMIT"
