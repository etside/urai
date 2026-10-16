# tests/fixtures

Test fixtures used by the offline CI jobs. Nothing here is a real model, node
graph, or checkpoint — these are **synthetic** inputs built only to exercise
Urai code paths without a GPU, ComfyUI, or network.

## `ref2va_vsa_4step_api.json`

A **synthetic ComfyUI API-format workflow** for the H3 Ref2VA VSA path. It is
**NOT** the real graph and is **NOT** meant to be submitted to ComfyUI. The real
graph ships with the custom node and lives at:

    <ComfyUI>/custom_nodes/ComfyUI-Ref2VA-VSA/workflows/ref2va_vsa_4step_api.json

This fixture mirrors the class_types and input keys the patcher
(`jev.ref2va.patch_workflow`) keys off, so `scripts/video/test_ref2va.py` can
prove the patcher sets:

| node id | class_type           | patched input(s)                       |
|---------|----------------------|----------------------------------------|
| `1`     | `UNETLoader`         | `unet_name` (read only)                |
| `2`     | `LoraLoaderModelOnly`| `lora_name`, `strength_model` (read)   |
| `3`     | `Ref2VAVSAGatePatch` | `sparsity`                             |
| `4`     | `MiniMaxH3SigmaShift`| `shift_video`, `shift_audio` (read)    |
| `5`     | `CLIPTextEncode`     | `text`                                 |
| `6`     | `LoadImage`          | `image`                                |
| `7`     | `EmptyLatentImage`   | `width`, `height`, `length`            |
| `8`     | `KSampler`           | `seed`                                 |
| `9`     | `SaveVideo`          | `filename_prefix`                      |

Node ids are 1-digit strings keyed in a dict, each value
`{"class_type": ..., "inputs": {...}}` — the exact ComfyUI API format. Links are
`["<node_id>", <output_index>]`; values that are not asserted are placeholder
numbers/strings.

Do not add real checkpoint names, gate paths, or prompt text here beyond what
the patcher assertions need; keep the fixture minimal and deterministic.
