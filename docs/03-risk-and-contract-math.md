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

## Sizing (adaptive capital, release 0.8.0)
`equity` is the latest owner-confirmed Exness equity snapshot (`ayesha capital`, `desktop/ayesha/capital.py`), never
OANDA's practice balance and never a constant: the same formula runs at $20, $500 or $5,000.
```
usd_per_price_per_lot = tick_value / tick_size          # MT5 tick_value is already in account currency
loss_per_lot_usd   = loss_price * usd_per_price_per_lot + commission_round_trip
nominal_budget_usd = equity * risk_per_trade_percent / 100      # 0.5 % default, hard cap 1 % (HARD_MAX_RISK_PERCENT)
remaining_day_usd  = equity * 2 % - realized_loss_today - open_risk
remaining_open_usd = equity * 1 % - open_risk                   # unknown risk of an open trade = the whole 1 %
usable_budget_usd  = max(0, min(nominal_budget_usd, remaining_day_usd, remaining_open_usd))
lot = floor_to_step(usable_budget_usd / loss_per_lot_usd)       # Decimal floor, never rounds up
lot < volume_min  =>  NO_TRADE: MIN_LOT_EXCEEDS_RISK (or DAILY_RISK_PAUSE / OPEN_RISK_CAP when the budget is used up)
net_rr = (profit_price * usd_per_price_per_lot - commission) / loss_per_lot_usd
```
A valid stop is never moved to make the minimum lot fit, and the risk percentage never rises because equity grew.
Gaps and news slippage can lose more than the modelled stop; the budget is a model, not a guaranteed maximum.

## Hard gates (any one => NO_TRADE)
`BROKER_SPEC_UNVERIFIED` (live use of a spec not read from MT5 or owner-confirmed for this pair), `CONTRACT_SPEC_MISSING`,
`EQUITY_UNKNOWN`, `CAPITAL_UNVERIFIED` / `CAPITAL_STALE` / `POSITION_STATE_UNVERIFIED` / `MARGIN_UNVERIFIED` (scanner),
`MARKET_CLOSED`, `DATA_STALE`, `NEWS_LOCKOUT`, `NEWS_UNVERIFIED` (strict mode), `INVALID_LEVELS`,
`SPREAD_TOO_WIDE`, `STOP_TOO_TIGHT_FOR_VOLATILITY`, `STOP_INSIDE_BROKER_STOPS_LEVEL`,
`MIN_LOT_EXCEEDS_RISK`, `NET_RR_BELOW_MIN`, `DAILY_RISK_PAUSE` (2 losses or 2% day loss),
`OPEN_RISK_CAP`, `CORRELATED_EXPOSURE_<CCY>`, `INSUFFICIENT_FREE_MARGIN`, `CONFIG_RISK_ABOVE_CAP`.
News phases other than CLEAR / UPCOMING add their own code (e.g. `NEWS_PRE_EVENT_LOCKOUT`, `NEWS_REACTION_WATCH`).

## Small-account reality (assumed specs, verify with `ayesha spec-check`)
At $20 equity and 0.5% risk the budget is $0.10. On Standard, 0.01 lot on EURUSD costs about
$0.10 per pip, so a 10-pip stop risks $1.00 (5% of equity): **NO_TRADE**. On Standard Cent the
same 0.01 cent-lot risks about $0.01 (0.05%), which fits the rule.
