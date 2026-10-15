"""Core data types shared by feed, rules, risk and backtest."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class Candle:
    """One closed bar. Prices are BID prices; `spread` is in price units (ask - bid) at bar close."""

    time: datetime  # UTC bar open time, tz-aware
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0  # tick volume for OTC forex, not traded volume
    spread: float = 0.0

    def __post_init__(self) -> None:
        if self.time.tzinfo is None:
            raise ValueError("Candle.time must be timezone-aware UTC")
        if not (self.low <= min(self.open, self.close) and self.high >= max(self.open, self.close)):
            raise ValueError(f"Inconsistent OHLC at {self.time}: {self.open} {self.high} {self.low} {self.close}")

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def bullish(self) -> bool:
        return self.close > self.open

    @property
    def bearish(self) -> bool:
        return self.close < self.open


@dataclass(frozen=True)
class InstrumentSpec:
    """Broker contract specification for one symbol, as read from the broker terminal.

    `tick_value` is the profit/loss in ACCOUNT currency for one tick move on 1.0 lot
    (MT5 `trade_tick_value`), which already includes quote->USD conversion.
    """

    symbol: str
    digits: int
    tick_size: float
    tick_value: float
    contract_size: float
    volume_min: float
    volume_step: float
    volume_max: float
    pip_size: float
    base_currency: str
    quote_currency: str
    commission_per_lot_round_trip: float = 0.0
    stops_level_points: int = 0
    margin_per_lot: float | None = None  # account currency, if known
    source: str = "UNKNOWN"

    @property
    def pip_value_per_lot(self) -> float:
        return self.tick_value * (self.pip_size / self.tick_size)

    @property
    def point(self) -> float:
        return 10 ** (-self.digits)


@dataclass(frozen=True)
class Quote:
    symbol: str
    time: datetime
    bid: float
    ask: float

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    def age_seconds(self, now: datetime | None = None) -> float:
        now = now or datetime.now(timezone.utc)
        return (now - self.time).total_seconds()


@dataclass
class AccountState:
    equity_usd: float
    balance_usd: float | None = None
    free_margin_usd: float | None = None
    realized_loss_today_usd: float = 0.0
    losses_today: int = 0
    open_risk_usd: float = 0.0
    open_positions: list[tuple[str, str]] = field(default_factory=list)  # (symbol, BUY|SELL)


def pip_size_for(symbol: str) -> float:
    """Conventional pip size: 0.01 for JPY quote pairs, 0.0001 otherwise (FX majors/crosses)."""
    return 0.01 if symbol.upper()[3:6] == "JPY" else 0.0001
