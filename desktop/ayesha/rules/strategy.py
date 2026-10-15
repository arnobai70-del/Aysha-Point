"""SWEEP_MSS_FVG setup (master spec section J, "Bullish raid reversal", mirrored for shorts).

Sequence on the setup timeframe, all on closed bars:
  1. A recognised liquidity level (PDH/PDL, Asia H/L, swing, EQH/EQL) is swept and reclaimed.
  2. Within `mss_within_bars`, structure breaks the opposite way with a displacement candle.
  3. A fresh, unmitigated FVG in the new direction exists between the sweep and the break.
  4. Entry at the FVG proximal edge (or midpoint), SL beyond the sweep extreme + buffer,
     target = nearest opposing liquidity whose net RR after spread >= min_net_rr.
  5. Only inside an allowed trade session. Risk/news/lot gates are applied afterwards by
     the risk engine; this module only proposes candidates.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from ayesha.models import Candle, pip_size_for
from ayesha.rules.primitives import FVG, Analyzer, LiquidityLevel, StructureBreak, Sweep
from ayesha.sessions import SessionEngine

TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240}


@dataclass
class Signal:
    signal_id: str
    symbol: str
    direction: str
    setup: str
    created_index: int
    bar_close_utc: datetime
    entry: float
    stop: float
    targets: tuple[float, ...]
    spread: float
    atr: float
    score: int
    grade: str
    expires_index: int
    session: list[str]
    htf_bias: int
    trace: list[str] = field(default_factory=list)
    score_breakdown: dict[str, int] = field(default_factory=dict)
    liquidity_source: str = ""  # swept level, e.g. PDL
    target_name: str = ""       # target liquidity, e.g. ASIA_H
    mtf: dict[str, str] = field(default_factory=dict)  # one combined multi-timeframe explanation
    fvg_zone: tuple[float, float] = (0.0, 0.0)          # (bottom, top) of the entry FVG


@dataclass
class Rejection:
    index: int
    symbol: str
    direction: str
    reason: str


class Aggregator:
    """Builds closed higher-timeframe bars from closed lower-timeframe bars (no partial bars)."""

    def __init__(self, src_minutes: int, dst_minutes: int) -> None:
        self.src, self.dst = src_minutes, dst_minutes
        self.bucket: list[Candle] = []

    def update(self, c: Candle) -> Candle | None:
        epoch = int(c.time.timestamp())
        start = epoch - epoch % (self.dst * 60)
        if self.bucket and int(self.bucket[0].time.timestamp()) - int(self.bucket[0].time.timestamp()) % (self.dst * 60) != start:
            self.bucket = []  # gap: drop the incomplete bucket rather than invent data
        self.bucket.append(c)
        if epoch + self.src * 60 >= start + self.dst * 60:
            b = self.bucket
            self.bucket = []
            return Candle(datetime.fromtimestamp(start, tz=timezone.utc), b[0].open, max(x.high for x in b),
                          min(x.low for x in b), b[-1].close, sum(x.volume for x in b), b[-1].spread)
        return None


def signal_key(version: str, symbol: str, setup: str, t: datetime, anchor: str, direction: str, entry: float,
               pip: float) -> str:
    q = round(entry / pip)
    raw = f"{version}|{symbol}|{setup}|{t.isoformat()}|{anchor}|{direction}|{q}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class SweepMssFvg:
    SETUP = "SWEEP_MSS_FVG"

    def __init__(self, symbol: str, spec: dict[str, Any]) -> None:
        self.symbol = symbol.upper()
        self.spec = spec
        self.rules = spec["rules"]
        self.entry_cfg = spec["entry"]
        self.min_rr = spec["risk"]["min_net_rr"]
        self.slip = spec["risk"]["slippage_buffer_pips"]
        self.max_spread = spec["risk"]["max_spread_pips"]
        self.pip = pip_size_for(self.symbol)
        self.sessions = SessionEngine(spec)
        self.tf = TF_MINUTES[self.entry_cfg["setup_timeframe"]]
        self.ltf = Analyzer(self.rules)
        self.htf = Analyzer(self.rules)
        self.agg = Aggregator(self.tf, TF_MINUTES[self.entry_cfg["bias_timeframe"]])
        mtf = spec.get("mtf", {})
        self.mtf_cfg = mtf
        ctx_tf = mtf.get("context_timeframe")
        self.ctx = Analyzer(self.rules)  # H4 major structure (built from the same closed bars)
        self.agg_ctx = Aggregator(self.tf, TF_MINUTES[ctx_tf]) if ctx_tf else None
        self.armed: dict[int, Sweep] = {}
        self.day_start: datetime | None = None
        self.day_hi = self.day_lo = None
        self.asia_bars: list[Candle] = []
        self.asia_done_for: datetime | None = None
        self.rejections: list[Rejection] = []
        self.version = spec["strategy_version"]

    # --- main --------------------------------------------------------------------------------
    def on_bar(self, c: Candle) -> list[Signal]:
        """Call once per CLOSED setup-timeframe bar. Returns new candidate signals."""
        # day levels must be known before this bar can sweep them; they use only past bars
        self._day_levels_before(c)
        ev = self.ltf.update(c)
        self._day_levels_after(c)
        h = self.agg.update(c)
        if h is not None:
            self.htf.update(h)
        if self.agg_ctx is not None:
            h4 = self.agg_ctx.update(c)
            if h4 is not None:
                self.ctx.update(h4)

        for sw in ev.sweeps:
            self.armed[sw.direction] = sw
        for d in list(self.armed):
            if self.ltf.i - self.armed[d].index > self.rules["mss_within_bars"]:
                del self.armed[d]

        out = []
        for br in ev.breaks:
            sw = self.armed.get(br.direction)
            if sw is None:
                continue
            if not br.displacement:
                self.rejections.append(Rejection(self.ltf.i, self.symbol, _dir(br.direction), "BREAK_WITHOUT_DISPLACEMENT"))
                continue
            sig = self._build(c, sw, br)
            if sig:
                out.append(sig)
            del self.armed[br.direction]
        return out

    # --- daily/session liquidity references (built from past bars only) -----------------
    def _day_levels_before(self, c: Candle) -> None:
        ds = self.sessions.trading_day(c.time)
        if self.day_start is not None and ds != self.day_start:
            self.ltf.add_level("PDH", 1, self.day_hi)
            self.ltf.add_level("PDL", -1, self.day_lo)
            self.day_start, self.day_hi, self.day_lo = ds, None, None
            self.asia_bars = []
        if not self.sessions.asia.contains(c.time) and self.asia_bars and self.asia_done_for != ds:
            self.ltf.add_level("ASIA_H", 1, max(b.high for b in self.asia_bars))
            self.ltf.add_level("ASIA_L", -1, min(b.low for b in self.asia_bars))
            self.asia_done_for = ds
            self.asia_bars = []

    def _day_levels_after(self, c: Candle) -> None:
        ds = self.sessions.trading_day(c.time)
        if self.day_start is None or self.day_hi is None:
            self.day_start, self.day_hi, self.day_lo = ds, c.high, c.low
        else:
            self.day_hi, self.day_lo = max(self.day_hi, c.high), min(self.day_lo, c.low)
        if self.sessions.asia.contains(c.time):
            self.asia_bars.append(c)

    def _build(self, c: Candle, sw: Sweep, br: StructureBreak) -> Signal | None:
        a = self.ltf
        d = br.direction
        dname = _dir(d)
        close_t = c.time + timedelta(minutes=self.tf)

        def reject(reason: str) -> None:
            self.rejections.append(Rejection(a.i, self.symbol, dname, reason))

        if not self.sessions.tradeable(close_t):
            return reject("OUTSIDE_TRADE_SESSION")
        fvgs = [f for f in a.fvgs if f.direction == d and sw.index - 2 <= f.created_at <= a.i
                and not f.mitigated and not f.invalidated]
        if not fvgs:
            return reject("NO_FRESH_FVG")
        fvg: FVG = max(fvgs, key=lambda f: f.created_at)
        atr = a.atr.value
        if self.entry_cfg["entry_mode"] == "midpoint":
            entry = fvg.mid
        else:
            entry = fvg.top if d == 1 else fvg.bottom
        buf = self.entry_cfg["sl_buffer_atr"] * atr
        stop = sw.extreme - buf if d == 1 else sw.extreme + buf
        spread = c.spread
        loss = abs(entry - stop) + spread + self.slip * self.pip
        # nearest opposing liquidity with enough net RR
        side = 1 if d == 1 else -1
        cands = sorted((lv for lv in a.active_levels(side) if (lv.price - entry) * d > 0),
                       key=lambda lv: abs(lv.price - entry))
        target: LiquidityLevel | None = None
        rr = 0.0
        for lv in cands:
            rr = (abs(lv.price - entry) - spread) / loss
            if rr >= self.min_rr:
                target = lv
                break
        if target is None:
            return reject("NO_TARGET_WITH_MIN_RR")

        bias = self.htf.trend
        ctx = self.ctx.trend if self.agg_ctx is not None else 0
        if self.mtf_cfg.get("block_against_context") and bias * d < 0 and ctx * d < 0:
            return reject("HTF_CONTEXT_AGAINST")  # H1 and H4 both against: no counter-trend raids
        zone = self._h1_zone(entry)
        sb = self._score(sw, br, fvg, bias * d, rr, spread, close_t, ctx * d, zone, d)
        score = sum(sb.values())
        grade = "A_PLUS" if score >= self.spec["scoring"]["a_plus"] else "WATCH" if score >= self.spec["scoring"]["watch"] else "IGNORE"
        if self.entry_cfg.get("require_htf_bias") and bias * d <= 0:
            return reject("HTF_BIAS_AGAINST")
        sid = signal_key(self.version, self.symbol, self.SETUP, close_t, f"{sw.level.name}@{sw.index}", dname, entry, self.pip)
        trace = [
            f"OBSERVED: {sw.level.name} {sw.level.price:.5f} swept (extreme {sw.extreme:.5f}) and reclaimed at bar {sw.index}",
            f"OBSERVED: {br.kind} {dname} through swing {br.level:.5f} with displacement at bar {br.index}",
            f"OBSERVED: {dname} FVG {fvg.bottom:.5f}-{fvg.top:.5f} created bar {fvg.created_at}, unmitigated",
            f"RULE_BASED_INFERENCE: possible failed {'breakdown' if d == 1 else 'breakout'} (liquidity raid hypothesis)",
            f"TARGET: {target.name} {target.price:.5f}, net RR {rr:.2f} after spread",
            f"HTF_BIAS: H1 {'aligned' if bias * d > 0 else 'neutral' if bias == 0 else 'against'}, "
            f"H4 {'aligned' if ctx * d > 0 else 'neutral' if ctx == 0 else 'against'}",
            f"H1_ZONE: {zone[0]}" + (f" ({zone[1]:.2f} of H1 range)" if zone[1] is not None else ""),
            "UNAVAILABLE: actual bank order locations / stop inventory",
        ]
        return Signal(sid, self.symbol, dname, self.SETUP, a.i, close_t, entry, stop, (target.price,), spread, atr,
                      score, grade, a.i + self.entry_cfg["expiry_bars"], self.sessions.active(close_t), bias, trace, sb,
                      sw.level.name, target.name, self._mtf_text(ctx, bias, zone, sw, br, fvg),
                      (fvg.bottom, fvg.top))

    def _h1_zone(self, price: float) -> tuple[str, float | None]:
        """Premium/discount of `price` inside the latest H1 dealing range (last confirmed H1 swing high/low)."""
        hi, lo = self.htf.last_swing("HIGH", unbroken=False), self.htf.last_swing("LOW", unbroken=False)
        if hi is None or lo is None or hi.price <= lo.price:
            return "UNKNOWN", None
        loc = (price - lo.price) / (hi.price - lo.price)
        name = "DISCOUNT" if loc < 0.5 else "PREMIUM"
        if loc < 0 or loc > 1:
            name = "OUTSIDE_RANGE"
        return name, loc

    @staticmethod
    def _trend_word(t: int) -> str:
        return "UP" if t > 0 else "DOWN" if t < 0 else "RANGE"

    def _mtf_text(self, ctx: int, bias: int, zone: tuple[str, float | None], sw: Sweep, br: StructureBreak,
                  fvg: FVG) -> dict[str, str]:
        last = self.htf.breaks[-1] if self.htf.breaks else None
        return {
            "H4": self._trend_word(ctx) if self.agg_ctx is not None else "OFF",
            "H1": self._trend_word(bias),
            "H1_LAST": f"{last.kind}_{'UP' if last.direction > 0 else 'DOWN'}" if last else "NONE",
            "H1_ZONE": zone[0],
            "M15": f"{sw.level.name}_SWEEP>{br.kind}>FVG",
            "M5": "OFF",  # set by the multi-timeframe engine when M5 confirmation is enabled
        }

    def _score(self, sw: Sweep, br: StructureBreak, fvg: FVG, align: int, rr: float, spread: float,
               t: datetime, ctx_align: int = 0, zone: tuple[str, float | None] = ("UNKNOWN", None),
               d: int = 1) -> dict[str, int]:
        liq = {"PDH": 15, "PDL": 15, "EQH": 15, "EQL": 15, "ASIA_H": 12, "ASIA_L": 12}.get(sw.level.name, 8)
        sess = self.sessions.active(t)
        return {
            # H1 bias up to 10, H4 context up to 5 (same 15-point budget as before)
            "htf_bias": (10 if align > 0 else 5 if align == 0 else 0) + (5 if ctx_align > 0 else 2 if ctx_align == 0 else 0),
            "structure": 15 if br.kind == "CHOCH" else 10,
            "liquidity": liq,
            "displacement": 10,
            "fvg_quality": 10 if fvg.displacement else 5,
            "session": 10 if {"LONDON", "NEW_YORK"} <= set(sess) else 8,
            "target_path": 10 if rr >= 3 else 6,
            "quote_cost": 10 if spread / self.pip <= self.max_spread / 2 else 5 if spread / self.pip <= self.max_spread else 0,
            "news_integrity": 0,  # filled by the scanner once the calendar is checked
        }


def _dir(d: int) -> str:
    return "BUY" if d == 1 else "SELL"
