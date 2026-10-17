"""As-of regime detector (plan §7.1, ticket AI-010), research only.

Pre-registered before any real data was seen; changing a threshold needs a new `VERSION`. Labels come from CLOSED
H4 bars only (built from closed M15 bars by the legacy aggregator), so a label is known at the close of the H4 bar
that produced it (`detected_at`) and never earlier. Labels are computed once, forward in time, and never rewritten:
a later bar can change the next label, not an earlier one.

Features at each H4 close (all from that bar and earlier ones):
- `efficiency`: Kaufman efficiency ratio over the last `ER_BARS` H4 closes, |net move| / sum of |moves| (0..1).
- `slope_atr`: change of EMA(`EMA_BARS`) over the last `SLOPE_BARS` H4 bars, per bar, in units of ATR(H4).
- `atr_percentile`: rank of today's ATR(H4) among the previous `VOL_WINDOW` ATR(H4) values (past only, the current
  value is not part of its own baseline).

Rules, in this order:
1. `UNKNOWN` until every feature exists (warm-up), or when the bar sequence has a gap longer than `MAX_GAP`.
2. `HIGH_VOL` when `atr_percentile` >= `HIGH_VOL_PCT`.
3. `TREND_UP` / `TREND_DOWN` when `efficiency` >= `TREND_ER` and |`slope_atr`| >= `TREND_SLOPE` (sign of the slope)
   and the close is on the same side of the EMA.
4. `RANGE` when `efficiency` <= `RANGE_ER` and |`slope_atr`| <= `RANGE_SLOPE`.
5. `TRANSITION` otherwise: between the thresholds, so the label is uncertain.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from ayesha.models import Candle
from ayesha.research.provenance import iso
from ayesha.research.strategies.protocol import EMA, AsOfContext, code_sha
from ayesha.rules.primitives import ATR

DETECTOR_ID = "regime-h4-er-slope-vol"
VERSION = "1.0.0"
LABELS = ("TREND_UP", "TREND_DOWN", "RANGE", "HIGH_VOL", "TRANSITION", "UNKNOWN")

ER_BARS = 20
EMA_BARS = 20
SLOPE_BARS = 5
ATR_BARS = 14
VOL_WINDOW = 120         # 20 trading days of H4 bars
HIGH_VOL_PCT = 0.90
TREND_ER = 0.35
TREND_SLOPE = 0.10
RANGE_ER = 0.20
RANGE_SLOPE = 0.05
MAX_GAP = timedelta(days=4)  # a weekend is about 2 days; longer means missing data
WARMUP_H4 = VOL_WINDOW + ATR_BARS

PARAMETERS = {"er_bars": ER_BARS, "ema_bars": EMA_BARS, "slope_bars": SLOPE_BARS, "atr_bars": ATR_BARS,
              "vol_window": VOL_WINDOW, "high_vol_percentile": HIGH_VOL_PCT, "trend_er": TREND_ER,
              "trend_slope_atr": TREND_SLOPE, "range_er": RANGE_ER, "range_slope_atr": RANGE_SLOPE,
              "max_gap_hours": MAX_GAP.total_seconds() / 3600}


@dataclass(frozen=True)
class RegimeLabel:
    label: str
    detected_at: datetime | None          # close time of the H4 bar that produced it
    efficiency: float | None = None
    slope_atr: float | None = None
    atr_percentile: float | None = None
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["detected_at"] = iso(self.detected_at)
        for k in ("efficiency", "slope_atr", "atr_percentile"):
            d[k] = None if d[k] is None else round(d[k], 4)
        return d


START = RegimeLabel("UNKNOWN", None, reason="WARMUP")


class RegimeDetector:
    """Feed it every closed base bar through `update(ctx)`; `current` is the label known at that bar's close."""

    def __init__(self) -> None:
        self._reset()
        self.last_time: datetime | None = None
        self.current = START
        self.history: list[RegimeLabel] = []

    def _reset(self) -> None:
        self.ema = EMA(EMA_BARS)
        self.atr = ATR(ATR_BARS)
        self.closes: deque[float] = deque(maxlen=ER_BARS + 1)
        self.emas: deque[float] = deque(maxlen=SLOPE_BARS + 1)
        self.atrs: deque[float] = deque(maxlen=VOL_WINDOW)

    def update(self, ctx: AsOfContext) -> RegimeLabel:
        h4 = ctx.just_closed("H4")
        if h4 is not None:
            self.current = self._on_h4(h4, ctx.close_utc)
            self.history.append(self.current)
        return self.current

    def _on_h4(self, b: Candle, closed_at: datetime) -> RegimeLabel:
        gap = self.last_time is not None and b.time - self.last_time > MAX_GAP
        if gap:
            self._reset()  # a hole in the data: start the warm-up again rather than bridge it
        self.last_time = b.time
        ema = self.ema.update(b.close)
        atr_prev = list(self.atrs)
        atr = self.atr.update(b)
        self.closes.append(b.close)
        if ema is not None:
            self.emas.append(ema)
        if atr is not None:
            self.atrs.append(atr)
        if (ema is None or atr is None or atr <= 0 or len(self.closes) <= ER_BARS or len(self.emas) <= SLOPE_BARS
                or len(atr_prev) < VOL_WINDOW):
            return RegimeLabel("UNKNOWN", closed_at, reason="DATA_GAP" if gap else "WARMUP")
        cl = list(self.closes)
        path = sum(abs(cl[i] - cl[i - 1]) for i in range(1, len(cl)))
        er = abs(cl[-1] - cl[0]) / path if path > 0 else 0.0
        slope = (self.emas[-1] - self.emas[0]) / SLOPE_BARS / atr
        pct = sum(1 for a in atr_prev if a < atr) / len(atr_prev)
        feats = {"efficiency": er, "slope_atr": slope, "atr_percentile": pct}
        if pct >= HIGH_VOL_PCT:
            return RegimeLabel("HIGH_VOL", closed_at, **feats, reason="ATR_PERCENTILE")
        if er >= TREND_ER and slope >= TREND_SLOPE and b.close > ema:
            return RegimeLabel("TREND_UP", closed_at, **feats, reason="EFFICIENT_RISING")
        if er >= TREND_ER and slope <= -TREND_SLOPE and b.close < ema:
            return RegimeLabel("TREND_DOWN", closed_at, **feats, reason="EFFICIENT_FALLING")
        if er <= RANGE_ER and abs(slope) <= RANGE_SLOPE:
            return RegimeLabel("RANGE", closed_at, **feats, reason="INEFFICIENT_FLAT")
        return RegimeLabel("TRANSITION", closed_at, **feats, reason="BETWEEN_THRESHOLDS")


