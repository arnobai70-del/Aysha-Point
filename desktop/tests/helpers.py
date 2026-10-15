"""Test helpers: build candles from compact tuples and generate synthetic price paths."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from ayesha.models import Candle

T0 = datetime(2025, 3, 3, 0, 0, tzinfo=timezone.utc)  # a Monday


def bars(ohlc: list[tuple[float, float, float, float]], start: datetime = T0, minutes: int = 15,
         spread: float = 0.00008) -> list[Candle]:
    return [Candle(start + timedelta(minutes=minutes * i), o, h, l, c, 100, spread)
            for i, (o, h, l, c) in enumerate(ohlc)]


def synthetic(n: int, seed: int = 7, start: datetime = T0, price: float = 1.08, minutes: int = 15,
              vol: float = 0.0006) -> list[Candle]:
    """Random walk with volatility clustering and occasional impulses; skips weekends."""
    rng = random.Random(seed)
    out, t, p, sigma = [], start, price, vol
    while len(out) < n:
        if t.weekday() >= 5:
            t += timedelta(minutes=minutes)
            continue
        sigma = max(vol * 0.3, min(vol * 3, sigma * (1 + rng.gauss(0, 0.1))))
        drift = rng.gauss(0, sigma)
        if rng.random() < 0.03:
            drift *= 4  # impulse / displacement
        o = p
        c = o + drift
        h = max(o, c) + abs(rng.gauss(0, sigma * 0.5))
        l = min(o, c) - abs(rng.gauss(0, sigma * 0.5))
        out.append(Candle(t, round(o, 5), round(h, 5), round(l, 5), round(c, 5), 100, 0.00008))
        p = c
        t += timedelta(minutes=minutes)
    return out
