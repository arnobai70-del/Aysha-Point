"""The research strategy contract (plan §4.3 / §6.2, ticket AI-008).

A strategy is fed one CLOSED base bar at a time through an `AsOfContext` and answers with legacy-shaped events
(`ayesha.rules.mtf.Event`). Causality is structural: the context is built incrementally by the runner, so at bar i it
holds bars 0..i and the higher-timeframe bars that closed by then (aggregated from those bars with the legacy
`Aggregator`, which never emits a partial bar). A strategy never receives the candle list, so it cannot look ahead.

Event kinds understood by the common runner:
- SETUP: a limit order at `signal.entry`, alive until `signal.expires_index` (the legacy setup path), or, with
  `needs_confirmation`, a setup that waits for a later CONFIRMED / CONFIRM_FAILED event (legacy M5 confirmation).
- CONFIRMED / CONFIRM_FAILED: the legacy confirmation outcome of an earlier SETUP.
- MARKET: an order filled at the next bar's open (entry = the signal bar's close is only the reference price).

Plugins are not a security sandbox (plan §4.3): only the built-in strategies in `loader.REGISTRY` can be loaded.
"""

from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from ayesha.models import Candle
from ayesha.rules.mtf import Event
from ayesha.rules.strategy import TF_MINUTES, Aggregator, Signal

BASE_TF = "M15"
HISTORY = 64  # closed bars kept per timeframe for `AsOfContext.last`


class AsOfContext:
    """What a strategy may know at the close of the current base bar, and nothing later."""

    def __init__(self, symbol: str, base_tf: str = BASE_TF) -> None:
        self.symbol = symbol
        self.base_tf = base_tf
        self.base_minutes = TF_MINUTES[base_tf]
        self.index = -1
        self.bar: Candle | None = None
        self.closed: dict[str, Candle | None] = {}
        self._hist: dict[str, deque[Candle]] = {base_tf: deque(maxlen=HISTORY)}
        self._agg: dict[str, Aggregator] = {}
        for tf in ("H1", "H4"):
            if TF_MINUTES[tf] > self.base_minutes:
                self._agg[tf] = Aggregator(self.base_minutes, TF_MINUTES[tf])
                self._hist[tf] = deque(maxlen=HISTORY)

    def advance(self, c: Candle) -> None:
        """Runner only: the next closed base bar."""
        self.index += 1
        self.bar = c
        self._hist[self.base_tf].append(c)
        self.closed = {}
        for tf, agg in self._agg.items():
            h = agg.update(c)
            self.closed[tf] = h
            if h is not None:
                self._hist[tf].append(h)

    @property
    def close_utc(self) -> datetime:
        return self.bar.time + timedelta(minutes=self.base_minutes)

    def just_closed(self, tf: str) -> Candle | None:
        """The `tf` bar that closed together with the current base bar, if any."""
        return self.closed.get(tf)

    def last(self, tf: str, n: int) -> tuple[Candle, ...]:
        """The last `n` closed bars of `tf` (oldest first), never more than `HISTORY`."""
        h = self._hist[tf]
        return tuple(h)[-n:] if n < len(h) else tuple(h)


class ResearchStrategy(Protocol):
    strategy_id: str
    version: str
    kind: str  # BASELINE | CONTROL | EXPERIMENTAL

    def manifest(self) -> dict[str, Any]: ...

    def evaluate(self, ctx: AsOfContext) -> list[Event]: ...

    @property
    def rejections(self) -> list: ...


@dataclass(frozen=True)
class Param:
    """A pre-registered parameter: its value and the bounds a sensitivity run may move it within."""

    value: float
    low: float
    high: float
    step: float

    def ok(self, v: float) -> bool:
        return self.low - 1e-12 <= v <= self.high + 1e-12


@dataclass
class Rejection:
    index: int
    symbol: str
    direction: str
    reason: str


class EMA:
    """Exponential moving average over closed values, seeded with the simple mean of the first `n`."""

    def __init__(self, n: int) -> None:
        self.n = int(n)
        self.k = 2.0 / (self.n + 1)
        self.value: float | None = None
        self._seed: list[float] = []

    def update(self, x: float) -> float | None:
        if self.value is None:
            self._seed.append(x)
            if len(self._seed) == self.n:
                self.value = sum(self._seed) / self.n
        else:
            self.value = x * self.k + self.value * (1 - self.k)
        return self.value


def code_sha(path: str | Path) -> str:
    """SHA-256 of a source file with line endings normalised (a Windows checkout gives the same hash)."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def research_signal(strategy_id: str, version: str, symbol: str, direction: str, index: int, close_t: datetime,
                    entry: float, stop: float, target: float, spread: float, atr: float, expires_index: int,
                    sessions: list[str], trace: list[str], pip: float) -> Signal:
    """A legacy-shaped `Signal` for a research proposal. Its id is namespaced by strategy and version, so it can
    never collide with a live `signal_id`; score and grade are not used (no rule points, never a live grade)."""
    q = round(entry / pip)
    raw = f"research|{strategy_id}|{version}|{symbol}|{close_t.isoformat()}|{direction}|{q}"
    sid = "rs" + hashlib.sha256(raw.encode()).hexdigest()[:14]
    return Signal(sid, symbol, direction, strategy_id.upper().replace("-", "_"), index, close_t, entry, stop,
                  (target,), spread, atr, 0, "RESEARCH", expires_index, sessions, 0, trace, {})


def target_for(direction: str, ref: float, stop: float, spread: float, slip: float, rr: float) -> float:
    """Target whose net reward-to-risk after one spread is exactly `rr`, with the legacy cost model (loss side:
    |entry - stop| + spread + slippage buffer; profit side: |target - entry| - spread)."""
    loss = abs(ref - stop) + spread + slip
    dist = rr * loss + spread
    return ref + dist if direction == "BUY" else ref - dist
