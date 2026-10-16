"""Economic calendar (master spec section L; News Intelligence spec A1).

CSV columns: time_utc,currency,impact,title   (impact: HIGH | MEDIUM | LOW)
Optional CSV columns (only when a permitted source really supplies them):
    forecast,previous,actual,actual_published_utc,revised_previous,state,observed_utc
`observed_utc` is when this record was first seen in the source (a point-in-time snapshot); replays
never show a row before that time (ayesha.backtest.asof).
Coverage is explicit: outside [coverage_start, coverage_end] the status is UNKNOWN,
which blocks trades in strict mode. Never treat a missing calendar as "no news".

`NewsCalendar.status()` is the legacy fixed-window check (kept for research tools and as a
floor). The live decision is `ayesha.news.guard.NewsGuard`, which adds tiers, phases,
provenance/staleness and post-release market stability.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATES = ("SCHEDULED", "RESCHEDULED", "CANCELLED_OR_MOVED", "CORRECTED", "CONFLICT")


@dataclass(frozen=True)
class NewsEvent:
    time: datetime
    currency: str
    impact: str
    title: str
    provider: str = "UNKNOWN"
    event_id: str = ""
    state: str = "SCHEDULED"  # one of STATES
    previous_time: datetime | None = None  # set when the source moved the event
    forecast: str | None = None  # raw text as published by the source, e.g. "0.3%"
    previous: str | None = None
    actual: str | None = None  # only ever set after the official release
    actual_published_at: datetime | None = None
    revised_previous: str | None = None
    fetched_at: datetime | None = None  # when this record was observed (as-of time)
    history: tuple[str, ...] = field(default=())  # audit trail: "2026-10-15T12:00Z time 12:30->13:30", ...

    def __post_init__(self) -> None:
        if self.time.tzinfo is None:
            raise ValueError("NewsEvent.time must be timezone-aware")
        if not self.event_id:
            object.__setattr__(self, "event_id", make_event_id(self.currency, self.title, self.time))


def make_event_id(currency: str, title: str, t: datetime, ordinal: int = 0) -> str:
    """Stable id for an event within its ISO week (a same-week reschedule keeps the id)."""
    y, w, _ = t.astimezone(timezone.utc).isocalendar()
    key = f"{currency.upper()}|{' '.join(title.lower().split())}|{y}-W{w:02d}|{ordinal}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


class NewsCalendar:
    def __init__(self, events: list[NewsEvent], coverage_start: datetime, coverage_end: datetime,
                 before_min: int = 30, after_min: int = 30, impacts: tuple[str, ...] = ("HIGH",),
                 provider: str = "UNKNOWN", fetched_at: datetime | None = None) -> None:
        self.events = sorted(events, key=lambda e: e.time)
        self.coverage = (coverage_start, coverage_end)
        self.before = timedelta(minutes=before_min)
        self.after = timedelta(minutes=after_min)
        self.impacts = impacts
        self.provider = provider
        self.fetched_at = fetched_at  # None = provenance unknown: the live guard treats it as unverified

    @classmethod
    def from_csv(cls, path: str | Path, **kw) -> "NewsCalendar":
        p = Path(path)
        evs = []
        with p.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                t = _ts(row["time_utc"])
                pub = _ts(row["actual_published_utc"]) if (row.get("actual_published_utc") or "").strip() else None
                st = (row.get("state") or "SCHEDULED").strip().upper() or "SCHEDULED"
                evs.append(NewsEvent(t, row["currency"].strip().upper(), row["impact"].strip().upper(),
                                     row["title"].strip(), provider=f"CSV:{p.name}",
                                     state=st if st in STATES else "CONFLICT",
                                     forecast=_opt(row.get("forecast")), previous=_opt(row.get("previous")),
                                     actual=_opt(row.get("actual")), actual_published_at=pub,
                                     revised_previous=_opt(row.get("revised_previous")),
                                     fetched_at=_ts(row["observed_utc"]) if _opt(row.get("observed_utc")) else None))
        if not evs:
            raise ValueError("Calendar file has no events; coverage cannot be established")
        day = timedelta(days=1)
        start = min(e.time for e in evs).replace(hour=0, minute=0, second=0, microsecond=0)
        end = max(e.time for e in evs).replace(hour=0, minute=0, second=0, microsecond=0) + day
        fetched = kw.pop("fetched_at", datetime.fromtimestamp(p.stat().st_mtime, timezone.utc))
        return cls(evs, kw.pop("coverage_start", start), kw.pop("coverage_end", end),
                   provider=kw.pop("provider", f"CSV:{p.name}"), fetched_at=fetched, **kw)

    def status(self, symbol: str, t: datetime) -> tuple[str, NewsEvent | None]:
        """Legacy fixed window: HIGH impact +-30 min on either currency of the pair."""
        if not (self.coverage[0] <= t < self.coverage[1]):
            return "UNKNOWN", None
        ccys = {symbol[:3].upper(), symbol[3:6].upper()}
        for e in self.events:
            if e.time - self.before <= t <= e.time + self.after and e.currency in ccys and e.impact in self.impacts:
                return "BLOCKED", e
        return "CLEAR", None


def _ts(s: str) -> datetime:
    t = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _opt(s: str | None) -> str | None:
    s = (s or "").strip()
    return s or None
