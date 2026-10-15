"""Session engine (master spec section G). All windows computed with IANA zones, never fixed offsets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

SESSION_NAMES = ("SYDNEY", "TOKYO", "LONDON", "NEW_YORK")


def _t(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


@dataclass(frozen=True)
class Window:
    tz: ZoneInfo
    start: time
    end: time

    def contains(self, t_utc: datetime) -> bool:
        local = t_utc.astimezone(self.tz).time()
        if self.start <= self.end:
            return self.start <= local < self.end
        return local >= self.start or local < self.end

    def bounds_for(self, t_utc: datetime) -> tuple[datetime, datetime]:
        """UTC start/end of this window on the local date of t_utc (window must not cross midnight)."""
        d = t_utc.astimezone(self.tz).date()
        s = datetime.combine(d, self.start, self.tz).astimezone(timezone.utc)
        e = datetime.combine(d, self.end, self.tz).astimezone(timezone.utc)
        return s, e


class SessionEngine:
    def __init__(self, spec: dict[str, Any]) -> None:
        s = spec["sessions"]
        self.windows = {n: Window(ZoneInfo(s[n]["tz"]), _t(s[n]["start"]), _t(s[n]["end"])) for n in SESSION_NAMES}
        self.trade_sessions = tuple(s["trade_sessions"])
        a, r = s["asia_range"], s["rollover"]
        self.asia = Window(ZoneInfo(a["tz"]), _t(a["start"]), _t(a["end"]))
        self.rollover = Window(ZoneInfo(r["tz"]), _t(r["start"]), _t(r["end"]))
        wo, wc = s["week_open"], s["week_close"]
        self._wo = (ZoneInfo(wo["tz"]), wo["weekday"], _t(wo["time"]))
        self._wc = (ZoneInfo(wc["tz"]), wc["weekday"], _t(wc["time"]))

    def active(self, t_utc: datetime) -> list[str]:
        return [n for n, w in self.windows.items() if w.contains(t_utc)]

    def market_open(self, t_utc: datetime) -> bool:
        """FX week: Sunday 17:00 New York to Friday 17:00 New York. Holidays come from the calendar."""
        tz, _, close_t = self._wc
        local = t_utc.astimezone(tz)
        wd, lt = local.weekday(), local.time()
        if wd == 5:  # Saturday
            return False
        if wd == 4 and lt >= close_t:
            return False
        if wd == 6 and lt < self._wo[2]:
            return False
        return True

    def status(self, t_utc: datetime) -> str:
        if not self.market_open(t_utc):
            return "CLOSED"
        if self.rollover.contains(t_utc):
            return "ROLLOVER"
        if not self.active(t_utc):
            return "THIN"
        return "OPEN"

    def tradeable(self, t_utc: datetime) -> bool:
        return self.status(t_utc) == "OPEN" and any(n in self.trade_sessions for n in self.active(t_utc))

    @staticmethod
    def trading_day(t_utc: datetime) -> datetime:
        """FX trading day starts 17:00 New York. Returns the day's start in UTC."""
        ny = ZoneInfo("America/New_York")
        local = t_utc.astimezone(ny)
        start = datetime.combine(local.date(), time(17, 0), ny)
        if local < start:
            start = datetime.combine(local.date() - timedelta(days=1), time(17, 0), ny)
        return start.astimezone(timezone.utc)
