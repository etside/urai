#!/usr/bin/env bash
# Urai one-command installer: repo + `urai` on PATH + optional local model.
#   export GH_TOKEN=$(gh auth token); curl -fsSL -H "Authorization: Bearer $GH_TOKEN" https://raw.githubusercontent.com/etside/urai/main/install.sh | bash  # private repo: `gh auth login` first
# Env:
#   URAI_DIR    (default ~/.local/share/urai)
#   URAI_MODEL  (default empty = remote-first, no download; e.g. coder05-fast for offline coding)
#   URAI_MASTER_KEY (optional: saved for `urai ask --remote` / `urai agent --remote`)
#   URAI_REMOTE_URL (default http://127.0.0.1:8777)
set -euo pipefail
DIR="${URAI_DIR:-$HOME/.local/share/urai}"
MODEL="${URAI_MODEL:-}"
REMOTE="${URAI_REMOTE_URL:-http://127.0.0.1:8777}"
command -v python3 >/dev/null || { echo "need python3 (>=3.10)"; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || { echo "need python3 >= 3.10 (found $(python3 -V 2>&1))"; exit 1; }
command -v git >/dev/null || { echo "need git"; exit 1; }
if [ -d "$DIR/.git" ]; then
  echo "updating $DIR"; git -C "$DIR" pull --ff-only
else
  echo "cloning into $DIR"; git clone --depth 1 https://github.com/etside/urai.git "$DIR"
fi
echo "installing Python package..."
pip install -q -e "$DIR" || pip install -q -e "$DIR[local]" || {
  echo "NOTE: pip install failed — trying with --user flag"
  pip install -q --user -e "$DIR" || true
}
mkdir -p "$HOME/.local/bin"
ln -sf "$DIR/bin/urai" "$HOME/.local/bin/urai"
ln -sf "$DIR/bin/jev" "$HOME/.local/bin/jev"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "NOTE: add to PATH: export PATH=\"\$HOME/.local/bin:\$PATH\"";; esac
if [ -n "$MODEL" ]; then
  echo "fetching model ($MODEL)..."
  "$DIR/bin/urai" model download "$MODEL"
else
  echo "no model downloaded yet — pick one in the Studio (or rerun with URAI_MODEL=coder05-fast)"
  echo "API endpoint: $REMOTE"
fi
if [ -n "${URAI_MASTER_KEY:-}" ]; then
  "$DIR/bin/urai" login "$URAI_MASTER_KEY" --url "$REMOTE" >/dev/null || true
  echo "saved master key for remote use"
fi
echo "OK: $(urai version 2>/dev/null || echo installed)"
echo "try: urai studio   # starts the API and opens the Studio"
echo "     urai api      # API only: http://127.0.0.1:8777/app"
echo "docs: $DIR/README.md and $DIR/docs/"

