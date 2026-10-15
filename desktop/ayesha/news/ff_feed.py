"""Weekly economic calendar from the Forex Factory export feed (opt-in).

Forex Factory publishes its weekly calendar as a JSON export (the "Export" link on its calendar
page, served from nfs.faireconomy.media) for use in trading tools. AYESHA fetches it at most
once per `min_refetch` and caches it locally, so it never hammers the source. Coverage is the
week the file describes; outside it the calendar returns UNKNOWN (strict mode then blocks).

If the fetch fails and the cache is older than `max_age`, the calendar is treated as missing:
signals become NEWS_UNVERIFIED, never "no news".

The export carries `forecast` and `previous` as text, timestamped here by the fetch time (as-of).
It does NOT carry a publication-verified `actual`, so actual-vs-forecast analysis is BLOCKED BY
DATA with this source; any `actual` field it may contain is ignored. Every refresh goes through the
event ledger (`ayesha.news.ledger`), so moved, dropped or downgraded events are never silent.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from ayesha.news.calendar import NewsCalendar, NewsEvent
from ayesha.news.ledger import reconcile

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
PROVIDER = "FOREXFACTORY_WEEKLY_EXPORT"
IMPACT = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW", "holiday": "LOW", "non-economic": "LOW"}


def _txt(v) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


def parse_ff(items: list[dict], fetched_at: datetime | None = None) -> list[NewsEvent]:
    evs = []
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            t = datetime.fromisoformat(str(it["date"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if t.tzinfo is None:
            continue  # unknown zone: skip rather than guess
        raw_impact = str(it.get("impact", "")).lower()
        evs.append(NewsEvent(t.astimezone(timezone.utc), str(it.get("country", "")).strip().upper(),
                             IMPACT.get(raw_impact, "HIGH"),  # unknown impact tag: assume HIGH, never LOW
                             str(it.get("title", "")).strip(), provider=PROVIDER,
                             forecast=_txt(it.get("forecast")), previous=_txt(it.get("previous")),
                             fetched_at=fetched_at))
    return evs


def week_coverage(evs: list[NewsEvent]) -> tuple[datetime, datetime]:
    """The file covers one Sunday-to-Sunday week in US/Eastern time.

    Coverage is narrowed, never widened: it starts at the latest and ends at the earliest
    possible US/Eastern midnight (UTC-4 or UTC-5), so no hour outside the file counts as covered.
    """
    first = min(e.time for e in evs)
    sunday = (first - timedelta(days=(first.weekday() + 1) % 7)).replace(hour=0, minute=0, second=0, microsecond=0)
    return sunday + timedelta(hours=5), sunday + timedelta(days=7, hours=4)


class FFCalendarSource:
    def __init__(self, cache_path: Path, url: str = FF_URL, ledger_path: Path | None = None, fetch: Callable[[str], bytes] | None = None,
                 clock: Callable[[], datetime] | None = None, min_refetch: timedelta = timedelta(hours=1),
                 max_age: timedelta = timedelta(hours=24)) -> None:
        self.cache = Path(cache_path)
        self.ledger_path = Path(ledger_path) if ledger_path else self.cache.with_name("news-ledger.json")
        self.url = url
        self._fetch = fetch or self._http
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.min_refetch, self.max_age = min_refetch, max_age
        self.last_error = ""

    @staticmethod
    def _http(url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "AYESHA-FX/0.5 (personal advisory tool)"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()

    def _read_cache(self) -> tuple[datetime, list[dict]] | None:
        try:
            d = json.loads(self.cache.read_text(encoding="utf-8"))
            return datetime.fromisoformat(d["fetched_at"]), d["items"]
        except (OSError, ValueError, KeyError):
            return None

    def calendar(self, **kw) -> NewsCalendar | None:
        now = self.clock()
        cached = self._read_cache()
        if cached is None or now - cached[0] >= self.min_refetch:
            try:
                items = json.loads(self._fetch(self.url).decode("utf-8"))
                if not isinstance(items, list) or not items:
                    raise ValueError("empty calendar")
                self.cache.parent.mkdir(parents=True, exist_ok=True)
                self.cache.write_text(json.dumps({"fetched_at": now.isoformat(), "items": items}), encoding="utf-8")
                cached = (now, items)
                self.last_error = ""
            except Exception as e:  # network or format problem: fall back to a fresh-enough cache only
                self.last_error = f"{type(e).__name__}: {e}"
        if cached is None or now - cached[0] > self.max_age:
            return None
        evs = parse_ff(cached[1], cached[0])
        if not evs:
            return None
        start, end = week_coverage(evs)
        try:
            led = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            led = {}
        led, evs = reconcile(led, evs, cached[0], (start, end))
        try:
            self.ledger_path.write_text(json.dumps(led, indent=1), encoding="utf-8")
        except OSError as e:
            self.last_error = f"ledger not saved: {e}"
        return NewsCalendar(evs, start, end, provider=PROVIDER, fetched_at=cached[0], **kw)
