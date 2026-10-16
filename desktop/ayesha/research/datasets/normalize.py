"""Normalise provider bars to `research.market_bar/1` rows, and turn accepted rows back into legacy `Candle`s.

Parsing is tolerant on purpose: a bad row becomes a quality issue with its line number instead of an exception, so
the quality report can say exactly what was wrong. Values are copied, never repaired. The CSV path converts exactly
like the legacy loader (`ayesha.feed.csv_feed.load_candles`), so a snapshot replays bit-for-bit like the same CSV.
"""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from ayesha.models import Candle
from ayesha.research.provenance import canonical_json, iso, parse_iso

TF_MINUTES = {"M5": 5, "M15": 15}
BAR_SCHEMA = "research.market_bar/1"


@dataclass
class RawBar:
    """One provider bar as read, before any check. `error` is set when the row could not even be parsed."""

    line: int | None
    time: datetime | None
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    spread: float | None  # price units (ask - bid at close); None when unknown
    ask_close: float | None
    complete: bool
    observed_at: datetime
    error: str | None = None


def point_for(symbol: str) -> float:
    """MT5-style point used by the legacy CSV format (spread column in whole points)."""
    return 0.001 if symbol.upper()[3:6] == "JPY" else 0.00001


def _parse_time(v: str) -> datetime:
    """Exactly the legacy CSV rule: unix seconds, or ISO-8601 (naive means UTC)."""
    v = v.strip()
    if v.replace(".", "", 1).isdigit():
        return datetime.fromtimestamp(float(v), tz=timezone.utc)
    t = datetime.fromisoformat(v.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def parse_csv(data: bytes, symbol: str, observed_at: datetime) -> tuple[list[RawBar], list[str]]:
    """Legacy export format: time,open,high,low,close[,volume,spread(points)]. Returns (bars, missing columns)."""
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    cols = [c.strip() for c in (reader.fieldnames or [])]
    missing = [c for c in ("time", "open", "high", "low", "close") if c not in cols]
    if missing:
        return [], missing
    point = point_for(symbol)
    out: list[RawBar] = []
    for row in reader:
        line = reader.line_num
        try:
            t = _parse_time(row["time"])
            o, h, lo, c = (float(row[k]) for k in ("open", "high", "low", "close"))
            vol = float(row.get("volume") or 0)
            sp = row.get("spread")
            spread = float(sp or 0) * point if sp is not None else None
            out.append(RawBar(line, t, o, h, lo, c, vol, spread, None, True, observed_at))
        except (KeyError, TypeError, ValueError) as e:
            out.append(RawBar(line, None, None, None, None, None, None, None, None, True, observed_at,
                              f"line {line}: {type(e).__name__}"))
    return out, []


def from_candles(candles: Iterable[Candle], ask_close: dict[datetime, float], observed: dict[datetime, datetime],
                 default_observed: datetime) -> list[RawBar]:
    """Bars parsed by the legacy OANDA adapter (closed only), plus ASK close and receive time from the raw response."""
    return [RawBar(None, c.time, c.open, c.high, c.low, c.close, c.volume, c.spread, ask_close.get(c.time), True,
                   observed.get(c.time, default_observed)) for c in candles]


def to_row(b: RawBar, provider: str, symbol: str, timeframe: str, spread_basis: str) -> dict[str, Any]:
    assert b.time is not None
    return {
        "schema_version": BAR_SCHEMA,
        "provider": provider,
        "symbol": symbol,
        "timeframe": timeframe,
        "bar_open_utc": iso(b.time),
        "bar_close_utc": iso(b.time + timedelta(minutes=TF_MINUTES[timeframe])),
        "bid_open": b.open,
        "bid_high": b.high,
        "bid_low": b.low,
        "bid_close": b.close,
        "ask_close": b.ask_close,
        "spread": b.spread,
        "spread_basis": spread_basis if b.spread is not None else "UNKNOWN",
        "volume": b.volume if b.volume is not None else 0.0,
        "is_closed": bool(b.complete),
        "observed_at_utc": iso(b.observed_at),
    }


def finite(*xs: float | None) -> bool:
    return all(x is not None and math.isfinite(x) for x in xs)


def row_line(b: RawBar, provider: str, symbol: str, timeframe: str, spread_basis: str) -> bytes:
    """One canonical JSON Lines record: identical bars always give identical bytes."""
    return canonical_json(to_row(b, provider, symbol, timeframe, spread_basis)) + b"\n"


def parse_line(line: bytes) -> dict[str, Any]:
    return json.loads(line)


def to_candle(row: dict[str, Any]) -> Candle:
    """Accepted row -> the legacy Candle the replay engine reads (BID prices, spread in price units)."""
    return Candle(parse_iso(row["bar_open_utc"]), row["bid_open"], row["bid_high"], row["bid_low"], row["bid_close"],
                  row["volume"], row["spread"] if row["spread"] is not None else 0.0)
