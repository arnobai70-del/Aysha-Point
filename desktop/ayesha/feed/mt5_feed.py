"""Read-only MetaTrader 5 adapter (Windows, local terminal already logged in by the owner).

Safety: this module only ever calls functions in `_ALLOWED`. Any other attribute of the
MetaTrader5 package (including every trading function) is unreachable through `_MT5`,
and `scripts/check_no_order_api.py` fails CI if trading calls appear anywhere in the repo.
No login, password or server is ever passed or stored: the terminal must already be open.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ayesha.models import Candle, InstrumentSpec, Quote, pip_size_for

_ALLOWED = frozenset({
    "initialize", "shutdown", "last_error", "version", "terminal_info", "account_info",
    "symbols_get", "symbol_info", "symbol_select", "symbol_info_tick", "copy_rates_range",
    "copy_rates_from_pos", "order_calc_margin",
    "TIMEFRAME_M1", "TIMEFRAME_M5", "TIMEFRAME_M15", "TIMEFRAME_H1", "TIMEFRAME_H4", "TIMEFRAME_D1",
    "ORDER_TYPE_BUY",  # constant only, used for margin calculation
})

TIMEFRAMES = {"M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
              "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4", "D1": "TIMEFRAME_D1"}


class _MT5:
    """Allow-list proxy around the MetaTrader5 module."""

    def __init__(self, module: Any) -> None:
        self._m = module

    def __getattr__(self, name: str) -> Any:
        if name not in _ALLOWED:
            raise PermissionError(f"MT5 function '{name}' is not allowed (read-only adapter)")
        return getattr(self._m, name)


class MT5ReadOnlyFeed:
    def __init__(self, module: Any | None = None, server_utc_offset_hours: float = 0.0) -> None:
        if module is None:
            try:
                import MetaTrader5 as module  # type: ignore[no-redef]
            except ImportError as e:  # pragma: no cover - Windows only
                raise RuntimeError("MetaTrader5 package not installed. Run: pip install MetaTrader5 (Windows)") from e
        self.mt5 = _MT5(module)
        self._aliases: dict[str, str] = {}
        self._offset = timedelta(hours=server_utc_offset_hours)

    # --- lifecycle -------------------------------------------------------------------------
    def connect(self) -> dict[str, Any]:
        if not self.mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {self.mt5.last_error()} (is the terminal open and logged in?)")
        return self.account()

    def account(self) -> dict[str, Any]:
        acct = self.mt5.account_info()
        if acct is None:
            raise RuntimeError("MT5 terminal has no logged-in account")
        return {
            "login_masked": f"***{str(acct.login)[-3:]}",
            "server": acct.server,
            "currency": acct.currency,
            "balance": acct.balance,
            "equity": acct.equity,
            "margin_free": acct.margin_free,
            "leverage": acct.leverage,
            "trade_mode": {0: "DEMO", 1: "CONTEST", 2: "REAL"}.get(acct.trade_mode, str(acct.trade_mode)),
        }

    def close(self) -> None:
        self.mt5.shutdown()

    # --- symbols ---------------------------------------------------------------------------
    def resolve(self, symbol: str) -> str:
        """Map a canonical symbol (EURUSD) to the broker name (e.g. EURUSDm on Exness Standard)."""
        symbol = symbol.upper()
        if symbol in self._aliases:
            return self._aliases[symbol]
        if self.mt5.symbol_info(symbol) is not None:
            name = symbol
        else:
            cands = sorted(s.name for s in (self.mt5.symbols_get(f"{symbol}*") or []))
            if not cands:
                raise KeyError(f"Symbol {symbol} not found on this account")
            name = cands[0]
        self.mt5.symbol_select(name, True)
        self._aliases[symbol] = name
        return name

    def instrument(self, symbol: str) -> InstrumentSpec:
        name = self.resolve(symbol)
        i = self.mt5.symbol_info(name)
        if i is None:
            raise KeyError(name)
        margin = None
        tick = self.mt5.symbol_info_tick(name)
        if tick is not None:
            margin = self.mt5.order_calc_margin(self.mt5.ORDER_TYPE_BUY, name, 1.0, tick.ask)
        return InstrumentSpec(
            symbol=symbol.upper(),
            digits=i.digits,
            tick_size=i.trade_tick_size,
            tick_value=i.trade_tick_value,
            contract_size=i.trade_contract_size,
            volume_min=i.volume_min,
            volume_step=i.volume_step,
            volume_max=i.volume_max,
            pip_size=pip_size_for(symbol),
            base_currency=i.currency_base,
            quote_currency=i.currency_profit,
            stops_level_points=i.trade_stops_level,
            margin_per_lot=margin,
            source=f"MT5:{name}",
        )

    def quote(self, symbol: str) -> Quote:
        name = self.resolve(symbol)
        t = self.mt5.symbol_info_tick(name)
        if t is None:
            raise RuntimeError(f"No tick for {name}")
        return Quote(symbol.upper(), datetime.fromtimestamp(t.time, tz=timezone.utc) - self._offset, t.bid, t.ask)

    def candles(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[Candle]:
        """Closed bars only: a bar whose open+duration is after `end` is dropped by the caller.

        MT5 bar times are broker server time. `server_utc_offset_hours` converts them to UTC;
        `ayesha spec-check` prints an estimate from the live tick time so it can be verified.
        """
        name = self.resolve(symbol)
        tf = getattr(self.mt5, TIMEFRAMES[timeframe])
        rates = self.mt5.copy_rates_range(name, tf, start, end)
        if rates is None:
            raise RuntimeError(f"copy_rates_range failed: {self.mt5.last_error()}")
        point = 10 ** (-self.mt5.symbol_info(name).digits)
        return [
            Candle(datetime.fromtimestamp(int(r["time"]), tz=timezone.utc) - self._offset, float(r["open"]), float(r["high"]),
                   float(r["low"]), float(r["close"]), float(r["tick_volume"]), float(r["spread"]) * point)
            for r in rates
        ]
