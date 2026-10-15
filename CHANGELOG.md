# Changelog

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
