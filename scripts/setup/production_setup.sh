#!/usr/bin/env bash
# Urai production setup — verify CPU/GPU, credentials, media relays, skills and
# pinned dependencies; optionally install what is missing.
#
#   bash scripts/setup/production_setup.sh            # report only (safe)
#   bash scripts/setup/production_setup.sh --install  # pip deps + Kaggle CLI
#   bash scripts/setup/production_setup.sh --verify   # runtime smoke checks
#
# Design rules: idempotent, no destructive steps, NO secret values printed.
# Missing credentials are reported as MISSING — never substituted or faked.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

MODE=check
for arg in "$@"; do
  case "$arg" in
    --install) MODE=install ;;
    --verify)  MODE=verify ;;
    --help)    sed -n '2,10p' "$0"; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

say() { printf '\n\033[1m### %s\033[0m\n' "$*"; }
ok()  { printf '  \033[32mOK\033[0m   %s\n' "$*"; }
warn(){ printf '  \033[33mWARN\033[0m %s\n' "$*"; }
miss(){ printf '  \033[31mMISS\033[0m %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

say "1. Host / Python"
uname -sm
if have python3; then
  PY=$(python3 -c 'import sys; print(".".join(map(str,sys.version_info[:3])))')
  printf '  python3 %s\n' "$PY"
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' \
    && ok "Python >= 3.12" || warn "Python < 3.12 — upgrade before training paths"
else
  miss "python3"
fi

say "2. Compute (CPU / GPU) and llama.cpp build policy"
if have nvidia-smi; then
  nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader 2>/dev/null | head -4 || true
  ok "NVIDIA detected — build with -DGGML_CUDA=ON; offload -ngl 99 (>=6GB free) / 20 (3-6GB) / 10 (<3GB)"
elif have rocm-smi || [ -d /opt/rocm ]; then
  ok "AMD/ROCm detected — build with -DGGML_HIP=ON; -ngl 10..99 by free VRAM"
elif [ "$(uname -s)" = "Darwin" ]; then
  ok "Apple/Metal — default build, -ngl 99"
else
  warn "No GPU probe succeeded — CPU policy. Use a <=4B Q4 GGUF; heavy training goes to Kaggle/Modal."
fi
printf '  nproc=%s\n' "$(nproc 2>/dev/null || echo '?')"

say "3. Credentials (names only — values are never read or logged)"
check_env() {
  if [ -n "${!1:-}" ]; then ok "$1 set"; else miss "$1"; fi
}
printf '  %s\n' "LLM / agent:"
for k in OPENAI_API_KEY ANTHROPIC_API_KEY OPENROUTER_API_KEY VERCEL_AI_GATEWAY_API_KEY \
         TEACHER_API_KEY URAI_API_KEY URAI_MASTER_KEY; do check_env "$k"; done
printf '  %s\n' "Media relays (Wan video / Seedream image):"
for k in DASHSCOPE_API_KEY ARK_API_KEY; do check_env "$k"; done

printf '  %s\n' "Kaggle GPU training:"
KAGGLE_OK=0
if [ -n "${KAGGLE_USERNAME:-}" ] && [ -n "${KAGGLE_KEY:-}" ]; then
  ok "KAGGLE_USERNAME + KAGGLE_KEY set"; KAGGLE_OK=1
elif [ -f "$HOME/.kaggle/kaggle.json" ]; then
  mode=$(stat -c '%a' "$HOME/.kaggle/kaggle.json" 2>/dev/null || echo '?')
  ok "~/.kaggle/kaggle.json present (mode $mode)"
  [ "$mode" = "600" ] || warn "kaggle.json should be mode 600 — chmod 600 ~/.kaggle/kaggle.json"
  KAGGLE_OK=1
else
  miss "no Kaggle credentials (env or ~/.kaggle/kaggle.json)"
  printf '       Add them at kaggle.com -> Account -> Create New API Token, then:\n'
  printf '       mkdir -p ~/.kaggle && cp kaggle.json ~/.kaggle/ && chmod 600 ~/.kaggle/kaggle.json\n'
fi
if have kaggle; then ok "kaggle CLI: $(kaggle --version 2>/dev/null | head -1)"; else miss "kaggle CLI"; fi

# VPS deployments keep secrets in env files; list key NAMES only, since a
# credential can be present in .env without being exported in this shell.
printf '  %s\n' "Env files (key names only):"
FOUND_ENV=0
while IFS= read -r f; do
  [ -f "$f" ] || continue
  if [ -r "$f" ] || sudo -n test -r "$f" 2>/dev/null; then
    FOUND_ENV=1
    printf '    %s:\n' "$f"
    { cat "$f" 2>/dev/null || sudo -n cat "$f" 2>/dev/null; } \
      | grep -oE '^[A-Za-z][A-Za-z0-9_]*=' | sort -u | sed 's/^/      /' | head -40
  fi
done < <(printf '%s\n' /etc/urai/env "$HOME/urai/.env" "$ROOT/.env" /home/reeha/urai/.env \
         | awk '!seen[$0]++')
[ "$FOUND_ENV" = "1" ] || printf '    none found\n'

say "4. Skills"
for s in summarize tool-calling human-conversation; do
  [ -f "skills/$s/SKILL.md" ] && ok "skills/$s" || miss "skills/$s"
done
if have ./bin/urai; then
  ./bin/urai skill list 2>/dev/null | grep -E 'summarize|tool-calling|human-conversation' | sed 's/^/    /' || true
fi

say "5. Pinned dependencies"
if [ -f requirements.txt ]; then
  ok "requirements.txt ($(wc -l < requirements.txt) lines)"
  while read -r line; do
    case "$line" in ''|'#'*) continue ;; esac
    pkg=${line%%==*}; ver=${line#*==}
    have_src=$(python3 -c "import importlib.metadata as m; print(m.version('$pkg'))" 2>/dev/null || true)
    if [ "$have_src" = "$ver" ]; then ok "$pkg==$ver"; else warn "$pkg: installed=${have_src:-none} pinned=$ver"; fi
  done < requirements.txt
else
  miss "requirements.txt"
fi

if [ "$MODE" = "install" ]; then
  say "6. Install (only what is safe to install)"
  python3 -m pip install -r requirements.txt
  if [ "$KAGGLE_OK" = "1" ] && ! have kaggle; then
    python3 -m pip install kaggle
    ok "kaggle CLI installed"
  else
    warn "Kaggle CLI not installed — credentials missing"
  fi
  if [ -d third_party/llama.cpp ]; then
    if have nvidia-smi; then FLAGS="-DGGML_CUDA=ON";
    elif have rocm-smi || [ -d /opt/rocm ]; then FLAGS="-DGGML_HIP=ON";
    else FLAGS="-DGGML_NATIVE=ON"; fi
    cmake -S third_party/llama.cpp -B third_party/llama.cpp/build -DCMAKE_BUILD_TYPE=Release $FLAGS
    cmake --build third_party/llama.cpp/build -j"$(nproc)" \
      --target llama-server llama-cli llama-bench llama-quantize
  else
    warn "third_party/llama.cpp not present — clone pinned version first (see README)"
  fi
fi

if [ "$MODE" = "verify" ] || [ "$MODE" = "install" ]; then
  say "7. Runtime verification"
  [ -x ./bin/urai ] && ./bin/urai version || miss "bin/urai not executable"
  [ -x ./bin/urai ] && ./bin/urai gpu || true
  python3 - <<'PY' 2>/dev/null || true
import json
try:
    from jev.relays import status
    print("  relays:", json.dumps(status(), separators=(",", ":")))
except Exception as exc:  # report, never fabricate
    print("  relays: unavailable:", type(exc).__name__)
PY
  if have curl && curl -fsS --max-time 4 http://127.0.0.1:8777/health >/dev/null 2>&1; then
    ok "API health on :8777"
  else
    warn "API not running on :8777 (start with './bin/urai api')"
  fi
fi

say "Next steps"
printf '  Kaggle GPU: %s\n' "docs/KAGGLE_NOW.md + docs/SETUP_PRODUCTION.md (uses existing kaggle.json or KAGGLE_* env)"
printf '  Wan video:  %s\n' "export DASHSCOPE_API_KEY=... then ./bin/urai video 'prompt' --provider wan3"
printf '  Image:      %s\n' "export ARK_API_KEY=... then ./bin/urai imagine 'prompt'"
printf '  LLM:        %s\n' "existing OPENAI/ANTHROPIC/OPENROUTER/VERCEL keys are auto-detected; local fallback via llama-server"
printf '  Full guide: %s\n' "docs/SETUP_PRODUCTION.md"
