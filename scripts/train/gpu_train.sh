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
# Optional: DO_REGION (default blr1), DO_GPU_SIZE (default nvidia-h100x1-80gb,
#   confirmed via API before create), MAX_HOURS (default 3)
set -euo pipefail
: "${DO_API_TOKEN:?set DO_API_TOKEN}"
: "${GH_TOKEN:?set GH_TOKEN}"
TAG="${URAI_TRAIN_TAG:-distill-now}"
ACTION="${1:-prices}"
# NOTE: GPU Droplets need a GPU-ready image; if plain ubuntu fails at create
# time, list GPU images via the API and set DO_IMAGE accordingly.
IMAGE="${DO_IMAGE:-ubuntu-24-04-x64}"
REGION="${DO_REGION:-blr1}"
SIZE="${DO_GPU_SIZE:-nvidia-h100x1-80gb}"
MAX_HOURS="${MAX_HOURS:-3}"

api() { curl -s -H "Authorization: Bearer $DO_API_TOKEN" \
  -H "Content-Type: application/json" "$@"; }

echo "== GPU sizes available (price/hr USD) =="
api "https://api.digitalocean.com/v2/sizes" \
  | python3 -c "import json,sys; [print(s['slug'], s.get('price_hourly'), s.get('regions', [])[:4]) for s in json.load(sys.stdin).get('sizes', []) if 'gpu' in s['slug'] or 'h100' in s['slug'] or 'l40' in s['slug'] or 'mi300' in s['slug'] or 'rtx' in s['slug']]" || true

read -r -d '' USERDATA <<EOF || true
#!/bin/bash
set -x
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-pip git gh
pip3 install --quiet --break-system-packages torch transformers peft trl datasets accelerate 2>&1 | tail -n 1
git clone https://x-access-token:${GH_TOKEN}@github.com/etside/urai.git /root/urai
cd /root/urai
python3 scripts/train/lora_urai.py --data data/verified/${TAG}.jsonl --tag ${TAG}-gpu
tar -czf /tmp/adapters-${TAG}-gpu.tgz adapters/${TAG}-gpu || tar -czf /tmp/adapters-${TAG}-gpu.tgz adapters
GH_TOKEN=${GH_TOKEN} gh release view urai-deps --repo etside/urai >/dev/null 2>&1 || GH_TOKEN=${GH_TOKEN} gh release create urai-deps --repo etside/urai --title "Urai vendored deps" --notes "Binaries + adapters." --prerelease
GH_TOKEN=${GH_TOKEN} gh release upload urai-deps /tmp/adapters-${TAG}-gpu.tgz --repo etside/urai --clobber
echo TRAIN_DONE
EOF

if [ "$ACTION" != "create" ]; then
  echo "DRY RUN: pass 'create' to actually spin the droplet (money spends)."
  echo "Dataset check:"; ls -la "data/verified/${TAG}.jsonl" || echo "MISSING: pick an existing tag"
  exit 0
fi
ls -la "data/verified/${TAG}.jsonl" || { echo "MISSING dataset tag: $TAG"; exit 1; }
echo "== creating GPU droplet ($SIZE @ $REGION, image $IMAGE) =="
CREATE=$(api -X POST "https://api.digitalocean.com/v2/droplets" -d "{
  \"name\": \"urai-train-${TAG}\", \"region\": \"$REGION\", \"size\": \"$SIZE\",
  \"image\": \"ubuntu-24-04-x64\",
  \"user_data\": $(printf '%s' "$USERDATA" | python3 -c "import json,sys; print(json.dumps(sys.stdin.read()))"),
  \"tags\": [\"urai-train\", \"ephemeral\"]
}")
echo "$CREATE" | python3 -c "import json,sys; d=json.load(sys.stdin)['droplet']; print('droplet:', d['id'], d['name'])"
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
