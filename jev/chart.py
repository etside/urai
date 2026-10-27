"""
urai/chart.py — Data visualization capability for Urai AI.

Provides chart generation from raw data. Uses matplotlib when available;
falls back to a pure-stdlib SVG generator that produces real visual output
(no placeholder text). Never raises — always returns a result dict.

Port inspired by OpenManus's chart_visualization tool.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import time
from typing import Any


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chart(
    data: list | dict,
    kind: str = "bar",
    title: str = "",
    xlabel: str = "",
    ylabel: str = "",
    out: str = "",
) -> dict:
    """Generate a chart from data.

    Parameters
    ----------
    data:
        - list of numeric values          → treated as y-values, x = index
        - list of {"x": ..., "y": ...}    → scatter / line points
        - list of {"label": ..., "value": ...} → categorical bar/pie
        - dict {label: value}             → categorical bar/pie
    kind:
        "bar" | "line" | "pie" | "scatter" | "histogram"
    title, xlabel, ylabel:
        Axis / title labels.
    out:
        Output file path. Defaults to /tmp/urai_chart_<hash>.png (or .svg).

    Returns
    -------
    dict with keys:
        ok        bool   — True on success
        path      str    — path to the generated file
        b64_png   str    — base64-encoded file content (PNG or SVG)
        kind      str    — the chart kind used
        backend   str    — "matplotlib" or "svg"
        error     str    — populated only when ok=False
    """
    try:
        norm = _normalise_data(data, kind)
        if not out:
            tag = hashlib.md5(json.dumps(norm, default=str).encode()).hexdigest()[:8]
            out = f"/tmp/urai_chart_{tag}"

        try:
            import matplotlib  # noqa: F401
            result = _matplotlib_chart(norm, kind, title, xlabel, ylabel, out)
            result["backend"] = "matplotlib"
        except ImportError:
            result = _svg_chart(norm, kind, title, xlabel, ylabel, out)
            result["backend"] = "svg"

        result["kind"] = kind
        return result

    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "path": "", "b64_png": "", "kind": kind, "error": str(exc)}


def data_to_chart(prompt: str, data_text: str) -> dict:
    """Ask Urai's LLM to choose the best chart type and parameters, then generate it.

    Falls back to a sensible default if the LLM is unavailable.

    Returns the same shape as :func:`chart`.
    """
    kind, title, xlabel, ylabel, parsed = _llm_choose_chart(prompt, data_text)
    return chart(parsed, kind=kind, title=title, xlabel=xlabel, ylabel=ylabel)


# ---------------------------------------------------------------------------
# Data normalisation
# ---------------------------------------------------------------------------

def _normalise_data(data: list | dict, kind: str) -> list:
    """Return a list of {"label": str, "x": float, "y": float} records."""
    if isinstance(data, dict):
        return [{"label": str(k), "x": float(i), "y": float(v)}
                for i, (k, v) in enumerate(data.items())]

    if not isinstance(data, list) or len(data) == 0:
        raise ValueError("data must be a non-empty list or dict")

    first = data[0]

    if isinstance(first, (int, float)):
        return [{"label": str(i), "x": float(i), "y": float(v)}
                for i, v in enumerate(data)]

    if isinstance(first, dict):
        # {"x": ..., "y": ...} or {"label": ..., "value": ...}
        if "y" in first:
            return [
                {
                    "label": str(r.get("label", r.get("x", i))),
                    "x": float(r.get("x", i)),
                    "y": float(r["y"]),
                }
                for i, r in enumerate(data)
            ]
        if "value" in first:
            return [
                {"label": str(r.get("label", i)), "x": float(i), "y": float(r["value"])}
                for i, r in enumerate(data)
            ]

    # last resort: stringify everything
    return [{"label": str(i), "x": float(i), "y": float(v) if isinstance(v, (int, float)) else 0.0}
            for i, v in enumerate(data)]


# ---------------------------------------------------------------------------
# Matplotlib backend
# ---------------------------------------------------------------------------

def _matplotlib_chart(
    norm: list,
    kind: str,
    title: str,
    xlabel: str,
    ylabel: str,
    out: str,
) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415

    fig, ax = plt.subplots(figsize=(9, 5))
    xs = [r["x"] for r in norm]
    ys = [r["y"] for r in norm]
    labels = [r["label"] for r in norm]

    if kind == "bar":
        ax.bar(labels, ys, color="#4C72B0")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=30, ha="right")
    elif kind == "line":
        ax.plot(xs, ys, marker="o", color="#4C72B0")
    elif kind == "scatter":
        ax.scatter(xs, ys, color="#4C72B0", alpha=0.7)
    elif kind == "histogram":
        ax.hist(ys, bins=min(20, len(ys)), color="#4C72B0", edgecolor="white")
    elif kind == "pie":
        ax.pie(ys, labels=labels, autopct="%1.1f%%")
    else:
        ax.bar(labels, ys, color="#4C72B0")

    if title:
        ax.set_title(title)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)

    fig.tight_layout()
    path = out if out.endswith(".png") else out + ".png"
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)

    with open(path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode()

    return {"ok": True, "path": path, "b64_png": b64}


# ---------------------------------------------------------------------------
# Pure-stdlib SVG fallback
# ---------------------------------------------------------------------------

_SVG_COLORS = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3",
    "#937860", "#DA8BC3", "#8C8C8C", "#CCB974", "#64B5CD",
]

_SVG_HEADER = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" '
    'width="{W}" height="{H}" style="background:#fff;font-family:sans-serif">\n'
)


def _svg_chart(
    norm: list,
    kind: str,
    title: str,
    xlabel: str,
    ylabel: str,
    out: str,
) -> dict:
    """SVG chart generator — no external deps."""
    dispatch = {
        "bar": _svg_bar,
        "line": _svg_line,
        "pie": _svg_pie,
        "scatter": _svg_scatter,
        "histogram": _svg_histogram,
    }
    fn = dispatch.get(kind, _svg_bar)
    svg = fn(norm, title, xlabel, ylabel)

    path = out if out.endswith(".svg") else out + ".svg"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg)

    b64 = base64.b64encode(svg.encode()).decode()
    return {"ok": True, "path": path, "b64_png": b64}


def _svg_bar(norm: list, title: str, xlabel: str, ylabel: str) -> str:
    W, H = 720, 420
    pad_l, pad_r, pad_t, pad_b = 60, 20, 50, 80
    cw = W - pad_l - pad_r
    ch = H - pad_t - pad_b

    ys = [r["y"] for r in norm]
    labels = [r["label"] for r in norm]
    max_y = max(ys) if ys else 1
    min_y = min(0.0, min(ys))
    span = max_y - min_y or 1

    n = len(norm)
    group_w = cw / n
    bar_w = max(2, group_w * 0.6)

    lines = [_SVG_HEADER.format(W=W, H=H)]

    # axes
    lines.append(f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t+ch}" stroke="#888" stroke-width="1.5"/>')
    lines.append(f'<line x1="{pad_l}" y1="{pad_t+ch}" x2="{pad_l+cw}" y2="{pad_t+ch}" stroke="#888" stroke-width="1.5"/>')

    # y gridlines
    for tick in range(5):
        ty = pad_t + ch - (tick / 4) * ch
        tv = min_y + (tick / 4) * span
        lines.append(f'<line x1="{pad_l}" y1="{ty:.1f}" x2="{pad_l+cw}" y2="{ty:.1f}" stroke="#eee" stroke-width="1"/>')
        lines.append(f'<text x="{pad_l-5}" y="{ty+4:.1f}" text-anchor="end" font-size="11" fill="#555">{tv:.1f}</text>')

    # bars
    for i, (y, label) in enumerate(zip(ys, labels)):
        bx = pad_l + i * group_w + (group_w - bar_w) / 2
        bar_h = abs(y - min_y) / span * ch
        by = pad_t + ch - (y - min_y) / span * ch
        color = _SVG_COLORS[i % len(_SVG_COLORS)]
        lines.append(
            f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" '
            f'height="{bar_h:.1f}" fill="{color}" rx="2"/>'
        )
        # x label
        lx = bx + bar_w / 2
        lines.append(
            f'<text x="{lx:.1f}" y="{pad_t+ch+16}" text-anchor="middle" '
            f'font-size="11" fill="#333" transform="rotate(30,{lx:.1f},{pad_t+ch+16})">'
            f'{_esc(label)}</text>'
        )
        # value on top
        if bar_h > 14:
            lines.append(
                f'<text x="{lx:.1f}" y="{by-3:.1f}" text-anchor="middle" '
                f'font-size="10" fill="#fff">{y:.1f}</text>'
            )

    _svg_titles(lines, title, xlabel, ylabel, W, H, pad_l, pad_t, cw, ch)
    lines.append("</svg>")
    return "".join(lines)


def _svg_line(norm: list, title: str, xlabel: str, ylabel: str) -> str:
    W, H = 720, 420
    pad_l, pad_r, pad_t, pad_b = 60, 20, 50, 60
    cw = W - pad_l - pad_r
    ch = H - pad_t - pad_b

    xs = [r["x"] for r in norm]
    ys = [r["y"] for r in norm]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max_x - min_x or 1
    span_y = max_y - min_y or 1

    def to_svg(x, y):
        return (
            pad_l + (x - min_x) / span_x * cw,
            pad_t + ch - (y - min_y) / span_y * ch,
        )

    lines = [_SVG_HEADER.format(W=W, H=H)]
    lines.append(f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t+ch}" stroke="#888" stroke-width="1.5"/>')
    lines.append(f'<line x1="{pad_l}" y1="{pad_t+ch}" x2="{pad_l+cw}" y2="{pad_t+ch}" stroke="#888" stroke-width="1.5"/>')

    pts = [to_svg(x, y) for x, y in zip(xs, ys)]
    polyline = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
    lines.append(f'<polyline points="{polyline}" fill="none" stroke="{_SVG_COLORS[0]}" stroke-width="2.5"/>')
    for px, py in pts:
        lines.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{_SVG_COLORS[0]}"/>')

    _svg_titles(lines, title, xlabel, ylabel, W, H, pad_l, pad_t, cw, ch)
    lines.append("</svg>")
    return "".join(lines)


def _svg_pie(norm: list, title: str, xlabel: str, ylabel: str) -> str:
    W, H = 600, 460
    cx, cy, r = W // 2, H // 2 - 10, 160
    total = sum(r2["y"] for r2 in norm) or 1

    lines = [_SVG_HEADER.format(W=W, H=H)]
    angle = -math.pi / 2

    for i, rec in enumerate(norm):
        frac = rec["y"] / total
        sweep = frac * 2 * math.pi
        x1 = cx + r * math.cos(angle)
        y1 = cy + r * math.sin(angle)
        x2 = cx + r * math.cos(angle + sweep)
        y2 = cy + r * math.sin(angle + sweep)
        large = 1 if sweep > math.pi else 0
        color = _SVG_COLORS[i % len(_SVG_COLORS)]
        lines.append(
            f'<path d="M{cx},{cy} L{x1:.2f},{y1:.2f} '
            f'A{r},{r} 0 {large},1 {x2:.2f},{y2:.2f} Z" fill="{color}"/>'
        )
        # label at midpoint
        mid = angle + sweep / 2
        lx = cx + (r * 0.65) * math.cos(mid)
        ly = cy + (r * 0.65) * math.sin(mid)
        lines.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
            f'font-size="11" fill="#fff">{frac*100:.1f}%</text>'
        )
        # legend
        ly2 = 30 + i * 18
        lines.append(f'<rect x="10" y="{ly2}" width="14" height="14" fill="{color}" rx="2"/>')
        lines.append(f'<text x="28" y="{ly2+11}" font-size="12" fill="#333">{_esc(rec["label"])}</text>')
        angle += sweep

    if title:
        lines.append(f'<text x="{W//2}" y="20" text-anchor="middle" font-size="15" font-weight="bold" fill="#222">{_esc(title)}</text>')
    lines.append("</svg>")
    return "".join(lines)


def _svg_scatter(norm: list, title: str, xlabel: str, ylabel: str) -> str:
    W, H = 720, 420
    pad_l, pad_r, pad_t, pad_b = 60, 20, 50, 60
    cw = W - pad_l - pad_r
    ch = H - pad_t - pad_b

    xs = [r["x"] for r in norm]
    ys = [r["y"] for r in norm]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max_x - min_x or 1
    span_y = max_y - min_y or 1

    lines = [_SVG_HEADER.format(W=W, H=H)]
    lines.append(f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t+ch}" stroke="#888" stroke-width="1.5"/>')
    lines.append(f'<line x1="{pad_l}" y1="{pad_t+ch}" x2="{pad_l+cw}" y2="{pad_t+ch}" stroke="#888" stroke-width="1.5"/>')

    for i, (x, y) in enumerate(zip(xs, ys)):
        px = pad_l + (x - min_x) / span_x * cw
        py = pad_t + ch - (y - min_y) / span_y * ch
        lines.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="5" fill="{_SVG_COLORS[0]}" opacity="0.7"/>')

    _svg_titles(lines, title, xlabel, ylabel, W, H, pad_l, pad_t, cw, ch)
    lines.append("</svg>")
    return "".join(lines)


def _svg_histogram(norm: list, title: str, xlabel: str, ylabel: str) -> str:
    ys = [r["y"] for r in norm]
    bins = min(20, len(ys))
    if not ys:
        return _svg_bar(norm, title, xlabel, ylabel)

    min_v, max_v = min(ys), max(ys)
    span = max_v - min_v or 1
    counts = [0] * bins
    for v in ys:
        b = int((v - min_v) / span * (bins - 1e-9))
        counts[b] += 1

    edges = [min_v + i / bins * span for i in range(bins)]
    hist_norm = [{"label": f"{e:.1f}", "x": float(i), "y": float(c)}
                 for i, (e, c) in enumerate(zip(edges, counts))]
    return _svg_bar(hist_norm, title, xlabel or "Value", ylabel or "Count")


def _svg_titles(lines, title, xlabel, ylabel, W, H, pad_l, pad_t, cw, ch):
    if title:
        lines.append(
            f'<text x="{pad_l + cw//2}" y="{pad_t - 10}" text-anchor="middle" '
            f'font-size="15" font-weight="bold" fill="#222">{_esc(title)}</text>'
        )
    if xlabel:
        lines.append(
            f'<text x="{pad_l + cw//2}" y="{H - 8}" text-anchor="middle" '
            f'font-size="13" fill="#555">{_esc(xlabel)}</text>'
        )
    if ylabel:
        ry = pad_t + ch // 2
        lines.append(
            f'<text x="14" y="{ry}" text-anchor="middle" font-size="13" fill="#555" '
            f'transform="rotate(-90,14,{ry})">{_esc(ylabel)}</text>'
        )


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ---------------------------------------------------------------------------
# LLM chart-type chooser (used by data_to_chart)
# ---------------------------------------------------------------------------

def _llm_choose_chart(prompt: str, data_text: str) -> tuple:
    """Return (kind, title, xlabel, ylabel, parsed_data).

    Tries to call Urai's LLM via jev.llm if available; otherwise applies
    simple heuristics.
    """
    try:
        import jev.llm as llm  # type: ignore[import]

        system = (
            "You are a data-visualization assistant. "
            "Given a description and raw data, respond with JSON only:\n"
            '{"kind": "bar|line|pie|scatter|histogram", "title": "...", '
            '"xlabel": "...", "ylabel": "...", "data": [...]}\n'
            "data must be a list of {label, value} objects or {x, y} objects."
        )
        user_msg = f"Description: {prompt}\n\nData:\n{data_text}"
        resp = llm.complete(system=system, user=user_msg)
        parsed = json.loads(resp)
        return (
            parsed.get("kind", "bar"),
            parsed.get("title", ""),
            parsed.get("xlabel", ""),
            parsed.get("ylabel", ""),
            parsed.get("data", []),
        )
    except Exception:  # noqa: BLE001
        pass

    # Heuristic fallback
    data_lower = data_text.lower()
    if any(w in data_lower for w in ("percent", "%", "share", "proportion")):
        kind = "pie"
    elif any(w in data_lower for w in ("time", "date", "month", "year", "trend")):
        kind = "line"
    elif any(w in data_lower for w in ("distribution", "histogram", "frequency")):
        kind = "histogram"
    else:
        kind = "bar"

    # Try to parse numeric values from data_text
    import re
    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", data_text)
    parsed = [{"label": str(i), "value": float(v)} for i, v in enumerate(nums[:50])]
    return kind, prompt[:60], "", "", parsed


# ---------------------------------------------------------------------------
# CLI entry point for quick testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sample = {"Apples": 30, "Bananas": 55, "Cherries": 20, "Dates": 40, "Elderberries": 15}
    r = chart(sample, kind="bar", title="Fruit Survey", xlabel="Fruit", ylabel="Count")
    print(r)

    r2 = chart(
        [{"x": i, "y": math.sin(i * 0.5)} for i in range(20)],
        kind="line", title="Sine Wave",
    )
    print(r2)
