# Master-spec rule coverage (implemented vs not)

"Implemented" means objective code with a threshold in `contracts/strategy-spec.yaml` and tests. Nothing here claims to
see bank orders; "institutional" items are price-behavior hypotheses only.

| Spec item | Python scanner | Pine chart | Notes |
|---|---|---|---|
| H1 confirmed swings (left/right bars) | ✅ | ✅ | detected only after right bars close |
| H2 BOS / H3 CHoCH / MSS with displacement | ✅ | ✅ | |
| H4 liquidity: PDH/PDL, Asia H/L, swing, EQH/EQL | ✅ | ✅ | |
| H5 sweep-and-reclaim vs breakout | ✅ | ✅ | |
| H6 displacement (body × ATR, body/range) | ✅ | ✅ | |
| H7 FVG with mitigation/invalidation lifecycle | ✅ | ✅ | |
| H8 inversion FVG, BPR | ❌ | ❌ | not built |
| H9 order blocks, breakers, mitigation blocks | ❌ | ❌ | not built |
| H10 premium/discount, equilibrium, dealing range | ⚠️ H1 range zone shown | ❌ | explained in every signal (`H1_ZONE`); not scored or gated yet |
| H11 inducement / internal liquidity | ❌ | ❌ | not built |
| H12 SMT divergence | ❌ | ❌ | needs two reliable feeds; not built |
| H13 Judas swing / Power of Three / AMD | ❌ | ❌ | partly covered by the Asia-range sweep idea only |
| H14 spread/slippage friction | ✅ | ⚠️ assumed spread | Pine cannot read broker spread |
| G sessions (IANA zones, DST, kill zones) | ✅ | ✅ | |
| J HTF bias (H1) + last H1 BOS/CHoCH | ✅ | ✅ bias only | confirmed H1 bar only |
| J H4 context | ✅ (blocks when H1 and H4 both oppose) | ✅ table row | context only; same confirmed-bar idiom in Pine |
| J M5 confirmation (optional, off by default) | ✅ | ❌ | `mtf.confirm_timeframe: M5`; market entry at the confirmation close, short expiry |
| J M1 scalp | ❌ refused | ❌ | disabled until it has its own validation evidence |
| J setup: SWEEP_MSS_FVG (bullish/bearish) | ✅ | ✅ | the only setup today |
| J setup: trend continuation | ❌ | ❌ | not built |
| K risk engine, all hard gates | ✅ | ⚠️ lot estimate only | |
| L news lockout | ✅ CSV / Forex Factory, tiered state machine (see below) | ❌ | Pine cannot see the calendar; the phone blocks chart candidates during a PC news window |
| M canonical ids, states, lifecycle | ✅ | n/a | |
| Q PC scanner without MT5 | ✅ OANDA v20 | n/a | |
| R chart ↔ scanner parity report | ❌ | ❌ | independent calculations; app says so |
| S validation report (IS/OOS, walk-forward, breakdowns, $ feasibility) | ✅ tooling (`ayesha report`, `backtest` workflow), feasibility $20–$5,000, adaptive account | n/a | real data needs the owner's OANDA token (secret or `backtest-local.bat`) |
| O Android screens O1–O10 | ⚠️ home, inbox (active/archive), details with MTF and news, settings with Update capital, watchlist, diagnostics, PC link, journal + statistics | | no charts in-app; equity is typed on both sides and compared by digest, not synced |

## News intelligence & adaptive capital spec v1.0 (release 0.8.0)

