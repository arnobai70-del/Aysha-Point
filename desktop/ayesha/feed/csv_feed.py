"""CSV candle loader/writer.

Format (header required): time,open,high,low,close,volume,spread
`time` is ISO-8601 UTC (e.g. 2025-01-06T08:00:00Z) or a unix timestamp in seconds.
`spread` is in POINTS (MT5 convention) and converted to price with `point`.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ayesha.models import Candle


def _parse_time(v: str) -> datetime:
    v = v.strip()
    if v.replace(".", "", 1).isdigit():
        return datetime.fromtimestamp(float(v), tz=timezone.utc)
    t = datetime.fromisoformat(v.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def load_candles(path: str | Path, point: float) -> list[Candle]:
    out: list[Candle] = []
    with Path(path).open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.append(
                Candle(
                    time=_parse_time(row["time"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume") or 0),
                    spread=float(row.get("spread") or 0) * point,
                )
            )
    out.sort(key=lambda c: c.time)
    check_monotonic(out)
    return out


def save_candles(path: str | Path, candles: list[Candle], point: float) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume", "spread"])
        for c in candles:
            w.writerow([c.time.strftime("%Y-%m-%dT%H:%M:%SZ"), c.open, c.high, c.low, c.close, c.volume,
                        round(c.spread / point)])


def check_monotonic(candles: list[Candle]) -> None:
    for a, b in zip(candles, candles[1:]):
        if b.time <= a.time:
            raise ValueError(f"Candles not strictly increasing at {b.time}")


def resample(candles: list[Candle], minutes: int) -> list[Candle]:
    """Aggregate to a higher timeframe on UTC boundaries. Partial last bucket is dropped."""
    if not candles:
        return []
    step = timedelta(minutes=minutes)
    out: list[Candle] = []
    bucket: list[Candle] = []
    bucket_start = None
    src_step = candles[1].time - candles[0].time if len(candles) > 1 else step

    def flush():
        if bucket and bucket[-1].time + src_step >= bucket_start + step:
            out.append(Candle(bucket_start, bucket[0].open, max(c.high for c in bucket),
                              min(c.low for c in bucket), bucket[-1].close,
                              sum(c.volume for c in bucket), bucket[-1].spread))

    for c in candles:
        epoch = int(c.time.timestamp())
        start = datetime.fromtimestamp(epoch - epoch % (minutes * 60), tz=timezone.utc)
        if start != bucket_start:
            flush()
            bucket, bucket_start = [], start
        bucket.append(c)
    flush()
    return out
