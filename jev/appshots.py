#!/usr/bin/env python3
"""jev/appshots.py — Screen capture for Urai context (PersonalJarvis Appshots concept).

Appshots: capture the current screen or a window region, feed it as vision
context to Urai so it can see what you're looking at.

PersonalJarvis: "Press two keys to show Jarvis the window you are looking at"
Urai version: API endpoint + tool that captures screen and feeds to vision model.

Requires: scrot (Linux), screencapture (macOS), or PIL/mss (cross-platform).
Gracefully unavailable if none present.
"""
from __future__ import annotations
import base64, os, subprocess, tempfile, time
from pathlib import Path

def capture_screen(region: tuple | None = None, out: str | None = None) -> dict:
    """Capture full screen or a region (x, y, w, h).
    Returns {ok, path, b64_png, width, height, captured_at}.
    """
    t0 = time.time()
    if not out:
        out = f"/tmp/urai_appshot_{int(t0)}.png"

    # Try mss (best cross-platform)
    try:
        import mss, mss.tools  # type: ignore
        with mss.mss() as sct:
            if region:
                x, y, w, h = region
                mon = {"left": x, "top": y, "width": w, "height": h}
            else:
                mon = sct.monitors[1]  # primary monitor
            sct_img = sct.grab(mon)
            mss.tools.to_png(sct_img.rgb, sct_img.size, output=out)
            b64 = base64.b64encode(Path(out).read_bytes()).decode()
            return {"ok": True, "path": out, "b64_png": b64,
                    "width": sct_img.width, "height": sct_img.height,
                    "captured_at": t0, "backend": "mss"}
    except ImportError:
        pass

    # Try scrot (Linux)
    if os.name != "nt":
        cmd = ["scrot"]
        if region:
            x, y, w, h = region
            cmd += ["-a", f"{x},{y},{w},{h}"]
        cmd.append(out)
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=10)
            if r.returncode == 0 and Path(out).exists():
                b64 = base64.b64encode(Path(out).read_bytes()).decode()
                return {"ok": True, "path": out, "b64_png": b64,
                        "captured_at": t0, "backend": "scrot"}
        except Exception:
            pass

    # Try PIL ImageGrab
    try:
        from PIL import ImageGrab  # type: ignore
        bbox = region if region else None
        img = ImageGrab.grab(bbox=bbox)
        img.save(out)
        b64 = base64.b64encode(Path(out).read_bytes()).decode()
        return {"ok": True, "path": out, "b64_png": b64,
                "width": img.width, "height": img.height,
                "captured_at": t0, "backend": "pil"}
    except ImportError:
        pass

    return {"ok": False, "error": "No screen capture tool available. "
            "Install: pip install mss  OR  apt install scrot",
            "path": "", "b64_png": "", "captured_at": t0}


def capture_and_ask(question: str = "What do you see on screen?",
                    region: tuple | None = None) -> dict:
    """Capture screen and ask Urai's vision model about it.
    Returns {ok, answer, screenshot_path}.
    """
    shot = capture_screen(region=region)
    if not shot["ok"]:
        return {"ok": False, "error": shot["error"], "answer": "", "screenshot_path": ""}
    try:
        from .vision import see
        result = see(shot["b64_png"], question)
        return {"ok": result.get("ok", False),
                "answer": result.get("answer", ""),
                "screenshot_path": shot["path"]}
    except Exception as e:
        return {"ok": False, "error": str(e), "answer": "",
                "screenshot_path": shot["path"]}


def list_recent_shots(limit: int = 10) -> list[dict]:
    """List recent appshot files from /tmp."""
    shots = sorted(Path("/tmp").glob("urai_appshot_*.png"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"path": str(p), "size": p.stat().st_size,
             "ts": p.stat().st_mtime} for p in shots[:limit]]
