# Master plan section Z: checklist with evidence (release 0.7.0)

Source: [master plan section Z](AYESHA_AI_FOREX_TRADING_ASSISTANT_MASTER_PLAN.md). Status words:
**DONE** = built and proven by an automated test or a committed file (evidence named) ·
**PARTIAL** = part built/proven, the rest is said · **OWNER** = needs the owner's account, device or decision ·
**CHANGED** = replaced by an owner decision (see [DECISIONS.md](DECISIONS.md)) · **OPEN** = not built.
Test names refer to `desktop/tests/*.py` (Python) and `android/app/src/test/.../CoreTest.kt` (Kotlin).

## Z1: Product decisions & approvals
| Item | Status | Evidence / note |
|---|---|---|
| Owner reviewed and approved master specification | DONE | Owner asked to follow the plan in the recommended order (DECISIONS 2026-10-14) |
| GitHub repository URL and access | DONE | github.com/arnobai70-del/Aysha-Point, push to `main` allowed by owner |
| OS version and PC hardware/network | OWNER | Windows assumed; not confirmed |
| Android 13 handset compatibility, install method | OWNER | APK sideload; device not tested (AT-19) |
| Account base currency USD, equity input format | PARTIAL | USD assumed; equity typed in `install.bat` / phone settings |
| Exness Standard contract settings from terminal | CHANGED/OWNER | No MT5: owner types values from the Exness app (`confirm-broker`) |
| Broker platform / legal data adapter | CHANGED | MT5 optional; OANDA v20 practice API is the data source |
| TradingView Basic indicator/alert entitlements | OWNER | Official pricing lists no technical alerts on Basic; owner attempt pending (AT-01) |
| Eligible realtime authorized feed and cost | PARTIAL | OANDA practice token, free; owner has not created one yet |
| Chart mirroring limitation accepted | PARTIAL | Documented; chart and PC are independent calculations |
| No-VPS requirement; optional external relay | DONE | ntfy.sh relay, disclosed (DECISIONS); FCM/Tailscale not used |
| Manual-trade-only scope | DONE | `scripts/check_no_order_api.py`, `test_repo_has_no_order_api` |
| Profile defaults and pairs | DONE | `contracts/strategy-spec.yaml` (6 pairs, 0.5% risk) |

## Z2: Repository and CI
| Item | Status | Evidence / note |
|---|---|---|
| Git repo initialized | DONE | `main` branch |
| README, MASTER_SPEC, rulebook, glossary | PARTIAL | README, master plan, strategy spec, STATUS/DECISIONS/VERIFICATION; no glossary |
| Gitignore and `.env.example` | PARTIAL | `.gitignore`; no `.env` used (token lives in the Windows user environment) |
| Branch / PR policy, labels, milestones | CHANGED | Owner asked for direct pushes to `main` |
| CI: Python tests | DONE | `ci` workflow, Ubuntu + Windows (lint/typecheck not configured) |
| CI: Android unit/build | DONE | `build-android` workflow runs JVM tests and builds the APK |
| CI: Pine static check | DONE | `generate_pine.py --check`, `test_pine_alert_payload_matches_phone_parser` |
| Dependency lockfiles, vulnerability scanning | OPEN | |
| Secrets scan | PARTIAL | No secrets in the repo by design; no dedicated scanner job |
| Release tag/changelog/versioning | DONE | `contracts/version.json`, `test_version_manifest_matches_components`, release tag `android-v<ver>-b<run>` |
| Docs + checklist updated per feature commit | PARTIAL | Done for each release; not enforced by CI |

## Z3: Data and broker fundamentals
| Item | Status | Evidence / note |
|---|---|---|
| Approved data connector authenticated locally | OWNER | OANDA adapter built; owner token pending (AT-02) |
| Read-only adapter (no order calls) | DONE | `check_no_order_api.py` (MT5, Pine strategy, OANDA write endpoints) |
| Stable symbol alias mapping | DONE | `test_mt5_adapter_is_read_only_and_resolves_suffix`, OANDA `EUR_USD` mapping |
| Contract size/min/step/max per symbol | PARTIAL | Assumed until owner confirms; READY blocked until then (`test_ready_guard_blocks_unverified_contract`) |
| USD pip value for cross/JPY | DONE | risk tests, Kotlin `unknownInstrumentsFailClosed` |
| Bid/ask/spread and quote timestamps | DONE | `test_oanda_feed_reads_bid_ask_and_skips_forming_bar` (fake HTTP) |
| Historical data integrity / lookback | PARTIAL | Closed bars only, monotonic check; no real-data run yet |
| Timeframe aggregation on UTC boundaries | DONE | `test_aggregator_closed_bars_only` |
| Reconnect, backfill, stale-quote tests | PARTIAL | Stale/offline states, push retry (AT-32), phone reconnect backoff (code); no live outage test |
| Closed market / holiday / rollover | PARTIAL | Week open/close and rollover in sessions tests; holidays not modelled |
| TradingView feed difference measured | OPEN | Disclosed on the chart (FEED NOTE row) and in the app; not measured |

