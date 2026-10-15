# Changelog

## 0.6.0 — 2026-10-15 (re-audit v2: free, MT5-free signal path)
- PC scanner runs without MT5: `--feed oanda` (OANDA v20 practice API, bid/ask candles, quote age). `export --feed oanda` gives real history for backtests.
- Exness spec without MT5: repo assumption until the owner confirms it from the Exness app (`ayesha confirm-broker`); READY is impossible before that.
- News gate from the Forex Factory weekly export (`--news-ff`, cached hourly; stale ⇒ NEWS_UNVERIFIED).
- Signed PC → phone push through ntfy.sh (`--push`, `ayesha pair`, `ayesha push-test`), heartbeat every 5 min and on state change, STOPPED on exit. Non-READY records are sent as archive-only so the phone can show why.
- Spread gate uses max(feed spread, typical Exness spread).
- Android 0.3.0: PC link service, READY / CHART_CANDIDATE / NO_TRADE / UNVERIFIED / EXPIRED with reasons, active and archive inbox, watchlist, diagnostics (PC offline/stale, last TradingView alert, rejected messages), strict BAR/ST/V/TF/delay/signature checks, process-wide store lock and corrupt-file recovery.
- Pine: alerts only on the 15m setup timeframe; table shows a timeframe warning. App `StrategyInfo` generated from the spec alongside the Pine file.
- CI: live relay round-trip job; Python↔Kotlin signature vector and wire-format fixture; version manifest test; OANDA write endpoints added to the no-order scan. Release notes carry commit, strategy hash, APK SHA-256 and signer.

## 0.5.0 — 2026-10-15 (audit P0 fixes)
- Phone app 0.2.0: lot sizing fails closed (RISK_UNVERIFIED for unknown instruments, missing USD rate or bad settings); the chart's lot is never used as a fallback. Settings are validated before saving.
- Every alert is labelled CHART_CANDIDATE with the unverified checks (news, live spread, broker spec) listed in the app.
- Indicator alert line adds `BAR=` (signal bar close, UTC ms), `QUSD=` (quote→USD rate for crosses) and `ST=CHART_CANDIDATE`. The app takes expiry and the dedup id from `BAR`, flags late pushes and never notifies an already-expired setup.
- New docs: STATUS, DECISIONS, VERIFICATION.

## 0.4.0 — 2026-10-15 (TradingView-first)
- Indicator fires `alert()` on each SWEEP → MSS → FVG setup with pair, reasons, entry/SL/TP, RR and lot estimate, for TradingView phone notifications. MT5 no longer needed for daily use.
- Chart draws numbered reasons: ① sweep, ② MSS, ③ FVG entry zone, ④ entry/SL/TP + lot label; keeps last N setups, greys out expired ones.
- Lot estimate from equity/risk/account-type inputs (Standard or Cent contract, `request.currency_rate` for JPY/CAD/crosses), floors to 0.01, NO TRADE when 0.01 lot exceeds the budget.
- TradingView + phone alert guide in Bengali.

## 0.3.0 — 2026-10-14 (phases 4–6)
- Live scanner: warmup, closed-bar polling, live risk gates (quote age, spread, news, equity, daily pause from journal, open risk, correlated exposure), READY/WATCH/NO_TRADE records, lifecycle (EXPIRED, MISSED, ENTRY_TOUCHED, OBSERVED_TP/SL), DATA_STALE / FEED_OFFLINE health.
- SQLite registry (WAL, migrations), append-only signal events, idempotent inserts and deliveries, manual journal.
- Alerts: console + opt-in Telegram (token from environment). No account data in alert text.
- CLI: scan, signals, mark, telegram-test. MT5 server-time offset config + estimate in spec-check.
- Pine v6 chart helper generated from the strategy spec (`scripts/generate_pine.py`, CI check). Not yet compiled on TradingView.
- 69 tests.

## 0.2.0 — 2026-10-14 (phases 1–2)
- Monorepo, canonical `contracts/strategy-spec.yaml` with `strategy_hash`, signal JSON schema.
- Risk engine: decimal lot flooring, spread-once cost model, all hard NO_TRADE gates, broker order price helper.
- Read-only MT5 adapter behind an allow-list proxy (Exness suffix resolution, masked login); CSV feed and resampler.
- Order-API safety scanner wired into tests and CI.
- Session engine on IANA zones (DST-safe), FX week, rollover, trading day.
- Causal ICT/SMC primitives: ATR, confirmed swings, BOS/CHoCH/MSS, displacement, FVG lifecycle, liquidity levels (PDH/PDL, Asia, swing, EQH/EQL), sweep vs breakout.
- SWEEP_MSS_FVG setup with rule trace (OBSERVED / RULE_BASED_INFERENCE / UNAVAILABLE) and score breakdown (not a probability).
- Bar-by-bar replay backtester with conservative fills, walk-forward split, capital feasibility report.
- CLI: lot-table, risk, spec-check, export, backtest. 62 tests incl. zero-lookahead.
