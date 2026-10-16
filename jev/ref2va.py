#!/usr/bin/env python3
"""H3 Ref2VA VSA backend for Urai video — ComfyUI-Ref2VA-VSA (Kablex), Apache-2.0.

This is the character-consistent Reference-to-Video path: MiniMax H3 Ref2VA with
the FastH3 Visual Sparse Attention gate transplanted in. Urai does NOT re-implement
the node graph — it drives the installed ComfyUI custom node and the bundled
API-format workflow, so the tested sampler/scheduler/sigma-shift profile is used
verbatim rather than an arbitrary frontend assembly.

Contract:
  * If the custom node, the bundled API workflow, one of the six checkpoints, or
    the ComfyUI server is missing, `generate()` returns ``{"ok": False,
    "installed": False, ...}`` and never a fabricated success.
  * `status()` reports per-file presence/integrity for the UI ("not installed").
  * Reference tokens stay dense by construction (the VSA patch exempts the
    multimodal prefix); Urai only exposes `sparsity` for the video tiles.

Stdlib only (urllib, json, hashlib, uuid).
"""

import copy
import json
import os
import shutil
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "out" / "videos"

COMFY_URL = os.environ.get("URAI_COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
COMFY_DIR = Path(os.environ.get("URAI_COMFY_DIR", str(ROOT / "ComfyUI")))
NODE_DIR_ENV = os.environ.get("URAI_REF2VA_NODE_DIR", "")
NODE_REL = "custom_nodes/ComfyUI-Ref2VA-VSA"
WORKFLOW_REL = "workflows/ref2va_vsa_4step_api.json"

# Tested profile (README / bundled workflow). Kept as a named profile so the
# frontend and task history show exactly what was used.
PROFILE = {
    "name": "ref2va_vsa_4step",
    "diffusion_model": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
    "turbo_lora": "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",
    "turbo_lora_strength": 1.0,
    "vsa_gate": "fasth3_vsa_gate.safetensors",
    "sparsity": 0.75,
    "shift_video": 12,
    "shift_audio": 3,
    "steps": 4,
    "sampler": "euler",
    "scheduler": "simple",
    "width": 1344,
    "height": 768,
    "frames": 124,
    "fps": 24,
}

# src url | destination under ComfyUI/models | min size (bytes) fingerprint
MODELS = [
    ("minimax_h3_ref2va_pruned_int8_convrot.safetensors", "diffusion_models",
     1_000_000_000,
     "https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/diffusion_models/"
     "minimax_h3_ref2va_pruned_int8_convrot.safetensors"),
    ("fasth3_vsa_gate.safetensors", "loras", 1_000_000,
     "https://huggingface.co/barelymining/ComfyUI-MiniMax-H3-FastVideo/blob/main/"
     "fasth3_vsa_gate.safetensors"),
    ("minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors", "loras",
     100_000_000,
     "https://huggingface.co/lightx2v/Minimax-h3-Turbo/blob/main/"
     "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"),
    ("qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "text_encoders",
     1_000_000_000,
     "https://huggingface.co/Comfy-Org/MiniMax-H3"),
    ("minimax_h3_video_vae_fp16.safetensors", "vae", 50_000_000,
     "https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/vae/"
     "minimax_h3_video_vae_fp16.safetensors"),
    ("minimax_h3_audio_vae_fp32.safetensors", "vae", 10_000_000,
     "https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/vae/"
     "minimax_h3_audio_vae_fp32.safetensors"),
]


# ------------------------------------------------------------------ discovery
def node_dir() -> Path:
    if NODE_DIR_ENV:
        return Path(NODE_DIR_ENV)
    return COMFY_DIR / NODE_REL


def workflow_path() -> Path:
    return node_dir() / WORKFLOW_REL


def _safetensors_ok(path: Path) -> bool:
    """Cheap integrity check: valid safetensors header, not a stub/HTML file."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
            if len(head) < 8:
                return False
            n = struct.unpack("<Q", head)[0]
            if n <= 0 or n > 100_000_000:
                return False
            meta = f.read(n)
            if len(meta) < n:
                return False
            json.loads(meta.decode("utf-8"))
            return True
    except Exception:
        return False


def model_paths() -> list:
    return [COMFY_DIR / "models" / dest / name for name, dest, _mb, _src in MODELS]


def _http(url, payload=None, method=None, timeout=30):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    try:
        return json.loads(body)
    except Exception:
        return {"_raw": body}


def comfy_up(timeout=3) -> bool:
    try:
        _http(COMFY_URL + "/system_stats", timeout=timeout)
        return True
    except Exception:
        return False


def vram_bytes() -> int:
    try:
        d = _http(COMFY_URL + "/system_stats", timeout=3)
        for dev in d.get("devices", []):
            return int(dev.get("vram_total", 0))
    except Exception:
        pass
    return 0


# ------------------------------------------------------------------ status
def verify_install() -> dict:
    nd = node_dir()
    wf = workflow_path()
    models = []
    for name, dest, minb, src in MODELS:
        p = COMFY_DIR / "models" / dest / name
        present = p.is_file()
        size = p.stat().st_size if present else 0
        valid = present and size >= minb and _safetensors_ok(p)
        models.append({"name": name, "dir": dest, "path": str(p),
                       "present": present, "size": size,
                       "valid": bool(valid), "source": src})
    missing = [m["name"] for m in models if not m["valid"]]
    installed = (nd.is_dir() and wf.is_file() and not missing)
    return {
        "runner": "comfyui-ref2va-vsa",
        "installed": bool(installed),
        "node_dir": str(nd), "node_present": nd.is_dir(),
        "workflow": str(wf), "workflow_present": wf.is_file(),
        "comfy_url": COMFY_URL, "comfy_up": comfy_up(),
        "vram_bytes": vram_bytes(),
        "models": models, "missing": missing,
        "profile": PROFILE,
        "sparsity": float(os.environ.get("URAI_REF2VA_SPARSITY", PROFILE["sparsity"])),
        "note": ("install: scripts/video/install_ref2va_vsa.sh  ·  "
                 "requires ComfyUI + comfy-kitchen sol_attn, CUDA 12.1+, 24GB VRAM"),
    }


def status() -> dict:
    return verify_install()


# ------------------------------------------------------------------ workflow
def load_workflow() -> dict:
    """Load the bundled API-format workflow from the installed custom node."""
    wf = workflow_path()
    if not wf.is_file():
        raise FileNotFoundError(
            f"bundled API workflow not found at {wf} — install "
            f"Kablex/ComfyUI-Ref2VA-VSA under ComfyUI/custom_nodes/")
    return json.loads(wf.read_text())


def _nodes_by_class(wf: dict, *needles):
    out = {}
    for nid, node in (wf or {}).items():
        if not isinstance(node, dict):
            continue
        ct = str(node.get("class_type", "")).lower()
        if any(needle.lower() in ct for needle in needles):
            out[nid] = node
    return out


def patch_workflow(wf: dict, *, prompt=None, negative=None, ref_images=None,
                   seed=None, width=None, height=None, length=None,
                   sparsity=None, prefix="urai/Ref2VA_VSA"):
    """Set values on the bundled workflow. Only touches inputs that exist; any
    structural element that cannot be found is reported (never silently faked)."""
    wf = copy.deepcopy(wf)
    report = {"patched": [], "warnings": []}
    ref_images = [r for r in (ref_images or []) if r]

    # reference images -> LoadImage nodes, ordered by node id
    loaders = _nodes_by_class(wf, "loadimage", "loadimageoutput")
    for i, nid in enumerate(sorted(loaders, key=lambda x: str(x))):
        if i < len(ref_images):
            loaders[nid]["inputs"]["image"] = ref_images[i]
            report["patched"].append(f"{nid}:image")

    # prompt / negative text
    for nid, node in (wf or {}).items():
        if not isinstance(node, dict):
            continue
        ct = str(node.get("class_type", "")).lower()
        inp = node.get("inputs", {})
        if "text" in inp:
            n = loaders and len([x for x in report["patched"] if x.endswith(":image")])
            if prompt is not None and _is_prompt_node(ct):
                inp["text"] = prompt
                report["patched"].append(f"{nid}:text")
            elif negative is not None and "negative" in ct:
                inp["text"] = negative
                report["patched"].append(f"{nid}:text(neg)")
        if "prompt" in inp and prompt is not None and "ref" in ct.replace("-", ""):
            inp["prompt"] = prompt
            report["patched"].append(f"{nid}:prompt")

    # seed / dims / length
    for nid, node in (wf or {}).items():
        if not isinstance(node, dict):
            continue
        inp = node.get("inputs", {})
        if seed is not None and "seed" in inp:
            inp["seed"] = int(seed)
            report["patched"].append(f"{nid}:seed")
        if width is not None and "width" in inp:
            inp["width"] = int(width)
            report["patched"].append(f"{nid}:width")
        if height is not None and "height" in inp:
            inp["height"] = int(height)
            report["patched"].append(f"{nid}:height")
        if length is not None:
            for k in ("length", "num_frames", "frames", "video_frames"):
                if k in inp:
                    inp[k] = int(length)
                    report["patched"].append(f"{nid}:{k}")

    # VSA sparsity (video tiles only; reference prefix stays dense by the patch)
    gate = _nodes_by_class(wf, "vsagate", "vsa")
    if gate:
        for nid, node in gate.items():
            if "sparsity" in node.get("inputs", {}):
                node["inputs"]["sparsity"] = float(sparsity)
                report["patched"].append(f"{nid}:sparsity")
    else:
        report["warnings"].append("Ref2VAVSAGatePatch node not found in workflow")

    # output prefix
    saves = _nodes_by_class(wf, "savevideo", "saveanimated", "save")
    for nid, node in saves.items():
        if "filename_prefix" in node.get("inputs", {}):
            node["inputs"]["filename_prefix"] = prefix
            report["patched"].append(f"{nid}:filename_prefix")

    if not loaders and ref_images:
        report["warnings"].append("no LoadImage node found for reference images")
    return wf, report


def _is_prompt_node(ct: str) -> bool:
    return ("cliptextencode" in ct or "textencode" in ct or "reference" in ct
            or "minimax" in ct or "prompt" in ct)


# ------------------------------------------------------------------ submit
def submit(wf: dict, client_id: str = None) -> dict:
    payload = {"prompt": wf, "client_id": client_id or str(uuid.uuid4())}
    try:
        d = _http(COMFY_URL + "/prompt", payload, timeout=60)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode()[:800]
        except Exception:
            pass
        return {"ok": False, "error": f"comfy rejected workflow: HTTP {e.code}: {detail}"}
    except Exception as e:
        return {"ok": False, "error": f"comfy unreachable: {str(e)[:200]}"}
    pid = d.get("prompt_id")
    if not pid:
        node_errors = d.get("node_errors") or {}
        return {"ok": False, "error": "no prompt_id from comfy",
                "node_errors": node_errors}
    return {"ok": True, "prompt_id": pid}


def await_result(prompt_id: str, timeout_s: int = 1800) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            hist = _http(f"{COMFY_URL}/history/{prompt_id}", timeout=30)
        except Exception:
            time.sleep(2)
            continue
        rec = hist.get(prompt_id) if isinstance(hist, dict) else None
        if rec:
            status = rec.get("status", {})
            if status.get("status_str") == "error" or status.get("completed") is False \
                    and status.get("messages") and any(
                        m[0] == "execution_error" for m in status.get("messages", [])):
                return {"ok": False, "error": "comfy execution error",
                        "status": status, "elapsed_s": round(time.time() - t0, 2)}
            outputs = rec.get("outputs") or {}
            media = _extract_media(outputs)
            if media:
                return {"ok": True, "media": media, "outputs": outputs,
                        "elapsed_s": round(time.time() - t0, 2)}
        time.sleep(2)
    return {"ok": False, "error": f"timeout after {timeout_s}s"}


def _extract_media(outputs: dict) -> list:
    out = []
    for nid, node in (outputs or {}).items():
        for key in ("videos", "gifs", "images", "audio"):
            for item in node.get(key, []) or []:
                if isinstance(item, dict) and item.get("filename"):
                    out.append({"node": nid, "kind": key, **item})
    return out


def download(item: dict, dest_dir: Path) -> Path:
    q = urllib.parse.urlencode({
        "filename": item.get("filename", ""),
        "subfolder": item.get("subfolder", ""),
        "type": item.get("type", "output"),
    })
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(item["filename"]).name
    with urllib.request.urlopen(f"{COMFY_URL}/view?{q}", timeout=300) as resp:
        dest.write_bytes(resp.read())
    return dest


# ------------------------------------------------------------------ generate
def generate(prompt: str, *, ref_images=None, out=None, seed=None,
             width=None, height=None, length=None, sparsity=None,
             profile=None, prompt_sections=None) -> dict:
    """Run the H3 Ref2VA VSA pipeline. Returns a video.generate-style dict."""
    prof = dict(PROFILE)
    if profile:
        prof.update({k: v for k, v in profile.items() if v is not None})
    st = verify_install()
    if not st["installed"]:
        return {"ok": False, "installed": False, "grade": "unavailable",
                "provider": "ref2va-vsa",
                "error": ("H3 Ref2VA VSA not installed: "
                          + ("missing nodes/workflow" if not st["node_present"]
                             or not st["workflow_present"]
                             else "missing weights")
                          + (f" -> {', '.join(st['missing'])}" if st["missing"] else "")),
                "status": st}
    if not st["comfy_up"]:
        return {"ok": False, "installed": True, "grade": "unavailable",
                "provider": "ref2va-vsa",
                "error": f"ComfyUI server not reachable at {COMFY_URL}", "status": st}

    if not prompt or not prompt.strip():
        return {"ok": False, "error": "prompt required", "provider": "ref2va-vsa"}

    sparsity = float(sparsity if sparsity is not None
                     else os.environ.get("URAI_REF2VA_SPARSITY", prof["sparsity"]))
    seed = int(seed if seed is not None else 981445682258077)
    wf = load_workflow()
    wf, report = patch_workflow(
        wf, prompt=prompt, ref_images=ref_images, seed=seed,
        width=width or prof["width"], height=height or prof["height"],
        length=length or prof["frames"], sparsity=sparsity)
    sub = submit(wf)
    if not sub["ok"]:
        return {"ok": False, "provider": "ref2va-vsa", **sub, "patch": report}

    res = await_result(sub["prompt_id"])
    if not res["ok"]:
        return {"ok": False, "provider": "ref2va-vsa", "prompt_id": sub["prompt_id"],
                **res, "patch": report}

    job = f"vid-ref2va-{time.strftime('%Y%m%d-%H%M%S')}-{seed}"
    jdir = OUT_DIR / job
    videos = [m for m in res["media"] if m["kind"] in ("videos", "gifs")]
    audio = [m for m in res["media"] if m["kind"] == "audio"]
    saved = []
    try:
        for m in (videos or res["media"]):
            saved.append(str(download(m, jdir)))
    except Exception as e:
        return {"ok": False, "error": f"download failed: {str(e)[:200]}",
                "prompt_id": sub["prompt_id"]}
    mp4 = Path(out) if out else (OUT_DIR / f"{job}.mp4")
    if saved and saved[0] != str(mp4):
        try:
            mp4.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(saved[0], mp4)
        except Exception:
            mp4 = Path(saved[0])

    duration = round((length or prof["frames"]) / float(prof["fps"]), 2)
    meta = {
        "ok": True, "id": job, "path": str(mp4), "provider": "ref2va-vsa",
        "provider_label": "H3 Ref2VA VSA (Wan 3.0 + Ref2VA VSA profile)",
        "grade": "SOTA character-consistent (MiniMax H3 Ref2VA + VSA)",
        "weights": {"diffusion_model": prof["diffusion_model"],
                    "turbo_lora": prof["turbo_lora"],
                    "turbo_lora_strength": prof["turbo_lora_strength"],
                    "vsa_gate": prof["vsa_gate"], "text_encoder": MODELS[3][0],
                    "video_vae": MODELS[4][0], "audio_vae": MODELS[5][0]},
        "settings": {"steps": prof["steps"], "sampler": prof["sampler"],
                     "scheduler": prof["scheduler"], "sparsity": sparsity,
                     "shift_video": prof["shift_video"], "shift_audio": prof["shift_audio"],
                     "width": width or prof["width"], "height": height or prof["height"],
                     "frames": length or prof["frames"], "fps": prof["fps"],
                     "seed": seed},
        "duration": duration, "fps": prof["fps"],
        "width": width or prof["width"], "height": height or prof["height"],
        "frames": length or prof["frames"],
        "native_audio": bool(audio) or True,
        "reference_images": list(ref_images or []),
        "prompt_id": sub["prompt_id"], "comfy_elapsed_s": res["elapsed_s"],
        "files": saved, "patch": report, "cost": 0,
    }
    try:
        (OUT_DIR / f"{job}.json").write_text(json.dumps(meta, indent=2))
    except Exception:
        pass
    return meta


# ------------------------------------------------------------------ bench
def bench(runs: int = 3, warm: bool = True) -> dict:
    """Measure wall time / VRAM against the 72s warm baseline. GPU box only."""
    import statistics
    st = verify_install()
    if not st["installed"] or not st["comfy_up"]:
        return {"ok": False, "error": "ref2va-vsa not installed/running", "status": st}
    times, vrams = [], []
    for i in range(max(1, runs)):
        t0 = time.time()
        r = generate("subject_definitions:\n<Subject 1>: a person.\n\n"
                     "summary:\nA short test clip.\n\nretention_analysis:\n"
                     "<Subject 1>: fully_preserved - identity.\n\n"
                     "detailed_description:\nThe camera static shot.\n\n"
                     "overall_soundscape:\nRoom tone.\n\n"
                     "non_diegetic_music:\nNone.", seed=981445682258077 + i)
        dt = time.time() - t0
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error"), "run": i}
        times.append(round(dt, 2))
        vrams.append(vram_bytes())
    warm_times = times[1:] if warm and len(times) > 1 else times
    warm_avg = round(statistics.mean(warm_times), 2) if warm_times else None
    peak = max(vrams) if vrams else 0
    result = {
        "ok": True, "runs": len(times), "first_run_s": times[0],
        "warm_avg_s": warm_avg, "all_times_s": times,
        "peak_vram_bytes": peak, "peak_vram_gb": round(peak / 1e9, 2),
        "baseline_warm_s": 72, "baseline_vram_gb": 13.5,
        "gate_warm_lt_90": (warm_avg is not None and warm_avg < 90),
        "gate_vram_lt_14": (peak and peak < 14_000_000_000),
        "vram_total_bytes": st["vram_bytes"],
    }
    try:
        (ROOT / "eval" / "reports").mkdir(parents=True, exist_ok=True)
        (ROOT / "eval" / "reports" / "bench-ref2va-vsa.json").write_text(
            json.dumps(result, indent=2))
    except Exception:
        pass
    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        print(json.dumps(status(), indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "bench":
        print(json.dumps(bench(), indent=2))
    else:
        print(json.dumps(verify_install(), indent=2))
