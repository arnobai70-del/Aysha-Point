# AYESHA FX: status (release 0.6.0, 2026-10-15)

**Implemented** = code exists. **Tested (CI)** = automated tests on GitHub Actions. **Verified** = seen working on the
real platform (TradingView account, a real phone, the owner's broker, real market data). Nothing below is verified on
a real platform yet; those items are **PENDING OWNER DEVICE/AUTHORIZATION**.

State: **demo/paper only, fail-closed. Not for real-money decisions.**

| Part | Implemented | Tested (CI) | Verified on real platform |
|---|---|---|---|
| Mode B: PC scanner without MT5 (OANDA v20 data, bid/ask, quote age) | yes | fake-HTTP tests | **pending**: owner OANDA practice token |
| Mode B: signed PC → phone push via ntfy.sh + heartbeat / offline state | yes | unit + **live relay round trip in CI** | **pending**: real phone |
| Exness spec without MT5 (assumed → owner-confirmed) | yes | yes | **pending**: owner types values from the Exness app |
| News gate: Forex Factory weekly export (cached) or CSV | yes | yes (fixtures) | pending first live fetch |
| Risk engine, all hard gates, $20/25/30 Standard = NO_TRADE | yes | yes | no live Exness check |
| Phone app: strict checks (BAR/ST/V/TF/watchlist/delay/signature), READY vs CHART_CANDIDATE vs NO_TRADE vs UNVERIFIED, archive | yes | 21 JVM tests | **pending**: Android 13 device |
| Phone app: PC link service, diagnostics, watchlist, store lock + corrupt-file recovery | yes | build only (Android framework code) | **pending**: device |
| Pine indicator (chart explanation ①–④, alerts only on 15m) | yes | generated from spec, parses, payload keys checked | **pending**: compile in TradingView |
| Mode A: TradingView `alert()` → phone | yes | parser tests | **blocked on Basic**: official pricing lists no technical alerts on Basic |
| Rules + zero-lookahead replay backtester | yes | synthetic data | **no real-data report yet** (`ayesha export --feed oanda` makes one possible) |
| Python ↔ Pine behavior parity | no | no | no |
| Python ↔ Kotlin wire-format parity | yes | shared fixture + signature vector | n/a |

## What an alert means
- **READY** only comes from the PC scanner, signed with the owner's pairing code, fresh, same strategy hash, and every
  PC gate passed (feed fresh, spread within limit using the larger of feed and typical Exness spread, news clear,
  owner-confirmed Exness spec, lot within budget). It is still advice, not permission: check price and spread in Exness.
- **CHART_CANDIDATE** comes from TradingView only: chart rules fired; news, live spread, broker spec unchecked.
- **NO_TRADE / UNVERIFIED / EXPIRED** never raise an entry notification; they sit in the archive with reasons.

## Owner actions needed (in order)
1. TradingView Basic: try one "AYESHA → Any alert() function call" alert; report allowed / upgrade asked (AT-01).
2. Add the indicator to EURUSD 15m; report compile errors or a screenshot of ①–④ (AT-16).
3. Install the APK on the Android 13 phone; grant notification access; press Test alert (AT-19).
4. For the free path: OANDA practice token, `confirm-broker`, `pair`, `push-test`, then run the scanner
   ([guide](08-pc-scanner-no-mt5.md)) (AT-02, AT-04, AT-05).
5. Add the four `AYESHA_KEYSTORE_*` repository secrets so updates install without uninstalling (AT-23).

See [VERIFICATION.md](VERIFICATION.md) for every acceptance test and [FEATURE_MATRIX.md](FEATURE_MATRIX.md) for rule coverage.
