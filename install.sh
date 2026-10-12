#!/usr/bin/env bash
# Urai one-command installer: repo + `urai` on PATH + default model.
#   curl -fsSL https://raw.githubusercontent.com/tukitattu/urai/main/install.sh | bash
# Env: URAI_DIR (default ~/.local/share/urai), URAI_MODEL (default coder05-fast)
set -euo pipefail
DIR="${URAI_DIR:-$HOME/.local/share/urai}"
MODEL="${URAI_MODEL:-coder05-fast}"
command -v python3 >/dev/null || { echo "need python3 (>=3.10)"; exit 1; }
command -v git >/dev/null || { echo "need git"; exit 1; }
if [ -d "$DIR/.git" ]; then
  echo "updating $DIR"; git -C "$DIR" pull --ff-only
else
  echo "cloning into $DIR"; git clone --depth 1 https://github.com/tukitattu/urai.git "$DIR"
fi
mkdir -p "$HOME/.local/bin"
ln -sf "$DIR/bin/urai" "$HOME/.local/bin/urai"
ln -sf "$DIR/bin/jev" "$HOME/.local/bin/jev"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "NOTE: add to PATH: export PATH=\"\$HOME/.local/bin:\$PATH\"";; esac
echo "fetching default model ($MODEL)..."
"$DIR/bin/urai" model download "$MODEL"
echo "OK: $(urai version) — try: urai ask \"hello\""
