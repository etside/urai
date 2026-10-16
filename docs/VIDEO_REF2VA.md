# H3 Ref2VA + VSA — character-consistent reference-to-video (Urai)

Urai's **`ref2va_vsa`** profile renders a short video that keeps a character
consistent across shots by conditioning on reference images/clips/audio.
It is the **MiniMax H3 Reference-to-Video** model with the **FastH3 Visual
Sparse Attention (VSA)** gate transplanted in — the combination packaged by
Kablex as **ComfyUI-Ref2VA-VSA**.

This page is the operator's manual: what it is, what it needs, how to install
it, how the graph is wired, how to write prompts, and how to verify it. It is
deliberately honest about the failure modes.

## What it is

- **Model:** MiniMax **H3 Ref2VA** (Reference-to-Video-Audio) — turns a written
  six-section prompt plus 1..N reference media into a video clip with synced
  native audio, holding subject identity across the clip.
- **Speed patch:** **Visual Sparse Attention** (FastH3). A learned gate selects
  a fraction of the video attention tiles to compute fully; the rest are
  approximated. This is what turns a ~11-minute dense render into ~72 seconds
  on an RTX 4090.
- **Packaging:** **ComfyUI-Ref2VA-VSA** (author: Kablex) is a ComfyUI custom
  node that bundles the exact API-format workflow Urai drives. Urai does **not**
  reassemble the graph in the frontend — it patches and submits the node's own
  tested workflow, so the sampler/scheduler/sigma-shift profile is used
  verbatim.
- **License:** the ComfyUI-Ref2VA-VSA **node code is Apache-2.0**. The model
  weights it loads (MiniMax H3, the turbo LoRA, the VSA gate, the Qwen3-VL text
  encoder) are distributed by their upstream authors under **their own
  licenses/terms** — check each model card before commercial use. Urai ships no
  weights; it only knows where they belong.

## Requirements

**Hardware**

- NVIDIA GPU with **24 GB VRAM** (RTX 3090 / 4090 / A5000 / L40S). The tested
  profile peaks around **13.5 GB**, so 24 GB is the supported floor with
  headroom; smaller cards are unsupported.
- Enough disk for the checkpoints — **tens of GB**.

**Software**

- **ComfyUI ≥ 0.36** with **native MiniMax-H3** support.
- **comfy-kitchen** with the **CUDA `sol_attn`** kernel. Without it VSA does
  not accelerate (it falls back to dense) — the install script warns and you
  should not expect the 72 s number.
- **PyTorch 2.4+** on **CUDA 12.1+**.

The install script runs **on the GPU box**, not on the control VPS and not on a
laptop.

## Install

```bash
# On the GPU box:
URAI_COMFY_DIR=/opt/ComfyUI scripts/video/install_ref2va_vsa.sh --download
```

The script:

1. clones/updates `https://github.com/Kablex/ComfyUI-Ref2VA-VSA` into
   `$URAI_COMFY_DIR/custom_nodes/ComfyUI-Ref2VA-VSA`;
2. checks that `comfy_kitchen` (CUDA `sol_attn`) is importable, and **warns**
   (does not fail) if it is missing;
3. with `--download`, fetches the six checkpoints (below) into
   `$URAI_COMFY_DIR/models/*`;
4. runs `scripts/video/verify_ref2va_models.py` and prints next steps.

Without `--download` it is a **check-only** run. After installing, **restart
ComfyUI** — the nodes appear under **FastH3 / VSA → Ref2VA VSA Gate
Transplant**. Then point Urai at the server with `URAI_COMFY_URL`.

### Environment knobs

| Variable | Default | Meaning |
|---|---|---|
| `URAI_COMFY_URL` | `http://127.0.0.1:8188` | ComfyUI server Urai submits to |
| `URAI_COMFY_DIR` | `<repo>/ComfyUI` | ComfyUI root; models live under `models/` |
| `URAI_REF2VA_NODE_DIR` | `$URAI_COMFY_DIR/custom_nodes/ComfyUI-Ref2VA-VSA` | override the node dir |
| `URAI_REF2VA_SPARSITY` | `0.75` | VSA sparsity for the **video** tiles |
| `URAI_REF2VA_REPO` | `https://github.com/Kablex/ComfyUI-Ref2VA-VSA` | install-script clone source |

