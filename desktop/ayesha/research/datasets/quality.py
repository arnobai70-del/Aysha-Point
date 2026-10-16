"""Quality gate for one symbol/timeframe partition (`research.quality_report/1`). Facts first, then a decision.

Data is never repaired here: no forward fill, no synthetic bars, no "best guess" for a broken row. HIGH severity
issues (unparseable or impossible prices, conflicting duplicates, bars not closed when observed, misaligned times)
make the partition REJECTED. MEDIUM issues (gaps or coverage beyond the research policy, flat "stuck feed" runs,
identical duplicates, unsorted input) make it DEGRADED: usable for inspection, and for a run only when the owner
asks with --allow-degraded, which is written into the result. Expected bars follow the FX week (Sunday 17:00 to
Friday 17:00 New York, IANA zones, so DST is handled), skip the daily rollover minutes and 25 Dec / 1 Jan.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ayesha.research.datasets.normalize import TF_MINUTES, RawBar, finite
from ayesha.research.provenance import iso
from ayesha.sessions import SessionEngine

NY = ZoneInfo("America/New_York")
SEVERITY = {
    "MISSING_COLUMN": "HIGH", "NO_ROWS": "HIGH", "PARSE_ERROR": "HIGH", "NON_FINITE_PRICE": "HIGH",
    "NON_POSITIVE_PRICE": "HIGH", "OHLC_INCONSISTENT": "HIGH", "NEGATIVE_SPREAD": "HIGH", "NON_FINITE_SPREAD": "HIGH",
    "NEGATIVE_VOLUME": "HIGH", "BID_ABOVE_ASK": "HIGH", "DUPLICATE_CONFLICT": "HIGH", "MISALIGNED_TIMESTAMP": "HIGH",
    "FUTURE_BAR": "HIGH", "INCOMPLETE_BAR": "HIGH",
    "DUPLICATE_IDENTICAL": "MEDIUM", "OUT_OF_ORDER_SORTED": "MEDIUM", "GAP_OVER_POLICY": "MEDIUM",
    "COVERAGE_BELOW_POLICY": "MEDIUM", "STALE_RUN": "MEDIUM",
    "SPREAD_UNKNOWN": "INFO", "ZERO_SPREAD": "INFO", "ASK_UNKNOWN": "INFO", "BAR_OUTSIDE_MARKET_HOURS": "INFO",
}


class _Issues:
    def __init__(self) -> None:
        self.d: dict[str, dict[str, Any]] = {}

    def add(self, code: str, example: str | None = None, n: int = 1) -> None:
        it = self.d.setdefault(code, {"code": code, "severity": SEVERITY[code], "count": 0, "examples": []})
        it["count"] += n
        if example is not None and len(it["examples"]) < 5:
            it["examples"].append(example)

    def list(self) -> list[dict[str, Any]]:
        order = {"HIGH": 0, "MEDIUM": 1, "INFO": 2}
        return sorted(self.d.values(), key=lambda x: (order[x["severity"]], x["code"]))


def _where(b: RawBar) -> str:
    return iso(b.time) if b.time else f"line {b.line}"


def _closure(t: datetime) -> bool:
    d = t.astimezone(NY)
    return (d.month, d.day) in ((12, 25), (1, 1))


def expected_open(t: datetime, sessions: SessionEngine) -> bool:
    """A bar opening at t is expected: market open, not in the rollover minutes, not 25 Dec / 1 Jan (NY date)."""
    return sessions.market_open(t) and not sessions.rollover.contains(t) and not _closure(t)


def session_label(t: datetime, sessions: SessionEngine) -> str:
    act = sessions.active(t)
    return "+".join(act) if act else "OFF_SESSION"


def assess(bars: list[RawBar], symbol: str, timeframe: str, spec: dict[str, Any], policy: dict[str, Any],
           missing_columns: list[str] | None = None) -> tuple[list[RawBar], dict[str, Any]]:
    """Return (accepted bars in time order, one per timestamp; quality report). Rejected rows are left out of the
    normalised partition but counted in the report; the raw file keeps everything as received."""
    iss = _Issues()
    tf = timedelta(minutes=TF_MINUTES[timeframe])
    sessions = SessionEngine(spec)
    for c in missing_columns or []:
        iss.add("MISSING_COLUMN", c)
    good: list[RawBar] = []
    for b in bars:
        if b.error:
            iss.add("PARSE_ERROR", b.error)
            continue
        if not finite(b.open, b.high, b.low, b.close):
            iss.add("NON_FINITE_PRICE", _where(b))
            continue
        if min(b.open, b.high, b.low, b.close) <= 0:
            iss.add("NON_POSITIVE_PRICE", _where(b))
            continue
        if b.high < b.low or not (b.low <= b.open <= b.high and b.low <= b.close <= b.high):
            iss.add("OHLC_INCONSISTENT", _where(b))
            continue
        if b.spread is not None and not finite(b.spread):
            iss.add("NON_FINITE_SPREAD", _where(b))
            continue
        if b.spread is not None and b.spread < 0:
            iss.add("NEGATIVE_SPREAD", _where(b))
            continue
        if b.volume is not None and (not finite(b.volume) or b.volume < 0):
            iss.add("NEGATIVE_VOLUME", _where(b))
            continue
        if b.ask_close is not None and (not finite(b.ask_close) or b.ask_close < b.close):
            iss.add("BID_ABOVE_ASK", _where(b))
            continue
        if not b.complete:
            iss.add("INCOMPLETE_BAR", _where(b))
            continue
        if int(b.time.timestamp()) % int(tf.total_seconds()) or b.time.microsecond:
            iss.add("MISALIGNED_TIMESTAMP", _where(b))
            continue
        if b.time + tf > b.observed_at:
            iss.add("FUTURE_BAR", f"{_where(b)} closes after it was observed")
            continue
        good.append(b)
    if any(b.time is not None and a.time is not None and b.time < a.time for a, b in zip(good, good[1:])):
        iss.add("OUT_OF_ORDER_SORTED")
    good.sort(key=lambda b: b.time)
    uniq: list[RawBar] = []
    for b in good:
        if uniq and uniq[-1].time == b.time:
            a = uniq[-1]
            same = (a.open, a.high, a.low, a.close, a.volume, a.spread, a.ask_close) == \
                   (b.open, b.high, b.low, b.close, b.volume, b.spread, b.ask_close)
            iss.add("DUPLICATE_IDENTICAL" if same else "DUPLICATE_CONFLICT", _where(b))
            continue
        uniq.append(b)

    unknown_spread = sum(1 for b in uniq if b.spread is None)
    if unknown_spread:
        iss.add("SPREAD_UNKNOWN", n=unknown_spread)
    zero = [b for b in uniq if b.spread == 0]
    if zero:
        iss.add("ZERO_SPREAD", _where(zero[0]), n=len(zero))
    no_ask = sum(1 for b in uniq if b.ask_close is None)
    if no_ask:
        iss.add("ASK_UNKNOWN", n=no_ask)

    # flat bars repeating the previous close: a stuck feed, not a quiet market
    run, run_start = 0, None
    for prev, b in zip(uniq, uniq[1:]):
        flat = b.open == b.high == b.low == b.close == prev.close and b.time - prev.time == tf
        if flat:
            run, run_start = run + 1, run_start or b
            continue
        if run >= policy["stale_run_bars"]:
            iss.add("STALE_RUN", f"{run} flat bars from {_where(run_start)}")
        run, run_start = 0, None
    if run >= policy["stale_run_bars"]:
        iss.add("STALE_RUN", f"{run} flat bars from {_where(run_start)}")

    # expected bars between the first and last bar (FX week, rollover and closures skipped)
    present = {b.time for b in uniq}
    by_session: dict[str, int] = {}
    missing_by_session: dict[str, int] = {}
    expected = missing = longest = cur = 0
    for b in uniq:
        if not expected_open(b.time, sessions):
            iss.add("BAR_OUTSIDE_MARKET_HOURS", _where(b))
        lab = session_label(b.time, sessions)
        by_session[lab] = by_session.get(lab, 0) + 1
    if uniq:
        t, end = uniq[0].time, uniq[-1].time
        while t <= end:
            if expected_open(t, sessions):
                expected += 1
                if t in present:
                    if cur > policy["max_gap_bars"]:
                        iss.add("GAP_OVER_POLICY", f"{cur} bars missing before {iso(t)}")
                    cur = 0
                else:
                    missing += 1
                    cur += 1
                    longest = max(longest, cur)
                    lab = session_label(t, sessions)
                    missing_by_session[lab] = missing_by_session.get(lab, 0) + 1
            t += tf
    else:
        iss.add("NO_ROWS")
    coverage = round(100.0 * (expected - missing) / expected, 3) if expected else None
    if coverage is not None and coverage < policy["min_coverage_percent"]:
        iss.add("COVERAGE_BELOW_POLICY", f"{coverage}% < {policy['min_coverage_percent']}%")

    issues = iss.list()
    sev = {i["severity"] for i in issues}
    decision = "REJECTED" if "HIGH" in sev else "DEGRADED" if "MEDIUM" in sev else "PASS"
    report = {
        "schema_version": "research.quality_report/1",
        "symbol": symbol, "timeframe": timeframe,
        "rows_in": len(bars), "rows_out": len(uniq),
        "start_utc": iso(uniq[0].time) if uniq else None,
        "end_utc": iso(uniq[-1].time) if uniq else None,
        "expected_bars": expected, "missing_bars": missing, "coverage_percent": coverage,
        "longest_gap_bars": longest,
        "issues": issues,
        "bars_by_session": dict(sorted(by_session.items())),
        "missing_by_session": dict(sorted(missing_by_session.items())),
        "policy": {**policy, "market_hours": "Sun 17:00-Fri 17:00 America/New_York; rollover and 25 Dec/1 Jan skipped",
                   "timezone": "UTC timestamps; sessions in IANA zones (DST aware)", "repair": "NONE"},
        "decision": decision,
    }
    return uniq, report


def worst(states: list[str]) -> str:
    return "REJECTED" if "REJECTED" in states else "DEGRADED" if "DEGRADED" in states else "PASS"
