# Unblocking DO GPU: limit-increase ticket (the one human step)

## Status (proven via API, $0 spent)
- Account GPU limit is **0**: `DO-REJECTED: creating this/these droplet(s)
  will exceed your GPU limit` (run 38817620591).
- Self-service `/v2/sizes` lists 0 GPU sizes = contract/GPU-gated account.
- The API cannot raise quotas. Only Support can.

## File the ticket (2 minutes)
1. https://cloud.digitalocean.com/support/tickets → New ticket.
2. Category: **Billing/Quota** (or Droplets → GPU).
3. Subject: `Request GPU droplet limit increase for ML fine-tuning`.
4. Body (paste):
   > Hi, please raise the GPU droplet limit on this account from 0 to 2
   > (region tor1 preferred). Use case: short-lived (1h, auto-destroyed)
   > single-GPU fine-tuning runs (QLoRA on a 4B open-weights model) for our
   > own AI service. Ephemeral droplets only, tagged urai-train, destroyed
   > automatically after each run. Account is in good standing and will
   > carry a card for the ~$4.41/hr H100 usage. Thank you.

## What fires automatically once the limit lifts
- `urai-gpu-run.yml` (dispatch, `phases` input 1–2): shards
  `distill-now.jsonl` via `shard_dataset.py`, spins one H100 per shard in
  parallel (cap: `droplet_limit - 1`, VPS occupies one), trains Unsloth
  QLoRA per phase, uploads each adapter to the `urai-deps` release,
  destroys every droplet at the 1h cap, deletes the ephemeral SSH key.
- Then: bench-gate each adapter, keep the winner, merge → GGUF → register.
