"""Assumed contract specs for research/backtests when no broker terminal is connected.

These are NOT broker-verified. The risk engine blocks live use of any spec whose
`source` does not start with "MT5". Real values must come from the MT5 terminal.
"""

from __future__ import annotations

from ayesha.models import InstrumentSpec, pip_size_for

# Account types: Standard = 100,000 units per lot, balance in USD.
# StandardCent = balance in US cents (USC); 1 cent-lot = 1,000 units per lot in USD terms.
CONTRACT_UNITS = {"Standard": 100_000.0, "StandardCent": 1_000.0}


def quote_to_usd(symbol: str, price: float, usd_rates: dict[str, float] | None = None) -> float:
    """USD value of 1 unit of the quote currency.

    usd_rates maps currency -> USD per 1 unit of that currency (e.g. {"JPY": 0.0067, "CAD": 0.73}).
    """
    quote = symbol[3:6].upper()
    if quote == "USD":
        return 1.0
    if symbol[:3].upper() == "USD":
        return 1.0 / price  # e.g. USDJPY: 1 JPY = 1/price USD
    if usd_rates and quote in usd_rates:
        return usd_rates[quote]
    raise ValueError(f"Need a USD rate for {quote} to value {symbol}")


def assumed_fx_spec(
    symbol: str,
    price: float,
    account_type: str = "Standard",
    usd_rates: dict[str, float] | None = None,
) -> InstrumentSpec:
    symbol = symbol.upper()
    pip = pip_size_for(symbol)
    digits = 3 if pip == 0.01 else 5
    tick = 10 ** (-digits)
    units = CONTRACT_UNITS[account_type]
    tick_value = units * tick * quote_to_usd(symbol, price, usd_rates)
    return InstrumentSpec(
        symbol=symbol,
        digits=digits,
        tick_size=tick,
        tick_value=tick_value,
        contract_size=units,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=200.0,
        pip_size=pip,
        base_currency=symbol[:3],
        quote_currency=symbol[3:6],
        source=f"ASSUMED_{account_type.upper()}",
    )
