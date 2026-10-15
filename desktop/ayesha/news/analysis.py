"""Conditional news analysis (News Intelligence spec A1 layers 2 and 3). Advisory only.

Nothing here can make a trade READY. Scenario cards describe what an above / near / below
forecast figure could mean *all else equal*; they are not predictions and carry no probability.
Reaction summaries describe what closed M5 bars did after a verified release.

Anti-lookahead: `pre_release_view` strips every post-release field (actual, revisions,
publication time), and `scenario_card` only ever sees that view. `reaction` uses `actual` only when
the source gave a publication time that is not after `now`.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from ayesha.models import Candle
from ayesha.news import classify
from ayesha.news.calendar import NewsEvent

NOT_A_PREDICTION = ("Conditional scenarios, not a prediction. The real move can be the opposite "
                    "(positioning, revisions, other releases, guidance, risk sentiment). No trade from news alone.")


def pre_release_view(e: NewsEvent) -> NewsEvent:
    """The event as it was knowable before the release: no actual, no revision, no publication time."""
    return replace(e, actual=None, actual_published_at=None, revised_previous=None)


def _pair_effect(symbol: str, ccy: str, ccy_effect: int) -> str:
    if ccy_effect == 0:
        return "UNKNOWN"
    s = symbol.upper()
    if ccy == s[:3]:
        return "UP" if ccy_effect > 0 else "DOWN"
    if ccy == s[3:6]:
        return "DOWN" if ccy_effect > 0 else "UP"
    return "UNKNOWN"  # event currency is not in the pair (global-risk event): no simple mapping


def scenario_card(event: NewsEvent, symbol: str) -> dict[str, Any]:
    e = pre_release_view(event)
    pol = classify.polarity(e.title)
    card: dict[str, Any] = {"event_id": e.event_id, "title": e.title, "currency": e.currency, "impact": e.impact,
                            "tier": classify.tier(e.title, e.impact), "time_utc": e.time.isoformat(),
                            "provider": e.provider, "as_of_utc": e.fetched_at.isoformat() if e.fetched_at else None,
                            "forecast": e.forecast, "previous": e.previous, "is_prediction": False,
                            "probability": None, "scenarios": [], "note": NOT_A_PREDICTION}
    try:
        fc = classify.parse_number(e.forecast)
    except classify.Malformed:
        fc = None
    if fc is None or pol == 0:
        card["direction"] = "UNKNOWN"
        card["summary"] = "Direction unknown; protection active." + (
            "" if fc is not None else " (no usable forecast from the source)")
        return card
    card["direction"] = "CONDITIONAL"
    for case, sign in (("ABOVE_FORECAST", pol), ("NEAR_FORECAST", 0), ("BELOW_FORECAST", -pol)):
        card["scenarios"].append({
            "case": case,
            "currency_effect": "STRONGER" if sign > 0 else "WEAKER" if sign < 0 else "UNCLEAR",
            "pair_effect": _pair_effect(symbol, e.currency, sign) if sign else "UNCLEAR",
        })
    above = card["scenarios"][0]
    card["summary"] = (f"Above forecast {e.forecast}: {e.currency} could be {above['currency_effect'].lower()} "
                       f"({symbol} {above['pair_effect'].lower()}), all else equal; below: the opposite. "
                       "Not a prediction.")
    return card


def reaction(event: NewsEvent, symbol: str, now: datetime, m5: list[Candle],
             baseline_range: float | None) -> dict[str, Any]:
    """What happened after the release, from closed M5 bars. Explanation only."""
    out: dict[str, Any] = {"event_id": event.event_id, "state": "UNAVAILABLE", "surprise": None,
                           "expected_pair_effect": None, "observed_pair_move": None, "observed_atr": None,
                           "actual_verified": False, "is_permission": False}
    pol = classify.polarity(event.title)
    if event.actual is not None and event.actual_published_at is not None and event.actual_published_at <= now:
        try:
            act, fc = classify.parse_number(event.actual), classify.parse_number(event.forecast)
        except classify.Malformed:
            act = fc = None
        if act is not None and fc is not None:
            out["actual_verified"] = True
            out["surprise"] = "ABOVE" if act > fc else "BELOW" if act < fc else "IN_LINE"
            sign = (1 if act > fc else -1 if act < fc else 0) * pol
            out["expected_pair_effect"] = _pair_effect(symbol, event.currency, sign) if sign else "UNCLEAR"
    else:
        out["actual_note"] = "Actual not available from a verified, timestamped source (BLOCKED BY DATA)."
    pre = [b for b in m5 if b.time < event.time]
    post = [b for b in m5 if b.time >= event.time and b.time.timestamp() + 300 <= now.timestamp()]
    if not pre or not post or not baseline_range:
        return out
    move = (post[-1].close - pre[-1].close) / baseline_range
    up = (max(b.high for b in post) - pre[-1].close) / baseline_range
    dn = (pre[-1].close - min(b.low for b in post)) / baseline_range
    out["observed_atr"] = round(move, 2)
    out["observed_pair_move"] = "UP" if move >= 1 else "DOWN" if move <= -1 else "FLAT"
    if min(up, dn) > 3:
        out["state"] = "WHIPSAW"
    elif out["expected_pair_effect"] in ("UP", "DOWN") and out["observed_pair_move"] != "FLAT":
        out["state"] = "CONFIRMS" if out["observed_pair_move"] == out["expected_pair_effect"] else "CONFLICTS"
    else:
        out["state"] = "OBSERVED_ONLY" if not out["actual_verified"] else "UNCLEAR"
    return out