### The six checkpoints

Exact filenames, destinations and Hugging Face sources (as the install script
fetches them):

| # | File (exact) | Destination under `ComfyUI/models/` | Hugging Face source |
|---|---|---|---|
| 1 | `minimax_h3_ref2va_pruned_int8_convrot.safetensors` | `diffusion_models/` | `Comfy-Org/MiniMax-H3` → `diffusion_models/…` |
| 2 | `fasth3_vsa_gate.safetensors` | `loras/` | `barelymining/ComfyUI-MiniMax-H3-FastVideo` → `fasth3_vsa_gate.safetensors` |
| 3 | `minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors` | `loras/` | `lightx2v/Minimax-h3-Turbo` → `minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors` |
| 4 | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | `text_encoders/` | `Comfy-Org/MiniMax-H3` → `text_encoders/…` |
| 5 | `minimax_h3_video_vae_fp16.safetensors` | `vae/` | `Comfy-Org/MiniMax-H3` → `vae/…` |
| 6 | `minimax_h3_audio_vae_fp32.safetensors` | `vae/` | `Comfy-Org/MiniMax-H3` → `vae/…` |

`verify_install()` records per-file `present`, `size`, `valid` (a real
safetensors header, not an HTML error page or a stub) and `source`.

## Node graph (the exact 4-step wiring)

The bundled workflow is a straight chain; Urai patches values into it rather
than rebuilding it:

```
UNETLoader                      (minimax_h3_ref2va_pruned_int8_convrot.safetensors)
      │  MODEL
      ▼
LoraLoaderModelOnly             (minimax_h3_ref2v_turbo_4step…, strength_model = 1.0)
      │  MODEL
      ▼
Ref2VAVSAGatePatch              (gate_path = fasth3_vsa_gate.safetensors, sparsity = 0.75)
      │  MODEL
      ▼
MiniMaxH3SigmaShift             (shift_video = 12, shift_audio = 3)
      │  MODEL
      ▼
BasicScheduler (steps=4, scheduler=simple) ─┐
BasicGuider ───────────────────────────────┼─► SamplerCustomAdvanced (sampler=euler)
                                            │
EmptyLatentImage (1344×768, length=124) ────┘
```

- **`UNETLoader`** loads the INT8 Ref2VA diffusion model.
- **`LoraLoaderModelOnly`** applies the 4-step turbo LoRA at **strength 1.0**.
  `ModelOnly` means it does not touch the text encoder.
- **`Ref2VAVSAGatePatch`** installs the VSA gate and sets the **video-tile
  sparsity** (`0.75` = 75% of sparse-attention tiles approximated).
- **`MiniMaxH3SigmaShift`** applies the shifted noise schedule,
  `shift_video=12`, `shift_audio=3` — the tested balance for the turbo profile.
- **`BasicScheduler`** is configured for `steps=4`, `scheduler=simple`;
  **`BasicGuider`** carries the conditioning; **`SamplerCustomAdvanced`** runs
  the `euler` sampler. The latent is `1344×768`, `124` frames @ 24 fps (≈5.2 s).
- **`SaveVideo`** writes under the Urai prefix (`urai/Ref2VA_VSA` by default).

### Why reference tokens stay dense

The VSA patch operates on the **multimodal prefix boundary**. The reference
images/clips (the `<Picture N>` / `<Video N>` tokens) are part of the
conditioning the whole render depends on, so the patch **exempts that prefix**:
reference tokens are computed **100% dense**, and **sparsity applies only to
the generated video tiles**. Urai therefore exposes a single `sparsity` knob for
the video tiles and never lets it degrade the reference fidelity by
construction.

## Turbo LoRA rules