def manifest() -> dict[str, Any]:
    return {"detector_id": DETECTOR_ID, "version": VERSION, "labels": list(LABELS), "parameters": PARAMETERS,
            "source": "closed H4 bars aggregated from closed M15 bars (legacy Aggregator)",
            "warmup_h4_bars": WARMUP_H4, "code_sha256": code_sha(__file__),
            "note": "context only: never a permission to trade, never a gate; thresholds pre-registered"}


def timeline(symbol: str, candles: list[Candle]) -> dict[str, Any]:
    """Labels over a series, for the `research regime` command and the dashboard."""
    ctx, det = AsOfContext(symbol), RegimeDetector()
    for c in candles:
        ctx.advance(c)
        det.update(ctx)
    hist = det.history
    counts = {k: 0 for k in LABELS}
    for h in hist:
        counts[h.label] += 1
    switches = sum(1 for a, b in zip(hist, hist[1:]) if a.label != b.label)
    known = [h for h in hist if h.label != "UNKNOWN"]
    return {"symbol": symbol, "detector": manifest(), "h4_bars": len(hist),
            "share": {k: (round(v / len(hist), 3) if hist else None) for k, v in counts.items()},
            "counts": counts, "switches": switches,
            "first_known_at": iso(known[0].detected_at) if known else None,
            "recent": [h.as_dict() for h in hist[-30:]]}
