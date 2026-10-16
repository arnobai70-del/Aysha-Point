# AYESHA FX: status (release 1.0.0, 2026-10-16)

**Implemented** = code exists. **Tested (CI)** = automated tests on GitHub Actions. **Verified** = seen working on the
real platform (TradingView account, a real phone, the owner's broker, real market data). Nothing below is verified on
a real platform yet; those items are **PENDING OWNER DEVICE/AUTHORIZATION**.

State: **demo/paper only, fail-closed. Not for real-money decisions.** No real-data backtest and no forward test has
been run, so there is **no validated trading edge yet**. News direction (actual vs forecast) is not backtested at all.

Release 0.9.0 adds the **research plane** (Hybrid AI plan, milestone v0.9.0), **off by default**. It never produces
READY, never sends anything to the phone and places no orders; with research on or off, the advisory path below is
byte-identical to 0.8.0 (golden fingerprint, plan T06). The phone app stays 0.5.0 (no new APK).
Release 1.0.0 adds the research **Strategy Lab** (milestone v1.0.0): the baseline, one control and one experimental
strategy replayed by one common runner and compared on the same data, split, costs and hypothetical accounts. It is
still research only; no strategy in it is validated, and none of them can reach the phone.

| Part | Implemented | Tested (CI) | Verified on real platform |
|---|---|---|---|
| PC scanner without MT5 (OANDA v20 data, bid/ask, quote age) | yes | fake-HTTP tests | **pending**: owner OANDA practice token |
| Windows one-time setup (`install.bat` → `ayesha setup`: token, capital, leverage, per-pair contract, pairing), daily start (`start-ayesha.bat`: capital check, scan, restarts on network errors, stops on config/token errors), `ayesha doctor`, `backtest-local.bat` | yes | **Windows CI runs every script end to end** incl. failures and recovery (`scripts/windows_script_tests.ps1`) | **pending**: owner PC |
| Credential handling (token hidden, registry API, redaction), hardened backtest workflow, secret and workflow scans | yes | yes (see SECURITY.md) | n/a |
| **News state machine** (A1–A3): tiered windows (central bank 45/60, CPI/NFP/PCE 45/30, high 30/30, medium 10/10), USD as a global currency, overlapping events, moved/cancelled/corrected events, clock drift, post-news stability on closed M5 bars, shock on medium/low events, `NEWS_UNVERIFIED` when the source is missing/stale/untrusted | yes | N01–N06, N12 (`test_news_capital.py`) | first live week on owner PC pending |
| **News notices** (A4): upcoming, entries blocked, post-news summary (after the market settled), READY cancelled; signed, never a trade signal; phone blocks TradingView candidates during a PC news window | yes | N10, N11 + Kotlin `parsesPythonNewsNoticeAndItIsNeverATradeSignal`, `pcNewsWindowBlocksTvCandidatesAndPcReady`, `invalidatedReadyIsNoTradeAndCancelled` | **pending**: real phone |
| **Numbers analysis** (A5): actual vs forecast only after publication; conditional scenarios, no probabilities; `UNKNOWN` / `BLOCKED BY DATA` without verified numbers | yes (advisory only, never a gate that can open a trade) | N07–N09 | Forex Factory weekly export has no verified actuals, so live analysis is **BLOCKED BY DATA** |
| Event ledger: every news decision with source, fetch time, hash, phase and reasons (no secrets) | yes | N12 | n/a |
| **Adaptive capital** (B1–B3): owner-entered Exness equity (`ayesha capital`, phone Update capital), 24 h validity (4 h after a deposit, withdrawal or >25 % change), open trades confirmed within 12 h, free margin with open trades, deposits/withdrawals kept out of P&L, Standard vs Cent, PC/phone digest check (`CAPITAL_MISMATCH`), equity never on the relay | yes | C01–C03, C08, C09 + Kotlin `capitalDigestMatchesPythonVector`, `phoneEquityMustBeConfirmedWithinADay`, `sameCodeLotFollowsEquityUpAndDown` | **pending**: owner types real Exness equity |
| Per-pair Exness contract (min lot, step, contract size, commission, stop level, leverage); EURUSD confirmation never reused for another pair | yes | C04 | **pending**: owner confirms each pair from the Exness app |
| Sizing: floor to step, 1% hard cap, never narrows a stop to fit the minimum lot, daily 2% / two losses / open risk 1% / correlation, phone lot never above the PC lot | yes | C05–C07, C10 + Kotlin `pcLotIsNeverExceededOnThePhone` | no live Exness check |
| Capital warnings (B4): weekly drawdown ≥4% without deposits, capital or open-trade confirmation expiring within 2 h; warnings only, never a gate | yes | `test_b4_*`, `test_doctor_shows_capital_warnings_as_codes_without_amounts` | n/a |
| Risk history (B5): `ayesha capital --history` (snapshots, 7-day change, change journal, warnings) | yes | `test_b5_capital_history_shows_snapshots_change_journal_and_warnings` | n/a |
| Multi-timeframe: H4 context, H1 bias / last BOS-CHoCH / premium-discount, M15 setup, optional M5 confirmation, M1 scalp refused | yes | unit + causality tests, replay and scanner tests | needs real data |
| Hard READY guard (news CLEAR, verified per-pair spec, valid capital and open trades, fresh quote, fresh data, lot > 0, no blockers) independent of config; READY not entered yet is re-checked and turned INVALIDATED on new news or abnormal spread | yes | `test_ready_guard_*`, `test_n10_*`, `test_c10_*` | n/a |
| Signed PC → phone push via ntfy.sh, heartbeat (with capital status), READY retry after a failed push (re-checked first), WATCH → READY upgrade, wire format 4, signal schema 1.1 | yes | unit + **live relay round trip in CI** + I02 integration fixture | **pending**: real phone |
| News gate source: Forex Factory weekly export (cached, at most hourly) or CSV | yes | fixtures + **live fetch job in CI** | first fetch on owner PC pending |
| Validation report (`ayesha report`): pairs × modes, in/out-of-sample, walk-forward, session/direction/H4 breakdown, adaptive account and feasibility at $20/$25/$30/$100/$500/$1,000/$5,000 | yes | synthetic data only | **pending**: `backtest` workflow needs the `AYESHA_OANDA_TOKEN` repo secret, or `backtest-local.bat` on the owner PC |
| **P2 news comparison**: no-news vs legacy 30/30 vs upgraded news on the same candles and signals, point-in-time calendar view (actuals hidden until published), integrity and incomplete-data warnings, sample sizes, OOS split | yes | `test_news_backtest.py` (17 tests, synthetic data) | **BLOCKED BY DATA**: no permitted point-in-time historical calendar is integrated; the owner must supply one (`--news calendar.csv`) |
| Phone app 0.5.0: READY / WATCH / CHART_CANDIDATE / NO_TRADE (incl. a cancelled READY, shown as INVALIDATED) / UNVERIFIED / EXPIRED, news watch, Update capital, capital mismatch, MTF explanation, journal with real-trade statistics, heartbeat replay protection | yes | 39 JVM tests + CI build | **pending**: Android 13 device |
| Pine indicator (①–④, H1 bias, H4 context row, feed note, alerts only on 15m), version row `0.4.0 #9bb5e8ed5937` | yes | generated from spec, payload keys checked | **pending**: compile in TradingView |
| TradingView `alert()` → phone (Mode A) | yes | parser tests | **blocked on Basic**: no technical alerts on Basic |
| Python ↔ Pine behavior parity | no | no | no |
| Python ↔ Kotlin wire-format parity (incl. MTF, news notices, capital digest) | yes | shared fixtures + signature and digest vectors | n/a |

### Research plane (0.9.0 foundation, 1.0.0 Strategy Lab; off by default)

| Part | Implemented | Tested (CI) | Verified on real platform |
|---|---|---|---|
| Legacy path unchanged with research present, on or off (signal ids, statuses, signed messages, replay trades, CLI, 65 protected files) | golden fingerprint from the 0.8.0 code | T06 `test_legacy_compatibility.py` (Ubuntu + Windows) | n/a |
| Frozen datasets: OANDA practice download or exported CSV, raw kept, write-once manifest, content hashes, quality PASS / DEGRADED / REJECTED, nothing repaired | yes | `test_datasets.py` (fake HTTP, synthetic CSV) | **pending**: owner runs `research ingest --provider oanda` |
| Separate research registry (`research.db`): migrations, no-READY constraint, hash-linked audit, crash reconciliation, verified backup and restore | yes | `test_registry.py` | **pending**: owner PC |
| Baseline replay (`baseline-sweep-mss-fvg`, the unchanged live rules) with reproducible run id and `--verify`; parity with the legacy CSV path | yes | `test_baseline_parity.py` (synthetic), T01, T02 | **pending**: real data; no real result exists |
| Separate limited worker process (Windows job object memory/CPU caps, kill-on-close; POSIX nice + memory limit), timeout, one writer | yes | `test_worker_isolation.py` incl. the scanner golden scenario while a worker hangs (T07) | **pending**: owner PC |
| Read-only dashboard on 127.0.0.1 (key, Host check, GET only, no scripts, redacted, money hidden) | yes | `test_dashboard.py`, `research dashboard --check` (T08) | **pending**: owner PC |
| `ayesha research` CLI, research doctor, `start-research.bat`, `backup-research.bat`, isolation check | yes | `test_rollback_isolation.py` (T05, T10), `research_smoke.py`, `windows_research_tests.ps1`, `check_research_isolation.py` | **pending**: owner PC |
| **Strategy Lab (1.0.0)**: strategy contract and loader (baseline A frozen, control B London ORB, exactly one experimental C H1/H4 trend), common runner with the legacy fills and gates (baseline trade-for-trade equal to the legacy replay), cost models and sensitivity, account simulation with the live risk engine, split plan with sealed holdout, after-cost metrics, side-by-side comparison | yes | `test_strategy_lab.py`, `test_lab_runs.py`, `research_smoke.py` (synthetic) | **pending**: real data; no real result exists, so nothing is known about any of the three |
| Regimes, historical news comparison, ML, phone research tab (v1.1.0 to v1.3.0) | no | no | not started; historical news **BLOCKED BY DATA**, ML only with enough validated data |

## What an alert means
- **READY** only comes from the PC scanner, signed with the owner's pairing code, fresh, same strategy hash, news
  `CLEAR`, valid capital, and every PC gate passed, plus the hard READY guard. It is still advice, not permission:
  check price and spread in Exness.
- **WATCH** (PC): the setup is valid but not an entry yet, e.g. waiting for M5 confirmation. No notification; if it
  later becomes READY the phone updates the same signal and notifies once.
- **INVALIDATED** (PC): a READY you have not entered yet was cancelled (new news, news phase change, abnormal spread).
  The phone notifies once; do not place that order.
- **CHART_CANDIDATE** comes from TradingView only: chart rules fired; news, live spread, broker spec unchecked. The
  phone blocks it while the PC reports a news window.
- **News notices** (upcoming, blocked, after the news) are information, never a trade signal.
- **NO_TRADE / UNVERIFIED / EXPIRED** never raise an entry notification; they sit in the archive with reasons.

## Owner actions needed (in order)
Step-by-step Bengali guides with expected results: [10-owner-testing-guide.md](10-owner-testing-guide.md) and
[11-news-and-capital-guide.md](11-news-and-capital-guide.md).

1. Windows PC: run `desktop\windows\install.bat` (Python, token, Exness equity and open trades, leverage, contract per
   pair, pairing, doctor). Re-running it keeps earlier answers.
2. Phone: uninstall the old app after backing up the journal (each CI build has a new debug signer until step 6), install
   the 0.5.0 APK, grant notification access, type the pairing code, press Test, then **Update capital** with the same
   equity as the PC and check the app says it matches.
3. TradingView: replace the indicator with the current Pine file, check the VERSION row shows `0.4.0 #9bb5e8ed5937`
   and report compile errors or a screenshot (AT-16); try one `alert()` alert on Basic and report what happens (AT-01).
4. Real-data report: run `desktop\windows\backtest-local.bat` (token stays on the PC), or add the repository secret
   `AYESHA_OANDA_TOKEN` and run **Actions → backtest** (AT-25). For the news comparison add `--news calendar.csv` with a
   historical calendar you are allowed to use. Send the report files.
5. Forward test: run the scanner on demo/paper for at least 30 trading days and journal what you would have done
   (AT-26, I06). Real money is not advised before this and a real-data report exist.
6. Run `desktop\windows\make-signing-key.bat`, add its four `AYESHA_KEYSTORE_*`/`AYESHA_KEY_*` secrets, keep the key
   offline (AT-23). Back up the journal in the app before every uninstall.
7. Optional, research (1.0.0): approve the merge of the Strategy Lab pull request (0.9.0 is already merged); then,
   if you want, follow [12-research-guide.md](12-research-guide.md) (enable, ingest from OANDA practice, `research lab`,
   report) and send the `lab.md`. Research stays off unless you turn it on.

See [VERIFICATION.md](VERIFICATION.md), [MASTER_CHECKLIST.md](MASTER_CHECKLIST.md), [FEATURE_MATRIX.md](FEATURE_MATRIX.md)
and, for research, [RESEARCH_ACCEPTANCE.md](RESEARCH_ACCEPTANCE.md).
