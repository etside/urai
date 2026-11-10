#!/usr/bin/env bash
# Install ComfyUI-Ref2VA-VSA (MiniMax H3 Ref2VA + Visual Sparse Attention) for Urai.
#
# Run this ON THE GPU BOX (not the control VPS, not a laptop):
#   CUDA 12.1+ / PyTorch 2.4+ / NVIDIA GPU with 24GB VRAM (RTX 3090/4090/A5000/L40S)
#   ComfyUI (>=0.36 with native MiniMax-H3) and comfy-kitchen with CUDA sol_attn.
#
#   URAI_COMFY_DIR=/opt/ComfyUI scripts/video/install_ref2va_vsa.sh --download
#
# Flags:
#   --download   fetch the six checkpoints into ComfyUI/models/*
#   --check      verify only (default if --download not given)
set -euo pipefail

COMFY_DIR="${URAI_COMFY_DIR:-$HOME/ComfyUI}"
NODE_REL="custom_nodes/ComfyUI-Ref2VA-VSA"
NODE_DIR="$COMFY_DIR/$NODE_REL"
REPO="${URAI_REF2VA_REPO:-https://github.com/Kablex/ComfyUI-Ref2VA-VSA}"
WORKFLOW="$NODE_DIR/workflows/ref2va_vsa_4step_api.json"
DO_DOWNLOAD=0
[ "${1:-}" = "--download" ] && DO_DOWNLOAD=1

say() { printf '\033[36m[ref2va]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[ref2va:error]\033[0m %s\n' "$*" >&2; exit 1; }

command -v git >/dev/null || die "git not found"
[ -d "$COMFY_DIR" ] || die "ComfyUI dir not found: $COMFY_DIR (set URAI_COMFY_DIR)"

# 1. clone / update the custom node -------------------------------------------------
if [ -d "$NODE_DIR/.git" ]; then
  say "updating existing node at $NODE_DIR"
  git -C "$NODE_DIR" fetch --depth 1 origin && \
    git -C "$NODE_DIR" reset --hard origin/HEAD
else
  say "cloning $REPO -> $NODE_DIR"
  mkdir -p "$COMFY_DIR/custom_nodes"
  git clone --depth 1 "$REPO" "$NODE_DIR"
fi
git -C "$NODE_DIR" rev-parse HEAD | sed 's/^/[ref2va] node revision: /'

[ -f "$WORKFLOW" ] || die "bundled API workflow missing: $WORKFLOW"

# 2. verify comfy-kitchen sol_attn --------------------------------------------------
say "checking comfy-kitchen CUDA sol_attn ..."
python3 - <<'PY' || say "WARNING: comfy-kitchen sol_attn not importable — VSA will fall back to dense (no speedup). Install comfy-kitchen with CUDA support."
try:
    import comfy_kitchen  # noqa
    print("[ref2va] comfy-kitchen present")
except Exception as e:
    raise SystemExit(f"not importable: {e}")
PY

# 3. fetch the six checkpoints -------------------------------------------------------
hf_fetch() {  # repo remote_path dest_dir
  local repo="$1" remote="$2" dest="$3"
  mkdir -p "$dest"
  if command -v hf >/dev/null; then
    hf download "$repo" "$remote" --local-dir "$dest" >/dev/null
  elif command -v huggingface-cli >/dev/null; then
    huggingface-cli download "$repo" "$remote" --local-dir "$dest" >/dev/null
  else
    local url="https://huggingface.co/$repo/resolve/main/$remote"
    wget -q --show-progress -O "$dest/$(basename "$remote")" "$url"
  fi
}

if [ "$DO_DOWNLOAD" = "1" ]; then
  say "downloading checkpoints (tens of GB; ensure disk space) ..."
  M="$COMFY_DIR/models"
  hf_fetch Comfy-Org/MiniMax-H3 diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors "$M/diffusion_models"
  hf_fetch barelymining/ComfyUI-MiniMax-H3-FastVideo fasth3_vsa_gate.safetensors "$M/loras"
  hf_fetch lightx2v/Minimax-h3-Turbo minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors "$M/loras"
  hf_fetch Comfy-Org/MiniMax-H3 text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors "$M/text_encoders"
  hf_fetch Comfy-Org/MiniMax-H3 vae/minimax_h3_video_vae_fp16.safetensors "$M/vae"
  hf_fetch Comfy-Org/MiniMax-H3 vae/minimax_h3_audio_vae_fp32.safetensors "$M/vae"
else
  say "skipping downloads (pass --download to fetch weights)"
fi

# 4. verify + report ----------------------------------------------------------------
say "verifying installation ..."
URAI_COMFY_DIR="$COMFY_DIR" python3 "$(dirname "$0")/verify_ref2va_models.py" || true

cat <<EOF

[ref2va] done.

Next:
  1. restart ComfyUI   (nodes appear under FastH3/VSA -> Ref2VA VSA Gate Transplant)
  2. point Urai at it:  export URAI_COMFY_URL=http://127.0.0.1:8188
  3. smoke test:        bin/urai video "..." --provider ref2va   (or POST /v1/videos/generations with provider:"ref2va")
  4. benchmark:         python3 scripts/video/bench_ref2va.py
EOF
