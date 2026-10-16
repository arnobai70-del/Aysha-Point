"""Experimental C: H4/H1 trend continuation after an H1 pullback (plan §6.1 "Experimental C", research only).

The one experimental strategy of v1.0.0 (plan §11: exactly one). A hypothesis to measure, not a rule to trade.
Pre-registered before any real data was seen; changing a rule or a default needs a new version.

On closed bars only (H1 and H4 are built from the closed M15 bars; a higher-timeframe bar counts only once its last
M15 bar has closed):
1. H4 trend: EMA(`h4_fast`) above EMA(`h4_slow`) and the H4 close above EMA(`h4_fast`) = up (mirror for down).
2. H1 agrees: the H1 close is on the same side of EMA(`h1_ema`).
3. Pullback and resumption: the previous closed H1 bar touched the H1 EMA, and the H1 bar that just closed
   closed beyond the previous bar's high (up) or low (down).
4. Market order at the next M15 open; stop beyond the lowest low (highest high) of the last 3 H1 bars plus
   `stop_buffer_atr` x ATR(H1); target at net reward-to-risk `rr` after one spread and the slippage buffer.
   A stop wider than `max_stop_atr` x ATR(H1) is skipped. No new signal for `cooldown_h1` H1 bars after one.
5. Only when the live session engine calls the close time tradeable.
The common runner applies the same live risk gates as for every other strategy (spread, stop vs ATR(M15), net RR).
"""

from __future__ import annotations

from typing import Any

from ayesha.models import pip_size_for
from ayesha.research.strategies.protocol import (EMA, AsOfContext, Param, Rejection, code_sha, research_signal,
                                                 target_for)
from ayesha.rules.mtf import Event
from ayesha.rules.primitives import ATR
from ayesha.sessions import SessionEngine

STRATEGY_ID = "experimental-h1h4-trend"
VERSION = "1.0.0"
PARAMS = {
    "h4_fast": Param(20, 10, 30, 5),
    "h4_slow": Param(50, 30, 80, 10),
    "h1_ema": Param(20, 10, 30, 5),
    "stop_buffer_atr": Param(0.2, 0.0, 0.5, 0.1),
    "rr": Param(2.0, 2.0, 3.0, 0.5),
    "cooldown_h1": Param(4, 2, 8, 2),
    "max_stop_atr": Param(3.0, 2.0, 4.0, 0.5),
}
EXPLANATION = ("Experimental C: trend continuation. H4 EMA trend and H1 on the same side of its EMA; after an H1 "
               "pullback that touched the H1 EMA, the next H1 close beyond the previous H1 bar gives a market entry "
               "with the stop beyond the last 3 H1 bars and a fixed net reward-to-risk. Research only.")


class H1H4Trend:
    strategy_id = STRATEGY_ID
    version = VERSION
    kind = "EXPERIMENTAL"
    params_def = PARAMS
    explanation = EXPLANATION
    timeframes = ["M15", "H1", "H4"]
    lookback_bars = 80 * 16  # H4 slow EMA warm-up in M15 bars (upper bound of h4_slow)

    def __init__(self, symbol: str, spec: dict[str, Any], params: dict[str, float] | None = None) -> None:
        self.symbol = symbol.upper()
        self.p = {k: v.value for k, v in PARAMS.items()} | dict(params or {})
        if self.p["h4_fast"] >= self.p["h4_slow"]:
            raise ValueError("h4_fast must be shorter than h4_slow")
        self.pip = pip_size_for(self.symbol)
        self.slip = spec["risk"]["slippage_buffer_pips"] * self.pip
        self.sessions = SessionEngine(spec)
        n = spec["rules"]["atr_period"]
        self.atr15, self.atr1 = ATR(n), ATR(n)
        self.h4f, self.h4s = EMA(self.p["h4_fast"]), EMA(self.p["h4_slow"])
        self.h1e = EMA(self.p["h1_ema"])
        self.h4_trend = 0
        self.h1_seen = 0
        self.prev_touch = False   # previous closed H1 bar touched its EMA
        self.last_signal_h1 = -10 ** 9
        self.rejections: list[Rejection] = []

    def _h4(self, b) -> None:
        f, s = self.h4f.update(b.close), self.h4s.update(b.close)
        if f is None or s is None:
            self.h4_trend = 0
        elif f > s and b.close > f:
            self.h4_trend = 1
        elif f < s and b.close < f:
            self.h4_trend = -1
        else:
            self.h4_trend = 0

    def evaluate(self, ctx: AsOfContext) -> list[Event]:
        c = ctx.bar
        atr15 = self.atr15.update(c)
        h4 = ctx.just_closed("H4")
        if h4 is not None:
            self._h4(h4)
        h1 = ctx.just_closed("H1")
        if h1 is None:
            return []
        self.h1_seen += 1
        prev_ema = self.h1e.value
        atr1 = self.atr1.update(h1)
        ema = self.h1e.update(h1.close)
        last = ctx.last("H1", 3)
        touched_before, self.prev_touch = self.prev_touch, (
            prev_ema is not None and h1.low <= prev_ema <= h1.high)
        if None in (prev_ema, ema, atr1, atr15) or len(last) < 3 or self.h4_trend == 0:
            return []
        prev = last[-2]
        d = None
        if self.h4_trend == 1 and h1.close > ema and touched_before and h1.close > prev.high:
            d = "BUY"
        elif self.h4_trend == -1 and h1.close < ema and touched_before and h1.close < prev.low:
            d = "SELL"
        if d is None:
            return []
        if self.h1_seen - self.last_signal_h1 <= int(self.p["cooldown_h1"]):
            self.rejections.append(Rejection(ctx.index, self.symbol, d, "COOLDOWN"))
            return []
        close_t = ctx.close_utc
        if not self.sessions.tradeable(close_t):
            self.rejections.append(Rejection(ctx.index, self.symbol, d, "OUTSIDE_TRADE_SESSION"))
            return []
        buf = self.p["stop_buffer_atr"] * atr1
        stop = min(b.low for b in last) - buf if d == "BUY" else max(b.high for b in last) + buf
        if abs(c.close - stop) > self.p["max_stop_atr"] * atr1:
            self.rejections.append(Rejection(ctx.index, self.symbol, d, "STOP_TOO_WIDE"))
            return []
        self.last_signal_h1 = self.h1_seen
        tgt = target_for(d, c.close, stop, c.spread, self.slip, self.p["rr"])
        trace = [f"OBSERVED: H4 EMA{int(self.p['h4_fast'])}/{int(self.p['h4_slow'])} trend "
                 f"{'up' if d == 'BUY' else 'down'}; H1 close {h1.close:.5f} "
                 f"{'above' if d == 'BUY' else 'below'} EMA{int(self.p['h1_ema'])} {ema:.5f}",
                 f"OBSERVED: previous H1 bar touched the EMA; this H1 bar closed beyond its "
                 f"{'high' if d == 'BUY' else 'low'} {prev.high if d == 'BUY' else prev.low:.5f}",
                 f"PLAN: market entry at the next M15 open, stop {stop:.5f}, target {tgt:.5f} "
                 f"(net RR {self.p['rr']} after spread)", "EXPERIMENTAL STRATEGY: research only, never a live signal"]
        sig = research_signal(STRATEGY_ID, VERSION, self.symbol, d, ctx.index, close_t, c.close, stop, tgt,
                              c.spread, atr15, ctx.index + 1, self.sessions.active(close_t), trace, self.pip)
        return [Event("MARKET", sig)]


def source_sha() -> str:
    return code_sha(__file__)
