"""Feed audit (plan §7.3 / §12 "feed parity", v1.1.0), research only.

Compares the same pair and timeframe in two frozen datasets bar by bar, for example OANDA practice bars against an
export from the owner's own broker chart. It measures how far they differ (missing bars on each side, open/high/
low/close and spread differences in pips) and nothing else: neither feed becomes "the broker's truth", and parity
with Exness stays UNVERIFIED unless one of the datasets really is an Exness export and the audit says MATCHED.

Fixed thresholds (pre-registered, not tuned): at least `MIN_OVERLAP` common bars, otherwise `INSUFFICIENT_OVERLAP`;
`MATCHED` needs the 95th percentile of the close difference within `CLOSE_P95_PIPS`, its maximum within
`CLOSE_MAX_PIPS` and at most `MISSING_SHARE` of the overlap window missing on either side; anything else is
`DIFFERENT`. Stored as an `exports` artifact (`.feed-audit.json`) with an audit event, no registry table.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ayesha.models import pip_size_for
from ayesha.research.contracts import check
from ayesha.research.provenance import canonical_json, digest, iso, utc_now
from ayesha.research.simulation.baseline import RunRefused, load_candles

KIND, EXT = "exports", ".feed-audit.json"
TIMEFRAMES = {"M5": 5, "M15": 15}
MIN_OVERLAP = 500
CLOSE_P95_PIPS = 1.0
CLOSE_MAX_PIPS = 5.0
MISSING_SHARE = 0.02
THRESHOLDS = {"min_overlap_bars": MIN_OVERLAP, "close_p95_pips": CLOSE_P95_PIPS, "close_max_pips": CLOSE_MAX_PIPS,
              "max_missing_share": MISSING_SHARE}


def _q(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))], 3)


def _stats(xs: list[float], over: float | None = None) -> dict[str, Any]:
    out = {"bars": len(xs), "median": _q(xs, 0.5), "p95": _q(xs, 0.95), "max": round(max(xs), 3) if xs else None}
    if over is not None:
        out[f"over_{over:g}_pips"] = sum(1 for x in xs if x > over)
    return out


def _side(ws, dataset_id: str, symbol: str, tf: str) -> tuple[dict[str, Any], list]:
    ds = ws.db.dataset(dataset_id)
    if ds is None:
        raise RunRefused(f"unknown dataset {dataset_id}")
    if ds["quality_state"] == "REJECTED":
        raise RunRefused(f"{dataset_id} is REJECTED by its quality report: it cannot be audited")
    bars = load_candles(ws, dataset_id, symbol, tf)
    return {"dataset_id": dataset_id, "provider": ds["provider"], "quality_state": ds["quality_state"],
            "label": ds["label"], "bars": len(bars),
            "first_bar_utc": iso(bars[0].time) if bars else None,
            "last_bar_utc": iso(bars[-1].time) if bars else None}, bars


def compare(a: list, b: list, symbol: str, tf: str) -> dict[str, Any]:
    """The measurement itself (no storage): overlap, missing bars and differences in pips."""
    pip = pip_size_for(symbol)
    ma, mb = {x.time: x for x in a}, {x.time: x for x in b}
    if not a or not b:
        lo = hi = None
    else:
        lo, hi = max(a[0].time, b[0].time), min(a[-1].time, b[-1].time)
    win_a = {t for t in ma if lo is not None and lo <= t <= hi}
    win_b = {t for t in mb if lo is not None and lo <= t <= hi}
    both = sorted(win_a & win_b)
    window = len(win_a | win_b)
    d: dict[str, list[float]] = {k: [] for k in ("open", "high", "low", "close")}
    spread: list[float] = []
    spreads_known = bool(both) and any(ma[t].spread for t in both) and any(mb[t].spread for t in both)
    for t in both:
        x, y = ma[t], mb[t]
        for k in d:
            d[k].append(abs(getattr(x, k) - getattr(y, k)) / pip)
        if spreads_known:
            spread.append((y.spread - x.spread) / pip)
    overlap = {"from_utc": iso(lo), "to_utc": iso(hi), "window_bars": window, "common_bars": len(both),
               "missing_in_a": len(win_b - win_a), "missing_in_b": len(win_a - win_b),
               "missing_share": round(len((win_a | win_b) - (win_a & win_b)) / window, 4) if window else None,
               "bar_minutes": TIMEFRAMES[tf]}
    diffs = {k: _stats(v, CLOSE_MAX_PIPS if k == "close" else None) for k, v in d.items()}
    diffs["spread_b_minus_a"] = (_stats(spread) | {"mean": round(sum(spread) / len(spread), 3) if spread else None}
                                 if spreads_known else {"state": "UNKNOWN", "note": "a feed has no spread values"})
    if len(both) < MIN_OVERLAP:
        status = "INSUFFICIENT_OVERLAP"
    elif (diffs["close"]["p95"] <= CLOSE_P95_PIPS and diffs["close"]["max"] <= CLOSE_MAX_PIPS
          and overlap["missing_share"] <= MISSING_SHARE):
        status = "MATCHED"
    else:
        status = "DIFFERENT"
    return {"status": status, "overlap": overlap, "differences": diffs}


def audit(ws, dataset_a: str, dataset_b: str, symbol: str, timeframe: str = "M15",
          now: datetime | None = None) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    if timeframe not in TIMEFRAMES:
        raise RunRefused(f"timeframe must be one of {', '.join(TIMEFRAMES)}")
    if dataset_a == dataset_b:
        raise RunRefused("give two different datasets")
    sa, a = _side(ws, dataset_a, symbol, timeframe)
    sb, b = _side(ws, dataset_b, symbol, timeframe)
    m = compare(a, b, symbol, timeframe)
    notes = ["Measures how far two feeds differ; neither is the broker's truth.",
             "Parity with the Exness account stays UNVERIFIED unless one dataset is an Exness export of the same "
             "pair and the audit says MATCHED."]
    if m["status"] == "INSUFFICIENT_OVERLAP":
        notes.append(f"Only {m['overlap']['common_bars']} common bars (need {MIN_OVERLAP}): no conclusion.")
    if "DEGRADED" in (sa["quality_state"], sb["quality_state"]):
        notes.append("At least one dataset is DEGRADED by its quality report.")
    core = {"schema_version": "research.feed-audit/1", "source_type": "RESEARCH", "symbol": symbol,
            "timeframe": timeframe, "dataset_a": sa, "dataset_b": sb, **m, "thresholds": THRESHOLDS, "notes": notes}
    fid = "fa_" + digest(core)[:16]
    old = find(ws, fid)
    if old is not None:
        return old
    doc = check({**core, "feed_audit_id": fid, "created_at_utc": iso((now or utc_now()).replace(microsecond=0)),
                 "feed_audit_sha256": digest(core)}, "research.feed-audit/1")
    sha, p = ws.store.put(KIND, canonical_json(doc), EXT)
    ws.db.record_artifact(sha, KIND, p.relative_to(ws.root).as_posix(), p.stat().st_size)
    ws.db.audit("research", "FEED_AUDIT_CREATED", fid, {"a": dataset_a, "b": dataset_b, "symbol": symbol,
                                                        "timeframe": timeframe, "status": m["status"],
                                                        "artifact": sha})
    return doc


def audits(ws) -> list[dict[str, Any]]:
    out = []
    for a in ws.db.artifacts():
        if a["kind"] == KIND and a["relpath"].endswith(EXT + ".gz"):
            out.append(json.loads(ws.store.get(KIND, a["sha256"], EXT)))
    out.sort(key=lambda d: (d["created_at_utc"], d["feed_audit_id"]), reverse=True)
    return out


def find(ws, feed_audit_id: str) -> dict[str, Any] | None:
    return next((d for d in audits(ws) if d["feed_audit_id"] == feed_audit_id), None)