- **With the turbo LoRA (the default, recommended): `steps = 4`.** This is the
  `ref2va_vsa_4step` profile Urai ships and the one the benchmarks target.
- **Without the turbo LoRA:** the model needs the full schedule — run
  **20 steps**, sampler **`res_multistep`**. Urai does not silently switch
  profiles; if you omit the turbo LoRA you must set these yourself.
- Whatever profile you settle on, **save it**. Urai keeps the tested profile in
  `jev.ref2va.PROFILE` and echoes it in every job's metadata so the media
  gallery shows exactly what produced a clip.

The shipped profile:

| field | value |
|---|---|
| diffusion model | `minimax_h3_ref2va_pruned_int8_convrot.safetensors` |
| turbo LoRA | `minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors` @ `1.0` |
| VSA gate | `fasth3_vsa_gate.safetensors` |
| sparsity | `0.75` |
| shift video / audio | `12` / `3` |
| steps / sampler / scheduler | `4` / `euler` / `simple` |
| size / frames / fps | `1344×768` / `124` / `24` |

## The six-section prompt format

MiniMax H3 Ref2VA expects **structured English** with **exactly six sections,
in this order**. `jev/ref2va_prompt.py` compiles and validates them:

1. `subject_definitions`
2. `summary`
3. `retention_analysis`
4. `detailed_description`
5. `overall_soundscape`
6. `non_diegetic_music`

### Reference tags

References are addressed **1-based per media type**:

```
<Picture N>   <Video N>   <Audio N>   <Subject N>
```

`<Subject N>` is the entity you want preserved; `<Picture/Video/Audio N>` point
at the specific reference inputs in order.

### Retention vocabulary

Declare, per reference, **how strongly** it should be retained:

- **visual:** `fully_preserved` · `partially_preserved` · `attribute_transfer` ·
  `weak_reference`
- **audio:** `fully_copy` · `partially_copy` · `reference` · `weak_reference`

Format for a retention line:
`<tag> (context): <word> - <note>`.

### Camera-movement formula

Camera directions follow the documented formula:

```
The camera [movement] with [amplitude] at [speed] toward/revealing [target].
```

Allowed movements (validated — an unknown one **raises**): `Zoom In`, `Zoom
Out`, `Push In`, `Pull Out`, `Pan Left`, `Pan Right`, `Truck Left`, `Truck
Right`, `Tilt Up`, `Tilt Down`, `Arc Shot`, `Tracking Shot`, `Static Shot`,
`Shake Slightly`, `Shake Strongly`, `POV`, `Roll Clockwise`, `Roll
Counterclockwise`.

### Worked example

```text
subject_definitions:
<Subject 1>: a woman in a blue trench coat, platinum hair, silver pendant necklace.
<Picture 1>: a reference portrait of <Subject 1> on a plain grey backdrop.
<Video 1>: a reference clip establishing <Subject 1>'s walk cycle.

summary:
<Subject 1> walks through a rain-slick neon alley at night while the camera tracks alongside.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - preserve facial identity, platinum hair, blue trench coat, silver pendant.
<Picture 1> (style and palette): partially_preserved - keep the cool teal/magenta grade, allow a new background.
<Video 1> (camera and pacing): weak_reference - follow the broad tracking direction, not the exact frames.
<Audio 1> (voice): reference - follow timbre and accent, do not copy the source line.

detailed_description:
Shot 1: The camera tracks right with moderate amplitude at slow speed toward <Subject 1>. Rain beads on the blue trench coat and neon signage reflects in shallow puddles.

overall_soundscape:
Steady rain on metal and asphalt, distant traffic, a low rumble of thunder.

non_diegetic_music:
A sparse minor-key synth pulse at 90 BPM, no percussion.
```

### Using the compiler

```bash
# Print a compiled example + its validation report:
python3 jev/ref2va_prompt.py

# Validate a prompt from stdin:
python3 jev/ref2va_prompt.py validate < my_prompt.txt
```

In code:

