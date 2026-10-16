#!/usr/bin/env python3
"""Print how many self-service GPU sizes the DO account exposes.

0 means the account is contract-only (no self-service GPU droplets), so the
train router should fall back to Modal. Token-safe: reads DO_API_TOKEN from
the environment, prints only a count.
"""

import json
import os
import urllib.request

KEYS = ("gpu", "h100", "h200", "l40", "mi300", "rtx", "b300", "ada")


def main() -> None:
    tok = os.environ.get("DO_API_TOKEN", "")
    sizes = []
    if tok:
        try:
            req = urllib.request.Request(
                "https://api.digitalocean.com/v2/sizes",
                headers={"Authorization": "Bearer " + tok})
            with urllib.request.urlopen(req, timeout=30) as r:
                sizes = json.load(r).get("sizes", [])
        except Exception:
            sizes = []
    gpu = [s for s in sizes if any(k in s["slug"] for k in KEYS)]
    print(len(gpu))


if __name__ == "__main__":
    main()
