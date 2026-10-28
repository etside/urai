#!/usr/bin/env bash
# Parallel-phase GPU training for Urai Stage 2 (DigitalOcean, API-driven).
# Shards the dataset into N, spins one H100 per shard in parallel, trains
# Unsloth QLoRA per phase, uploads each adapter to the urai-deps release,
# destroys every droplet at the time cap. Cost guard: destroy-all trap.
#
# Required env (never committed, never logged):
#   DO_API_TOKEN   DigitalOcean API token
#   GH_TOKEN       GitHub token with repo scope (private etside/urai)
#   URAI_TRAIN_TAG dataset tag in data/verified/<TAG>.jsonl (default distill-now)
# Optional: TOR1 H100 (~$4.41/hr) capped 1h; URAI_PHASES 1-2 (default 1);
#   auto-capped by droplet headroom (limit minus running droplets).
set -euo pipefail
: "${DO_API_TOKEN:?set DO_API_TOKEN}"
: "${GH_TOKEN:?set GH_TOKEN}"
TAG="${URAI_TRAIN_TAG:-distill-now}"
ACTION="${1:-prices}"
IMAGE="${DO_IMAGE:-gpu-h100x1-base}"
REGION="${DO_REGION:-tor1}"
SIZE="${DO_GPU_SIZE:-gpu-h100x1-80gb}"
MAX_HOURS="${MAX_HOURS:-1}"
PHASES="${URAI_PHASES:-1}"

api() { curl -s -H "Authorization: Bearer $DO_API_TOKEN" \
  -H "Content-Type: application/json" "$@"; }

echo "== GPU sizes available (price/hr USD) =="
api "https://api.digitalocean.com/v2/sizes" \
  | python3 -c "import json,sys; [print(s['slug'], s.get('price_hourly'), s.get('regions', [])[:4]) for s in json.load(sys.stdin).get('sizes', []) if 'gpu' in s['slug'] or 'h100' in s['slug'] or 'l40' in s['slug'] or 'mi300' in s['slug'] or 'rtx' in s['slug']]" || true

read -r -d '' USERDATA <<'EOF' || true
#!/bin/bash
set -x
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-pip git gh
pip3 install --quiet --break-system-packages torch --index-url https://download.pytorch.org/whl/cu124 2>&1 | tail -n 3
pip3 install --quiet --break-system-packages unsloth trl peft accelerate bitsandbytes datasets 2>&1 | tail -n 5
BASE="${URAI_BASE:-unsloth/Qwen3-4B-bnb-4bit}"
MAX_STEPS="${MAX_TRAIN_STEPS:-300}"
echo "BASE=$BASE MAX_STEPS=$MAX_STEPS"
git clone https://x-access-token:__GH_TOKEN__@github.com/etside/urai.git /root/urai
cd /root/urai
python3 scripts/train/sft_unsloth.py --model "${BASE}" --train data/verified/__TAG__.jsonl --out adapters/__TAG__-gpu --epochs 1 --rank 16 --seq-len 2048 --max-steps "${MAX_STEPS}"
tar -czf /tmp/adapters-__TAG__-gpu.tgz adapters/__TAG__-gpu || tar -czf /tmp/adapters-__TAG__-gpu.tgz adapters
GH_TOKEN=__GH_TOKEN__ gh release view urai-deps --repo etside/urai >/dev/null 2>&1 || GH_TOKEN=__GH_TOKEN__ gh release create urai-deps --repo etside/urai --title "Urai vendored deps" --notes "Binaries + adapters." --prerelease
GH_TOKEN=__GH_TOKEN__ gh release upload urai-deps /tmp/adapters-__TAG__-gpu.tgz --repo etside/urai --clobber
echo TRAIN_DONE
EOF

USERDATA_TMPL="$USERDATA"
USERDATA_TMPL="${USERDATA_TMPL//__GH_TOKEN__/$GH_TOKEN}"

IDS=""
SSH_KEY_ID="${DO_SSH_KEY_IDS:-}"
destroy_all() {
  for id in $IDS; do
    api -X DELETE "https://api.digitalocean.com/v2/droplets/$id" >/dev/null 2>&1 || true
  done
  if [ -n "${SSH_KEY_ID:-}" ] && [ -z "${DO_SSH_KEY_IDS:-}" ]; then
    api -X DELETE "https://api.digitalocean.com/v2/account/keys/$SSH_KEY_ID" >/dev/null 2>&1 || true
  fi
  rm -f /tmp/urai-train-key /tmp/urai-train-key.pub
}
trap destroy_all EXIT