```python
from jev import ref2va_prompt as rp
p = rp.compile_prompt(
    subject_definitions="<Subject 1>: a woman in a blue trench coat.",
    summary="<Subject 1> walks through a rain-slick neon alley.",
    retention_analysis=rp.retention_line(rp.subj(1), "(appears in [Shot 1])",
                                         "fully_preserved", "identity and wardrobe."),
    detailed_description="Shot 1: " + rp.camera_phrase("Tracking Shot", "moderate", "slow"),
    overall_soundscape="Rain on pavement; distant traffic.",
    non_diegetic_music="Low ambient synth pad.",
)
assert rp.validate(p)["ok"]
```

`validate()` returns `ok`, `missing`, `non_english_sections`, `reference_tags`,
and `unknown_retention_words`.

## Integration with Urai

- **Profile id:** `ref2va_vsa` (label “H3 Ref2VA VSA”, kind `video`) is surfaced
  by `GET /v1/media/profiles` alongside its availability
  (`available = installed && comfy_up`), grade and detail string.
- **Generation:** `POST /v1/videos/generations` with **`provider: "ref2va"`**
  (aliases: `ref2va-vsa`, `ref2va_vsa`, `h3`, `h3-vsa`, `vsa`). Pass
  `ref_images: [...]` (aka `reference_images`), the six-section `prompt`, plus
  optional `seed`, `width`, `height`, `settings.frames`, and `profile` overrides.
  With `provider: "auto"`, the Ref2VA path is chosen when references are
  supplied **and** the install is present **and** ComfyUI is up; otherwise Urai
  falls to a configured provider and then the local animatic.
- **Metadata / media gallery:** each job writes
  `out/videos/<job>.json` and the gallery surfaces the fields it contains — the
  exact **weights** (`diffusion_model`, `turbo_lora` + `turbo_lora_strength`,
  `vsa_gate`, text encoder and VAEs), the **settings** (`steps`, `sampler`,
  `scheduler`, `sparsity`, `shift_video`, `shift_audio`, `width`, `height`,
  `frames`, `fps`, `seed`), and the clip **`duration`**. So a rendered clip is
  always traceable to the profile that produced it.
- **Separate profiles:** Ref2VA VSA is its own profile. **Wan 3.0** (`wan3`) and
  **Seedream 4.0** (`seedream4`) remain **distinct** profiles (both API-relay,
  gated on their own keys) and are never conflated with the local Ref2VA path.

## Verification and benchmarks

```bash
# Confirm node + workflow + all six checkpoints (exit 1 if incomplete):
python3 scripts/video/verify_ref2va_models.py [--json]

# Measure wall time / peak VRAM against the 72 s baseline (GPU box only):
python3 scripts/video/bench_ref2va.py [--runs 3]
```

**Acceptance gates:** warm inference **< 90 s** and peak **VRAM < 14 GB** at
`1344×768`.

Baseline numbers (tested reference):

| configuration | warm time | peak VRAM |
|---|---|---|
| **H3 Ref2VA + VSA, turbo 4-step (this profile)** | **~72 s** | **~13.5 GB** |
| MiniMax H3 native, dense | ~650 s | — |
| VDN (video diffusion baseline) | ~135 s | — |

The VSA patch is what buys the order-of-magnitude speedup over dense H3 while
staying near the VDN baseline's quality at far lower cost.

## Honesty (what “not installed” means)

Urai never fabricates a success. If the custom node, the bundled API workflow,
any of the six checkpoints, or the ComfyUI server is missing:

- `verify_install()` / `status()` return **`installed: false`** with a
  **`missing`** list of the exact files that failed presence/integrity, and the
  UI shows **“not installed.”**
- `generate()` returns `{ok: false, installed: false, grade: "unavailable", …}`
  with an error naming the missing pieces — never a placeholder or a fake clip.
- The install script also **warns** (does not fake) when `comfy-kitchen`
  `sol_attn` is missing, because that only removes the speedup, not correctness.

Install with `scripts/video/install_ref2va_vsa.sh --download`, restart ComfyUI,
then re-run `scripts/video/verify_ref2va_models.py`.
