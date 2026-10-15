# AYESHA FX: status (2026-10-15)

Plain answer to "what works today". **Implemented** = code exists. **Tested** = automated tests in CI.
**Verified** = checked on the real platform (TradingView, a phone, the owner's broker). Nothing is verified yet.

| Part | Implemented | Tested (CI) | Verified on real platform |
|---|---|---|---|
| Pine indicator: sweep → MSS → FVG, ①–④ drawings, `alert()` payload | yes | generated from spec, parses, payload keys match the phone parser | **no**, not compiled in TradingView yet |
| TradingView → phone push (Mode A) | yes | parser unit tests | **no**; Basic plan entitlement for `alert()` alerts unknown |
| Android app: notification listener, inbox, detail, settings | yes | core logic: 16 JVM tests; APK builds in Actions | **no**, not run on a real phone |
| Phone lot sizing (fail closed: RISK_UNVERIFIED / NO_TRADE) | yes | yes ($20/$25/$30, crosses, NaN, negatives) | no |
| Desktop risk engine with all hard gates | yes | yes (70 Python tests) | no broker data yet |
| Desktop rules + zero-lookahead replay backtester | yes | yes, on synthetic data | **no real-data backtest**; edge unknown |
| Desktop scanner + SQLite + Telegram (Mode B) | yes | yes | needs a data feed (MT5 read-only today) |
| News lockout | desktop only, needs a calendar file | yes | phone and Pine do **not** check news |

## What an alert means today
Every phone alert is a **CHART_CANDIDATE**: the chart rules fired and RR ≥ 2 after an assumed spread. It is **not** a
verified READY signal. News, the live Exness spread and the Exness contract spec are not checked; the app says so on
every alert. The lot shown comes only from the owner's own settings; if it cannot be computed safely the app shows
RISK_UNVERIFIED and does not notify.

## Open items (owner needed)
1. Try creating one AYESHA "Any alert() function call" alert on the TradingView account; report whether it is allowed.
2. Add the indicator to a 15m chart and report any compile error.
3. Install the APK, press "Test alert", then wait for a real alert.
See [VERIFICATION.md](VERIFICATION.md) for the checklist and [DECISIONS.md](DECISIONS.md) for why things are this way.
