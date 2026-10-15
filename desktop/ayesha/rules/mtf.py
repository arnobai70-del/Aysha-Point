"""Multi-timeframe engine: one explainable setup per pair, never one signal per timeframe.

    H4  context   major structure direction (aggregated from the setup bars)
    H1  bias      trend, last BOS/CHoCH, premium/discount of the H1 dealing range
    M15 setup     SWEEP -> MSS -> FVG candidate (SweepMssFvg)
    M5  confirm   optional: after price trades into the entry zone, an M5 candle must close
                  back in the trade direction, beyond the touch bar's extreme, with a real body.
                  Entry becomes that candle's close; RR is recomputed and must still pass.
    M1  scalp     not implemented; refused while `mtf.scalp_m1.enabled` is not validated.

The engine is fed CLOSED base bars: M5 when confirmation is on, otherwise M15. Everything is
causal: a confirmation can only use base bars that close after the setup bar.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any

from ayesha.models import Candle
from ayesha.rules.primitives import ATR
from ayesha.rules.strategy import TF_MINUTES, Aggregator, Signal, SweepMssFvg


class ScalpModeNotValidated(RuntimeError):
    pass


def check_scalp(spec: dict[str, Any]) -> None:
    sc = spec.get("mtf", {}).get("scalp_m1", {})
    if sc.get("enabled"):
        raise ScalpModeNotValidated("M1 scalp mode is disabled until it has its own validation evidence "
                                    "(set mtf.scalp_m1.enabled: false)")


@dataclass
class Event:
    kind: str  # SETUP | CONFIRMED | CONFIRM_FAILED
    signal: Signal
    reason: str = ""
    needs_confirmation: bool = False


@dataclass
class _Pending:
    sig: Signal
    born: int            # base-bar index when the setup closed
    touched_at: int | None = None
    touch_extreme: float | None = None


class MtfEngine:
    def __init__(self, symbol: str, spec: dict[str, Any]) -> None:
        check_scalp(spec)
        self.spec = spec
        self.strat = SweepMssFvg(symbol, spec)
        mtf = spec.get("mtf", {})
        self.setup_tf = spec["entry"]["setup_timeframe"]
        self.confirm_tf = mtf.get("confirm_timeframe") or None
        if self.confirm_tf and TF_MINUTES[self.confirm_tf] >= TF_MINUTES[self.setup_tf]:
            raise ValueError("confirm_timeframe must be lower than the setup timeframe")
        self.base_tf = self.confirm_tf or self.setup_tf
        self.base_min = TF_MINUTES[self.base_tf]
        self.agg = Aggregator(self.base_min, TF_MINUTES[self.setup_tf]) if self.confirm_tf else None
        self.within = int(mtf.get("confirm_within_bars", 6))
        self.body_atr = float(mtf.get("confirm_body_atr", 0.8))
        self.atr = ATR(spec["rules"]["atr_period"])
        self.min_rr = spec["risk"]["min_net_rr"]
        self.slip = spec["risk"]["slippage_buffer_pips"] * self.strat.pip
        ratio = TF_MINUTES[self.setup_tf] // self.base_min
        self.window = spec["entry"]["expiry_bars"] * ratio  # base bars a setup stays alive
        self.i = -1
        self.pending: dict[str, _Pending] = {}

    @property
    def rejections(self):
        return self.strat.rejections

    def on_bar(self, c: Candle) -> list[Event]:
        self.i += 1
        atr = self.atr.update(c)
        out: list[Event] = []
        if self.confirm_tf:
            out += self._confirm_step(c, atr)
            setup_bar = self.agg.update(c)
            sigs = self.strat.on_bar(setup_bar) if setup_bar is not None else []
        else:
            sigs = self.strat.on_bar(c)
        for s in sigs:
            s.mtf["M5"] = "PENDING" if self.confirm_tf else "OFF"
            out.append(Event("SETUP", s, needs_confirmation=bool(self.confirm_tf)))
            if self.confirm_tf:
                self.pending[s.signal_id] = _Pending(s, self.i)
        return out

    def _confirm_step(self, c: Candle, atr: float | None) -> list[Event]:
        out = []
        for sid, p in list(self.pending.items()):
            s = p.sig
            buy = s.direction == "BUY"
            fail = None
            if (c.low <= s.stop) if buy else (c.high >= s.stop):
                fail = "STOP_BEFORE_CONFIRMATION"
            elif self.i - p.born > self.window:
                fail = "SETUP_EXPIRED_UNCONFIRMED"
            elif p.touched_at is None:
                if (c.low <= s.entry) if buy else (c.high >= s.entry):
                    p.touched_at, p.touch_extreme = self.i, (c.high if buy else c.low)
                elif (c.high >= s.targets[-1]) if buy else (c.low <= s.targets[-1]):
                    fail = "TARGET_REACHED_BEFORE_ENTRY"
            else:
                body_ok = atr is not None and c.body >= self.body_atr * atr
                beyond = c.close > p.touch_extreme if buy else c.close < p.touch_extreme
                in_dir = c.bullish if buy else c.bearish
                if in_dir and beyond and body_ok:
                    entry = c.close
                    loss = abs(entry - s.stop) + c.spread + self.slip
                    rr = (abs(s.targets[-1] - entry) - c.spread) / loss if loss > 0 else 0
                    if rr < self.min_rr:
                        fail = "RR_BELOW_MIN_AFTER_CONFIRMATION"
                    else:
                        mtf = dict(s.mtf, M5=f"CONFIRMED_{'UP' if buy else 'DOWN'}")
                        conf = replace(s, entry=entry, spread=c.spread, mtf=mtf,
                                       trace=s.trace + [f"OBSERVED: M5 confirmation candle closed {entry:.5f} "
                                                        f"beyond touch-bar extreme {p.touch_extreme:.5f}; "
                                                        f"net RR now {rr:.2f}"])
                        conf.bar_close_utc = c.time + timedelta(minutes=self.base_min)
                        out.append(Event("CONFIRMED", conf))
                        del self.pending[sid]
                        continue
                elif self.i - p.touched_at >= self.within:
                    fail = "NO_M5_CONFIRMATION"
                else:
                    p.touch_extreme = max(p.touch_extreme, c.high) if buy else min(p.touch_extreme, c.low)
            if fail:
                s.mtf["M5"] = "FAILED"
                out.append(Event("CONFIRM_FAILED", s, fail))
                del self.pending[sid]
        return out
