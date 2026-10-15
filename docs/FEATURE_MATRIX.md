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
| H10 premium/discount, equilibrium, dealing range | ❌ | ❌ | not built |
| H11 inducement / internal liquidity | ❌ | ❌ | not built |
| H12 SMT divergence | ❌ | ❌ | needs two reliable feeds; not built |
| H13 Judas swing / Power of Three / AMD | ❌ | ❌ | partly covered by the Asia-range sweep idea only |
| H14 spread/slippage friction | ✅ | ⚠️ assumed spread | Pine cannot read broker spread |
| G sessions (IANA zones, DST, kill zones) | ✅ | ✅ | |
| J HTF bias (H1) | ✅ | ✅ | confirmed H1 bar only |
| J setup: SWEEP_MSS_FVG (bullish/bearish) | ✅ | ✅ | the only setup today |
| J setup: trend continuation | ❌ | ❌ | not built |
| K risk engine, all hard gates | ✅ | ⚠️ lot estimate only | |
| L news lockout | ✅ CSV / Forex Factory | ❌ | |
| M canonical ids, states, lifecycle | ✅ | n/a | |
| Q PC scanner without MT5 | ✅ OANDA v20 | n/a | |
| R chart ↔ scanner parity report | ❌ | ❌ | independent calculations; app says so |
| S real-data backtest report | ⚠️ tooling only | n/a | data needed |
| O Android screens O1–O10 | ⚠️ home, inbox (active/archive), details, settings, watchlist, diagnostics, PC link | | journal analytics (O9) not built |