if [ "$ACTION" != "create" ]; then
  echo "DRY RUN: pass 'create' to actually spin droplets (money spends)."
  echo "Dataset check:"; ls -la "data/verified/${TAG}.jsonl" || echo "MISSING: pick an existing tag"
  exit 0
fi
ls -la "data/verified/${TAG}.jsonl" || { echo "MISSING dataset tag: $TAG"; exit 1; }

# headroom: droplet_limit minus running droplets (VPS occupies one)
LIMIT="$(api "https://api.digitalocean.com/v2/account" | python3 -c "import json,sys; print(json.load(sys.stdin).get('account',{}).get('droplet_limit',0))")"
RUNNING="$(api "https://api.digitalocean.com/v2/droplets?per_page=1" | python3 -c "import json,sys; print(json.load(sys.stdin).get('meta',{}).get('total',99))")"
FREE=$(( LIMIT - RUNNING ))
[ "$FREE" -lt 1 ] && { echo "STOP: no droplet headroom (limit $LIMIT, running $RUNNING). File the GPU ticket: docs/GPU_LIMIT_REQUEST.md"; exit 1; }
N="$PHASES"; [ "$N" -gt "$FREE" ] && N="$FREE"; [ "$N" -gt 2 ] && N=2; [ "$N" -lt 1 ] && N=1
echo "phases: $N (headroom $FREE)"

# shard + push so droplets clone the shard files
python3 scripts/distill/shard_dataset.py "data/verified/${TAG}.jsonl" "$N"
git add "data/verified/${TAG}-p"*.jsonl
git -c user.name="urai-gpu" -c user.email="urai-gpu@users.noreply.github.com" commit -m "GPU phases: shard $TAG into $N" >/dev/null 2>&1 || true
git push origin HEAD 2>&1 | tail -n 1 || echo "WARN: shard push failed (droplets may miss shards)"

if [ -z "$SSH_KEY_ID" ]; then
  ssh-keygen -t ed25519 -f /tmp/urai-train-key -N "" -C "urai-train-ephemeral" >/dev/null
  KEYNAME="urai-train-$(date +%s)"
  RESP=$(api -X POST "https://api.digitalocean.com/v2/account/keys" -d "$(python3 -c "import json; print(json.dumps({'name': '$KEYNAME', 'public_key': open('/tmp/urai-train-key.pub').read().strip()}))")")
  SSH_KEY_ID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['ssh_key']['id'])")
  echo "ephemeral ssh key id: $SSH_KEY_ID (deleted on exit)"
fi

for i in $(seq 0 $(( N - 1 ))); do
  PTAG="${TAG}-p${i}"
  UD="${USERDATA_TMPL//__TAG__/$PTAG}"
  echo "== creating phase $i ($SIZE @ $REGION) =="
  CREATE=$(api -X POST "https://api.digitalocean.com/v2/droplets" -d "{
    \"name\": \"urai-train-${PTAG}\", \"region\": \"$REGION\", \"size\": \"$SIZE\",
    \"image\": \"$IMAGE\",
    \"user_data\": $(printf '%s' "$UD" | python3 -c "import json,sys; print(json.dumps(sys.stdin.read()))"),
    \"ssh_keys\": [$SSH_KEY_ID],
    \"tags\": [\"urai-train\", \"ephemeral\"]
  }")
  ID=$(echo "$CREATE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['droplet']['id'] if 'droplet' in d else '')")
  if [ -z "$ID" ]; then
    echo "$CREATE" | python3 -c "import json,sys; print('DO-REJECTED phase $i:', str(json.load(sys.stdin).get('message','?'))[:200])"
    continue
  fi
  IDS="$IDS $ID"
  echo "phase $i droplet: $ID"
done
[ -z "$IDS" ] && { echo "STOP: no droplets created, no spend."; exit 1; }

echo "== waiting for $N adapter assets (up to ${MAX_HOURS}h), then destroying all =="
deadline=$(( $(date +%s) + MAX_HOURS * 3600 ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  GOT=0
  for i in $(seq 0 $(( N - 1 ))); do
    if GH_TOKEN="$GH_TOKEN" gh release view urai-deps --repo etside/urai \
        --json assets --jq ".assets[].name" 2>/dev/null | grep -q "adapters-${TAG}-p${i}-gpu.tgz"; then
      GOT=$(( GOT + 1 ))
    fi
  done
  echo "adapters landed: $GOT/$N"
  [ "$GOT" -ge "$N" ] && break
  sleep 120
done
echo "== destroying all: $IDS =="
destroy_all
IDS=""
echo DONE
