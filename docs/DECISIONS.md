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
| 2026-10-15 | **One combined MTF setup per pair**: H4 context and H1 bias/zone explain and can block (both against), M15 makes the setup, optional M5 confirms. Higher timeframes never send their own signals | Mission v0.7.0; avoids duplicate alerts |
| 2026-10-15 | M5 confirmation is **off by default** and changes the entry to a market entry at the confirmation close with a 15-minute expiry; RR is recomputed and must still pass | Untested on real data; the limit-at-FVG entry stays the default |
| 2026-10-15 | M1 scalp mode is refused by the code until it has separate validation evidence | Master plan Z6 |
| 2026-10-15 | A hard READY guard in the scanner sits after the risk engine and ignores config switches (e.g. `strict_news: false`) | Mission v0.7.0 phase 1: READY must be impossible with unverified inputs |
| 2026-10-15 | Phone journal statistics use only results the owner typed for trades they took; signals, tests and backtests never enter them | Master plan Z6/Z9: real vs simulated separation |
| 2026-10-15 | Multi-year backtests run in a manual GitHub Actions workflow with the owner's OANDA token as a repository secret; data is never committed | Container cannot reach OANDA; secret stays in GitHub |

### News intelligence & adaptive capital spec v1.0 (release 0.8.0)

| Date | Decision | Why |
|---|---|---|
| 2026-10-16 | **Capital = equity the owner types from the Exness app** (`ayesha capital`, phone Update capital). Never the data feed's balance (the OANDA practice account is not the broker), never an Exness login | Spec B1/B3, C03; there is no Exness read API without credentials, and credentials are never requested |
| 2026-10-16 | A capital snapshot is valid 24 h (4 h after a deposit, a withdrawal or a change above 25 %); open trades must be confirmed within 12 h; free margin is needed when trades are open. Anything missing or stale is `CAPITAL_*` / `POSITION_STATE_UNVERIFIED` / `MARGIN_UNVERIFIED`, never a guess | Spec B3 "do not falsely verify account state", C02, C06 |
| 2026-10-16 | **Incompatible:** the scanner no longer takes `--equity` for sizing and 0.7.x `equity.txt` is not migrated; the owner types the equity once more (install.bat or `ayesha capital`) | An old number cannot be proven current; `--equity` stays for research commands only |
| 2026-10-16 | Equity never goes to the ntfy.sh relay. PC and phone compare a 16-hex HMAC digest of the amount in cents keyed with the pairing code (`CAPH`); a mismatch is `CAPITAL_MISMATCH` and the phone lot can never exceed the PC lot | Spec C09 and the owner's rule that equity stays off the public relay |
| 2026-10-16 | Unknown risk of an open trade counts as the whole 1 % open-risk cap | Fail closed: the scanner cannot see the owner's stop-loss in Exness |
| 2026-10-16 | Exness contract is confirmed **per pair** (contract size, min/step/max lot, commission, stop level, typical spread); a 0.7.x one-record file counts for EURUSD only | Spec C04: EURUSD values must not be reused for other pairs |
| 2026-10-16 | Margin is checked with leverage capped at 1:200 whatever the account leverage | Exness limits leverage around news; the conservative value never overstates free margin |
| 2026-10-16 | Risk per trade stays a percentage (0.5 %, hard cap 1 %); a higher equity changes the dollar budget and the lot, never the percentage. Config above the cap is `CONFIG_RISK_ABOVE_CAP` | Spec B2; "$20–30 is not a permanent limit" without loosening risk |
| 2026-10-16 | Capital warnings (weekly drawdown ≥4 % on cash-flow-adjusted equity, confirmations expiring within 2 h) are warnings only: they never block a trade and never loosen a gate | Spec B4 asked for warnings after tests; the existing daily 2 % / two-loss / open-risk gates already block |
| 2026-10-16 | News windows by tier: central bank 45/60, CPI/NFP/PCE 45/30, other high 30/30, medium 10/10, low informational. A config or a title can only make a window stricter, never shorter than the legacy 30/30 for high impact | Spec A2, N02 |
| 2026-10-16 | USD top-tier and central-bank events block every enabled pair (incl. EURJPY); other events block only pairs with that currency | Spec N01; USD moves all majors at those releases |
| 2026-10-16 | No cooldown-only release: after the window, two closed M5 bars must show normal spread (at most the larger of 1.5× the 120-minute pre-event baseline and baseline + 0.2 pip, never above the 1.5-pip cap) and range (≤2× baseline), without a shock bar (3×) or whipsaw; a late shock extends the cooldown by 30 min; missing or unclosed bars keep it blocked. The reaction watch is bounded at 120 minutes after the window (`reaction_watch_max_minutes`); past that the event stops blocking and the absolute spread cap, quote age and risk gates decide | Spec A3, N05, N06. The bound stops a session change (e.g. New York open after a London baseline) from blocking a whole day; it is a research default to check with P2 data |
| 2026-10-16 | `UPCOMING` allows a READY only when the setup expires before the next lockout starts (expiry is cut to that time). A READY not yet entered is re-checked on every poll and before a retried push; new news, a phase change or abnormal spread turns it into `INVALIDATED` and the phone is told | Spec N10 |
| 2026-10-16 | Moved, dropped, cancelled and corrected events are kept in a local ledger; the old time keeps blocking, a correction opens a new window, a lowered impact is ignored | Spec N03, N12; a source change must never clear protection silently |
| 2026-10-16 | Actual vs forecast analysis is advisory only (conditional scenarios, no probabilities, never a gate that opens a trade). Forex Factory's weekly export has no verified actual or publication time, so live analysis is `BLOCKED BY DATA` | Spec A5, N07–N09; no scraping or unlicensed feeds |
| 2026-10-16 | **Incompatible:** wire format 4 and signal schema 1.1. Phone 0.5.0 shows READY from a PC without the new keys as UNVERIFIED; PC and phone must both be updated | New news/capital fields are part of the READY contract; no silent protocol change |
| 2026-10-16 | Strategy hash is now `9bb5e8ed5937`; the Pine indicator must be replaced so its VERSION row and alerts match the phone | The hash covers the whole spec, including the new news and capital sections |
| 2026-10-16 | P2 backtests replay a **point-in-time** calendar: rows appear only after `observed_utc`, actuals only after `actual_published_utc`; rows without these are reported (`SCHEDULE_NOT_POINT_IN_TIME`, `ACTUAL_WITHOUT_PUBLICATION_TIME`). Legacy and upgraded modes use the same view and the same candles and signals | Spec A5, I03, I04; zero lookahead |
| 2026-10-16 | No historical calendar provider is integrated; the owner supplies a CSV they are allowed to use (`--news`). Without it the comparison is `NOT RUN (BLOCKED BY DATA)`; news direction is never backtested | No free licensed source with release times and consensus was found; the spec forbids scraping and unlicensed feeds |
| 2026-10-16 | Tier windows and stability thresholds were fixed in `strategy-spec.yaml` before any real-data run; the report never tunes them | Spec P2: no retrospective tuning |

