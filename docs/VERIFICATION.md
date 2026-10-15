# Verification checklist (acceptance tests, updated for 0.7.0)

Legend: **CI** = proven by an automated test on GitHub Actions (test name given) · **PARTIAL** = part proven, rest pending ·
**PENDING OWNER** = needs the owner's account, phone or authorization · **OPEN** = not built yet.
Green CI alone never means "done": every PENDING OWNER line must be seen on the real platform.

| # | Test | Status | Evidence / what is missing |
|---|---|---|---|
| AT-01 | Basic plan: one Pine technical alert attempt documented | PENDING OWNER | Official pricing says Basic has no technical alerts; owner's own attempt not yet recorded |
| AT-02 | Non-MT5 data adapter passes provider auth + live quote check | PARTIAL | `test_oanda_feed_reads_bid_ask_and_skips_forming_bar` (fake HTTP). Live: owner runs `ayesha scan --feed oanda --once` |
| AT-03 | Feed offline/stale ⇒ no READY, visible failure | CI + PENDING device | `test_stale_feed_is_reported`, heartbeat `STATE=` in `test_scanner_pushes_signed_ready_archive_and_heartbeat`; app shows PC offline/stopped/stale (device pending) |
| AT-04 | Scheduled London/NY scan locally without MT5 | PARTIAL | `install.bat` (optional Startup entry) + `start-ayesha.bat` (auto-restart); `test_windows_scripts_call_valid_commands`; Windows CI runs the start script. Not run on owner PC |
| AT-05 | One real scanner ID reaches Android exactly once | PARTIAL | Relay: CI job `relay` (live ntfy.sh publish → read → signature verify). Phone receipt pending device |
| AT-06 | Repeated/reordered delivery ⇒ no duplicate active alert | CI | `test_scanner_end_to_end_no_duplicates`; Kotlin `barTimeDrivesExpiryAndId` (same id for re-push), PC id `PC|<signal_id>` |
| AT-07 | Expired/stale/replayed alert never a fresh entry | CI | Kotlin `oldOrMalformedTvPayloadsAreUnverified` (late, expired on arrival), `pcMessagesNeedValidSignature` |
| AT-08 | Missing BAR/ST/V ⇒ UNVERIFIED | CI | Kotlin `oldOrMalformedTvPayloadsAreUnverified` |
| AT-09 | Invalid QUSD/NaN/inf/SL/TP ⇒ no usable lot | CI | Kotlin `rejectsFutureBarAndNonFiniteLevels`, `badSettingsFailClosed`, `unknownInstrumentsFailClosed` |
| AT-10 | Unsupported pair/suffix/account/contract ⇒ NO_TRADE/UNVERIFIED | CI | Kotlin `unknownInstrumentsFailClosed`; Python `test_assumed_exness_spec_blocks_live_until_owner_confirms` (unknown account type, NaN rate), `test_mt5_adapter_is_read_only_and_resolves_suffix` |
| AT-11 | $20/25/30 Exness Standard at 0.5–1% ⇒ NO_TRADE | CI | Python `test_exness_standard_small_accounts_are_no_trade` (6 cases); Kotlin `smallAccountsNeverExceedBudget` |
| AT-12 | Spread above bound ⇒ block | CI | `test_spread_floor_never_lets_feed_spread_be_tighter_than_broker`, `test_hard_gates`. Real Exness spread pending |
| AT-13 | No verified calendar (strict) ⇒ NO_TRADE | CI | `test_no_calendar_strict_mode_blocks`, `test_forex_factory_calendar_blocks_and_caches` (stale cache ⇒ none) |
| AT-14 | High-impact news window ⇒ NO_TRADE | CI | `test_news_calendar`, `test_forex_factory_calendar_blocks_and_caches` |
| AT-15 | Correlated positions + daily loss ⇒ blockers | CI | `test_correlated_usd_exposure`, `test_daily_pause_after_two_losses`, `test_daily_loss_cap` |
| AT-16 | Pine compiles on Basic and draws ①–④ | PENDING OWNER | Only parse + generation checks in CI |
| AT-17 | Confirmed-bar/no-repaint, re-run, DST parity | PARTIAL | Python: `test_zero_lookahead`, DST session tests. Pine: closed-bar alerts, HTF `[1]` + lookahead idiom; not run in TradingView |
| AT-18 | Chart feed mismatch shown as PARTIAL/MISMATCH/UNVERIFIED | PARTIAL | PC records `chart_parity: UNVERIFIED`; app says chart and PC are independent. No automatic comparison yet |
| AT-19 | Android 13 install + notification access consent | PENDING OWNER | APK builds in CI |
| AT-20 | Real notification opens correct symbol/TF with matching levels | PENDING OWNER | URL built from alert symbol/TF (`parsesIndicatorAlert`) |
| AT-21 | Store survives kill/restart/concurrency/corruption | PARTIAL | Process-wide lock, atomic temp-file rename, corrupt file moved aside (code). No device test |
| AT-22 | App stays CHART_CANDIDATE without news/spread/broker checks | CI | Kotlin `freshCurrentTvAlertIsChartCandidateOnly` (TV alerts can never be READY) |
| AT-23 | Stable signer: upgrade without uninstall | PENDING OWNER | Needs `AYESHA_KEYSTORE_*` secrets; release notes state the signer used |
| AT-24 | No auto-order APIs/endpoints | CI | `scripts/check_no_order_api.py` (MT5, Pine strategy, OANDA write endpoints), `test_repo_has_no_order_api` |
| AT-25 | Real-data backtest with OOS, R, drawdown | PENDING OWNER | `ayesha report` + `backtest` workflow ready (`test_report_cli_on_synthetic_csv`, synthetic only). Needs the `AYESHA_OANDA_TOKEN` repo secret; no real result exists yet |
| AT-26 | 30-day demo forward log | OPEN | Registry + journal ready; needs the scanner running for 30 days |
| AT-27 | Code, tests, docs, evidence committed | PARTIAL | Code/tests/docs on `main`; real-device screenshots pending |
| AT-28 | Windows/Ubuntu/Android CI green on same HEAD + artifact hashes | CI | ci (ubuntu, windows, relay) + build-android; APK SHA-256 in each release |
| AT-29 | No undisclosed always-on server | CI/doc | Only ntfy.sh (disclosed, opt-in), OANDA (data), Forex Factory (calendar); docs/08 and app Settings say so |
| AT-30 | Failures show health states, never false "Ready" | PARTIAL | READY only for signed fresh PC signals with all gates; PC offline/stale shown on home screen (device pending) |
| AT-31 | READY impossible without CLEAR news, verified spec, fresh quote/data, lot > 0, no blockers, even if config is loosened | CI | `test_ready_guard_holds_even_with_strict_news_off`, `test_ready_guard_blocks_unverified_contract` |
| AT-32 | READY push that failed (network) is retried until expiry, never sent twice | CI | `test_failed_ready_push_is_retried_once_delivered`, `test_confirmed_event_upgrades_record_and_pushes_ready_once` |
| AT-33 | Replayed old heartbeat cannot show the PC as online | CI (core) + PENDING device | Kotlin `replayedHeartbeatCannotMakePcLookOnline`; LinkService accepts only newer heartbeats |
| AT-34 | One combined MTF setup, no per-timeframe signals | CI | `test_one_signal_per_setup_not_per_timeframe`, `test_default_is_m15_only_with_full_mtf_text` |
| AT-35 | M5 confirmation is causal and fails closed (stop first, target first, expiry, weak candle, RR after confirmation) | CI | `test_mtf_confirmation_is_causal`, `test_buy_confirms_*`, `test_weak_candle_*`, `test_stop_before_confirmation`, `test_target_before_entry`, `test_rr_rechecked_after_confirmation`, `test_expired_unconfirmed`, `test_sell_mirror_confirms` |
| AT-36 | WATCH → READY upgrade updates the same phone signal; READY is never downgraded by a replay | CI | `test_confirmed_event_upgrades_record_and_pushes_ready_once`, `test_confirm_failed_is_archived_not_alerted`, Kotlin `onlyWatchToReadyOrNoTradeMayReplaceAStoredSignal`. Device pending |
| AT-37 | M1 scalp cannot be enabled without validation | CI | `test_scalp_m1_refused_until_validated` |
| AT-38 | Health check for a nontechnical owner never prints the token | CI | `test_doctor_reports_every_missing_piece`, `test_doctor_all_green_with_fakes`, CI step "Doctor runs without credentials" |
| AT-39 | Journal statistics use only the owner's typed real results | CI (core) + PENDING device | Kotlin `journalStatsUseOnlyTypedResults`; app shows tests and signals separately |
| AT-40 | Report covers IS/OOS, walk-forward, pair/session/mode breakdown, $20–30 feasibility, and labels its data | CI (synthetic) | `test_report_on_synthetic_data_is_labelled`, `test_capital_feasibility_respects_min_lot`. Real data pending (AT-25) |
