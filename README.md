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

**Status:** demo/paper only, fail-closed. See [`docs/STATUS.md`](docs/STATUS.md) and [`docs/VERIFICATION.md`](docs/VERIFICATION.md).

**Free path (Mode B, canonical):** PC scanner on OANDA practice data → signed push (ntfy.sh) → AYESHA phone app.
Guide (বাংলা): [`docs/08-pc-scanner-no-mt5.md`](docs/08-pc-scanner-no-mt5.md).

1. Phone: install [`ayesha-fx.apk`](https://github.com/arnobai70-del/Aysha-Point/releases/latest/download/ayesha-fx.apk).
2. PC: `pip install -e desktop`, set `AYESHA_OANDA_TOKEN`, run `ayesha confirm-broker`, `ayesha pair` (type the code in the app), `ayesha push-test`.
3. Run `desktop\windows\run-scanner.bat` (`ayesha scan --feed oanda --equity 25 --news-ff --push`).

**Chart:** copy [`tradingview/AyeshaSmartMoney.pine`](tradingview/AyeshaSmartMoney.pine) into TradingView (15m) to see ①–④ on the chart.
TradingView-to-phone alerts (Mode A) need a plan with technical alerts; Basic lists none. Guides: [`docs/05-tradingview-guide.md`](docs/05-tradingview-guide.md) · [`docs/06-android-guide.md`](docs/06-android-guide.md)

## Optional Python tools (phases 1, 2, 4, 5, 6)

| Command | What it does | Needs MT5? |
|---|---|---|
| `ayesha lot-table --equity 20` | Shows what the 0.01 minimum lot would risk for typical stops | No |
| `ayesha risk ...` | Sizes one trade idea and runs every hard gate | No |
| `ayesha spec-check` | Reads real Exness contract specs and spreads, read-only | Yes (Windows) |
| `ayesha export --feed oanda --symbol EURUSD --tf M15 --days 730 --out eurusd_m15.csv` | Saves closed BID bars (+spread) to CSV | No (`--feed mt5` uses MT5) |
| `ayesha scan --feed oanda --equity 25 --news-ff --push` | Live advisory scanner, signal registry, signed phone push | No (`--feed mt5` uses MT5) |
| `ayesha confirm-broker` / `ayesha pair` / `ayesha push-test` | Owner-confirmed Exness spec, phone pairing code, test push | No |
| `ayesha signals` / `ayesha mark --id ... --placed` | Signal list and manual journal | No |
| `ayesha backtest --csv eurusd_m15.csv --symbol EURUSD --equity 20 --split 2025-07-01` | Bar-by-bar replay of the SWEEP_MSS_FVG setup, results in R after spread | No |

## Layout

```
contracts/       strategy-spec.yaml (canonical rules, hashed), signal.schema.json
desktop/ayesha/  risk/ feed/ (MT5 read-only, OANDA v20 read-only, CSV) broker.py delivery/ (console, Telegram, ntfy push) rules/ (primitives, strategy) backtest/ news/ sessions.py cli.py
desktop/tests/   84 tests: risk gates, DST sessions, primitives, zero-lookahead, fills, scanner, OANDA feed, push signing, safety
scripts/         check_no_order_api.py (CI fails on any trading call)
tradingview/     AyeshaSmartMoney.pine (generated chart helper) + template
android/         Kotlin app (no extra libraries): PC link, TradingView alert reader, inbox, checks, lot calc; APK built by GitHub Actions
```

## Develop

```bash
cd desktop
pip install -e ".[dev]"        # add ",mt5" on Windows
pytest -q
python ../scripts/check_no_order_api.py ..
```

Backtest results are historical simulations, not forecasts. Scores are rule points, not probabilities.
