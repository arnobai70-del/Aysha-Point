# AYESHA Master Plan — Review

Reviewed: AYESHA-FX-MASTER-001 v1.0 (uploaded 2026-10-14). This is a review, not legal or financial advice.

## What the plan proposes

A manual-execution decision-support tool for forex intraday trading, built from three parts that share one versioned rule contract:

1. **Windows PC scanner** (Python, PySide6, FastAPI, SQLite) that reads a legitimate feed (ideally a local MT5 terminal), runs formalized ICT/SMC rules (swings, BOS/MSS, liquidity sweeps, FVG, OB, PD arrays, sessions, news, spread), scores setups, and runs a strict risk engine that outputs `NO_TRADE` whenever lot size, data, news or cost checks fail.
2. **One Pine v6 TradingView indicator** that independently recomputes the same rules on chart data, with honest parity labels (`MATCHED` / `PARTIAL` / `UNVERIFIED` / `MISMATCH`).
3. **Android 13 app** (Kotlin/Compose) that receives FCM pushes, syncs details from the PC over Tailscale/LAN, and holds settings, calculator and journal.

It never places orders, never stores broker credentials, and treats "NO TRADE" as a normal output. The spec is unusually honest about platform limits (Pine can't read the PC, banks' intent can't be seen, scores aren't probabilities).

## Biggest gaps and risks

### 1. The capital makes the system mostly unusable as specified (highest risk)
2,000–3,000 BDT is about $16–25. On Exness Standard the minimum is 0.01 lot (~$0.10/pip on EURUSD). A normal 8–15 pip structural stop costs $0.80–1.50, which is 3–9% of equity, against a 0.5% rule ($0.08–0.13). The plan's own section K example proves this: almost every A+ setup will correctly come out `NO_TRADE: MIN_LOT_EXCEEDS_RISK`.
Options: (a) a **Standard Cent** account (0.01 cent lot ≈ $0.001/pip, makes 0.5% risk feasible), (b) more capital, or (c) run demo/paper only until the edge is proven, which the plan requires anyway. This should be decided before anything else, because it changes the symbol/lot scheme in the risk engine.

### 2. Regulatory (must verify yourself)
If you are a Bangladesh resident: under the Foreign Exchange Regulation Act 1947, sending money abroad for speculative online forex/CFD trading is generally not permitted, and Bangladesh Bank has issued public warnings about online forex platforms. Exness is not licensed by a Bangladeshi regulator. This is the most serious real-world risk and it sits outside the software. Please confirm your legal position (ideally with a local professional) before any real-money use. A demo-only research tool carries none of this risk.

### 3. Strategy edge is unproven, and ICT/SMC is hard to formalize
Section H does a good job turning terms into algorithms, but there are dozens of tunable parameters (pivot bars, sweep penetration, displacement thresholds, FVG minimums, OB lookback, score weights). With few A+ signals per month, getting statistically meaningful results takes a long time and overfitting risk is high. Nothing in the plan's UI, app or chart is worth building if the rule engine shows no edge after costs on out-of-sample data. The milestones put Pine (M3) and Android (M4) before the real validation (M6). I'd reorder.

### 4. Scope is very large for one person
Three codebases in three languages (Python, Pine, Kotlin), plus FCM, Tailscale pairing, a companion chart, parity tooling and a code generator from YAML to Pine. Implementing every ICT primitive twice (Python and Pine) and keeping them in sync is a large ongoing cost.
Simplifications: use **Telegram** (already listed as a backup) for phone alerts in v1 instead of a custom Android app; keep Pine to a visual helper (sessions, PDH/PDL, FVGs, swings) rather than a full rule-parity engine; make the PC dashboard the source of truth.

### 5. Technical gaps
- **News calendar source** is unresolved. Strict mode blocks all trades without it, so it's a hard dependency. Free options are limited and scraping (e.g. ForexFactory) raises terms-of-use issues.
- **Historical bid/ask data**: MT5 gives decent bar history but limited tick/spread history. Realistic cost-aware backtests need variable spread data. Plan where this comes from.
- **Feed mismatch**: TradingView's OANDA/FX feed differs from Exness prices, so swings and FVGs will often differ by a pip or a bar. Expect `PARTIAL`/`MISMATCH` often; parity tolerance needs measuring early.
- **MT5 Python package** is Windows-only and talks to a running, logged-in terminal. That fits the design, but the terminal must stay open, and `order_send` exists in the library, so the "no order code" test is a good idea and should be in CI from day one.
- **"AI" naming**: the engine is rule-based. That's a strength, but the name may set wrong expectations.
- **PC uptime**: London + NY sessions in Dhaka time run roughly 13:00–02:00. The PC must be on and awake through that window.

### 6. Trading-risk points the plan handles well
Fail-closed gates, no rounding up lot size, daily loss pause, no martingale/grid, scores not called probabilities, observed vs inferred labels, append-only signal history. Keep all of these.

## Recommended first concrete build step

A small **read-only feasibility spike in Python on the Windows PC**, before any Pine or Android work:

1. Connect to the local Exness MT5 terminal (read-only), pull `symbol_info` (contract size, min/step lot, tick value) for the 6 pairs, plus 1 year of M5/M15/H1 EURUSD bars and current spread.
2. Implement only the section K risk calculator with the hard `NO_TRADE` gates, plus unit tests, including the $25 case.
3. Run it on your real account specs (Standard and, if possible, a Standard Cent demo) for typical stop sizes.

This answers the decisive question first (can this capital trade at all under 0.5% risk) and builds the foundation every later part needs. Next would be the rule primitives plus a bar-by-bar replay backtester on EURUSD, and only if that shows an edge after costs, the alert path and the chart indicator.
