"""E3: what the Claude API calls cost, per step, per match and since the app started.

Every call's token usage (from the API response) is priced with the model's per-million-token rates and
saved in match.json ("usage"), so the cost shows on the step that made the call and in the top bar. Prices
are Anthropic's first-party rates in US dollars (checked 12/11/2026); Claude bills in USD.
"""
from __future__ import annotations

import threading
import time

# $ per million tokens: input, output, cache read. Cache writes (5-minute) cost 1.25x input.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-opus-4-8": (5.00, 25.00, 0.50),
    "claude-sonnet-5": (2.00, 10.00, 0.20),
}
DEFAULT_PRICE = PRICES["claude-opus-5-5"]
STEP_NAMES = {"sheet": "Score sheet", "describe": "Descriptions"}
# Typical size of one call, for the "≈ $0.01" shown on a button before you press it.
TYPICAL = {"sheet": (4500, 3000), "describe": (1600, 700)}

_session = {"usd": 0.0, "calls": 0, "started": time.time()}
_lock = threading.Lock()


def _get(u, name: str) -> int:
    v = u.get(name) if isinstance(u, dict) else getattr(u, name, None)
    return int(v or 0)


def cost(model: str, usage) -> dict:
    """Tokens and dollars for one response's usage (an SDK Usage object or a dict)."""
    pin, pout, pread = PRICES.get(model, DEFAULT_PRICE)
    t = {"input": _get(usage, "input_tokens"), "output": _get(usage, "output_tokens"),
         "cache_read": _get(usage, "cache_read_input_tokens"), "cache_write": _get(usage, "cache_creation_input_tokens")}
    usd = (t["input"] * pin + t["output"] * pout + t["cache_read"] * pread + t["cache_write"] * pin * 1.25) / 1_000_000
    return {**t, "usd": round(usd, 6)}


def estimate(step: str, model: str, n: int = 1) -> float:
    """Rough cost of n typical calls for a step, before making them."""
    i, o = TYPICAL.get(step, (2000, 1000))
    return round(cost(model, {"input_tokens": i * n, "output_tokens": o * n})["usd"], 4)


def record(match_id: str | None, step: str, model: str, usage) -> dict:
    """Save one call against the match (if any) and the session."""
    entry = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "step": step, "model": model, **cost(model, usage)}
    with _lock:
        _session["usd"] += entry["usd"]
        _session["calls"] += 1
    if match_id:
        from . import matches
        try:
            with matches.edit(match_id) as m:
                m.setdefault("usage", []).append(entry)
        except matches.MatchError:
            pass
    return entry


def summary(match: dict | None) -> dict:
    """{match: {usd, calls, steps: [{step, name, usd, calls, tokens}]}, session: {usd, calls}}"""
    entries = (match or {}).get("usage") or []
    steps: dict[str, dict] = {}
    for e in entries:
        s = steps.setdefault(e["step"], {"step": e["step"], "name": STEP_NAMES.get(e["step"], e["step"]), "usd": 0.0,
                                         "calls": 0, "input": 0, "output": 0, "models": set()})
        s["usd"] += e["usd"]
        s["calls"] += 1
        s["input"] += e.get("input", 0) + e.get("cache_read", 0) + e.get("cache_write", 0)
        s["output"] += e.get("output", 0)
        s["models"].add(e.get("model", ""))
    for s in steps.values():
        s["usd"] = round(s["usd"], 4)
        s["models"] = sorted(m for m in s["models"] if m)
    with _lock:
        sess = {"usd": round(_session["usd"], 4), "calls": _session["calls"]}
    return {"match": {"usd": round(sum(e["usd"] for e in entries), 4), "calls": len(entries), "steps": list(steps.values())},
            "session": sess}
