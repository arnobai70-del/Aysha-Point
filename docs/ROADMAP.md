# AYESHA FX — Reordered Roadmap

This roadmap reorders the milestones in `docs/AYESHA_AI_FOREX_TRADING_ASSISTANT_MASTER_PLAN.md` (section Y) so that the
expensive parts (Android app, Pine parity, sync) are only built after the rule engine
has shown an edge **after costs** on out-of-sample data. All safety rules from the spec
still apply: manual execution only, no order API, fail closed into `NO_TRADE`.

| Phase | Goal | Deliverable | Exit gate |
|---|---|---|---|
| 0 | Plan review | `reviews/ayesha-plan-review.md`, this roadmap | Owner chose the reordered roadmap (done 2026-10-14) |
| 1 | Foundation + risk | Monorepo, `contracts/strategy-spec.yaml`, risk engine with all hard `NO_TRADE` gates, read-only MT5 + CSV adapters, `no order API` safety test, CI | Risk tests pass; owner runs `ayesha spec-check` on the PC and sees real Exness lot specs |
| 2 | Rules + replay | Sessions (IANA/DST), swings, BOS/CHoCH/MSS, displacement, FVG, liquidity pools + sweeps, sweep-reversal setup, bar-by-bar replay backtester with spread/slippage | Primitive tests pass; zero-lookahead test passes |
| 3 | Validate edge | MT5 history export → backtest on ≥ 2 years EURUSD + other majors, train/holdout split, walk-forward, report in R after costs | Out-of-sample expectancy > 0 after costs with a sample size that is reported honestly. **If not, stop and revise rules, do not build UI.** |
| 4 | Live scanner (PC) | Scheduler on confirmed candle close, signal state machine, SQLite registry, news calendar import, CLI/tray status | Runs a full London + NY session on demo without errors or duplicate signals |
| 5 | Phone alerts v1 | Telegram bot alerts (opt-in, token in OS secret store) | Test alert received; dedup works |
| 6 | Chart helper | Pine v6 visual indicator (sessions, PDH/PDL, swings, FVG, sweeps), constants generated from the spec | Compiles on TradingView Basic; no repaint on confirmed bars |
| 7 | Forward test | ≥ 30 days demo forward observation, journal | Results logged; no profit claims |
| 8 | Android app + private sync | Kotlin app, FCM, Tailscale pairing (spec section O) | Only after phase 7 is acceptable |

## Owner decision 2026-10-15: TradingView-first, MT5 optional

The owner trades in the Exness app and does not want MT5 to be required. So v1 is:
**TradingView indicator (PC) → TradingView alert → phone notification → open the same pair on TradingView and see steps ①–④ on the chart.**
The indicator itself finds the setup, explains it and estimates the lot from the equity typed into its settings.
The Python scanner/backtester stays as an optional research tool (it needs MT5 or CSV data).
The custom Android app (phase 8) is next; it needs its own market-data source because TradingView alerts cannot reach a custom app without a paid webhook plan and a server.

## What the owner must do (cannot be automated)

1. Add the indicator on TradingView and create one alert per pair (see `docs/05-tradingview-guide.md`).
2. Decide on capital mode: Standard (most trades will be `NO_TRADE` at ~$20), **Standard Cent**, more capital, or demo only.
3. Check the legal position for online forex in your country before real money.
4. Give the GitHub repository to push to (private recommended).

## Status (2026-10-14)

- Phases 1, 2 built and tested. Phase 4 (scanner + registry + journal) and phase 5 (Telegram) built and tested with a fake feed.
- Phase 6 Pine helper written and generated from the spec; **not yet compiled on TradingView**, parity test pending.
- **Phase 3 is blocked on the owner's PC**: needs `spec-check` output and MT5 history export + backtest reports.
- Phases 7, 8 wait for phase 3 results.

See `CHANGELOG.md` for details. Checklist items in the master spec are only ticked with test evidence.

## 2026-10-15 re-audit v2 (release 0.6.0)
- Canonical live path is now Mode B: PC scanner on OANDA v20 data (no MT5) → signed ntfy.sh push → Android app. TradingView stays the chart explanation; its alerts are optional (Basic has no technical alerts).
- Next, in order: owner device/account checks (docs/STATUS.md "Owner actions"), real-data backtest from `ayesha export --feed oanda` with a reserved out-of-sample period, then 30 days of demo forward logging. No new setups until that evidence exists.
