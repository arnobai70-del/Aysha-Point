# Changelog

## 0.8.0 — 2026-10-16 (news intelligence and adaptive capital)
Implements the AYESHA FX News Intelligence & Adaptive Capital Management spec v1.0 (P0, P1 and the P2 tooling). Manual execution only: nothing places, changes or closes an order.
- News protection (strategy 0.4.0): event tiers (central bank, top data, high, medium, low) with windows that are never shorter than the legacy HIGH 30/30; USD top data and central-bank events block every enabled pair; state machine UPCOMING → PRE_EVENT_LOCKOUT → EVENT_LIVE → POST_EVENT_COOLDOWN → REACTION_WATCH → CLEAR, and NEWS_UNVERIFIED for a missing, stale, unprovenanced, clock-drifted or incomplete calendar. After the window the market must settle on closed M5 bars (spread and range near the pre-event baseline); a shock extends the cooldown, whipsaw blocks. Rescheduled, dropped and corrected events stay visible in a local event ledger.
- News analysis is advisory only: conditional above/near/below scenario cards (no probability), post-release reaction summaries that are never a permission. Forex Factory's weekly export has no verified actual values, so actual-vs-forecast is **BLOCKED BY DATA**.
- Adaptive capital: `ayesha capital` keeps a versioned, owner-entered Exness equity history on the PC (deposits and withdrawals apart from trading P&L), valid for 24 h (4 h after a deposit, withdrawal or >25 % change), with a once-per-session open-trades confirmation. Every lot is computed from the latest snapshot: min(0.5 % of equity, remaining daily 2 %, remaining open 1 %), floored to the broker step, never above the hard 1 % cap. The same setup becomes feasible as equity grows; $20–30 is not a ceiling. OANDA's practice balance is never used.
- Exness contract values are confirmed per pair (`ayesha confirm-broker`: contract size, min/step/max lot, commission, stop level, typical spread), plus account leverage; margin is estimated at no more than 1:200 around news.
- Scanner: READY needs news CLEAR/UPCOMING, a verified per-pair spec, fresh capital and confirmed positions; an active READY is re-checked every poll and cancelled with a signed INVALIDATED when news or the quote turns against it; expiry is capped before the next lockout. Separate signed News Watch notices (upcoming, lockout, release, post-news summary that waits for a settled market).
- Weekly drawdown and confirmation-expiry **warnings** (never a gate): `capital.weekly_drawdown_warning_percent: 4.0` on the cash-flow-adjusted 7-day equity, `freshness_warning_hours: 2`. `ayesha capital --history` shows snapshots, the 7-day change without deposits, your own journal and the warnings.
- Phone wire format 4 (`WF NP NE NT NI NV CAPV CAPT CAPH RISKP SPEC`): the equity amount is never sent, only a keyed digest so the phone can show CAPITAL_MISMATCH. Signal schema 1.1 adds the news and capital fields (additive).
- Android 0.5.0: News Watch notifications and card, capital card (Update capital, 24 h freshness, PC match), PC READY needs wire format 4 + matching capital + allowed news phase + owner-confirmed spec + risk ≤ 1 %; never a larger lot than the PC's; TradingView candidates are blocked during a PC news window; a cancelled READY is always notified.
- P2 evaluation tooling: `ayesha report --news <calendar.csv>` replays the same candles and signals with news not modelled, the legacy 30/30 window and the upgraded guard on a point-in-time calendar (actuals hidden until published, closed M5 bars only), with cost-adjusted R, win-rate CIs, drawdown, out-of-sample, news regime, $20/$25/$30/$100/$500/$1,000/$5,000 feasibility and a hypothetical adaptive account with the hard gates. Always states **NEWS DIRECTION NOT BACKTESTED**. No real-data run exists yet: it needs the owner's OANDA data and a historical calendar the owner may use.
- Tests: acceptance tests N01–N12, C01–C10, I01–I04 (I05/I06 PENDING OWNER), see docs/VERIFICATION.md. All price data in tests is synthetic.
- Open trades are typed as `PAIR SIDE [$risk]` (e.g. `EURUSD BUY $0.50`): the amount is the USD lost at the trade's stop-loss and needs a `$` (or `risk=`), so a lot size typed by mistake is refused instead of understating open risk.
- Docs: Bengali owner guide for news and capital (docs/11); README, STATUS, VERIFICATION (N/C/I mapping), DECISIONS (incompatible changes: wire format 4, no `--equity` for the scanner, per-pair contract, new strategy hash), FEATURE_MATRIX, MASTER_CHECKLIST, SECURITY, ROADMAP and the Android, PC scanner, risk, backtest and owner-test guides updated.

