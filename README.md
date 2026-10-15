# AYESHA FX

Advisory-only ICT/SMC forex analysis for manual trading on Exness. **It never places,
modifies or closes orders** and never asks for any login or password. `NO_TRADE` is a
normal, often correct, output.

- Full spec: [`docs/AYESHA_AI_FOREX_TRADING_ASSISTANT_MASTER_PLAN.md`](docs/AYESHA_AI_FOREX_TRADING_ASSISTANT_MASTER_PLAN.md)
- Plan review: [`docs/00-plan-review.md`](docs/00-plan-review.md)
- Roadmap and current phase: [`docs/ROADMAP.md`](docs/ROADMAP.md)
- Windows setup (বাংলা): [`docs/07-setup-windows.md`](docs/07-setup-windows.md)
- TradingView guide: [`docs/05-tradingview-guide.md`](docs/05-tradingview-guide.md)
- Risk math: [`docs/03-risk-and-contract-math.md`](docs/03-risk-and-contract-math.md)

## Quick start (no MT5 needed)

1. Copy [`tradingview/AyeshaSmartMoney.pine`](tradingview/AyeshaSmartMoney.pine) into TradingView's Pine Editor and add it to a 15m chart.
2. Create an alert on each pair: Condition **AYESHA → Any alert() function call**, **Notify in app**.
3. The TradingView phone app shows the alert; open that pair to see the numbered reasons on the chart.

Guide (বাংলা): [`docs/05-tradingview-guide.md`](docs/05-tradingview-guide.md)

## Optional Python tools (phases 1, 2, 4, 5, 6)

| Command | What it does | Needs MT5? |
|---|---|---|
| `ayesha lot-table --equity 20` | Shows what the 0.01 minimum lot would risk for typical stops | No |
| `ayesha risk ...` | Sizes one trade idea and runs every hard gate | No |
| `ayesha spec-check` | Reads real Exness contract specs and spreads, read-only | Yes (Windows) |
| `ayesha export --symbol EURUSD --tf M15 --days 730 --out eurusd_m15.csv` | Saves closed bars to CSV | Yes (Windows) |
| `ayesha scan --news data\calendar.csv [--telegram]` | Live advisory scanner, READY alerts, signal registry | Yes (Windows) |
| `ayesha signals` / `ayesha mark --id ... --placed` | Signal list and manual journal | No |
| `ayesha backtest --csv eurusd_m15.csv --symbol EURUSD --equity 20 --split 2025-07-01` | Bar-by-bar replay of the SWEEP_MSS_FVG setup, results in R after spread | No |

## Layout

```
contracts/       strategy-spec.yaml (canonical rules, hashed), signal.schema.json
desktop/ayesha/  risk/ feed/ (MT5 read-only, CSV) rules/ (primitives, strategy) backtest/ news/ sessions.py cli.py
desktop/tests/   69 tests: risk gates, DST sessions, primitives, zero-lookahead, fills, scanner, safety
scripts/         check_no_order_api.py (CI fails on any trading call)
tradingview/     AyeshaSmartMoney.pine (generated chart helper) + template
android/         phase 8
```

## Develop

```bash
cd desktop
pip install -e ".[dev]"        # add ",mt5" on Windows
pytest -q
python ../scripts/check_no_order_api.py ..
```

Backtest results are historical simulations, not forecasts. Scores are rule points, not probabilities.
