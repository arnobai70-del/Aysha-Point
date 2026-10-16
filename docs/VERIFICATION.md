# Verification checklist (acceptance tests, updated for 0.8.0)

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
| AT-11 | $20/25/30 Exness Standard at 0.5–1% ⇒ NO_TRADE | CI | Python `test_exness_standard_small_accounts_are_no_trade` (6 cases), `test_c07_min_lot_explanation_at_25_and_same_geometry_feasible_later`; Kotlin `smallAccountsNeverExceedBudget` |
| AT-12 | Spread above bound ⇒ block | CI | `test_spread_floor_never_lets_feed_spread_be_tighter_than_broker`, `test_hard_gates`. Real Exness spread pending |
| AT-13 | No verified calendar (strict) ⇒ NO_TRADE | CI | `test_no_calendar_strict_mode_blocks`, `test_forex_factory_calendar_blocks_and_caches` (stale cache ⇒ none), `test_n04_untrusted_calendar_is_news_unverified` |
| AT-14 | High-impact news window ⇒ NO_TRADE | CI | `test_news_calendar`, `test_forex_factory_calendar_blocks_and_caches`, `test_n02_windows_by_tier` (tiered windows since 0.8.0) |
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
| AT-25 | Real-data backtest with OOS, R, drawdown | PENDING OWNER | `ayesha report` + `backtest` workflow ready (`test_report_cli_on_synthetic_csv`, synthetic only). Needs the `AYESHA_OANDA_TOKEN` repo secret or `backtest-local.bat`; no real result exists yet. The news comparison also needs a permitted historical calendar (I04) |
| AT-26 | 30-day demo forward log | OPEN | Registry + journal ready; needs the scanner running for 30 days |
| AT-27 | Code, tests, docs, evidence committed | PARTIAL | Code/tests/docs on `main`; real-device screenshots pending |
| AT-28 | Windows/Ubuntu/Android CI green on same HEAD + artifact hashes | CI | ci (ubuntu, windows, relay, news) + build-android; APK SHA-256 in each release (see I01) |
| AT-29 | No undisclosed always-on server | CI/doc | Only ntfy.sh (disclosed, opt-in), OANDA (data), Forex Factory (calendar); docs/08 and app Settings say so |
| AT-30 | Failures show health states, never false "Ready" | PARTIAL | READY only for signed fresh PC signals with all gates; PC offline/stale shown on home screen (device pending) |
| AT-31 | READY impossible without CLEAR news, verified spec, valid capital, fresh quote/data, lot > 0, no blockers, even if config is loosened | CI | `test_ready_guard_holds_even_with_strict_news_off`, `test_ready_guard_blocks_unverified_contract`, `test_c02_bad_stale_or_missing_capital_never_gives_ready` |
| AT-32 | READY push that failed (network) is retried until expiry, never sent twice | CI | `test_failed_ready_push_is_retried_once_delivered`, `test_confirmed_event_upgrades_record_and_pushes_ready_once` |
| AT-33 | Replayed old heartbeat cannot show the PC as online | CI (core) + PENDING device | Kotlin `replayedHeartbeatCannotMakePcLookOnline`; LinkService accepts only newer heartbeats |
| AT-34 | One combined MTF setup, no per-timeframe signals | CI | `test_one_signal_per_setup_not_per_timeframe`, `test_default_is_m15_only_with_full_mtf_text` |
| AT-35 | M5 confirmation is causal and fails closed (stop first, target first, expiry, weak candle, RR after confirmation) | CI | `test_mtf_confirmation_is_causal`, `test_buy_confirms_*`, `test_weak_candle_*`, `test_stop_before_confirmation`, `test_target_before_entry`, `test_rr_rechecked_after_confirmation`, `test_expired_unconfirmed`, `test_sell_mirror_confirms` |
| AT-36 | WATCH → READY upgrade updates the same phone signal; READY is never downgraded by a replay | CI | `test_confirmed_event_upgrades_record_and_pushes_ready_once`, `test_confirm_failed_is_archived_not_alerted`, Kotlin `onlyWatchToReadyOrNoTradeMayReplaceAStoredSignal`. Device pending |
| AT-37 | M1 scalp cannot be enabled without validation | CI | `test_scalp_m1_refused_until_validated` |
| AT-38 | Health check for a nontechnical owner never prints the token | CI | `test_doctor_reports_every_missing_piece`, `test_doctor_all_green_with_fakes`, CI step "Doctor runs without credentials" |
| AT-39 | Journal statistics use only the owner's typed real results | CI (core) + PENDING device | Kotlin `journalStatsUseOnlyTypedResults`; app shows tests and signals separately |
| AT-40 | Report covers IS/OOS, walk-forward, pair/session/mode breakdown, feasibility at $20–$5,000, adaptive account, and labels its data | CI (synthetic) | `test_report_on_synthetic_data_is_labelled`, `test_capital_feasibility_respects_min_lot`, `test_report_has_adaptive_accounts_for_every_mode`. Real data pending (AT-25) |
| AT-41 | Workflow inputs cannot inject shell code; secrets not interpolated into scripts | CI | `scripts/check_workflows.py` (CI step + `test_workflows_and_repo_hygiene`), `test_backtest_inputs_are_strictly_validated`, `test_backtest_run_validate_only` |
| AT-42 | OANDA token never on a command line, in logs, URLs, reports or commits | CI | no `setx` in scripts (`test_windows_scripts_call_valid_commands`), `test_oanda_feed_maps_401_to_auth_rejected_without_leaking_token`, `test_redact_scrubs_token_and_bearer`, Windows CI scenarios assert the token never appears in output, `scripts/check_no_secrets.py` |
| AT-43 | Local real-data backtest without the token in GitHub | PARTIAL | `backtest-local.bat` + `ayesha backtest-run`; input errors tested on Windows CI; real OANDA download pending owner token |
| AT-44 | Install / start scripts: failures and recovery | CI (Windows) | `scripts/windows_script_tests.ps1`: before install, first install, re-run keeps values, rejected token stops, network down restarts then gives up when capped, corrupt equity, moved Python, token removal |
| AT-45 | App update keeps the journal | PARTIAL | Kotlin `backupRestoreNeverLosesATypedResult`, `inboxLimitNeverDropsJournalTrades`; CI `Signing self-test` proves a `make-signing-key` key signs the APK. Owner key + device upgrade test pending |


