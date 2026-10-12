#!/usr/bin/env python3
"""Reassemble a downloaded Urai release bundle.

Release assets over ~1.9GB are split as <name>.part00, <name>.part01, ...
(because GitHub Release files cap at 2GB). This joins them back and
verifies against SHA256SUMS.txt when present.

    python3 scripts/assemble_release.py ~/Downloads/urai-v1.1
"""

import hashlib
import sys
from pathlib import Path


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(d: Path) -> int:
    groups = {}
    for p in sorted(d.iterdir()):
        if ".part" in p.name and p.is_file():
            base = p.name.split(".part")[0]
            groups.setdefault(base, []).append(p)
    if not groups:
        print("no .partNN files found — nothing to reassemble")
        return 0
    sums = {}
    sf = d / "SHA256SUMS.txt"
    if sf.exists():
        for line in sf.read_text().splitlines():
            parts = line.split()
            if len(parts) == 2:
                sums[parts[1]] = parts[0]
    rc = 0
    for base, parts in sorted(groups.items()):
        dest = d / base
        with open(dest, "wb") as out:
            for p in parts:
                out.write(p.read_bytes())
        ok, n = True, dest.stat().st_size
        if base in sums:
            ok = sha256(dest) == sums[base]
        print(f"{'OK  ' if ok else 'FAIL'} {base} ({n >> 20} MB)")
        rc += 0 if ok else 1
    return rc


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python3 scripts/assemble_release.py <download-dir>")
    sys.exit(main(Path(sys.argv[1])))
