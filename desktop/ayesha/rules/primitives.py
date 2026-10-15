"""Incremental ICT/SMC primitives (master spec section H).

Everything here is causal: `Analyzer.update(candle)` sees one CLOSED bar at a time and
only emits events that are knowable at that bar's close. A swing at index k is reported
at k + right_bars, never earlier. Terms like "order block" or "liquidity" are chart
models, not observations of bank orders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ayesha.models import Candle


@dataclass
class Swing:
    kind: str  # HIGH | LOW
    index: int  # bar of the extreme
    confirmed_at: int  # bar at which it became known
    price: float
    broken: bool = False
    swept: bool = False


@dataclass
class StructureBreak:
    kind: str  # BOS | CHOCH
    direction: int  # +1 bullish, -1 bearish
    index: int
    level: float
    swing_index: int
    displacement: bool

    @property
    def is_mss(self) -> bool:
        return self.kind == "CHOCH" and self.displacement


@dataclass
class FVG:
    direction: int
    created_at: int  # index of candle C
    bottom: float
    top: float
    displacement: bool  # candle B was a displacement candle
    mitigated: bool = False
    invalidated: bool = False

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def size(self) -> float:
        return self.top - self.bottom


@dataclass
class LiquidityLevel:
    name: str  # PDH, PDL, ASIA_H, ASIA_L, SWING_H, SWING_L, EQH, EQL
    side: int  # +1 buy-side (above price, highs), -1 sell-side (below, lows)
    price: float
    created_at: int
    breach_at: int | None = None
    extreme: float | None = None
    consumed: bool = False


@dataclass
class Sweep:
    level: LiquidityLevel
    index: int  # reclaim bar
    extreme: float  # lowest low (sell-side) / highest high (buy-side) of the raid

    @property
    def direction(self) -> int:
        """Direction of the expected reversal: sell-side sweep => bullish (+1)."""
        return -self.level.side


@dataclass
class BarEvents:
    index: int
    swings: list[Swing] = field(default_factory=list)
    breaks: list[StructureBreak] = field(default_factory=list)
    fvgs: list[FVG] = field(default_factory=list)
    sweeps: list[Sweep] = field(default_factory=list)
    displacement: int = 0  # +1/-1 if this bar is a displacement candle


class ATR:
    """Wilder ATR over closed bars."""

    def __init__(self, period: int) -> None:
        self.period = period
        self.value: float | None = None
        self._prev_close: float | None = None
        self._seed: list[float] = []

    def update(self, c: Candle) -> float | None:
        tr = c.range if self._prev_close is None else max(c.high, self._prev_close) - min(c.low, self._prev_close)
        self._prev_close = c.close
        if self.value is None:
            self._seed.append(tr)
            if len(self._seed) == self.period:
                self.value = sum(self._seed) / self.period
        else:
            self.value = (self.value * (self.period - 1) + tr) / self.period
        return self.value


def is_displacement(c: Candle, atr: float | None, body_atr: float, body_frac: float) -> int:
    if atr is None or c.range <= 0:
        return 0
    if c.body >= body_atr * atr and c.body / c.range >= body_frac:
        return 1 if c.bullish else -1
    return 0


class Analyzer:
    """Feeds closed candles of ONE timeframe and maintains structure, FVGs and liquidity."""

    def __init__(self, rules: dict[str, Any]) -> None:
        self.r = rules
        self.bars: list[Candle] = []
        self.atr = ATR(rules["atr_period"])
        self.atr_hist: list[float | None] = []
        self.swings: list[Swing] = []
        self.trend = 0
        self.fvgs: list[FVG] = []
        self.levels: list[LiquidityLevel] = []
        self.breaks: list[StructureBreak] = []

    # --- helpers --------------------------------------------------------------------------
    @property
    def i(self) -> int:
        return len(self.bars) - 1

    def last_swing(self, kind: str, unbroken: bool = True) -> Swing | None:
        for s in reversed(self.swings):
            if s.kind == kind and (not unbroken or not s.broken):
                return s
        return None

    def add_level(self, name: str, side: int, price: float) -> LiquidityLevel:
        lv = LiquidityLevel(name, side, price, self.i)
        self.levels.append(lv)
        return lv

    def active_levels(self, side: int | None = None) -> list[LiquidityLevel]:
        return [l for l in self.levels if not l.consumed and (side is None or l.side == side)]

    # --- main ------------------------------------------------------------------------------
    def update(self, c: Candle) -> BarEvents:
        self.bars.append(c)
        atr = self.atr.update(c)
        self.atr_hist.append(atr)
        ev = BarEvents(self.i)
        r = self.r
        ev.displacement = is_displacement(c, atr, r["displacement_body_atr"], r["displacement_body_frac"])
        if atr is None:
            return ev
        self._sweeps(c, atr, ev)
        self._structure(c, atr, ev)
        self._swings(atr, ev)
        self._fvg(atr, ev)
        self._fvg_lifecycle(c)
        return ev

    def _swings(self, atr: float, ev: BarEvents) -> None:
        L, R = self.r["swing_left_bars"], self.r["swing_right_bars"]
        k = self.i - R
        if k - L < 0:
            return
        b = self.bars
        hk, lk = b[k].high, b[k].low
        # tie-break: strictly beyond the left window, at least equal to the right window (earliest bar wins)
        if all(hk > b[j].high for j in range(k - L, k)) and all(hk >= b[j].high for j in range(k + 1, k + R + 1)):
            self._new_swing(Swing("HIGH", k, self.i, hk), atr, ev)
        if all(lk < b[j].low for j in range(k - L, k)) and all(lk <= b[j].low for j in range(k + 1, k + R + 1)):
            self._new_swing(Swing("LOW", k, self.i, lk), atr, ev)

    def _new_swing(self, s: Swing, atr: float, ev: BarEvents) -> None:
        # A swing that price has already closed beyond (during the right window) is born broken.
        later = self.bars[s.index + 1:]
        buf = self.r["bos_buffer_atr"] * atr
        if s.kind == "HIGH" and any(c.close > s.price + buf for c in later):
            s.broken = True
        if s.kind == "LOW" and any(c.close < s.price - buf for c in later):
            s.broken = True
        self.swings.append(s)
        ev.swings.append(s)
        if s.broken:
            return
        side = 1 if s.kind == "HIGH" else -1
        tol = self.r["eq_tolerance_atr"] * atr
        prev = [x for x in self.swings[:-1] if x.kind == s.kind and not x.broken and not x.swept][-5:]
        matches = [x.price for x in prev if abs(x.price - s.price) <= tol]
        if matches:
            name = "EQH" if side == 1 else "EQL"
            price = max(matches + [s.price]) if side == 1 else min(matches + [s.price])
        else:
            name, price = ("SWING_H" if side == 1 else "SWING_L"), s.price
        self.add_level(name, side, price)

    def _structure(self, c: Candle, atr: float, ev: BarEvents) -> None:
        buf = self.r["bos_buffer_atr"] * atr
        disp = ev.displacement
        sh, sl = self.last_swing("HIGH"), self.last_swing("LOW")
        if sh and c.close > sh.price + buf:
            sh.broken = True
            self._consume_at(1, sh.price)
            kind = "CHOCH" if self.trend == -1 else "BOS"
            br = StructureBreak(kind, 1, self.i, sh.price, sh.index, disp == 1)
            self.trend = 1
            self.breaks.append(br)
            ev.breaks.append(br)
        if sl and c.close < sl.price - buf:
            sl.broken = True
            self._consume_at(-1, sl.price)
            kind = "CHOCH" if self.trend == 1 else "BOS"
            br = StructureBreak(kind, -1, self.i, sl.price, sl.index, disp == -1)
            self.trend = -1
            self.breaks.append(br)
            ev.breaks.append(br)

    def _consume_at(self, side: int, price: float) -> None:
        for lv in self.levels:
            if lv.side == side and not lv.consumed and lv.name.startswith(("SWING", "EQ")) and lv.price == price:
                lv.consumed = True

    def _fvg(self, atr: float, ev: BarEvents) -> None:
        if self.i < 2:
            return
        a, b, c = self.bars[-3], self.bars[-2], self.bars[-1]
        min_gap = self.r["fvg_min_gap_atr"] * atr
        disp = is_displacement(b, self.atr_hist[-2], self.r["displacement_body_atr"], self.r["displacement_body_frac"])
        if c.low - a.high >= min_gap and c.low > a.high:
            f = FVG(1, self.i, a.high, c.low, disp == 1)
            self.fvgs.append(f)
            ev.fvgs.append(f)
        if a.low - c.high >= min_gap and c.high < a.low:
            f = FVG(-1, self.i, c.high, a.low, disp == -1)
            self.fvgs.append(f)
            ev.fvgs.append(f)

    def _fvg_lifecycle(self, c: Candle) -> None:
        max_age = self.r["fvg_max_age_bars"]
        for f in self.fvgs:
            if f.invalidated or f.created_at == self.i:
                continue
            if self.i - f.created_at > max_age:
                f.invalidated = True
                continue
            if f.direction == 1:
                if c.low <= f.top:
                    f.mitigated = True
                if c.close < f.bottom:
                    f.invalidated = True
            else:
                if c.high >= f.bottom:
                    f.mitigated = True
                if c.close > f.top:
                    f.invalidated = True
        if len(self.fvgs) > 200:
            self.fvgs = [f for f in self.fvgs if not f.invalidated][-100:]

    def _sweeps(self, c: Candle, atr: float, ev: BarEvents) -> None:
        pen = self.r["sweep_min_penetration_atr"] * atr
        reclaim = self.r["sweep_reclaim_bars"]
        for lv in self.active_levels():
            if lv.created_at >= self.i:
                continue
            if lv.side == -1:
                pierced, back_inside = c.low < lv.price - pen, c.close > lv.price
                extreme_fn, beyond = min, c.low
            else:
                pierced, back_inside = c.high > lv.price + pen, c.close < lv.price
                extreme_fn, beyond = max, c.high
            if lv.breach_at is None:
                if pierced:
                    lv.breach_at, lv.extreme = self.i, beyond
                else:
                    continue
            else:
                lv.extreme = extreme_fn(lv.extreme, beyond)
            if back_inside:
                lv.consumed = True
                ev.sweeps.append(Sweep(lv, self.i, lv.extreme))
                for s in self.swings:  # mark the underlying swing as swept
                    if s.price == lv.price:
                        s.swept = True
            elif self.i - lv.breach_at >= reclaim:
                lv.consumed = True  # kept closing beyond: breakout, not a sweep
