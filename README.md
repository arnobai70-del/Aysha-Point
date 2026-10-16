# AYESHA FX

Advisory-only ICT/SMC forex analysis for manual trading on Exness. **It never places,
modifies or closes orders** and never asks for any login or password. `NO_TRADE` is a
normal, often correct, output. There is **no validated trading edge yet**: no real-data
backtest or forward test has been run.

- Full spec: [`docs/AYESHA_AI_FOREX_TRADING_ASSISTANT_MASTER_PLAN.md`](docs/AYESHA_AI_FOREX_TRADING_ASSISTANT_MASTER_PLAN.md)
- Plan review: [`docs/00-plan-review.md`](docs/00-plan-review.md)
- Roadmap and current phase: [`docs/ROADMAP.md`](docs/ROADMAP.md)
- Windows setup (বাংলা): [`docs/07-setup-windows.md`](docs/07-setup-windows.md)
- TradingView guide: [`docs/05-tradingview-guide.md`](docs/05-tradingview-guide.md)
- Risk math: [`docs/03-risk-and-contract-math.md`](docs/03-risk-and-contract-math.md)
- News protection and adaptive capital (বাংলা): [`docs/11-news-and-capital-guide.md`](docs/11-news-and-capital-guide.md)

## Quick start (no MT5 needed)

**Status:** demo/paper only, fail-closed. See [`docs/STATUS.md`](docs/STATUS.md) and [`docs/VERIFICATION.md`](docs/VERIFICATION.md).

**Free path (Mode B, canonical):** PC scanner on OANDA practice data → signed push (ntfy.sh) → AYESHA phone app.
Guide (বাংলা): [`docs/08-pc-scanner-no-mt5.md`](docs/08-pc-scanner-no-mt5.md).

