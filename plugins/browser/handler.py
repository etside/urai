"""Browser plugin hook: routes "browser" hook payloads to jev.browser."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def on_hook(hook, payload):
    from jev import browser as _b
    if hook != "browser":
        return {"ok": False, "error": f"unsupported hook: {hook}"}
    steps = payload.get("steps", [])
    return _b.run_steps(steps, goal=payload.get("goal", ""),
                        run_id=payload.get("run_id"))
