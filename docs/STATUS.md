# AYESHA FX: status (release 0.7.0, 2026-10-15)

**Implemented** = code exists. **Tested (CI)** = automated tests on GitHub Actions. **Verified** = seen working on the
real platform (TradingView account, a real phone, the owner's broker, real market data). Nothing below is verified on
a real platform yet; those items are **PENDING OWNER DEVICE/AUTHORIZATION**.

State: **demo/paper only, fail-closed. Not for real-money decisions.** No real-data backtest has been run yet, so
there is no evidence that the strategy has an edge.

| Part | Implemented | Tested (CI) | Verified on real platform |
|---|---|---|---|
| PC scanner without MT5 (OANDA v20 data, bid/ask, quote age) | yes | fake-HTTP tests | **pending**: owner OANDA practice token |
| Windows one-time setup (`install.bat`), daily start with auto-restart (`start-ayesha.bat`), `ayesha doctor` | yes | Windows CI runs the start script and doctor; commands in the scripts are parsed by a test | **pending**: owner PC |
| Multi-timeframe: H4 context, H1 bias / last BOS-CHoCH / premium-discount, M15 setup, optional M5 confirmation, M1 scalp refused | yes | unit + causality tests, replay and scanner tests | needs real data |
| Hard READY guard (news CLEAR, verified spec, fresh quote, fresh data, lot > 0, no blockers) independent of config | yes | `test_ready_guard_*` | n/a |
| Signed PC → phone push via ntfy.sh, heartbeat, READY retry after a failed push, WATCH → READY upgrade | yes | unit + **live relay round trip in CI** | **pending**: real phone |
| Exness spec without MT5 (assumed → owner-confirmed) | yes | yes | **pending**: owner types values from the Exness app |
| News gate: Forex Factory weekly export (cached) or CSV | yes | fixtures + **live fetch job in CI** | first fetch on owner PC pending |
| Risk engine, all hard gates, $20/25/30 Standard = NO_TRADE | yes | yes | no live Exness check |
| Validation report (`ayesha report`): pairs × modes, in/out-of-sample, walk-forward, session/direction/H4 breakdown, $20–30 feasibility | yes | synthetic data only | **pending**: `backtest` workflow needs the `AYESHA_OANDA_TOKEN` repo secret |
| Phone app 0.4.0: READY / WATCH / CHART_CANDIDATE / NO_TRADE / UNVERIFIED / EXPIRED, MTF explanation, journal with real-trade statistics, heartbeat replay protection | yes | 27 JVM tests + CI build | **pending**: Android 13 device |
| Pine indicator (①–④, H1 bias, H4 context row, feed note, alerts only on 15m) | yes | generated from spec, payload keys checked | **pending**: compile in TradingView |
| TradingView `alert()` → phone (Mode A) | yes | parser tests | **blocked on Basic**: no technical alerts on Basic |
| Python ↔ Pine behavior parity | no | no | no |
| Python ↔ Kotlin wire-format parity (incl. MTF) | yes | shared fixture + signature vector | n/a |

## What an alert means
- **READY** only comes from the PC scanner, signed with the owner's pairing code, fresh, same strategy hash, and every
  PC gate passed, plus the hard READY guard. It is still advice, not permission: check price and spread in Exness.
- **WATCH** (PC): the setup is valid but not an entry yet, e.g. waiting for M5 confirmation. No notification; if it
  later becomes READY the phone updates the same signal and notifies once.
- **CHART_CANDIDATE** comes from TradingView only: chart rules fired; news, live spread, broker spec unchecked.
- **NO_TRADE / UNVERIFIED / EXPIRED** never raise an entry notification; they sit in the archive with reasons.

## Owner actions needed (in order)
1. Windows PC: run `desktop\windows\install.bat` once (Python, token, equity, Exness contract, pairing, doctor).
2. Phone: install the APK, grant notification access, type the pairing code, press Test.
3. GitHub: add the repository secret `AYESHA_OANDA_TOKEN`, then run **Actions → backtest → Run workflow** for the
   first real multi-year report (AT-25).
4. TradingView: add the indicator to EURUSD 15m and report compile errors or a screenshot (AT-16); try one
   `alert()` alert on Basic and report what happens (AT-01).
5. Add the four `AYESHA_KEYSTORE_*` repository secrets so app updates install without uninstalling (AT-23).

See [VERIFICATION.md](VERIFICATION.md), [MASTER_CHECKLIST.md](MASTER_CHECKLIST.md) and [FEATURE_MATRIX.md](FEATURE_MATRIX.md).
