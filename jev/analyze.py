#!/usr/bin/env python3
"""Analyze: rea-style reverse-engineering evidence for Urai (stdlib first).

Route-by-target workflow (own implementation, inspired by the
evidence-first discipline of morluto/rea):
  1. identify file kind from magic bytes (no extension trust)
  2. hash it (sha256) + size
  3. pull printable strings (min length 6, capped sample)
  4. parse container headers stdlib-only: ZIP/APK/JAR central directory,
     ELF sections/programs, PE headers, Mach-O load commands (best-effort)
  5. escalate to system tools only if present: nm, objdump, readelf, file
  6. return an Evidence record — findings + unknowns, never speculation

Read-only: never executes the target, never writes beside it.
"""

import hashlib
import os
import struct
import subprocess
import zipfile
from . import tools as _jev_tools
from pathlib import Path

STR_MIN = 6
STR_CAP = 200


def _magic(data: bytes) -> str:
    if data[:4] == b"\x7fELF":
        return "elf"
    if data[:2] == b"MZ":
        return "pe"
    if data[:4] in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf",
                    b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",
                    b"\xca\xfe\xba\xbe"):
        return "mach-o"
    if data[:4] == b"PK\x03\x04":
        return "zip"
    if data[:7] == b"#!/" or data[:2] == b"#!":
        return "script"
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"dex\n":
        return "dex"
    if data[:4] == b"\x03\x00\x08\x00":
        return "msi-cfb"
    return "unknown"


def _strings(data: bytes):
    out, cur = [], bytearray()
    for b in data:
        if 32 <= b < 127:
            cur.append(b)
        else:
            if len(cur) >= STR_MIN:
                try:
                    out.append(cur.decode())
                except Exception:
                    pass
            cur = bytearray()
    if len(cur) >= STR_MIN:
        try:
            out.append(cur.decode())
        except Exception:
            pass
    import re as _re
    def _mask(s):
        return _re.sub(r"([A-Za-z_]{0,20}(?:key|pass|token|secret)[A-Za-z_]{0,20}\s*[:=]\s*)\S+", r"\1***", s, flags=_re.IGNORECASE)
    interesting = [_mask(s) for s in out if any(k in s.lower() for k in
                   ("http", "api", "key", "pass", "token", "secret", "version",
                    "error", "fail", "Copyright", "license"))]

    interesting = [_re.sub(r"([A-Za-z_]{0,20}(?:key|pass|token|secret)[A-Za-z_]{0,20}\s*[:=]\s*)\S+",
                           r"\1***", s, flags=_re.IGNORECASE)[:160]
                   for s in interesting]
    return {"count": len(out), "interesting": interesting[:40],
            "sample": [_mask(s) for s in out[:STR_CAP]]}


def _elf(data: bytes) -> dict:
    try:
        cls = data[4]
        off = lambda o, sz: struct.unpack("<" + ("I" if cls == 1 else "Q"), data[o:o + sz])[0]
        info = {"class": 32 if cls == 1 else 64,
                "entry": hex(off(24, 4 if cls == 1 else 8))}
        return info
    except Exception as e:
        return {"error": str(e)[:100]}


def _pe(data: bytes) -> dict:
    try:
        pe_off = struct.unpack("<I", data[60:64])[0]
        machine, nsec = struct.unpack("<HH", data[pe_off + 4:pe_off + 8])
        return {"machine": hex(machine), "sections": nsec,
                "pe_offset": hex(pe_off)}
    except Exception as e:
        return {"error": str(e)[:100]}


def _zip_members(path: Path) -> dict:
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
        return {"members": len(names), "sample": names[:40],
                "is_apk": any(n == "AndroidManifest.xml" for n in names),
                "has_dex": any(n.endswith(".dex") for n in names),
                "has_js": sum(1 for n in names if n.endswith(".js"))}
    except Exception as e:
        return {"error": str(e)[:120]}


def _sys_tool(args, timeout=20) -> str:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            return ""
        return p.stdout[:3000]
    except Exception:
        return ""


def _analyze_path(path: str, max_bytes: int = 8_000_000) -> dict:
    """Return an Evidence record for the target file. Read-only."""
    p = Path(path)
    if not p.is_file():
        return {"ok": False, "error": f"not a file: {path}"}
    if p.stat().st_size > 100_000_000:
        return {"ok": False, "error": "file too large (>100MB)"}
    raw = p.read_bytes()[:max_bytes]
    kind = _magic(raw)
    ev = {"ok": True, "path": str(p), "size": p.stat().st_size,
          "sha256": hashlib.sha256(raw).hexdigest()[:16],
          "kind": kind, "findings": {}, "unknowns": []}
    ev["findings"]["strings"] = _strings(raw)
    if kind == "elf":
        ev["findings"]["elf"] = _elf(raw)
    elif kind == "pe":
        ev["findings"]["pe"] = _pe(raw)
    elif kind == "zip":
        ev["findings"]["archive"] = _zip_members(p)
    elif kind == "unknown":
        ev["unknowns"].append("unrecognized magic; strings-only evidence")
    for tool, args in (("nm", ["nm", "-D", str(p)]),
                       ("readelf", ["readelf", "-h", str(p)]),
                       ("file", ["file", "-b", str(p)])):
        if os.environ.get("URAI_ANALYZE_NOSYS"):
            break
        out = _sys_tool(args)
        if out:
            ev["findings"][tool] = out[:800]
    if not ev["findings"].get("nm") and not ev["findings"].get("readelf"):
        ev["unknowns"].append("no symbol tables recovered (nm/readelf absent or stripped)")
    return ev

def analyze(target: str = "", max_bytes: int = 8_000_000) -> dict:
    import urllib.request as _ur
    import tempfile
    import os as _os
    if not target:
        return {"ok": False, "error": "target file path or URL required"}
    if str(target).startswith(("http://", "https://")):
        try:
            data = _ur.urlopen(str(target), timeout=25).read(8_000_001)
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}
        fd, tmp = tempfile.mkstemp()
        try:
            _os.write(fd, data[:max_bytes]); _os.close(fd)
            r = _analyze_path(tmp, max_bytes=min(max_bytes, 8_000_000))
        finally:
            try: _os.unlink(tmp)
            except Exception: pass
        r["source"] = target
        return r
    try:
        path = _jev_tools._jail(target)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return _analyze_path(path, max_bytes)

__all__ = ["analyze"]
