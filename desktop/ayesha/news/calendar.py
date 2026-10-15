"""Economic calendar from a CSV import (master spec section L).

CSV columns: time_utc,currency,impact,title   (impact: HIGH | MEDIUM | LOW)
Coverage is explicit: outside [coverage_start, coverage_end] the status is UNKNOWN,
which blocks trades in strict mode. Never treat a missing calendar as "no news".
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class NewsEvent:
    time: datetime
    currency: str
    impact: str
    title: str


class NewsCalendar:
    def __init__(self, events: list[NewsEvent], coverage_start: datetime, coverage_end: datetime,
                 before_min: int = 30, after_min: int = 30, impacts: tuple[str, ...] = ("HIGH",)) -> None:
        self.events = sorted(events, key=lambda e: e.time)
        self.coverage = (coverage_start, coverage_end)
        self.before = timedelta(minutes=before_min)
        self.after = timedelta(minutes=after_min)
        self.impacts = impacts

    @classmethod
    def from_csv(cls, path: str | Path, **kw) -> "NewsCalendar":
        evs = []
        with Path(path).open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                t = datetime.fromisoformat(row["time_utc"].strip().replace("Z", "+00:00"))
                t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
                evs.append(NewsEvent(t, row["currency"].strip().upper(), row["impact"].strip().upper(), row["title"].strip()))
        if not evs:
            raise ValueError("Calendar file has no events; coverage cannot be established")
        day = timedelta(days=1)
        start = min(e.time for e in evs).replace(hour=0, minute=0, second=0, microsecond=0)
        end = max(e.time for e in evs).replace(hour=0, minute=0, second=0, microsecond=0) + day
        return cls(evs, kw.pop("coverage_start", start), kw.pop("coverage_end", end), **kw)

    def status(self, symbol: str, t: datetime) -> tuple[str, NewsEvent | None]:
        if not (self.coverage[0] <= t < self.coverage[1]):
            return "UNKNOWN", None
        ccys = {symbol[:3].upper(), symbol[3:6].upper()}
        for e in self.events:
            if e.time - self.before <= t <= e.time + self.after and e.currency in ccys and e.impact in self.impacts:
                return "BLOCKED", e
        return "CLEAR", None
