#!/usr/bin/env bash
# Urai one-command installer: repo + `urai` on PATH + optional local model.
#   curl -fsSL https://raw.githubusercontent.com/etside/urai/main/install.sh | bash
# Env:
#   URAI_DIR    (default ~/.local/share/urai)
#   URAI_MODEL  (default empty = remote-first, no download; e.g. coder05-fast for offline coding)
#   URAI_MASTER_KEY (optional: saved for `urai ask --remote` / `urai agent --remote`)
#   URAI_REMOTE_URL (default https://urai.daddyai.online)
set -euo pipefail
DIR="${URAI_DIR:-$HOME/.local/share/urai}"
MODEL="${URAI_MODEL:-}"
REMOTE="${URAI_REMOTE_URL:-https://urai.daddyai.online}"
command -v python3 >/dev/null || { echo "need python3 (>=3.10)"; exit 1; }
command -v git >/dev/null || { echo "need git"; exit 1; }
if [ -d "$DIR/.git" ]; then
  echo "updating $DIR"; git -C "$DIR" pull --ff-only
else
  echo "cloning into $DIR"; git clone --depth 1 https://github.com/etside/urai.git "$DIR"
fi
mkdir -p "$HOME/.local/bin"
ln -sf "$DIR/bin/urai" "$HOME/.local/bin/urai"
ln -sf "$DIR/bin/jev" "$HOME/.local/bin/jev"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "NOTE: add to PATH: export PATH=\"\$HOME/.local/bin:\$PATH\"";; esac
if [ -n "$MODEL" ]; then
  echo "fetching model ($MODEL)..."
  "$DIR/bin/urai" model download "$MODEL"
else
  echo "remote-first install (no model download). VPS API: $REMOTE"
fi
if [ -n "${URAI_MASTER_KEY:-}" ]; then
  "$DIR/bin/urai" login "$URAI_MASTER_KEY" --url "$REMOTE" >/dev/null || true
  echo "saved master key for remote use"
fi
echo "OK: $(urai version 2>/dev/null || echo installed)"
echo "try: urai login 856777 && urai ask --remote \"hello\""
echo "docs: $DIR/docs/ide-integration.md (VSCode/opencode), $DIR/docs/video-studios.md"