1. Phone: install [`ayesha-fx.apk`](https://github.com/arnobai70-del/Aysha-Point/releases/latest/download/ayesha-fx.apk).
2. Windows PC: double-click `desktop\windows\install.bat` once (token, Exness equity and open trades, leverage and
   the Exness contract per pair, pairing, health check).
3. Daily: `desktop\windows\start-ayesha.bat`. It asks once to confirm your Exness equity
   (`ayesha capital --session-start`), then runs `ayesha scan --feed oanda --account-type Standard --news-ff --push`
   and restarts itself. `ayesha doctor` shows what is missing.
4. When your Exness equity changes (profit, loss, deposit, withdrawal), run `ayesha capital` on the PC or use
   **Update capital** in the phone app. Budgets and lots follow the new equity with no code change; $20–30 is only
   today's balance, not a limit. Equity stays on the PC and phone; the relay only sees a short digest.

Owner test guide (বাংলা, PC + TradingView Basic + Android 13): [`docs/10-owner-testing-guide.md`](docs/10-owner-testing-guide.md). Security: [`docs/SECURITY.md`](docs/SECURITY.md).
Real-data report without putting the token in GitHub: `desktop\windows\backtest-local.bat` (add `--news calendar.csv`
for the news comparison when you have a historical calendar you are allowed to use).

Multi-timeframe and backtest guide (বাংলা): [`docs/09-mtf-and-backtest.md`](docs/09-mtf-and-backtest.md). Checklist: [`docs/MASTER_CHECKLIST.md`](docs/MASTER_CHECKLIST.md).

**Chart:** copy [`tradingview/AyeshaSmartMoney.pine`](tradingview/AyeshaSmartMoney.pine) into TradingView (15m) to see ①–④ on the chart.
TradingView-to-phone alerts (Mode A) need a plan with technical alerts; Basic lists none. Guides: [`docs/05-tradingview-guide.md`](docs/05-tradingview-guide.md) · [`docs/06-android-guide.md`](docs/06-android-guide.md)

## News protection (summary)

The scanner runs a fail-closed news state machine per pair: `CLEAR`, `UPCOMING`, `PRE_EVENT_LOCKOUT`, `EVENT_LIVE`,
`POST_EVENT_COOLDOWN`, `REACTION_WATCH`, `NEWS_UNVERIFIED`. Windows depend on the event (central bank 45/60 min,
CPI/NFP/PCE 45/30, other high impact 30/30, medium 10/10). After the timer the market must also settle on closed M5
bars (spread, range, shock, whipsaw) before an entry can be READY. A missing, stale or inconsistent calendar is
`NEWS_UNVERIFIED`, never "no news". News notices on the phone (upcoming, blocked, post-news summary) are information,
never a trade signal; the numbers analysis (actual vs forecast) only gives conditional scenarios and says `UNKNOWN`
or `BLOCKED BY DATA` when numbers are missing. **News direction is not backtested.**

## Optional Python tools

| Command | What it does | Needs MT5? |
|---|---|---|
| `ayesha capital` | Type the equity shown in Exness, deposits/withdrawals and open trades (sizing source) | No |
| `ayesha capital --show` / `--history` | Latest snapshot and whether it is valid / risk history: snapshots, 7-day change without deposits, journal, warnings | No |
| `ayesha lot-table --equity 20` | Shows what the 0.01 minimum lot would risk for typical stops | No |
| `ayesha risk ...` | Sizes one trade idea and runs every hard gate | No |
| `ayesha spec-check` | Reads real Exness contract specs and spreads, read-only | Yes (Windows) |
| `ayesha export --feed oanda --symbol EURUSD --tf M15 --days 730 --out eurusd_m15.csv` | Saves closed BID bars (+spread) to CSV | No (`--feed mt5` uses MT5) |
| `ayesha scan --feed oanda --account-type Standard --news-ff --push` | Live advisory scanner: news state machine, capital check, signal registry, signed phone push | No (`--feed mt5` uses MT5) |
| `ayesha confirm-broker` / `ayesha pair` / `ayesha push-test` | Owner-confirmed Exness spec per pair, phone pairing code, test push | No |
| `ayesha signals` / `ayesha mark --id ... --placed` | Signal list and manual journal | No |
| `ayesha backtest --csv eurusd_m15.csv --symbol EURUSD --equity 20 --split 2025-07-01` | Bar-by-bar replay of the SWEEP_MSS_FVG setup, results in R after spread | No |
| `ayesha report --data-dir data --split 2025-01-01 --label "..." --md report.md [--news calendar.csv]` | Validation report: pairs × modes, IS/OOS, walk-forward, breakdowns, adaptive account and feasibility at $20–$5,000; with `--news`, no-news vs legacy 30/30 vs upgraded news on the same candles | No |
| `ayesha doctor` | Health check: token, OANDA prices, Exness contract, capital, pairing, calendar, relay | No |
| `ayesha setup` / `ayesha set-token` | One-time setup (used by install.bat); token typed hidden, stored in the Windows user environment | No |
| `ayesha backtest-run --pairs EURUSD --days 1095 [--news calendar.csv]` | Validated OANDA export (M15 + M5) + validation report | No |
| `ayesha make-signing-key` | Stable Android release key (PKCS#12) and the four GitHub secret values | No |

## Layout

```
contracts/       strategy-spec.yaml (canonical rules incl. news tiers and capital policy, hashed), signal.schema.json (1.1)
desktop/ayesha/  risk/ feed/ (MT5 read-only, OANDA v20 read-only, CSV) broker.py capital.py delivery/ (console, Telegram, ntfy push)
                 rules/ (primitives, strategy, mtf) news/ (calendar, classify, guard, ledger, analysis, ff_feed)
                 backtest/ (replay, report, asof) sessions.py scanner.py doctor.py cli.py
desktop/windows/ install.bat, start-ayesha.bat, backtest-local.bat
desktop/tests/   178 tests: risk gates, DST sessions, primitives, zero-lookahead, MTF/M5 confirmation, news N01–N12,
                 capital C01–C10, point-in-time news replay, report, scanner, OANDA feed, push signing, doctor, safety
scripts/         check_no_order_api.py (CI fails on any trading call), check_no_secrets.py, check_workflows.py
tradingview/     AyeshaSmartMoney.pine (generated chart helper) + template
android/         Kotlin app (no extra libraries): PC link, news watch, capital check, TradingView alert reader, inbox,
                 lot calc, journal; 39 JVM tests; APK built by GitHub Actions
```

## Develop

```bash
cd desktop
pip install -e ".[dev]"        # add ",mt5" on Windows
pytest -q
python ../scripts/check_no_order_api.py ..
```

Backtest results are historical simulations, not forecasts. Scores are rule points, not probabilities.
