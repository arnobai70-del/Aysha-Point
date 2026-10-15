# Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-10-14 | Follow the master plan with the reordered roadmap (risk engine first, edge validation before alerts) | Owner asked for the recommended order without step-by-step approvals |
| 2026-10-14 | Manual execution only. No code may place, modify or close orders; CI scans for order APIs | Master plan rule; owner trades in the Exness app |
| 2026-10-15 | MT5 is **not** required. Daily use = TradingView indicator on PC → TradingView push → AYESHA Android app | Owner decision |
| 2026-10-15 | Code goes straight to GitHub `main`; owner receives only the Pine file and the APK | Owner decision; zips were hard to use |
| 2026-10-15 | Phone alerts are labelled CHART_CANDIDATE, never READY | Pine cannot see news, live broker spread or broker contract spec (audit P0-04) |
| 2026-10-15 | Lot sizing fails closed: unknown instrument, missing USD rate or bad settings → RISK_UNVERIFIED, no lot, no notification. The chart's own lot is never used as a fallback | Audit P0-03 |
| 2026-10-15 | Expiry and dedup use the signal bar close time (`BAR=`) from the indicator, not the phone's receive time | A late push must not get extra life or be shown twice (audit P0-05) |

## Two delivery modes
- **Mode A, TradingView bridge (current):** indicator `alert()` → TradingView app push → AYESHA app reads it.
  No server, no credentials. Depends on the TradingView plan allowing `alert()` alerts and on push delivery.
- **Mode B, PC scanner (fallback):** `desktop/` scanner with an authorized data feed, full risk gates and news lockout,
  pushing to the phone (Telegram today). Needs an owner decision on the data feed (MT5 read-only, or an authorized
  non-MT5 feed) and the push channel. Only built out if Mode A is blocked on the owner's plan.
