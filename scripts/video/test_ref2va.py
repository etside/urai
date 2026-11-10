#!/usr/bin/env python3
"""Offline CI test for the H3 Ref2VA VSA integration (no GPU, no ComfyUI).

    python3 scripts/video/test_ref2va.py

Covers:
  (a) ref2va_prompt.compile_prompt(...) emits all six section headers in order
      and validate().ok is True
  (b) an unknown camera movement raises
  (c) ref2va.patch_workflow(...) sets LoadImage image, prompt text, seed,
      width/height/length, gate sparsity and the SaveVideo prefix on the
      synthetic fixture, and returns a report
  (d) ref2va.verify_install() is honest (installed False + missing list) with
      nothing installed, and never raises

Stdlib only. Exits non-zero on any failure.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

# Point Urai at an empty ComfyUI dir and a dead server BEFORE importing ref2va,
# so the "nothing installed" path is deterministic and never touches a real box.
_TMP = tempfile.mkdtemp(prefix="urai-ref2va-test-")
os.environ["URAI_COMFY_DIR"] = _TMP
os.environ["URAI_COMFY_URL"] = "http://127.0.0.1:9"
os.environ.pop("URAI_REF2VA_NODE_DIR", None)

from jev import ref2va, ref2va_prompt  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "ref2va_vsa_4step_api.json"
FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


def by_class(wf, class_type):
    for nid, node in wf.items():
        if isinstance(node, dict) and node.get("class_type") == class_type:
            return nid, node
    return None, None


def test_prompt_sections():
    print("[a] six-section prompt compiler (<header> order + validate)")
    text = dict(
        subject_definitions="<Subject 1>: a woman in a blue trench coat.",
        summary="<Subject 1> walks through a rain-slick neon alley.",
        retention_analysis="<Subject 1> (appears in [Shot 1]): "
                           "fully_preserved - preserve facial identity.",
        detailed_description="Shot 1: " + ref2va_prompt.camera_phrase(
            "Tracking Shot", "moderate", "slow", "<Subject 1>"),
        overall_soundscape="Rain on pavement; distant traffic.",
        non_diegetic_music="Low ambient synth pad.",
    )
    prompt = ref2va_prompt.compile_prompt(**text)
    positions = []
    for sec in ref2va_prompt.SECTIONS:
        hdr = f"{sec}:"
        i = prompt.find(hdr)
        check(f"header present: {hdr}", i >= 0)
        positions.append(i)
    check("headers in canonical order",
          all(p >= 0 for p in positions) and positions == sorted(positions),
          str(positions))
    v = ref2va_prompt.validate(prompt)
    check("validate().ok is True", v.get("ok") is True, json.dumps(v))


def test_bad_camera():
    print("[b] unknown camera movement raises")
    raised = False
    try:
        ref2va_prompt.camera_phrase("Warp Speed")
    except ValueError:
        raised = True
    except Exception as e:  # wrong exception type is still a failure
        check("camera_phrase('Warp Speed') raises ValueError", False, repr(e))
        return
    check("camera_phrase('Warp Speed') raises ValueError", raised)


def test_patch_workflow():
    print("[c] patch_workflow mutates the synthetic fixture")
    original = json.loads(FIXTURE.read_text())
    out, report = ref2va.patch_workflow(
        original, prompt="PROMPT_TEXT_OK", ref_images=["a.png"], seed=42,
        width=1344, height=768, length=124, sparsity=0.75)
    check("returns (workflow, report)",
          isinstance(out, dict) and isinstance(report, dict))
    check("input workflow not mutated",
          original["6"]["inputs"]["image"] == "ref_placeholder.png")

    _, load = by_class(out, "LoadImage")
    check("LoadImage.image == 'a.png'",
          bool(load) and load["inputs"].get("image") == "a.png")
    _, te = by_class(out, "CLIPTextEncode")
    check("CLIPTextEncode.text == prompt",
          bool(te) and te["inputs"].get("text") == "PROMPT_TEXT_OK")
    _, ks = by_class(out, "KSampler")
    check("KSampler.seed == 42", bool(ks) and ks["inputs"].get("seed") == 42)
    _, lat = by_class(out, "EmptyLatentImage")
    check("latent.width == 1344", bool(lat) and lat["inputs"].get("width") == 1344)
    check("latent.height == 768", bool(lat) and lat["inputs"].get("height") == 768)
    check("latent.length == 124", bool(lat) and lat["inputs"].get("length") == 124)
    _, gate = by_class(out, "Ref2VAVSAGatePatch")
    check("gate.sparsity == 0.75",
          bool(gate) and gate["inputs"].get("sparsity") == 0.75)
    _, save = by_class(out, "SaveVideo")
    check("SaveVideo.filename_prefix == 'urai/Ref2VA_VSA'",
          bool(save) and save["inputs"].get("filename_prefix") == "urai/Ref2VA_VSA")
    check("report.patched is non-empty", bool(report.get("patched")))


def test_verify_install():
    print("[d] verify_install() honest when nothing is installed")
    try:
        st = ref2va.verify_install()
    except Exception as e:
        check("verify_install() never raises", False, repr(e))
        return
    check("verify_install() never raises", True)
    check("installed is False", st.get("installed") is False,
          str(st.get("installed")))
    check("missing is a non-empty list",
          isinstance(st.get("missing"), list) and len(st["missing"]) >= 1,
          str(st.get("missing")))
    check("no checkpoint reported valid",
          all(not m.get("valid") for m in st.get("models", [])))


def main():
    test_prompt_sections()
    test_bad_camera()
    test_patch_workflow()
    test_verify_install()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED: {', '.join(FAILURES)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
