# Risk and contract math

Implemented in `desktop/ayesha/risk/engine.py`; tests in `desktop/tests/test_risk.py`.

## Price model
All levels are bid-chart prices. Every order triggers when the bid touches its level, and the
round trip pays one spread:

```
loss_price   = |entry - stop| + spread + slippage_buffer
profit_price = |target - entry| - spread
```

`broker_order_prices()` converts chart levels into what to type in MT5 so this holds:
BUY limit = entry + spread, SL = stop, TP = target; SELL limit = entry, SL = stop + spread, TP = target + spread.

## Sizing
```
usd_per_price_per_lot = tick_value / tick_size          # MT5 tick_value is already in account currency
loss_per_lot_usd = loss_price * usd_per_price_per_lot + commission_round_trip
risk_budget_usd  = equity * risk_per_trade_percent / 100
lot = floor_to_step(risk_budget_usd / loss_per_lot_usd)  # Decimal floor, never rounds up
lot < volume_min  =>  NO_TRADE: MIN_LOT_EXCEEDS_RISK
net_rr = (profit_price * usd_per_price_per_lot - commission) / loss_per_lot_usd
```

## Hard gates (any one => NO_TRADE)
`CONTRACT_SPEC_UNVERIFIED` (live use of a non-MT5 spec), `CONTRACT_SPEC_MISSING`, `EQUITY_UNKNOWN`,
`MARKET_CLOSED`, `DATA_STALE`, `NEWS_LOCKOUT`, `NEWS_UNVERIFIED` (strict mode), `INVALID_LEVELS`,
`SPREAD_TOO_WIDE`, `STOP_TOO_TIGHT_FOR_VOLATILITY`, `STOP_INSIDE_BROKER_STOPS_LEVEL`,
`MIN_LOT_EXCEEDS_RISK`, `NET_RR_BELOW_MIN`, `DAILY_RISK_PAUSE` (2 losses or 2% day loss),
`OPEN_RISK_CAP`, `CORRELATED_EXPOSURE_<CCY>`, `INSUFFICIENT_FREE_MARGIN`, `CONFIG_RISK_ABOVE_CAP`.

## Small-account reality (assumed specs, verify with `ayesha spec-check`)
At $20 equity and 0.5% risk the budget is $0.10. On Standard, 0.01 lot on EURUSD costs about
$0.10 per pip, so a 10-pip stop risks $1.00 (5% of equity): **NO_TRADE**. On Standard Cent the
same 0.01 cent-lot risks about $0.01 (0.05%), which fits the rule.
