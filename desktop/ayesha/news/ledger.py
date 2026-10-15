"""Event ledger: remembers every calendar event seen, so changes are never silent (spec A2, N03).

A source refresh can move an event, drop it, lower its impact or correct a released figure. The
ledger compares each refresh with what was seen before and keeps the stricter picture:

- moved (same id, new time)   -> RESCHEDULED at the new time, plus a CANCELLED_OR_MOVED ghost that
                                 keeps blocking around the old time
- dropped from the source     -> CANCELLED_OR_MOVED ghost at the last known time
- impact lowered              -> the higher impact seen is kept
- released figure corrected   -> CORRECTED ghost at the correction time (a fresh post-event window)

Everything here is pure (ledger dict in, ledger dict out) so it is unit tested without network.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from ayesha.news.calendar import NewsEvent, make_event_id

IMPACT_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def assign_ids(events: list[NewsEvent]) -> list[NewsEvent]:
    """Ids from (currency, title, ISO week, n-th occurrence) so repeated titles in a week stay distinct."""
    seen: dict[tuple[str, str, tuple[int, int]], int] = {}
    out = []
    for e in sorted(events, key=lambda x: x.time):
        y, w, _ = e.time.isocalendar()
        k = (e.currency, " ".join(e.title.lower().split()), (y, w))
        n = seen.get(k, 0)
        seen[k] = n + 1
        out.append(replace(e, event_id=make_event_id(e.currency, e.title, e.time, n)))
    return out


def _iso(t: datetime | None) -> str | None:
    return t.astimezone(timezone.utc).isoformat() if t else None


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def reconcile(ledger: dict[str, Any], events: list[NewsEvent], fetched_at: datetime,
              covered: tuple[datetime, datetime], keep: timedelta = timedelta(days=10)
              ) -> tuple[dict[str, Any], list[NewsEvent]]:
    """Merge one source snapshot into the ledger. Returns (new ledger, events to use, ghosts included)."""
    led = {k: dict(v) for k, v in (ledger or {}).items()}
    now_iso = _iso(fetched_at)
    current = {e.event_id: e for e in assign_ids(events)}
    out: list[NewsEvent] = []

    for eid, e in current.items():
        rec = led.get(eid)
        hist = list(rec.get("history", [])) if rec else []
        if rec is None:
            rec = {"first_seen": now_iso, "time": _iso(e.time), "impact": e.impact}
        if _dt(rec["time"]) != e.time:
            hist.append(f"{now_iso} time {rec['time']} -> {_iso(e.time)}")
            rec["previous_time"] = rec["time"]
            rec["time"] = _iso(e.time)
        impact = max(e.impact, rec.get("impact", e.impact), key=lambda i: IMPACT_RANK.get(i, 2))
        if impact != e.impact:
            hist.append(f"{now_iso} impact lowered by source to {e.impact}; keeping {impact}")
        rec["impact"] = impact
        if e.actual is not None and rec.get("actual") not in (None, e.actual):
            hist.append(f"{now_iso} actual corrected {rec['actual']} -> {e.actual}")
            rec.setdefault("corrected_at", []).append(now_iso)
        if e.actual is not None:
            rec["actual"] = e.actual
        rec.pop("missing_since", None)
        rec.update(currency=e.currency, title=e.title, last_seen=now_iso, history=hist[-20:])
        led[eid] = rec
        prev = _dt(rec.get("previous_time"))
        ev = replace(e, impact=impact, state="RESCHEDULED" if prev else e.state, previous_time=prev,
                     fetched_at=fetched_at, history=tuple(hist))
        out.append(ev)
        if prev:
            out.append(replace(ev, time=prev, state="CANCELLED_OR_MOVED", event_id=eid + "~old"))
        for c in rec.get("corrected_at", []):
            ct = _dt(c)
            if ct > e.time:
                out.append(replace(ev, time=ct, state="CORRECTED", event_id=f"{eid}~fix{ct:%H%M}"))

    for eid, rec in led.items():
        if eid in current:
            continue
        t = _dt(rec["time"])
        if covered[0] <= t < covered[1] and t > fetched_at - timedelta(days=1):
            if "missing_since" not in rec:
                rec["missing_since"] = now_iso
                rec.setdefault("history", []).append(f"{now_iso} no longer listed by the source")
            out.append(NewsEvent(t, rec["currency"], rec["impact"], rec["title"], provider="LEDGER", event_id=eid,
                                 state="CANCELLED_OR_MOVED", fetched_at=fetched_at, history=tuple(rec["history"])))

    led = {k: v for k, v in led.items() if _dt(v["time"]) > fetched_at - keep}
    return led, sorted(out, key=lambda x: x.time)
