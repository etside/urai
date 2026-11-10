"""Minimal `.env` loader — stdlib only.

Urai is configured entirely through environment variables. To make the
documented `cp .env.example .env` workflow real, the API and CLI load a
`.env` file once at start-up:

  1. `$URAI_ENV_FILE` if set
  2. `.env` in the current directory
  3. `.env` in the repository root

Values already present in the environment always win. The format supports
comments, blank lines, `export KEY=value`, and single/double quoted values.
"""

from __future__ import annotations

import os
from pathlib import Path


def _parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        else:
            # strip an unquoted trailing comment: KEY=value  # comment
            if " #" in val:
                val = val.split(" #", 1)[0].rstrip()
        out[key] = val
    return out


def load(path: str | os.PathLike | None = None) -> list[str]:
    """Load a .env file into os.environ without overriding existing values.

    Returns the list of keys that were actually applied.
    """
    root = Path(__file__).resolve().parents[1]
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    elif os.environ.get("URAI_ENV_FILE"):
        candidates.append(Path(os.environ["URAI_ENV_FILE"]))
    else:
        candidates += [Path.cwd() / ".env", root / ".env"]

    for candidate in candidates:
        try:
            if not candidate.is_file():
                continue
            values = _parse(candidate.read_text(encoding="utf-8"))
        except OSError:
            continue
        applied = []
        for key, val in values.items():
            if key not in os.environ:
                os.environ[key] = val
                applied.append(key)
        return applied
    return []