| Spec item | PC scanner | Phone | Notes |
|---|---|---|---|
| A1 three layers: protection, notices, numbers analysis | ✅ | ✅ shows all three | only protection can block; notices and analysis never open a trade |
| A2 state machine (UPCOMING, PRE_EVENT_LOCKOUT, EVENT_LIVE, POST_EVENT_COOLDOWN, REACTION_WATCH, CLEAR, NEWS_UNVERIFIED) | ✅ `news/guard.py` | ✅ phase on READY (`NP=`) | `NEWS_UNKNOWN` of the spec maps to `NEWS_UNVERIFIED` |
| A2 tiered windows, overlaps, strictest wins, legacy 30/30 as minimum | ✅ | n/a | `news.tiers` in the spec; research defaults, not optimized |
| A2 reschedule / cancel / correction ledger | ✅ `news/ledger.py` | n/a | old time keeps blocking; correction opens a new window |
| A3 post-news stability on closed M5 bars (spread, range, shock, whipsaw, gaps) | ✅ | n/a | bounded at 120 min after the window |
| A3 READY re-checked before entry and before a retried push | ✅ `INVALIDATED` | ✅ cancel notice | |
| A4 notices: upcoming, entries blocked, post-news summary; open-trade advice | ✅ signed `AYESHA NEWS` | ✅ news watch card on the home screen | text tells the owner to check stop-loss and gap risk; never closes a trade |
| A5 provenance, coverage, age, clock drift | ✅ | ✅ calendar age on READY | Forex Factory weekly export only; no historical provider |
| A5 actual vs forecast, conditional scenarios | ⚠️ code ready, live input **BLOCKED BY DATA** | ✅ shows the PC's conditional scenario text | FF export has no verified actual or publication time |
| A5 anti-lookahead in replays | ✅ `backtest/asof.py` | n/a | rows after `observed_utc`, actuals after `actual_published_utc` |
| B1 owner-entered Exness equity, Standard and Cent | ✅ `ayesha capital` | ✅ Update capital | never the OANDA balance, never a login |
| B2 sizing from verified equity, floor to step, 1 % hard cap, margin at ≤1:200 | ✅ | ✅ phone lot ≤ PC lot | stop is never narrowed to fit 0.01 lot |
| B2 per-pair Exness contract | ✅ `confirm-broker` per pair | n/a | EURUSD values never reused |
| B3 snapshot age, open-trade confirmation, free margin, PC/phone digest | ✅ | ✅ `CAPITAL_MISMATCH` | equity never on the relay |
| B4 deposits/withdrawals not P&L; weekly drawdown and expiry warnings | ✅ warnings only | ⚠️ PC heartbeat capital status only | warnings never block or loosen a gate |
| B5 [Update capital] [Confirm open positions] [View risk history] | ✅ `ayesha capital`, `--positions`/`--no-positions`, `--history` | ✅ Update capital | no risk history screen on the phone yet |
| P2 legacy 30/30 vs upgraded on the same candles, point-in-time, OOS, CIs, sample sizes | ✅ tooling | n/a | **NOT RUN on real data**: needs OANDA history and a permitted historical calendar |
| P2 feasibility at $20/$25/$30/$100/$500/$1,000/$5,000 and adaptive account | ✅ tooling | n/a | hypothetical replay at assumed contract values, not a forecast |

## Hybrid Advanced AI plan v1.0 (release 0.9.0 research foundation, 1.0.0 Strategy Lab; off by default)

| Plan item | Research plane | Live path | Notes |
|---|---|---|---|
| §2.4 isolation contract (off by default, scanner never imports research, separate worker, read-only legacy DB) | ✅ | unchanged | `check_research_isolation.py` in CI; golden fingerprint T06 |
| §4 namespaced contracts (`research.*/1`) | ✅ 9 schemas (comparison added in 1.0.0) | unchanged (spec 0.4.0, schema 1.1, wire 4) | candidates `executable: false`, never READY |
| §5.1–5.2 frozen datasets with quality gate (PASS / DEGRADED / REJECTED) | ✅ OANDA practice or exported CSV | n/a | ASK high/low never invented; nothing filled in |
| §5.3–5.4 research folder and `research.db` (migrations, audit, backup/restore) | ✅ | `ayesha.db` only read (mode=ro) | `feature_sets`, `model_registry`, `model_approvals` not created yet |
| §6.1 Baseline A (SWEEP_MSS_FVG frozen) + parity with `ayesha backtest` | ✅ | n/a | real-data run **PENDING OWNER** |
| §6.1 Control B, Experimental C, strategy registry | ✅ B London ORB, C H1/H4 trend, built-in registry | n/a | Experimental D not built (one experiment per milestone); real-data run **PENDING OWNER** |
| §6.3 common runner, causality, intrabar ambiguity, cost variants, portfolio simulation | ✅ legacy fills, flags, 4 sensitivity models, live risk engine on dynamic equity | n/a | news not modelled; contract values ASSUMED |
| §6.4 after-cost metrics and side-by-side comparison | ✅ `research lab`, `compare`, dashboard Strategy Lab | n/a | ranking only with 100+ closed trades per strategy |
| §7 regimes, strategy × regime matrix, historical news | ❌ | n/a | v1.1.0; historical news **BLOCKED BY DATA** |
| §8 ML lab | ❌ | n/a | v1.2.0, only with enough validated real data |
| §9.1 Windows dashboard | ⚠️ Overview, Data, Runs, Strategy Lab, Live scanner (read-only), Diagnostics, Settings | n/a | no Replay chart / News context pages yet; GET only |
| §9.2 Android research tab | ❌ | n/a | v1.3.0 |
| §10 research CLI and config | ✅ `ayesha research …`, `research/config.yaml` | old commands unchanged | safety locks are schema constants |
| §12 T01–T12 | ⚠️ T01, T03, T05–T08, T10 CI; T02, T04, T09, T12 partial; T11 n/a | | [RESEARCH_ACCEPTANCE.md](RESEARCH_ACCEPTANCE.md) |