## 0.7.1 — 2026-10-15 (security hardening and owner-test preparation)
- `backtest` workflow: inputs passed only as quoted env vars and validated (`ayesha backtest-run`: pair allowlist, 30–3650 days, 2–12 folds, real split date inside the data); token only in the export step; `permissions: contents: read`; `persist-credentials: false`; only report files uploaded. New `scripts/check_workflows.py` fails CI on `${{ inputs/github.event/secrets }}` inside `run:`; `scripts/check_no_secrets.py` scans tracked files for credentials.
- OANDA token: no more `setx <token>` (command-line exposure). `ayesha set-token` / `ayesha setup` read it hidden and write HKCU\Environment through the registry API; lookup falls back to it; 401/403 ⇒ `AuthRejected`; error text redacted. See docs/SECURITY.md.
- Windows: `install.bat` now finds Python ≥ 3.11 robustly, records the interpreter, and runs `ayesha setup` (rerunnable, Enter keeps values). `start-ayesha.bat` restarts only on network/data failures (exit 4), stops on config (2) or rejected token (3), optional restart cap. New `backtest-local.bat` (multi-year report on the PC, token never in GitHub) and `make-signing-key.bat`.
- Windows CI runs the scripts end to end: before install, first install, re-run, rejected token, network down with capped restarts, corrupt equity, invalid backtest inputs, moved Python, token removal.
- Android 0.4.1: journal backup file (export / merge-restore, never loses a typed result; pairing code excluded), journal trades never dropped by the 300-alert limit. `ayesha make-signing-key` creates a stable PKCS#12 release key; every Android build self-tests such a key and prints the signer SHA-256 in the release notes.
- Docs: Bengali owner test guide for Windows PC, TradingView Basic and Android 13 (docs/10), SECURITY.md.

## 0.7.0 — 2026-10-15 (integration, multi-timeframe, validation)
- Multi-timeframe engine (strategy 0.3.0): one combined setup per pair. H4 context (blocks when H1 and H4 both oppose), H1 bias + last BOS/CHoCH + premium/discount zone, M15 SWEEP→MSS→FVG setup, optional M5 confirmation (`mtf.confirm_timeframe: M5`, off by default: entry becomes the confirmation close, RR recomputed, 15-minute expiry). M1 scalp is refused until validated. Every signal carries an `mtf` explanation.
- Scanner: hard READY guard independent of config (news CLEAR, verified spec, fresh quote and data, lot > 0, no blockers ⇒ else NO_TRADE `READY_GUARD:<reason>`); failed READY pushes retried until expiry, never twice (per-status delivery keys); WATCH_M5 → READY / CONFIRM_FAILED updates of the same signal id; WATCH_M5 expiry.
- Push wire format 3: `MTF=` key; PC statuses mapped to READY / WATCH / NO_TRADE; "why" line says when it waits for M5 or is a short-lived market entry.
- Windows: `install.bat` (Python check, install, hidden token prompt → user environment, equity, Exness contract, pairing, health check, optional Startup entry) and `start-ayesha.bat` (auto-restart). `ayesha doctor` checks token, OANDA prices, Exness contract, pairing code, news calendar and the relay.
- Validation report `ayesha report`: pairs × modes (M15 only, M5-confirmed), wins/losses, avg win/loss R, planned net RR, expectancy after costs, PF, max DD, in-sample vs out-of-sample, walk-forward folds (frozen rules), by session / direction / H4 context, $20/$25/$30 Exness Standard feasibility at 0.5% and 1%. Manual `backtest` workflow builds it from multi-year OANDA data with the owner's token secret; no real result exists yet.
- Android 0.4.0: WATCH state, MTF explanation card and notification summary, status meanings on the home screen, signed WATCH→READY upgrades notify once (replays never downgrade), heartbeat replay protection (PC freshness from the PC's own time, clock-skew warning), journal screen with real-trade results and statistics (separate from signals and tests).
- Pine: H4 context row, feed note (TradingView feed vs PC/OANDA vs Exness), H1 BIAS label.
- CI: doctor-without-credentials step, Windows start-script step, live Forex Factory fetch job.

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