## Z4: Sessions, structure and liquidity
| Item | Status | Evidence / note |
|---|---|---|
| IANA timezone and DST | DONE | `test_sessions.py` |
| Session overlap / opening range lifecycle | PARTIAL | Sessions and Asia range; no opening-range object |
| Prior-day/week highs/lows | PARTIAL | Prior day yes; prior week no |
| Confirmed swing detection | DONE | `test_primitives.py` |
| External/internal structure | OPEN | |
| BOS with close/buffer | DONE | primitives tests |
| CHoCH and displacement MSS | DONE | primitives tests |
| EQH/EQL pools | DONE | primitives tests |
| Sweep/reclaim vs breakout | DONE | primitives tests |
| Freshness, invalidation, zone expiry | DONE | FVG lifecycle tests, setup expiry |
| Trace separates observation and hypothesis | DONE | `OBSERVED:` / `RULE_BASED_INFERENCE:` lines in every signal |

## Z5: ICT/SMC and psychology
| Item | Status | Evidence / note |
|---|---|---|
| Three-candle FVG and mitigation | DONE | primitives tests |
| IFVG, BPR | OPEN | |
| Order blocks, breakers | OPEN | |
| Premium/discount reference | PARTIAL | H1 range zone in every signal and on the phone; not scored |
| Inducement, SMT, AMD/Judas | OPEN | |
| Fake breakout / late chase filter | PARTIAL | `TARGET_REACHED_BEFORE_ENTRY`, MISSED status, "do not chase" text |
| Inference label everywhere | DONE | trace labels; app and Pine say "chart model, not certainty" |
| No proprietary order flow disclosed | DONE | README, primitives docstring |

## Z6: Entry logic, scoring and risk
| Item | Status | Evidence / note |
|---|---|---|
| Intraday A+ reversal with fixture proof | PARTIAL | SWEEP_MSS_FVG on synthetic data; no real-data fixture |
| Intraday A+ continuation | OPEN | |
| Scalping default disabled | DONE | `mtf.scalp_m1.enabled: false` |
| Scalping cannot enable without QA evidence | DONE | `test_scalp_m1_refused_until_validated` |
| Score not a probability | DONE | `score_is_probability: false`, alert text tests |
| Score cannot override hard gates | DONE | risk engine + READY guard (AT-31) |
| Entry validated at bar close | DONE | `test_zero_lookahead`, `test_mtf_confirmation_is_causal` |
| Structural SL + buffer, not too tight | DONE | `min_stop_atr_fraction` gate tests |
| TP path and obstacles | PARTIAL | Target liquidity recorded; one target only |
| Net RR with friction | DONE | risk tests; recomputed after M5 confirmation (`test_rr_rechecked_after_confirmation`) |
| Lot floors to step, rejects below min | DONE | risk tests, Kotlin lot tests |
| Margin / leverage | PARTIAL | Free margin checked when the feed gives it (MT5); OANDA path has none |
| Spread/slippage limit | DONE | `test_spread_floor_never_lets_feed_spread_be_tighter_than_broker` |
| News lockout and stale calendar | DONE | news tests, live FF fetch job in CI |
| Daily loss / exposure / correlation | DONE | risk tests |
| $25 account produces NO_TRADE | DONE | `test_exness_standard_small_accounts_are_no_trade`, `test_small_equity_is_no_trade` |
| Duplicate, stale, missed never READY again | DONE | `test_scanner_end_to_end_no_duplicates`, AT-32, AT-36 |
| Manual outcomes: simulated vs actual | DONE (code) | Phone journal uses typed real results only (AT-39); backtests stay on the PC/CI |

## Z7: Pine v6 indicator
| Item | Status | Evidence / note |
|---|---|---|
| Compiles on Basic | OWNER | AT-16 |
| Clean/Analyst/Full modes | OPEN | |
| HTF bias and structural levels | DONE (code) | H1 bias and H4 context rows |
| EQH/EQL, session lines | PARTIAL | |
| FVG/OB/IFVG/BPR zones | PARTIAL | FVG only |
| MSS/BOS waits for confirmation | DONE (code) | closed-bar logic; not replayed in TradingView |
| Entry/SL/TP and expiry drawn | DONE (code) | |
| BUY/SELL/WAIT/NO_TRADE semantics | PARTIAL | |
| Risk-unverified disclosure | DONE (code) | "LOT = ESTIMATE, check Exness", FEED NOTE row |
| Dark/light theme, label collisions | OWNER | needs TradingView |
| Limits/performance on Basic | OWNER | |
| Bar replay vs live non-repaint | OWNER | |
| Constants generated from the spec | DONE | `generate_pine.py --check` |
| Pine cannot import scanner signals (guide) | DONE | docs/05, docs/08 |
| Chart candidate ≠ PC READY | DONE | Kotlin `freshCurrentTvAlertIsChartCandidateOnly` |

