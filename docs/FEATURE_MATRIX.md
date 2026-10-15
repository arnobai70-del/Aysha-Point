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
| L news lockout | ✅ CSV / Forex Factory | ❌ | |
| M canonical ids, states, lifecycle | ✅ | n/a | |
| Q PC scanner without MT5 | ✅ OANDA v20 | n/a | |
| R chart ↔ scanner parity report | ❌ | ❌ | independent calculations; app says so |
| S validation report (IS/OOS, walk-forward, breakdowns, $ feasibility) | ✅ tooling (`ayesha report`, `backtest` workflow) | n/a | real data needs the owner's OANDA token secret |
| O Android screens O1–O10 | ⚠️ home, inbox (active/archive), details with MTF, settings, watchlist, diagnostics, PC link, journal + statistics | | no charts in-app; no settings sync to PC |
