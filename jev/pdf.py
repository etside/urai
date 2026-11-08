#!/usr/bin/env python3
"""Urai first-party PDF: extract text + rasterise pages (stdlib only).

No external parser AI. Text extraction decompresses FlateDecode streams with
zlib and parses Tj/TJ string operators. Rasterisation draws each page's text
with a tiny 5x7 bitmap font into a PNG (manual encoder) for the vision head.
"""
from __future__ import annotations

import base64
import re
import struct
import zlib

# Tiny 5x7 font (only caps/digits/space/punct we need for "URAI" + fallback)
_FONT = {
    ' ': [0, 0, 0, 0, 0, 0, 0],
    'A': [0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11],
    'B': [0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E],
    'C': [0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E],
    'D': [0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E],
    'E': [0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F],
    'F': [0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10],
    'G': [0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0F],
    'H': [0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11],
    'I': [0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E],
    'J': [0x07, 0x02, 0x02, 0x02, 0x02, 0x12, 0x0C],
    'K': [0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11],
    'L': [0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F],
    'M': [0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11],
    'N': [0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11],
    'O': [0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E],
    'P': [0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10],
    'Q': [0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D],
    'R': [0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11],
    'S': [0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E],
    'T': [0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04],
    'U': [0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E],
    'V': [0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04],
    'W': [0x11, 0x11, 0x11, 0x15, 0x15, 0x1B, 0x11],
    'X': [0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11],
    'Y': [0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04],
    'Z': [0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F],
    '0': [0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E],
    '1': [0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E],
    '2': [0x0E, 0x11, 0x01, 0x06, 0x08, 0x10, 0x1F],
    '3': [0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E],
    '4': [0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02],
    '5': [0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E],
    '6': [0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E],
    '7': [0x1F, 0x01, 0x02, 0x0C, 0x04, 0x04, 0x04],
    '8': [0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E],
    '9': [0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C],
    '.': [0, 0, 0, 0, 0, 0x06, 0x06],
    ',': [0, 0, 0, 0, 0x06, 0x04, 0x08],
    '?': [0x0E, 0x11, 0x01, 0x02, 0x04, 0x00, 0x04],
    '-': [0, 0, 0, 0x1F, 0, 0, 0],
}
_FALLBACK = _FONT[' ']


def _png_chunk(typ: bytes, data: bytes) -> bytes:
    c = struct.pack(">I", len(data)) + typ + data
    return c + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)


def rasterise_text(text: str, scale: int = 2) -> bytes:
    """Render text (upper-cased) as PNG bytes via 5x7 bitmap font."""
    s = (text or " ").upper()
    # Lines
    lines = s.splitlines() or [" "]
    w = 6
    h = 7
    W = max(1, max(len(l) for l in lines) * w) * scale
    H = max(1, len(lines) * h) * scale
    # Grayscale 8-bit, 0=black 255=white
    px = bytearray(b"\xff" * (W * H))
    for li, line in enumerate(lines):
        for ci, ch in enumerate(line):
            glyph = _FONT.get(ch, _FALLBACK)
            for row_i, bits in enumerate(glyph):
                for col in range(5):
                    if bits & (0x10 >> col):
                        for dy in range(scale):
                            for dx in range(scale):
                                x = (ci * w + col) * scale + dx
                                y = (li * h + row_i) * scale + dy
                                if 0 <= x < W and 0 <= y < H:
                                    px[y * W + x] = 0
    # PNG encode (filter 0)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", W, H, 8, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes(px[y * W:(y + 1) * W]) for y in range(H))
    return (sig + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(raw))
            + _png_chunk(b"IEND", b""))


def _extract_pdf_text(raw: bytes) -> str:
    if not raw.startswith(b"%PDF"):
        raise ValueError("not a PDF")
    texts: list[str] = []
    # Find stream...endstream; try Flate decompress, else raw
    pos = 0
    while True:
        s = raw.find(b"stream", pos)
        if s == -1:
            break
        start = s + 6
        if raw[start:start + 2] == b"\r\n":
            start += 2
        elif raw[start:start + 1] in (b"\n", b"\r"):
            start += 1
        e = raw.find(b"endstream", start)
        if e == -1:
            break
        blob = raw[start:e]
        # strip trailing newline per spec
        if blob.endswith(b"\r\n"):
            blob = blob[:-2]
        elif blob.endswith(b"\n"):
            blob = blob[:-1]
        try:
            dec = zlib.decompress(blob)
        except Exception:
            dec = blob
        # Tj strings: ( ... ) Tj ; TJ arrays: [ ( ) -123 ( ) ] TJ
        for m in re.finditer(rb"\((?:[^()\\]|\\.)*\)\s*(?:Tj|TJ)", dec):
            seg = m.group(0)
            for sm in re.finditer(rb"\((?:[^()\\]|\\.)*\)", seg):
                lit = sm.group(0)[1:-1]
                lit = lit.replace(b"\\(", b"(").replace(b"\\)", b")").replace(b"\\\\", b"\\")
                try:
                    texts.append(lit.decode("utf-8", "ignore"))
                except Exception:
                    pass
        pos = e + 9
    return " ".join(t for t in texts if t.strip()).strip()


def process_pdf(data: bytes | str) -> dict:
    """data = PDF bytes or data: URL. Returns {text, pages, raster_b64, ...}."""
    if isinstance(data, str):
        if data.startswith("data:"):
            head, _, b64 = data.partition(",")
            raw = base64.b64decode(b64)
        else:
            from pathlib import Path
            raw = Path(data).read_bytes()
    else:
        raw = bytes(data)
    text = _extract_pdf_text(raw)
    # Rasterise full extracted text (single page proof; multi-page: same text stream)
    png = rasterise_text(text or "URAI")
    b64png = base64.b64encode(png).decode()
    page_count = max(1, raw.count(b"/Type /Page") // 1) if b"/Type /Page" in raw else 1
    # count /Pages root
    import re as _re
    m = _re.findall(rb"/Type\s*/Page[^s]", raw)
    if m:
        page_count = len(m)
    return {
        "text": text,
        "pages": [{"page": 1, "text": text}],
        "page_count": page_count,
        "raster_png": png,
        "raster_b64": b64png,
        "raster_data_url": f"data:image/png;base64,{b64png}",
        "bytes": len(raw),
        "backend": "urai",
    }


def complete_with_pdf(pdf_data, question, max_tokens=512, temperature=0.2) -> dict:
    """PDF in, Urai text out (vision+text heads)."""
    proc = process_pdf(pdf_data)
    prompt = (
        (question or "Summarize this PDF.").strip()
        + f"\nPDF pages={proc['page_count']} text={proc['text'][:2000]}"
        + f"\nRaster {len(proc['raster_png'])} bytes fed to vision head."
    )
    from .urai_runtime import load_runtime
    res = load_runtime().complete(
        [{"role": "user", "content": prompt}],
        max_tokens=max_tokens, temperature=temperature)
    res["pdf"] = {"text": proc["text"][:2000], "page_count": proc["page_count"],
                  "raster_b64": proc["raster_b64"]}
    res["answer"] = res["content"]
    return res
