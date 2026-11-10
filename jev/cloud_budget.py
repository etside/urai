#!/usr/bin/env python3
"""Cloud budget guard — track and cap outbound cloud API spend (stdlib only).

Tracks token counts per provider per UTC day in data/cloud_usage.json.
CloudAPIBackend calls record_usage() after each completion; check_budget()
is called before each request and raises BudgetExceeded if the daily cap
is hit.

Env vars (all optional, default unlimited):
  URAI_CLOUD_DAILY_LIMIT_USD   float, e.g. "2.00"  — hard daily cap total
  URAI_CLOUD_LIMIT_<PROVIDER>  float per-provider,  e.g. URAI_CLOUD_LIMIT_MOONSHOT=1.00

Pricing (USD per 1M tokens, input/output):
  Overridable via URAI_PRICING_JSON (path to JSON file).
  Defaults cover Kimi K2, DeepSeek, Claude Haiku, GPT-4o-mini.

All numbers are estimates — actual bills may differ.  This is a safety
brake, not a billing system.
"""
from __future__ import annotations
import json
import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USAGE_FILE = ROOT / "data" / "cloud_usage.json"
_lock = threading.Lock()

# USD per 1M tokens (input, output) — update when providers change pricing
_DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    "moonshot":   (0.15,  0.60),   # Kimi K2
    "deepseek":   (0.14,  0.28),   # DeepSeek R2 / reasoner
    "anthropic":  (0.25,  1.25),   # Claude Haiku 4.5
    "openai":     (0.15,  0.60),   # GPT-4o-mini
}


def _pricing() -> dict[str, tuple[float, float]]:
    p = os.environ.get("URAI_PRICING_JSON", "")
    if p:
        try:
            return json.loads(Path(p).read_text())
        except Exception:
            pass
    return _DEFAULT_PRICING


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _load() -> dict:
    try:
        return json.loads(USAGE_FILE.read_text())
    except Exception:
        return {}


def _save(data: dict):
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    USAGE_FILE.write_text(json.dumps(data, indent=2) + "\n")


def _cost_usd(provider: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = _pricing()
    inp, out = pricing.get(provider, (0.0, 0.0))
    return (prompt_tokens * inp + completion_tokens * out) / 1_000_000


# ── Public API ────────────────────────────────────────────────────────────────

class BudgetExceeded(RuntimeError):
    """Raised before a cloud call when daily limit would be exceeded."""
    pass


def record_usage(provider: str, prompt_tokens: int,
                 completion_tokens: int, model_id: str = "") -> dict:
    """Record tokens used and compute estimated cost.  Thread-safe."""
    cost = _cost_usd(provider, prompt_tokens, completion_tokens)
    today = _today()
    with _lock:
        data = _load()
        day = data.setdefault(today, {})
        prov = day.setdefault(provider, {
            "prompt_tokens": 0, "completion_tokens": 0,
            "estimated_usd": 0.0, "requests": 0,
        })
        prov["prompt_tokens"] += prompt_tokens
        prov["completion_tokens"] += completion_tokens
        prov["estimated_usd"] = round(prov["estimated_usd"] + cost, 6)
        prov["requests"] += 1
        if model_id:
            prov["last_model"] = model_id
        # Prune old days (keep 30)
        days = sorted(data.keys())
        for old in days[:-30]:
            del data[old]
        _save(data)
    return {"provider": provider, "cost_usd": round(cost, 6),
            "today_total_usd": day_total_usd(today)}


def day_total_usd(date: str | None = None) -> float:
    """Total estimated spend across all providers for a given UTC date."""
    date = date or _today()
    with _lock:
        data = _load()
    day = data.get(date, {})
    return round(sum(v.get("estimated_usd", 0.0) for v in day.values()), 6)


def check_budget(provider: str) -> None:
    """Raise BudgetExceeded if any applicable daily limit is hit.
    Call this before making a cloud request.
    """
    today = _today()
    with _lock:
        data = _load()
    day = data.get(today, {})

    # Per-provider limit
    prov_limit = os.environ.get(f"URAI_CLOUD_LIMIT_{provider.upper()}")
    if prov_limit:
        prov_spent = day.get(provider, {}).get("estimated_usd", 0.0)
        if prov_spent >= float(prov_limit):
            raise BudgetExceeded(
                f"Daily cloud limit for {provider} reached "
                f"(${prov_spent:.4f} >= ${float(prov_limit):.4f}). "
                f"Set URAI_CLOUD_LIMIT_{provider.upper()} to raise it.")

    # Global daily limit
    global_limit = os.environ.get("URAI_CLOUD_DAILY_LIMIT_USD")
    if global_limit:
        total = sum(v.get("estimated_usd", 0.0) for v in day.values())
        if total >= float(global_limit):
            raise BudgetExceeded(
                f"Daily cloud spend limit reached "
                f"(${total:.4f} >= ${float(global_limit):.4f}). "
                f"Set URAI_CLOUD_DAILY_LIMIT_USD to raise it.")


def usage_report(days: int = 7) -> dict:
    """Return usage summary for the last N days."""
    with _lock:
        data = _load()
    today = _today()
    all_days = sorted(data.keys())[-days:]
    report: dict = {"days": {}, "total_usd": 0.0}
    for d in all_days:
        day_data = data[d]
        day_total = round(sum(v.get("estimated_usd", 0.0)
                              for v in day_data.values()), 6)
        report["days"][d] = {
            "total_usd": day_total,
            "providers": {
                p: {"requests": v.get("requests", 0),
                    "prompt_tokens": v.get("prompt_tokens", 0),
                    "completion_tokens": v.get("completion_tokens", 0),
                    "estimated_usd": round(v.get("estimated_usd", 0.0), 6)}
                for p, v in day_data.items()
            },
            "is_today": d == today,
        }
        report["total_usd"] += day_total
    report["total_usd"] = round(report["total_usd"], 6)
    report["today_usd"] = day_total_usd()
    limits: dict = {}
    global_limit = os.environ.get("URAI_CLOUD_DAILY_LIMIT_USD")
    if global_limit:
        limits["global_daily_usd"] = float(global_limit)
    for provider in _DEFAULT_PRICING:
        pl = os.environ.get(f"URAI_CLOUD_LIMIT_{provider.upper()}")
        if pl:
            limits[f"{provider}_daily_usd"] = float(pl)
    report["limits"] = limits
    return report