### Hybrid Advanced AI plan v1.0 (release 0.9.0)

| Date | Decision | Why |
|---|---|---|
| 2026-10-16 | **Each plan milestone goes on its own branch and pull request** (`research/v0.9.0`); `main` changes only after the owner approves the merge | Owner's choice on the decision card; plan §14 |
| 2026-10-16 | Research is a subcommand (`ayesha research …`) of the existing CLI, imported only by that subcommand; not a second executable | One install; old argv, help and exit codes untouched (golden CLI fingerprint) |
| 2026-10-16 | Research is **off by default**; its safety locks (no promotion, no live hooks, no ML, no outside model calls, redaction, loopback dashboard) are constants in the config schema, so an edited file can only switch research off | Plan §2.4 and §10.2: a YAML file alone must not be able to loosen anything |
| 2026-10-16 | Dashboard = Python standard library web page on 127.0.0.1 with a one-time key, Host check and GET only; no PySide6 | Plan allows either; this adds no dependency (~200 MB saved) and has no state-changing request to forge |
| 2026-10-16 | No new dependency in 0.9.0 (base stays `pyyaml`, `tzdata`); `[research]`, `[ml]`, `[ui]` extras only when a milestone needs them | Plan §3: keep the base install light |
| 2026-10-16 | Heavy research jobs run in a separate low-priority worker process with memory/CPU limits and a timeout (Windows job object, POSIX nice + RLIMIT_AS), one writer at a time | Plan §2.4: a research crash or memory blow-up must not touch the scanner |
| 2026-10-16 | Datasets are frozen and content-addressed; quality PASS / DEGRADED / REJECTED; REJECTED is never run, DEGRADED only with `--allow-degraded` and labelled; nothing is filled in or repaired; ASK high/low are never invented | Plan §5.1–5.2 |
| 2026-10-16 | Parity statuses: `MATCHED`, `MATCHED_WITH_EXPLAINED_DIFFERENCES` (only sub-point spread rounding of the CSV export), `DIFFERENT` | The CSV export stores whole-point spreads (CP-00 finding 6); any other difference must be shown, not explained away |
| 2026-10-16 | `build-android` no longer runs for `contracts/research/**`, `contracts/version.json` or edits of its own workflow file | Otherwise the merge would publish a phantom APK with a new CI debug signer and force a phone reinstall (CP-00 finding 7) |
| 2026-10-16 | The plan's `ayesha broker` is read as the existing `ayesha confirm-broker`; `ayesha.__version__` corrected to the package version | CP-00 findings 1 and 3 |
| 2026-10-16 | The golden fingerprint of 0.8.0 (`tests/research/fixtures/legacy-golden-0.8.0.json`) may only be regenerated for an owner-approved change of the legacy path, recorded here | Plan §13: an unexpected legacy difference fails the release; it is never fixed by relabelling |

## Delivery modes
- **Mode B, PC scanner (canonical, free):** OANDA data → rules + all gates → signed ntfy push → AYESHA app inbox.
  Needs the PC on and online; the app shows PC offline / stopped / data stale.
- **Mode A, TradingView bridge (optional):** indicator `alert()` → TradingView app push → AYESHA app reads it as
  CHART_CANDIDATE. Works only on plans with technical alerts.
