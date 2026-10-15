"""Risk engine: position sizing and hard NO_TRADE gates (master spec section K).

Price convention: all levels (entry, stop, targets) are BID-chart prices, as broker charts
show. Model: every order triggers when the BID touches its level, and the round trip pays
one spread. So in both directions the executable loss distance is |entry - stop| + spread
and the profit distance is |target - entry| - spread. `broker_order_prices` converts the
chart levels into the prices to type into MT5 so that this model holds. A slippage buffer
is added to the loss side only. Nothing here can round a lot UP to make a trade possible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from ayesha.models import AccountState, InstrumentSpec

# Hard per-trade ceiling. No config value, news model or score can raise it (News spec B2, C05).
HARD_MAX_RISK_PERCENT = 1.0


@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade_percent: float = 0.5
    max_risk_per_trade_percent: float = 1.0
    max_open_risk_percent: float = 1.0
    max_daily_loss_percent: float = 2.0
    max_losses_per_day: int = 2
    max_same_currency_positions: int = 1
    min_net_rr: float = 2.0
    max_spread_pips: float = 1.5
    slippage_buffer_pips: float = 0.3
    min_stop_atr_fraction: float = 0.5
    max_quote_age_seconds: float = 30
    strict_news: bool = True

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> "RiskConfig":
        names = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in spec["risk"].items() if k in names})


@dataclass(frozen=True)
class TradeProposal:
    symbol: str
    direction: str  # BUY | SELL
    entry: float
    stop: float
    targets: tuple[float, ...]
    spread: float  # price units, current or expected
    atr: float  # price units on the setup timeframe
    quote_age_seconds: float = 0.0
    market_open: bool = True
    news_status: str = "UNKNOWN"  # CLEAR | BLOCKED | UNKNOWN


@dataclass
class RiskDecision:
    ok: bool
    blockers: list[str] = field(default_factory=list)
    lot: float = 0.0
    raw_lot: float = 0.0
    risk_budget_usd: float = 0.0
    max_loss_usd: float = 0.0
    loss_per_lot_usd: float = 0.0
    net_rr: list[float] = field(default_factory=list)
    stop_pips: float = 0.0
    min_lot_loss_usd: float = 0.0  # what the smallest allowed trade would risk
    min_lot_loss_percent: float = 0.0
    nominal_budget_usd: float = 0.0  # equity x risk%: before the daily / open-risk limits
    budget_limited_by: str = ""  # "" | DAILY_LOSS_LIMIT | OPEN_RISK_LIMIT
    margin_required_usd: float | None = None

    @property
    def status(self) -> str:
        return "RISK_VALIDATED" if self.ok else "NO_TRADE"


def floor_to_step(volume: float, step: float) -> float:
    """Floor a volume to the broker step using decimal math (never rounds up)."""
    v, s = Decimal(str(volume)), Decimal(str(step))
    if s <= 0:
        raise ValueError("volume_step must be positive")
    return float((v / s).to_integral_value(rounding=ROUND_FLOOR) * s)


def currency_exposure(symbol: str, direction: str) -> dict[str, int]:
    base, quote = symbol[:3].upper(), symbol[3:6].upper()
    sign = 1 if direction == "BUY" else -1
    return {base: sign, quote: -sign}


def evaluate(
    p: TradeProposal, inst: InstrumentSpec, acct: AccountState, cfg: RiskConfig, *, live: bool = True
) -> RiskDecision:
    """Size a proposal and apply every hard gate. `live=False` is for research/backtests only."""
    d = RiskDecision(ok=False)
    b = d.blockers
    if live and not (inst.source.startswith("MT5") or inst.source.startswith("OWNER_CONFIRMED:")):
        b.append("BROKER_SPEC_UNVERIFIED")

    # --- configuration and environment gates -------------------------------------------
    rp = cfg.risk_per_trade_percent
    if not (math.isfinite(rp) and 0 < rp <= min(cfg.max_risk_per_trade_percent, HARD_MAX_RISK_PERCENT)):
        b.append("CONFIG_RISK_ABOVE_CAP")
    if not math.isfinite(acct.equity_usd) or acct.equity_usd <= 0:
        b.append("EQUITY_UNKNOWN")
    if not all(math.isfinite(x) and x >= 0 for x in (acct.realized_loss_today_usd, acct.open_risk_usd)):
        b.append("ACCOUNT_STATE_INVALID")
    if inst.tick_value <= 0 or inst.tick_size <= 0 or inst.volume_step <= 0 or inst.volume_min <= 0:
        b.append("CONTRACT_SPEC_MISSING")
    if not p.market_open:
        b.append("MARKET_CLOSED")
    if p.quote_age_seconds > cfg.max_quote_age_seconds:
        b.append("DATA_STALE")
    if p.news_status == "BLOCKED":
        b.append("NEWS_LOCKOUT")
    elif p.news_status != "CLEAR" and cfg.strict_news:
        b.append("NEWS_UNVERIFIED")

    # --- geometry ------------------------------------------------------------------------
    if p.direction not in ("BUY", "SELL") or not p.targets:
        b.append("INVALID_PROPOSAL")
        return d
    sgn = 1 if p.direction == "BUY" else -1
    if sgn * (p.entry - p.stop) <= 0 or any(sgn * (t - p.entry) <= 0 for t in p.targets):
        b.append("INVALID_LEVELS")
        return d
    if "CONTRACT_SPEC_MISSING" in b or "EQUITY_UNKNOWN" in b or "ACCOUNT_STATE_INVALID" in b \
            or "CONFIG_RISK_ABOVE_CAP" in b:
        return d

    pip = inst.pip_size
    stop_dist = abs(p.entry - p.stop)
    d.stop_pips = stop_dist / pip
    if p.spread / pip > cfg.max_spread_pips:
        b.append("SPREAD_TOO_WIDE")
    if p.atr > 0 and stop_dist < cfg.min_stop_atr_fraction * p.atr:
        b.append("STOP_TOO_TIGHT_FOR_VOLATILITY")
    if inst.stops_level_points and stop_dist < inst.stops_level_points * inst.point:
        b.append("STOP_INSIDE_BROKER_STOPS_LEVEL")

    # --- sizing (spec B2: usable = min(nominal, remaining daily, remaining open)) ----------------
    eq = acct.equity_usd
    per_price_per_lot = inst.tick_value / inst.tick_size  # USD per 1.0 price unit per lot
    loss_price = stop_dist + p.spread + cfg.slippage_buffer_pips * pip
    d.loss_per_lot_usd = loss_price * per_price_per_lot + inst.commission_per_lot_round_trip
    d.nominal_budget_usd = eq * rp / 100.0
    remaining_day = eq * cfg.max_daily_loss_percent / 100.0 - acct.realized_loss_today_usd - acct.open_risk_usd
    remaining_open = eq * cfg.max_open_risk_percent / 100.0 - acct.open_risk_usd
    d.risk_budget_usd = max(0.0, min(d.nominal_budget_usd, remaining_day, remaining_open))
    if d.risk_budget_usd < d.nominal_budget_usd - 1e-12:
        d.budget_limited_by = "DAILY_LOSS_LIMIT" if remaining_day <= remaining_open else "OPEN_RISK_LIMIT"
    d.raw_lot = d.risk_budget_usd / d.loss_per_lot_usd
    d.lot = min(floor_to_step(d.raw_lot, inst.volume_step), floor_to_step(inst.volume_max, inst.volume_step))
    d.min_lot_loss_usd = inst.volume_min * d.loss_per_lot_usd
    d.min_lot_loss_percent = 100.0 * d.min_lot_loss_usd / eq
    if d.lot < inst.volume_min:
        if d.risk_budget_usd <= 0:
            b.append("DAILY_RISK_PAUSE" if d.budget_limited_by == "DAILY_LOSS_LIMIT" else "OPEN_RISK_CAP")
        else:
            b.append("MIN_LOT_EXCEEDS_RISK")
        d.lot = 0.0
    d.max_loss_usd = d.lot * d.loss_per_lot_usd

    for t in p.targets:
        profit_price = abs(t - p.entry) - p.spread
        profit = profit_price * per_price_per_lot - inst.commission_per_lot_round_trip
        d.net_rr.append(round(profit / d.loss_per_lot_usd, 3))
    if d.net_rr[-1] < cfg.min_net_rr:
        b.append("NET_RR_BELOW_MIN")

    # --- account-level circuit breakers ------------------------------------------------------
    if acct.losses_today >= cfg.max_losses_per_day and "DAILY_RISK_PAUSE" not in b:
        b.append("DAILY_RISK_PAUSE")
    elif acct.realized_loss_today_usd + acct.open_risk_usd + d.max_loss_usd > eq * cfg.max_daily_loss_percent / 100.0 + 1e-9 \
            and "DAILY_RISK_PAUSE" not in b:
        b.append("DAILY_RISK_PAUSE")
    if acct.open_risk_usd + d.max_loss_usd > eq * cfg.max_open_risk_percent / 100.0 + 1e-9 and "OPEN_RISK_CAP" not in b:
        b.append("OPEN_RISK_CAP")
    new_exp = currency_exposure(p.symbol, p.direction)
    for ccy, s in new_exp.items():
        same = sum(1 for sym, dr in acct.open_positions if currency_exposure(sym, dr).get(ccy) == s)
        if same >= cfg.max_same_currency_positions:
            b.append(f"CORRELATED_EXPOSURE_{ccy}")
            break
    if inst.margin_per_lot is not None and acct.free_margin_usd is not None and d.lot > 0:
        d.margin_required_usd = d.lot * inst.margin_per_lot
        if d.margin_required_usd > acct.free_margin_usd:
            b.append("INSUFFICIENT_FREE_MARGIN")
    elif live and d.lot > 0:
        b.append("MARGIN_UNVERIFIED")  # leverage or free margin unknown: never assume the margin is there

    d.ok = not b
    return d


def broker_order_prices(direction: str, entry: float, stop: float, target: float, spread: float) -> dict[str, float]:
    """MT5 limit/SL/TP prices that reproduce the "bid touches the chart level" model.

    MT5 triggers BUY entries and SELL exits on the ask, and SELL entries and BUY exits on the bid.
    """
    if direction == "BUY":
        return {"limit": entry + spread, "sl": stop, "tp": target}
    return {"limit": entry, "sl": stop + spread, "tp": target + spread}