## News intelligence & adaptive capital spec v1.0 (release 0.8.0)

Mandatory tests from section 6 of the handoff spec. Python tests are in `desktop/tests/test_news_capital.py` and
`desktop/tests/test_news_backtest.py`; Kotlin tests in `android/app/src/test/.../CoreTest.kt`. All synthetic or
fixture data: none of these proves that the strategy or the news protection makes money.

| # | Requirement | Status | Evidence / what is missing |
|---|---|---|---|
| N01 | Event valid, covered, timestamped; maps to EURUSD, USDJPY, EURJPY and other pairs | CI | `test_n01_event_maps_to_both_currencies_and_global_usd` (USD top data blocks every enabled pair; other USD high impact only USD pairs; EUR/JPY events only their pairs), `test_n01_forex_factory_times_are_converted_dst_safe` (EDT/EST, naive times dropped) |
| N02 | High impact 30/30, CPI/NFP/FOMC tighter windows ⇒ NO_TRADE; overlaps use the strictest | CI | `test_n02_windows_by_tier` (5 cases), `test_n02_overlapping_events_use_the_strictest_and_last_window`, `test_n02_tier_config_can_never_undercut_the_legacy_window`, `test_n02_title_can_only_make_an_event_stricter` |
| N03 | Delayed/rescheduled/cancelled/corrected events never silently CLEAR | CI | `test_n03_moved_dropped_and_corrected_events_never_silently_clear` (old time keeps blocking, new time blocks, dropped event stays as a ghost, lowered impact ignored, correction opens a new window) |
| N04 | Missing/stale/corrupt calendar, wrong timezone, clock drift ⇒ NEWS_UNVERIFIED, no READY | CI | `test_n04_untrusted_calendar_is_news_unverified` (missing, stale, future fetch time, unknown provenance, coverage gap, malformed, unknown currency, conflict, corrupt cache), `test_n04_quote_from_the_future_is_clock_drift`, `test_n01_forex_factory_times_are_converted_dst_safe` (time without zone dropped) |
| N05 | Medium impact with extreme spread/volatility also blocks | CI | `test_n05_medium_event_with_shock_or_extreme_spread_blocks` (also a LOW event with a shock) |
| N06 | After the window, abnormal spread, huge M5 range, missing bars or unclosed M5 ⇒ still blocked | CI | `test_n06_after_the_timer_the_market_must_settle` (spread, shock, gap, no baseline, no closed bar yet, feed stopped, live spread, whipsaw, late shock extends, forming bar ignored) |
| N07 | Actual vs forecast only after publication; zero lookahead | CI | `test_n07_actual_is_invisible_before_publication`; replay: `test_asof_hides_actual_until_published_and_rows_until_observed`, `test_zero_lookahead_future_bars_and_future_actuals_change_nothing` |
| N08 | Missing/conflicting numbers ⇒ UNKNOWN, no fabricated probability | CI | `test_n08_missing_or_conflicting_numbers_give_unknown_not_a_probability` |
| N09 | USD headline ⇒ conditional pair scenarios only, no BUY/SELL | CI | `test_n09_usd_headline_gives_conditional_pair_scenarios_only`; Kotlin `newsTextIsInformationOnly` |
| N10 | READY not yet entered becomes non-actionable on a new event or volatile quote | CI | `test_n10_ready_is_invalidated_when_a_new_event_appears`, `test_n10_expiry_is_capped_before_the_next_lockout`, `test_n10_a_failed_push_is_rechecked_before_it_is_retried`; replay `test_pending_order_is_cancelled_when_a_new_event_appears`; Kotlin `invalidatedReadyIsNoTradeAndCancelled` |
| N11 | Notifications signed, time-stamped, News Watch / NO_TRADE / READY distinct | CI | `test_n11_news_watch_ready_and_heartbeat_are_signed_and_distinct`; Kotlin `parsesPythonNewsNoticeAndItIsNeverATradeSignal`, `pcNewsWindowBlocksTvCandidatesAndPcReady`, `pcReadyNeedsWireFormat4FreshNewsAndMatchingCapital`. Real phone: PENDING OWNER |
| N12 | Offline source recovers safely; ledger auditable without secrets | CI | `test_n12_offline_news_source_recovers_and_ledger_is_auditable` |
| C01 | Equity $25 → $100 → $500 → $1,000 recomputes budget and lot, no code change | CI | `test_c01_budget_and_lot_follow_verified_equity_without_code_changes` (also $5,000 and a fall back to $400); Kotlin `sameCodeLotFollowsEquityUpAndDown` |
| C02 | Decline, withdrawal, bad numbers, stale snapshot, missing state, PC/phone mismatch ⇒ no READY, no guessed lot | CI | `test_c02_bad_stale_or_missing_capital_never_gives_ready`; Kotlin `phoneEquityMustBeConfirmedWithinADay`, `pcReadyNeedsWireFormat4FreshNewsAndMatchingCapital` |
| C03 | Standard USD vs Cent distinct; OANDA balance never used as Exness capital | CI | `test_c03_cent_and_standard_are_distinct_and_oanda_balance_is_never_used` |
| C04 | Per-symbol Exness spec; EURUSD confirmation never reused | CI | `test_c04_broker_spec_is_per_symbol` (also an old one-record file confirms EURUSD only). Owner values: PENDING OWNER |
| C05 | Lot floors to step, hard cap holds, stop never narrowed | CI | `test_c05_lot_floors_hard_cap_holds_and_stop_is_never_moved`; Kotlin `lotFloorsNeverRoundsUp`, `pcLotIsNeverExceededOnThePhone` |
| C06 | Unknown positions, stale margin, correlation, daily loss, two losses, open risk block | CI | `test_c06_positions_margin_exposure_and_daily_limits` |
| C07 | Min lot above budget at $25 ⇒ NO_TRADE with USD and %; same geometry feasible at higher equity | CI | `test_c07_min_lot_explanation_at_25_and_same_geometry_feasible_later` ($2.11 = 8.44 % at $25; 0.01 lot at $500) |
| C08 | Deposit/withdrawal not trade P&L; journal separate from tests | CI | `test_c08_deposits_are_not_trading_pnl`, `test_b4_weekly_drawdown_excludes_cash_flows_and_is_only_a_warning`; Kotlin `journalStatsUseOnlyTypedResults` |
| C09 | Update Capital persists and refreshes PC sizing; phone mismatch visible; no equity on the relay | CI | `test_c09_capital_updates_reach_the_scanner_and_never_the_relay`; Kotlin `capitalDigestMatchesPythonVector`, `heartbeatCarriesPcCapitalStatus`. Phone screen: PENDING OWNER |
| C10 | News/score cannot bypass daily or capital rules; unknown values fail closed | CI | `test_c10_news_and_scores_never_bypass_capital_or_daily_rules` |
| B4/B5 | Weekly drawdown and expiry warnings (warnings only); risk history view | CI | `test_b4_weekly_drawdown_excludes_cash_flows_and_is_only_a_warning`, `test_b4_confirmation_expiry_warning_before_it_goes_stale`, `test_b5_capital_history_shows_snapshots_change_journal_and_warnings`, `test_doctor_shows_capital_warnings_as_codes_without_amounts` |
| I01 | Windows/Ubuntu Python, Android unit/build, relay, news source green on the same commit | CI | Commit `c8dc37f` (release 0.8.0): [ci run 38881922779](https://github.com/arnobai70-del/Aysha-Point/actions/runs/38881922779) (desktop ubuntu + windows, relay, news) and [build-android run 38881922812](https://github.com/arnobai70-del/Aysha-Point/actions/runs/38881922812) (JVM tests + APK), release [android-v0.5.0-b9](https://github.com/arnobai70-del/Aysha-Point/releases/tag/android-v0.5.0-b9). Docs-only commits after it run `ci` only |
| I02 | Integration fixture: event → block → stabilisation → risk → signed phone explanation, no order | CI | `test_i02_event_block_stabilise_then_signed_ready` (record checked against `contracts/signal.schema.json` 1.1); no order API anywhere (`test_repo_has_no_order_api`) |
| I03 | Backtest output has data source, as-of integrity, incomplete-news warning, real sample sizes, no invented win rate | CI (synthetic) | `test_report_compares_news_modes_with_integrity_and_sample_sizes`, `test_incomplete_calendar_is_reported_and_fails_closed`, `test_report_on_synthetic_data_is_labelled`; without a calendar the report says `NOT RUN (BLOCKED BY DATA)` and always `NEWS DIRECTION NOT BACKTESTED` |
| I04 | News off vs on uses the same candles; cost-adjusted OOS comparison | CI (synthetic) + BLOCKED BY DATA | `test_news_modes_share_candles_and_signals`, `test_upgraded_blocks_everything_legacy_blocks_and_more`, `test_news_comparison_scores_what_the_protection_removed`, `test_report_cli_runs_the_news_comparison`. No real result: no OANDA history has been downloaded and no permitted point-in-time historical calendar is integrated |
| I05 | Real Windows PC, Android 13 phone, Pine compile, owner-confirmed Exness specs stay PENDING OWNER | PENDING OWNER | Not observed yet. Checklist: [11-news-and-capital-guide.md](11-news-and-capital-guide.md) section জ and [10-owner-testing-guide.md](10-owner-testing-guide.md) |
| I06 | Forward-paper period specified; live money not advertised as verified | PENDING OWNER | Period: at least 30 trading days on demo or paper, every READY journaled (docs/11 section জ, AT-26). README and STATUS say there is no validated trading edge |