## Z8: Windows scanner and local safety
| Item | Status | Evidence / note |
|---|---|---|
| Tray app UI | OPEN | Console window + `ayesha doctor` instead |
| Manual refresh | PARTIAL | `ayesha scan --once` |
| Continuous scan while PC is on | DONE (code) | `start-ayesha.bat` loop with auto-restart; owner run pending |
| Startup at login optional, off without consent | DONE | `install.bat` asks Y/N before adding the Startup entry |
| SQLite migrations / recovery | PARTIAL | migrations + WAL; no backup command |
| Feed watchdog / heartbeat / reconnect | DONE | stale/offline tests, heartbeat tests, push retry |
| Completed-candle scheduler and timezone | DONE | scanner drops forming bars (`FakeFeed` returns them) |
| A+ / WATCH / NO_TRADE journaled | DONE | registry events, `WATCH_M5`, `CONFIRM_FAILED` |
| Reason trace and blockers accessible | DONE | `ayesha signals --id`, phone details |
| State machine and idempotent delivery | DONE | per-status delivery keys (AT-32, AT-36) |
| No public local API by default | DONE | no server at all on the PC |
| Restart recovers pending signals | PARTIAL | restart never re-alerts (`test_scanner_end_to_end_no_duplicates`); warmup re-derives setups still waiting for M5, so a later confirmation upgrades the stored record; unconfirmed ones expire. Restart-during-wait not tested end to end |

## Z9: Android 13 app
| Item | Status | Evidence / note |
|---|---|---|
| Signed APK installs on Android 13 | OWNER | CI builds and signs; AT-19, AT-23 |
| POST_NOTIFICATIONS request and denial | DONE (code) | MainActivity |
| Secure pairing and revoke | DONE (code) | HMAC pairing code; `ayesha pair --new` revokes |
| Heartbeat, data age, status badges | DONE (code) | PC link card from PC heartbeat time (AT-33) |
| Watchlist | DONE (code) | Settings |
| Inbox and filtering | DONE (code) | active / archive tabs |
| Details with rule trace and risk status | DONE (code) | DetailActivity, MTF card |
| Capital/risk settings | DONE (code) | SettingsCheck tests |
| Settings sync to PC | OPEN | PC equity is typed separately (install.bat) |
| Risk preview refuses impossible min lot | DONE | Kotlin `smallAccountsNeverExceedBudget` |
| TradingView deep link | DONE (code) | `parsesIndicatorAlert` URL test |
| Canonical signal on companion chart | PARTIAL | levels copy button; no in-app chart |
| Exness action never submits a trade | DONE | the app has no broker integration |
| Journal and realized vs simulated | DONE (code) | JournalActivity, AT-39 |
| Offline history | DONE (code) | local JSON store |
| Dark/light, Bengali/English readability | OWNER | dark theme only |

## Z10: Sync, alerts and failures
| Item | Status | Evidence / note |
|---|---|---|
| FCM | CHANGED | ntfy.sh relay instead (no Google project needed) |
| Notification shows event time, delay handling | DONE | BAR/EXPU keys, Kotlin delay tests |
| LAN/Tailscale pairing | CHANGED | Not needed with the relay |
| Authenticated sync, rate limit, key rotation | PARTIAL | HMAC per message; `pair --new` rotates |
| Missed signals and duplicate replay | DONE | ntfy `since=` catch-up, id dedup, Transitions (AT-36) |
| Notification opens the specific detail | DONE (code) | PendingIntent with signal id |
| Stale push opens EXPIRED safely | DONE | Kotlin expiry tests |
| PC-off state on phone | DONE (code) | STOPPED / OFFLINE from heartbeat time |
| Phone offline and reconnection without duplicate push | DONE (code) | backoff + dedup; device pending |
| Relay unavailable degrades gracefully | PARTIAL | scanner keeps retrying READY until expiry; phone shows reconnecting |
| Chart mismatch not hidden | DONE | app and chart say the calculations are independent |

## Z11: Quantitative validation and release
| Item | Status | Evidence / note |
|---|---|---|
| Primitive fixtures and edge cases | DONE | `test_primitives.py` |
| Bar-by-bar replay with zero lookahead | DONE | `test_zero_lookahead`, `test_mtf_confirmation_is_causal` |
| Walk-forward / out-of-sample results | PARTIAL | Report code done (AT-40); real results pending (AT-25) |
| Spread, slippage, gap simulation | DONE | fill tests (gap through stop, same-bar stop wins) |
| Pair / session / mode breakdown | PARTIAL | Report code done; real results pending |
| Delivery delay, parity, false-positive metrics | OPEN | |
| Paper/demo forward evaluation | OWNER | AT-26 (30 days of scanner running) |
| No-trade cases in screenshots | OWNER | needs device |
| Install/uninstall and secret revocation documented | PARTIAL | docs/08 (install, `pair --new`); uninstall steps short |
| Release tags, APK, Pine included | DONE | GitHub release per build with APK SHA-256 |
| Release hashes and rollback | PARTIAL | hashes yes; rollback = install the previous release APK (signer must match) |
| Owner acceptance without profit claims | OWNER | |
