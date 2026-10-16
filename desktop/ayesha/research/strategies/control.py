"""Control B: London opening-range breakout (plan §6.1 "simple session/volatility baseline", research only).

Pre-registered rule, fixed before any real data was seen. It exists to show whether the complexity of Baseline A
adds anything over a plain, well-known session rule; it is not expected to have an edge either.

Each London trading day, per symbol, on closed M15 bars:
1. Opening range: the high and low of the first `range_bars` M15 bars from the London open (08:00 Europe/London,
   from the spec's session table, so DST is handled).
2. Breakout: within `entry_window_bars` bars after the range, the first bar that CLOSES above range high +
   `buffer_atr` x ATR(M15) gives BUY (below range low - buffer gives SELL). At most one signal per day.
3. Market order at the next bar's open; stop at the opposite side of the range; target at net reward-to-risk
   `rr` after one spread and the slippage buffer. A range wider than `max_stop_atr` x ATR is skipped.
4. Only when the live session engine calls the close time tradeable (London or New York, not the rollover).
Risk, spread, stop-tightness and RR gates are the common runner's (the live risk engine's), equal for every strategy.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from ayesha.models import pip_size_for
from ayesha.research.strategies.protocol import (AsOfContext, Param, Rejection, code_sha, research_signal,
                                                 target_for)
from ayesha.rules.mtf import Event
from ayesha.rules.primitives import ATR
from ayesha.sessions import SessionEngine

STRATEGY_ID = "control-london-orb"
VERSION = "1.0.0"
PARAMS = {
    "range_bars": Param(4, 2, 8, 1),
    "entry_window_bars": Param(16, 8, 24, 4),
    "buffer_atr": Param(0.1, 0.0, 0.3, 0.05),
    "rr": Param(2.0, 2.0, 3.0, 0.5),
    "max_stop_atr": Param(3.0, 2.0, 4.0, 0.5),
}
EXPLANATION = ("Control B: London opening-range breakout. Range = first M15 bars after 08:00 London; the first M15 "
               "close beyond it (plus a small ATR buffer) inside the entry window gives one market entry per day, "
               "stop at the other side of the range, fixed net reward-to-risk. Pre-registered, research only.")


class LondonOrb:
    strategy_id = STRATEGY_ID
    version = VERSION
    kind = "CONTROL"
    params_def = PARAMS
    explanation = EXPLANATION
    timeframes = ["M15"]
    lookback_bars = 14 + 8

    def __init__(self, symbol: str, spec: dict[str, Any], params: dict[str, float] | None = None) -> None:
        self.symbol = symbol.upper()
        self.p = {k: v.value for k, v in PARAMS.items()} | dict(params or {})
        self.pip = pip_size_for(self.symbol)
        self.slip = spec["risk"]["slippage_buffer_pips"] * self.pip
        self.sessions = SessionEngine(spec)
        self.london = self.sessions.windows["LONDON"]
        self.atr = ATR(spec["rules"]["atr_period"])
        self.day = None
        self.range: list = []
        self.after = 0
        self.done = False
        self.rejections: list[Rejection] = []

    def evaluate(self, ctx: AsOfContext) -> list[Event]:
        c = ctx.bar
        atr = self.atr.update(c)
        open_utc, _ = self.london.bounds_for(c.time)
        if c.time < open_utc:
            return []
        if self.day != open_utc:
            self.day, self.range, self.after, self.done = open_utc, [], 0, False
        n = int(self.p["range_bars"])
        if len(self.range) < n:
            # a gap inside the range window would make the range wrong: the day is skipped, nothing is filled in
            if c.time != open_utc + timedelta(minutes=15 * len(self.range)):
                self.done = True
            self.range.append(c)
            return []
        if self.done or atr is None:
            return []
        self.after += 1
        if self.after > int(self.p["entry_window_bars"]):
            self.done = True
            return []
        hi, lo = max(b.high for b in self.range), min(b.low for b in self.range)
        buf = self.p["buffer_atr"] * atr
        d = "BUY" if c.close > hi + buf else "SELL" if c.close < lo - buf else None
        if d is None:
            return []
        self.done = True
        close_t = ctx.close_utc
        if not self.sessions.tradeable(close_t):
            self.rejections.append(Rejection(ctx.index, self.symbol, d, "OUTSIDE_TRADE_SESSION"))
            return []
        stop = lo if d == "BUY" else hi
        if abs(c.close - stop) > self.p["max_stop_atr"] * atr:
            self.rejections.append(Rejection(ctx.index, self.symbol, d, "RANGE_TOO_WIDE_FOR_STOP"))
            return []
        tgt = target_for(d, c.close, stop, c.spread, self.slip, self.p["rr"])
        trace = [f"OBSERVED: London opening range {lo:.5f}-{hi:.5f} ({n} M15 bars from {open_utc:%H:%M} UTC)",
                 f"OBSERVED: M15 close {c.close:.5f} beyond the range by more than {self.p['buffer_atr']} ATR",
                 f"PLAN: market entry at the next bar's open, stop {stop:.5f}, target {tgt:.5f} "
                 f"(net RR {self.p['rr']} after spread)", "CONTROL STRATEGY: research only, never a live signal"]
        sig = research_signal(STRATEGY_ID, VERSION, self.symbol, d, ctx.index, close_t, c.close, stop, tgt,
                              c.spread, atr, ctx.index + 1, self.sessions.active(close_t), trace, self.pip)
        return [Event("MARKET", sig)]


def source_sha() -> str:
    return code_sha(__file__)
