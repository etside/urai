#!/usr/bin/env python3
"""Urai first-party vision: decode image_url parts locally, describe via runtime.

Handles data: URLs and http(s) image URLs. PNG decoding uses stdlib (zlib);
JPEG is detected by dimensions only (no external parser AI). Output feeds the
Urai text head via runtime.complete().
"""
from __future__ import annotations

import base64
import struct
import urllib.request
import zlib

MAX_IMAGE_MB = 12


def decode_image_url(url: str) -> tuple[bytes, str]:
    """Return (raw_bytes, mime) for data: or http(s) image URLs."""
    if url.startswith("data:"):
        head, _, b64 = url.partition(",")
        mime = head[5:].split(";", 1)[0] or "image/png"
        try:
            raw = base64.b64decode(b64, validate=False)
        except Exception as e:
            raise ValueError(f"bad data URL: {e}") from e
        if len(raw) > (MAX_IMAGE_MB << 20):
            raise ValueError("image too large")
        return raw, mime
    if url.startswith(("http://", "https://")):
        req = urllib.request.Request(url, headers={"User-Agent": "urai/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                mime = r.headers.get("Content-Type", "image/png").split(";", 1)[0].strip()
                raw = r.read((MAX_IMAGE_MB << 20) + 1)
        except Exception as e:
            raise ValueError(f"fetch failed: {e}") from e
        if len(raw) > (MAX_IMAGE_MB << 20):
            raise ValueError("image too large")
        return raw, mime
    # local path
    from pathlib import Path
    raw = Path(url).read_bytes()
    suffix = Path(url).suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    if len(raw) > (MAX_IMAGE_MB << 20):
        raise ValueError("image too large")
    return raw, mime


def png_dimensions(raw: bytes) -> dict:
    if not raw.startswith(b"\x89PNG"):
        raise ValueError("not a PNG")
    ihdr = raw[16:29]
    w, h = struct.unpack(">II", ihdr[0:8])
    bit, color = ihdr[8], ihdr[9]
    # decode IDAT for mean color (best effort; filters)
    pos = 8
    idat = b""
    while pos < len(raw):
        if pos + 8 > len(raw):
            break
        (ln,) = struct.unpack(">I", raw[pos:pos + 4])
        typ = raw[pos + 4:pos + 8]
        if typ == b"IDAT":
            idat += raw[pos + 8:pos + 8 + ln]
        pos += 12 + ln
    mean = None
    try:
        dec = zlib.decompress(idat)
        ch = {0: 1, 2: 3, 4: 2, 6: 4}.get(color, 3)
        # strip filter byte per scanline
        stride = w * ch + 1
        if stride > 0 and len(dec) >= stride:
            row = dec[1:1 + w * ch]
            if row:
                mean = round(sum(row) / len(row), 2)
    except Exception:
        mean = None
    return {"width": w, "height": h, "bit_depth": bit, "color_type": color,
            "mean_byte": mean, "format": "png"}


def jpeg_dimensions(raw: bytes) -> dict:
    if not raw.startswith(b"\xff\xd8"):
        raise ValueError("not a JPEG")
    i = 2
    while i < len(raw) - 9:
        if raw[i] != 0xFF:
            i += 1
            continue
        marker = raw[i + 1]
        if marker in (0xC0, 0xC2):
            h, w = struct.unpack(">HH", raw[i + 5:i + 9])
            return {"width": w, "height": h, "format": "jpeg"}
        if marker in (0xD9, 0xDA):
            break
        ln = struct.unpack(">H", raw[i + 2:i + 4])[0]
        i += 2 + ln
    raise ValueError("could not read JPEG size")


def describe_image(url: str) -> dict:
    raw, mime = decode_image_url(url)
    if mime.startswith("image/png") or raw.startswith(b"\x89PNG"):
        d = png_dimensions(raw)
    elif mime.startswith("image/jpeg") or raw.startswith(b"\xff\xd8"):
        d = jpeg_dimensions(raw)
    else:
        # Generic: sniff by magic
        if raw.startswith(b"\x89PNG"):
            d = png_dimensions(raw)
        elif raw.startswith(b"\xff\xd8"):
            d = jpeg_dimensions(raw)
        else:
            raise ValueError(f"unsupported image mime: {mime}")
    d["mime"] = mime
    d["bytes"] = len(raw)
    return d


def complete_with_image(image_url, question, max_tokens=512, temperature=0.2) -> dict:
    """Vision in, Urai text out. Returns server-style dict incl. backend="urai"."""
    desc = describe_image(image_url)
    # Build prompt: question + honest image stats (no vendor summariser)
    w, h = desc.get("width"), desc.get("height")
    mean = desc.get("mean_byte")
    stats = (f"Image {w}x{h} {desc.get('format','')} mean_byte={mean}. ")
    prompt = (question or "Describe this image.").strip() + "\n" + stats
    from .runtime import load_runtime
    res = load_runtime().complete(
        [{"role": "user", "content": prompt}],
        max_tokens=max_tokens, temperature=temperature)
    res["image"] = desc
    res["answer"] = res["content"]
    return res
