#!/usr/bin/env bash
# Urai free-teacher grind: distill a task dir in small per-category chunks
# so a crash/OOM loses minutes, not hours. Merges + global dedups at end.
#
#   URAI_FREE_TEACHER=1 OPENCODE_BIN=/home/kp/.opencode/bin/opencode \
#     bash scripts/distill/run_free_grind.sh data/raw_tasks/expanded distill-free-s7
#
# Each chunk: --exec --judge. Resume: completed chunks are skipped
# (outputs exist). Memory: one teacher call at a time (this box-safe).
set -u
SRC="${1:?task dir}"; TAG="${2:?output tag, e.g. distill-free-s7}"
OUTDIR="data/verified/chunks-$TAG"
mkdir -p "$OUTDIR" eval/reports
export URAI_FREE_TEACHER=1
: "${OPENCODE_BIN:=/home/kp/.opencode/bin/opencode}"
export OPENCODE_BIN
# refuse silent mock runs (a mock "grind" burns hours for zero data)
TNAME=$(python3 -c "import sys; sys.path.insert(0,'scripts/distill'); from teacher_client import get_teacher; print(get_teacher().name)")
if [ "$TNAME" = "mock-v1" ]; then
  echo "REFUSE: teacher is mock-v1. Set one of TEACHER_* (API), PUTER_API_KEY,"
  echo "LOCAL_TEACHER=1 (own served student), or URAI_FREE_TEACHER=1 (opencode CLI)."
  exit 1
fi
echo "teacher: $TNAME"
for tf in "$SRC"/*.jsonl; do
  [ -e "$tf" ] || continue
  cat="$(basename "$tf" .jsonl)"
  if [ -s "$OUTDIR/$cat.jsonl" ]; then echo "SKIP done: $cat"; continue; fi
  echo "== chunk $cat =="
  python3 scripts/distill/run_distill.py --tasks "$tf" \
    --out "$OUTDIR/$cat.jsonl" --system "${URAI_DISTILL_SYSTEM:-default}" \
    --report "eval/reports/$TAG-$cat.json" --exec --judge \
    || echo "CHUNK-FAILED: $cat (continuing)"
done
python3 - "$OUTDIR" "data/verified/$TAG.jsonl" <<'EOF'
import json, sys
src, dest = sys.argv[1], sys.argv[2]
import glob
seen, kept = set(), []
for f in sorted(glob.glob(src + "/*.jsonl")):
    for line in open(f):
        line = line.strip()
        if not line: continue
        r = json.loads(line)
        h = (r.get("content_hash")
             or json.dumps(r.get("completion", ""), sort_keys=True)[:200])
        if h in seen: continue
        seen.add(h)
        kept.append(line)
open(dest, "w").write("\n".join(kept) + ("\n" if kept else ""))
print(f"merged {len(kept)} records -> {dest}")
EOF
