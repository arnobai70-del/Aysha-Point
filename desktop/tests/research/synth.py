"""Synthetic inputs for the research tests: integer-only random-walk bars placed on the FX week only.

Unlike `golden.market` (frozen with the legacy fingerprint; it skips whole UTC weekend days), these bars follow the
research quality calendar exactly (Sunday 17:00 to Friday 17:00 New York, rollover minutes and 25 Dec / 1 Jan
skipped), so a clean series gets a PASS quality report. All prices are SYNTHETIC; nothing here is market evidence.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ayesha.config import load_spec
from ayesha.feed.csv_feed import save_candles
from ayesha.models import Candle
from ayesha.research.datasets.normalize import point_for
from ayesha.research.datasets.quality import expected_open
from ayesha.sessions import SessionEngine

T0 = datetime(2025, 3, 3, 0, 0, tzinfo=timezone.utc)  # a Monday


def fx_week(n: int, seed: int, start: datetime = T0, minutes: int = 15, price_points: int = 108_000,
            digits: int = 5) -> list[Candle]:
    sessions = SessionEngine(load_spec())
    rng = random.Random(seed)
    scale = 10 ** digits
    out: list[Candle] = []
    t, p, vol = start, price_points, 45
    while len(out) < n:
        if not expected_open(t, sessions):
            t += timedelta(minutes=minutes)
            continue
        step = max(1, vol // 10)
        vol = max(15, min(120, vol + rng.randint(-step, step)))
        move = sum(rng.randint(-vol, vol) for _ in range(3))
        if rng.randrange(100) < 3:
            move *= 4
        o, c = p, p + move
        h = max(o, c) + rng.randint(0, vol // 2)
        lo = min(o, c) - rng.randint(0, vol // 2)
        sp = rng.choice((6, 7, 8, 8, 9, 10))
        out.append(Candle(t, o / scale, h / scale, lo / scale, c / scale, 100.0, sp / scale))
        p = c
        t += timedelta(minutes=minutes)
    return out


def write_csv(folder: Path, symbol: str, timeframe: str, candles: list[Candle]) -> Path:
    """The legacy export format (`ayesha export` / backtest-run): spread in whole points."""
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f"{symbol}_{timeframe}.csv"
    save_candles(f, candles, point_for(symbol))
    return f


def csv_dir(folder: Path, symbol: str = "EURUSD", m15: int = 3000, m5: int = 0, seed: int = 7) -> Path:
    write_csv(folder, symbol, "M15", fx_week(m15, seed))
    if m5:
        write_csv(folder, symbol, "M5", fx_week(m5, seed + 1, minutes=5))
    return folder


class FakeOanda:
    """Answers the legacy `OandaFeed` candle requests from synthetic series (BID + ASK, `complete` flags).

    `fail` lists HTTP status codes to raise on the first calls (e.g. [503, 503] or [401]). Every request is recorded
    with its headers, so a test can prove the token travelled only in the Authorization header."""

    def __init__(self, series: dict[str, list[Candle]], fail: list[int] | None = None,
                 incomplete_last: bool = True) -> None:
        self.series, self.fail, self.incomplete_last = series, list(fail or []), incomplete_last
        self.calls: list[tuple[str, dict[str, str]]] = []

    @staticmethod
    def _t(s: str) -> datetime:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))

    def __call__(self, url: str, headers: dict[str, str]) -> dict:
        import urllib.error
        import urllib.parse

        self.calls.append((url, dict(headers)))
        if self.fail:
            raise urllib.error.HTTPError(url, self.fail.pop(0), "synthetic failure", {}, None)
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        tf, frm, to = q["granularity"][0], self._t(q["from"][0]), self._t(q["to"][0])
        rows = [c for c in self.series[tf] if frm <= c.time < to]
        out = []
        for i, c in enumerate(rows):
            f = "{:.5f}".format
            out.append({"time": c.time.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
                        "complete": not (self.incomplete_last and i == len(rows) - 1 and c is self.series[tf][-1]),
                        "volume": int(c.volume),
                        "bid": {"o": f(c.open), "h": f(c.high), "l": f(c.low), "c": f(c.close)},
                        "ask": {"o": f(c.open + c.spread), "h": f(c.high + c.spread), "l": f(c.low + c.spread),
                                "c": f(c.close + c.spread)}})
        return {"instrument": url.split("/instruments/")[1].split("/")[0], "granularity": tf, "candles": out}
