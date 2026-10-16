"""Cost models for the Strategy Lab (plan §6.3, §12 sensitivity; ticket AI-009).

The base model is the legacy replay's, word for word, because the common runner uses the legacy fill functions:
a fill pays the spread of its bar, the slippage buffer of the spec is added to the planned loss and to stop exits,
a bar that touches both stop and target is a stop, the fill bar cannot take profit, a gap through the stop exits
at the open, open trades are closed before the New York rollover, commission 0 (Exness Standard assumption).

Sensitivity variants change one cost at a time: wider spreads (+25 %, +50 %, applied to every bar, so the spread gate
sees them too), extra adverse slippage, or every decision acted on one closed bar late. Every model has an id and a
hash, and every strategy in one comparison runs with exactly the same models.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from ayesha.models import Candle
from ayesha.research.provenance import digest


@dataclass(frozen=True)
class CostModel:
    model_id: str = "lab-base-v1"
    spread_multiplier: float = 1.0
    extra_slippage_pips: float = 0.0
    delay_bars: int = 0
    commission_usd_per_lot: float = 0.0  # round trip; used by the account simulation (Standard account: 0)
    description: str = ("legacy replay fills: bar spread on each fill, spec slippage buffer on the plan and on stop "
                        "exits, stop first when a bar touches stop and target, no take-profit on the fill bar, gap "
                        "through the stop exits at the open, flat before the New York rollover, commission 0")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def hash(self) -> str:
        return digest(self.as_dict())[:16]

    def apply(self, candles: list[Candle]) -> list[Candle]:
        if self.spread_multiplier == 1.0:
            return candles
        m = self.spread_multiplier
        return [replace(c, spread=c.spread * m) for c in candles]


BASE = CostModel()
SENSITIVITY = (
    replace(BASE, model_id="spread+25%", spread_multiplier=1.25, description="every bar's spread x 1.25"),
    replace(BASE, model_id="spread+50%", spread_multiplier=1.5, description="every bar's spread x 1.5"),
    replace(BASE, model_id="slippage+0.5pip", extra_slippage_pips=0.5,
            description="0.5 pip extra adverse slippage on the planned loss and on stop exits"),
    replace(BASE, model_id="delay-1-bar", delay_bars=1,
            description="every decision acted on one closed bar later than the strategy produced it"),
)
