"""Point-in-time view of a historical calendar for replays (News spec A5; tests I03, N07).

A file of past calendar events usually holds today's final records: the latest schedule, final
actual values and revised previous values. Replaying with it as-is leaks the future, so a replay
only ever sees `AsOfCalendar.at(t)`:

- a row whose `observed_utc` is later than t does not exist yet;
- `actual` appears only after its `actual_published_utc`; a row without that time never shows its
  actual (nobody can prove when it was known), and `revised_previous` follows the actual;
- coverage stays the file's coverage, so a signal outside it is NEWS_UNVERIFIED, never "no news".

What cannot be repaired is reported by `integrity()`: when rows have no `observed_utc`, the schedule
itself (times, impact ratings, moved or cancelled events) is the file's final view, not what a
trader saw at the time. News direction (actual vs forecast) is never backtested here.
"""

from __future__ import annotations

import bisect
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from ayesha.news.calendar import NewsCalendar, NewsEvent

NEWS_DIRECTION = "NEWS DIRECTION NOT BACKTESTED"
MASKING = ("actual and revised values hidden until actual_published_utc; rows without a publication "
           "time never show an actual; rows with observed_utc are hidden before it")

# Events the guard can still be affected by: a window ends at most 60 min after the event and the
# reaction watch lasts at most 120 min more; ahead, a setup never lives longer than a trading day.
LOOKBACK = timedelta(hours=6)
LOOKAHEAD = timedelta(hours=36)


class AsOfCalendar:
    def __init__(self, cal: NewsCalendar, lookback: timedelta = LOOKBACK, lookahead: timedelta = LOOKAHEAD) -> None:
        self.cal = cal
        self.lookback, self.lookahead = lookback, lookahead
        self._times = [e.time for e in cal.events]  # NewsCalendar keeps events sorted by time

    def at(self, t: datetime) -> NewsCalendar:
        """The calendar as it could have been known at `t`."""
        lo = bisect.bisect_left(self._times, t - self.lookback)
        hi = bisect.bisect_right(self._times, t + self.lookahead)
        evs = [v for v in (visible(e, t) for e in self.cal.events[lo:hi]) if v is not None]
        return NewsCalendar(evs, *self.cal.coverage, before_min=int(self.cal.before.total_seconds() // 60),
                            after_min=int(self.cal.after.total_seconds() // 60), impacts=self.cal.impacts,
                            provider=self.cal.provider, fetched_at=t)

    def integrity(self, decision_times: list[datetime]) -> dict[str, Any]:
        evs = self.cal.events
        n = len(evs)
        observed = sum(1 for e in evs if e.fetched_at is not None)
        with_actual = sum(1 for e in evs if e.actual is not None)
        with_pub = sum(1 for e in evs if e.actual is not None and e.actual_published_at is not None)
        lo, hi = self.cal.coverage
        outside = sum(1 for t in decision_times if not lo <= t < hi)
        warnings = []
        if observed < n:
            warnings.append(f"SCHEDULE_NOT_POINT_IN_TIME: {n - observed} of {n} calendar rows have no observed_utc, "
                            "so their times and impact ratings are the file's final view, not what was known then")
        if outside:
            warnings.append(f"INCOMPLETE_NEWS_DATA: {outside} of {len(decision_times)} news decisions fall outside "
                            f"the calendar coverage {lo:%Y-%m-%d}..{hi:%Y-%m-%d} (treated as NEWS_UNVERIFIED)")
        if with_actual > with_pub:
            warnings.append(f"ACTUAL_WITHOUT_PUBLICATION_TIME: {with_actual - with_pub} rows have an actual but no "
                            "actual_published_utc; those actuals are never shown to the replay")
        return {"provider": self.cal.provider, "rows": n, "coverage_utc": [lo.isoformat(), hi.isoformat()],
                "rows_with_observed_utc": observed, "point_in_time_schedule": n > 0 and observed == n,
                "rows_with_actual": with_actual, "rows_with_actual_publication_time": with_pub,
                "actual_masking": MASKING, "decisions": len(decision_times),
                "decisions_outside_coverage": outside, "news_direction": NEWS_DIRECTION, "warnings": warnings}


def visible(e: NewsEvent, t: datetime) -> NewsEvent | None:
    """The row as it could be seen at `t`, or None when it was not in the source yet."""
    if e.fetched_at is not None and e.fetched_at > t:
        return None
    if e.actual_published_at is not None and e.actual_published_at <= t:
        return e
    if e.actual is None and e.revised_previous is None and e.actual_published_at is None:
        return e
    return replace(e, actual=None, actual_published_at=None, revised_previous=None)
