#!/usr/bin/env bash
# One-shot GPU training box for Urai Stage 2 (DigitalOcean, API-driven).
# No SSH needed: user-data clones the repo, trains, uploads adapters to a
# GitHub release, then this script destroys the droplet. Cost guard: the
# orchestrator destroys the droplet after MAX_HOURS no matter what.
#
# Required env (never committed, never logged):
#   DO_API_TOKEN   DigitalOcean API token
#   GH_TOKEN       GitHub token with repo scope (private etside/urai)
#   URAI_TRAIN_TAG dataset tag in data/verified/<TAG>.jsonl (default distill-now)
# Optional defaults: TOR1 x 1 x H100 (~$4.41/hr), capped at 1 hour.
#   confirmed via API before create), MAX_HOURS (default 3)
set -euo pipefail
: "${DO_API_TOKEN:?set DO_API_TOKEN}"
: "${GH_TOKEN:?set GH_TOKEN}"
TAG="${URAI_TRAIN_TAG:-distill-now}"
ACTION="${1:-prices}"
# NOTE: GPU Droplets need a GPU-ready image; if plain ubuntu fails at create
# time, list GPU images via the API and set DO_IMAGE accordingly.
IMAGE="${DO_IMAGE:-gpu-h100x1-base}"
REGION="${DO_REGION:-tor1}"
SIZE="${DO_GPU_SIZE:-gpu-h100x1-80gb}"
MAX_HOURS="${MAX_HOURS:-1}"

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

USERDATA="${USERDATA//__TAG__/$TAG}"
USERDATA="${USERDATA//__GH_TOKEN__/$GH_TOKEN}"
if [ "$ACTION" != "create" ]; then
  echo "DRY RUN: pass 'create' to actually spin the droplet (money spends)."
  echo "Dataset check:"; ls -la "data/verified/${TAG}.jsonl" || echo "MISSING: pick an existing tag"
  exit 0
fi
ls -la "data/verified/${TAG}.jsonl" || { echo "MISSING dataset tag: $TAG"; exit 1; }
# GPU-ready images refuse password auth: register an ephemeral SSH key
# (created here, deleted on exit — never touches the repo or logs).
SSH_KEY_ID="${DO_SSH_KEY_IDS:-}"
cleanup_key() {
  if [ -n "${SSH_KEY_ID:-}" ] && [ -z "${DO_SSH_KEY_IDS:-}" ]; then
    api -X DELETE "https://api.digitalocean.com/v2/account/keys/$SSH_KEY_ID" >/dev/null 2>&1 || true
  fi
  rm -f /tmp/urai-train-key /tmp/urai-train-key.pub
}
trap cleanup_key EXIT
if [ -z "$SSH_KEY_ID" ]; then
  ssh-keygen -t ed25519 -f /tmp/urai-train-key -N "" -C "urai-train-ephemeral" >/dev/null
  PUB="$(cat /tmp/urai-train-key.pub)"
  KEYNAME="urai-train-$(date +%s)"
  RESP=$(api -X POST "https://api.digitalocean.com/v2/account/keys" -d "$(python3 -c "import json; print(json.dumps({'name': '$KEYNAME', 'public_key': open('/tmp/urai-train-key.pub').read().strip()}))")")
  SSH_KEY_ID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['ssh_key']['id'])")
  echo "ephemeral ssh key id: $SSH_KEY_ID (deleted on exit)"
fi
echo "== creating GPU droplet ($SIZE @ $REGION, image $IMAGE) =="
CREATE=$(api -X POST "https://api.digitalocean.com/v2/droplets" -d "{
  \"name\": \"urai-train-${TAG}\", \"region\": \"$REGION\", \"size\": \"$SIZE\",
  \"image\": \"$IMAGE\",
  \"user_data\": $(printf '%s' "$USERDATA" | python3 -c "import json,sys; print(json.dumps(sys.stdin.read()))"),
  \"ssh_keys\": [$SSH_KEY_ID],
  \"tags\": [\"urai-train\", \"ephemeral\"]
}")
echo "$CREATE" | python3 -c "import json,sys; d=json.load(sys.stdin); print('droplet:', d['droplet']['id'], d['droplet']['name']) if 'droplet' in d else print('DO-REJECTED:', str(d.get('message', d))[:300])"
echo "$CREATE" | python3 -c "import json,sys; sys.exit(0 if 'droplet' in json.load(sys.stdin) else 3)" || { echo "STOP: droplet not created, no spend, destroying nothing."; exit 1; }
ID=$(echo "$CREATE" | python3 -c "import json,sys; print(json.load(sys.stdin)['droplet']['id'])")

echo "== waiting for adapters asset (up to ${MAX_HOURS}h), then destroying =="
deadline=$(( $(date +%s) + MAX_HOURS * 3600 ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  if GH_TOKEN="$GH_TOKEN" gh release view urai-deps --repo etside/urai \
      --json assets --jq ".assets[].name" 2>/dev/null | grep -q "adapters-${TAG}-gpu.tgz"; then
    echo "ADAPTERS LANDED"
    break
  fi
  sleep 120
done
echo "== destroying droplet $ID =="
api -X DELETE "https://api.digitalocean.com/v2/droplets/$ID" >/dev/null
echo DONE
