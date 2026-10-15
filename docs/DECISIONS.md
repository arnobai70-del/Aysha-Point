# Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-10-14 | Follow the master plan with the reordered roadmap (risk engine first, edge validation before alerts) | Owner asked for the recommended order without step-by-step approvals |
| 2026-10-14 | Manual execution only. No code may place, modify or close orders; CI scans for order APIs (MT5, Pine strategy, OANDA write endpoints) | Master plan rule; owner trades in the Exness app |
| 2026-10-15 | MT5 is **not** required | Owner decision |
| 2026-10-15 | Code goes straight to GitHub `main`; owner receives only the Pine file and the APK | Owner decision |
| 2026-10-15 | Phone alerts from TradingView are CHART_CANDIDATE, never READY | Pine cannot see news, live broker spread or broker spec |
| 2026-10-15 | Lot sizing fails closed (RISK_UNVERIFIED); chart lot never used as a fallback | Audit P0-03 |
| 2026-10-15 | Expiry and dedup from the signal bar (`BAR=`), not the phone's receive time | Audit P0-05 |
| 2026-10-15 | **Mode A cannot be the free-plan path**: TradingView Basic lists no technical alerts, and `alert()` alerts are technical. Pine stays as the chart explanation; alerts from it are optional | Re-audit P0-01 (official TradingView pricing/support pages cited there) |
| 2026-10-15 | **Mode B is the canonical live path**: PC scanner on OANDA v20 practice data (official API, bid/ask, free demo token) | Free, authorized, MT5-free, gives real spreads and quote ages; also provides multi-year history for backtests |
| 2026-10-15 | PC → phone transport: **ntfy.sh** public relay, opt-in, HMAC-signed with a 16-character pairing code, topic derived from the code; heartbeat every 5 min and on state change | No VPS, no open port on the PC, no account; relay sees only signal text. Disclosed in the app and guide. Telegram remains an optional extra channel |
| 2026-10-15 | Exness spec without MT5 = repo assumption until the owner types the values from the Exness app (`confirm-broker`); only then can a signal be READY | Re-audit P0-03: no unverified broker spec may produce READY |
| 2026-10-15 | News: Forex Factory weekly export, fetched at most hourly, cached; missing/stale ⇒ NEWS_UNVERIFIED | Strict news mode is the spec default |
| 2026-10-15 | Spread used by the PC gates = max(feed spread, owner's typical Exness spread) | OANDA spreads can be tighter than Exness's |
| 2026-10-15 | Phone treats missing BAR / ST / V, other strategy hash, other timeframe, late push, unsigned PC text, pair outside watchlist as UNVERIFIED (archive only) | Re-audit P0-03 / Milestone 2 |
| 2026-10-15 | TradingView chart and PC scanner are independent calculations; the app never claims they match | Different feeds can disagree (re-audit P0-02) |

## Delivery modes
- **Mode B, PC scanner (canonical, free):** OANDA data → rules + all gates → signed ntfy push → AYESHA app inbox.
  Needs the PC on and online; the app shows PC offline / stopped / data stale.
- **Mode A, TradingView bridge (optional):** indicator `alert()` → TradingView app push → AYESHA app reads it as
  CHART_CANDIDATE. Works only on plans with technical alerts.
