# AYESHA — AI Forex Trading Assistant
## A–Z Master Project Specification, Architecture, Rulebook & Mandatory Development Checklist

**Document ID:** AYESHA-FX-MASTER-001  
**Version:** 1.0 — Planning Baseline  
**Date:** 2026-10-15  
**Status:** Specification only. Development NOT authorized until owner approval.  
**Language:** বাংলা (প্রধান), English (technical identifiers)  
**Project owner:** Personal-use trader  
**Platforms:** TradingView Basic/free on PC; Windows PC-based scanner; custom Android 13 app; Exness Standard USD account; GitHub repository to be supplied by owner.

> **মূল লক্ষ্য:** বিশৃঙ্খল সিগন্যাল-বট নয়। ICT + SMC + প্রতিষ্ঠানের সম্ভাব্য আচরণ *সম্পর্কিত বাজারভিত্তিক অনুমান* + সেশন/নিউজ/স্প্রেড + কঠোর risk sizing দিয়ে খুব বাছাইকৃত forex trading setup বের করা। ফোনে সতর্কতা, PC TradingView chart-এ ব্যাখ্যামূলক মার্কিং; সব ট্রেড **মানুষ নিজে** Exness-এ নেবে। এক দিন কোনো ট্রেড না হলেও সমস্যা নেই। নিশ্চিত লাভ বা ‘perfect’ signal বলে কিছু নেই।

---

# A. Owner's Non-Negotiable Requirements

1. কোনো VPS বা নিজস্ব hosted backend থাকবে না। **Local Windows PC** হবে scanner/analysis engine-এর প্রধান host; TradingView indicator চলবে TradingView-এর Pine execution environment-এ এবং PC browser-এ দেখা যাবে; ফোনে Android app ইনস্টল থাকবে।
2. Android **13** প্রাথমিক লক্ষ্য; Play Store প্রকাশ আবশ্যক নয়, signed APK দিয়ে ব্যক্তিগত ব্যবহারে ইনস্টল করা যাবে।
3. TradingView **free account**-এ একটি composite Pine indicator থাকবে; অতিরিক্ত indicator নির্ভরতা থাকবে না। প্ল্যানভেদে chart/alert quota পরিবর্তন হতে পারে; ব্যবহারকারীর পরিকল্পনায় যাচাই করতে হবে।
4. ফোন অ্যাপ এবং chart একই strategy ruleset, symbol map, thresholds, config version এবং signal IDs ব্যবহার করবে। কিন্তু **TradingView Pine-এ PC-এর arbitrary external signal/AI result সরাসরি inject করা যাবে না**—তাই 100% external-to-Pine mirroring প্রতিশ্রুতি নয়। Pine-এর নিজস্ব chart-data-based rendering + parity check হবে; exact off-platform signal view থাকবে PC app-এর নিজস্ব chart/overlay-তে।
5. Market analysis manual trigger এবং automatic session scanning—উভয়ই; 24/7 PC uptime থাকলে operating hours অনুযায়ী নিরবচ্ছিন্ন scan; **PC বন্ধ থাকলে নতুন PC-generated signal হবে না**। Forex সাধারণত সপ্তাহের পাঁচ দিন প্রায় ২৪ ঘণ্টা লেনদেন হয়; weekend/holiday ব্যতিক্রম।
6. Broker: **Exness Standard**, হিসাবের মুদ্রা USD; অন্য broker/account type নির্বাচন বা সংযোজন ভবিষ্যৎ-সক্ষম করে রাখতে হবে।
7. ছোট capital: আনুমানিক ২,০০০–৩,০০০ টাকা সমমূল্যের USD, তবে সফটওয়্যারে প্রকৃত available USD equity হাতে সেট হবে। Minimum lot বা spread-এর কারণে safe trade সম্ভব না হলে **NO TRADE** বাধ্যতামূলক।
8. Prioritize **intraday**, scalp optional এবং default OFF; only enable with separate historical & forward evidence. No pressure to trade daily.
9. ICT/SMC-এর detailed rule-driven price-action reading, structure, liquidity, displacement, FVG, order block, session, HTF/LTF alignment, macro-news, correlation, risk, market-behavior inference থাকবে। Indicator-only crossover bot নয়।
10. Manual execution ONLY. কখনো Exness order place, stop modify, অথবা balance withdraw করবে না। Account login/Gmail/password সংগ্রহ নিষিদ্ধ।
11. Strong filter: No signal if missing price data, stale quote, unknown spreads, major news status unknown under strict mode, over-risk, or discordant chart/engine state.
12. GitHub repository owner দেবেন। কোড, spec, docs, tests, configuration examples, releases পরিবর্তিত হলেই Git commit/push হবে—secrets কখনো repository-তে নয়।
13. এখন **কোড শুরু নয়**। এই নথি পর্যালোচনা/অনুমোদনের পর বাস্তবায়ন।

# B. What Is Realistically Possible — Technical Reality Check

| চাওয়া | বাস্তব সমাধান | সীমা/নির্ভরতা |
|---|---|---|
| PC TradingView-তে Entry/SL/TP | Pine Script v6 overlay-তে setup zone, levels, explanations | Pine TradingView-এর নিজস্ব feed ও execution rules ব্যবহার করে; PC engine থেকে arbitrary signals pull করতে পারে না |
| PC scanner automatic market monitor | Local Python worker + supported market data feed + SQLite | PC running, net stable, feed access required |
| Android 13 app notification | Local scanner → Firebase Cloud Messaging (FCM) → phone | নিজস্ব VPS লাগবে না, কিন্তু Google-এর third-party push infrastructure লাগে; delivery timing guaranteed নয় |
| Phone app full signal history/details | App local Room DB; PC-এর local FastAPI service via **private Tailscale network**/trusted LAN | Both paired; remote details sync requires PC reachable; phone offline-এ cached signals পাওয়া যাবে |
| Chart এবং app একই signal | Shared formal rulebook; matching rule version; scanner-generated canonical signal ID; Pine-side matching candidate ID/parameters | Feed differences, candle times, off-platform news/costs, Pine limits হলে chart/app mismatch হতে পারে; warning shown |
| **Exact 1:1 scanner signal visually on chart** | In the **companion PC dashboard chart** rendered from PC canonical signals (e.g., local chart), exact | TradingView website-এর Pine chart-এ external arbitrary signals বসানো নয়; exact TV chart demand হলে supported API/product feasibility re-evaluate |
| Forex liquidity / big-bank psychology | Observable proxy events from candle/quoted-market data; measured uncertainty | Bank-এর প্রকৃত proprietary order flow, stop inventory বা intent দেখা যাবে না; manipulation দাবি করা যাবে না |
| 'Never miss signals' | Heartbeat, error monitor, reconnect, replay, alert queue | Network/device/offline state-এ zero-miss impossible |

**Critical design decision:** Central source of truth = PC Signal Registry (SQLite); Android follows it. Pine indicator **independent deterministic chart analyzer** with shared algorithm definitions, not a remote signal client. Each signal shows `MATCHED`, `PARTIAL`, `UNVERIFIED`, or `MISMATCH` where comparison is possible. If direct TradingView overlay cannot truthfully display a scanner result, app must say so; never silently fabricate chart alignment.

# C. Success Criteria and Explicit Non-Goals

### Success =
- Validated non-repainting (on confirmed bars) rules detect limited high-quality *candidate* setups with full rationale.
- User sees: pair, direction, exact proposed entry or zone, invalidation/SL, TP1/TP2, RR **after estimated cost**, calculated safe lot if possible, max $ loss, session, expiry, and reason.
- Mobile notification and chart (when underlying rule/data matches) are easy to cross-check using the same timestamp, symbol and rule-version fingerprint.
- App warns before over-risk and shows NO_TRADE when appropriate.
- Reproducible tests/backtests/data provenance—not guessed accuracy.

### Non-goals =
- Guaranteed accuracy/profit, '100% institutional knowledge', hidden bank orders, broker manipulation detection with certainty.
- Automated copy trading, broker password storage, binary options, martingale, grid, revenge trade, auto increase risk after loss.
- 24/7 detached cloud operation without an always-on computing device or third-party infrastructure.
- Unauthorized scraping of TradingView price feeds or breaking platform terms.

# D. System Components and Communication

```text
                   LEGITIMATE MARKET DATA FEED
                (MT5 terminal/broker feed or licensed API)
                              |
                              v
Windows PC ---------------------------------------------------------------
  1) Data Ingestion & Normalizer (UTC candles, bid/ask, spread, quality)
  2) Market Context Engine (sessions, news, trends, volatility)
  3) ICT/SMC Rule Engine + Scoring & Reason Builder
  4) Risk Engine (USD equity, broker contract specs, safe lot, margin)
  5) Signal State Machine + Registry + SQLite event journal
  6) Local Windows UI (pair list, chart, signals, settings, logs)
  7) Local FastAPI sync endpoint (localhost/LAN/Tailscale private only)
  8) FCM sender [OPTIONAL; uses Google cloud, NOT self-hosted VPS]
          |                                    |
          | canonical signal                    | notification ID/event
          v                                    v
   Companion local chart                  Android 13 App
   [EXACT scanner levels]                [inbox, details, settings, journal]
                                               |
                        Private sync (Tailscale or trusted Wi-Fi)
                                               |
                         Android cached signals / state updates

TradingView PC browser:
   Pine Script v6 overlay -> chart-native candidate geometry/Entry/SL/TP
   Same formal rules & config fingerprint -> compare to canonical signal
   NOTE: NO arbitrary external PC/Android data fetch from Pine.
```

**One unified product** does not imply one executable or remote Pine API. Product consists of three cooperating deliverables: (a) `ayesha-desktop.exe` scanner, (b) `Ayesha Smart Money.pine` indicator, (c) `ayesha-android.apk` app. One GitHub monorepo and one common versioned strategy contract; data feed/source alignment checked explicitly.

### PC online / offline matrix

| PC | Internet | Phone | Expected |
|---|---|---|---|
| ON | ON | online | scanner active, new signals, FCM, private sync |
| ON | ON | offline | scanner creates signals; phone downloads queued history on reconnect; cannot guarantee delayed FCM |
| ON | OFF | online | stale-feed block, no new trustworthy signals; journal stays local |
| OFF | any | online | no scanner signal generation; app last-sync banner & cached history |
| OFF | any | offline | previously cached records only |

**Do not** use Android WorkManager as a guaranteed sub-minute always-on market scanner; periodic tasks are inexact and limited. **Do not** silently rely on TradingView free alerts for 24h scanner continuity. <https://developer.android.com/develop/background-work/background-tasks/persistent/getting-started/define-work>

# E. Technology Stack — Deliberately Simple

| Layer | Decision | Why |
|---|---|---|
| Strategy & Scanner | Python 3.12+ | Data handling, testing and rule portability |
| Local PC UI | PySide6 (Qt) | Native compact Windows dashboard, installer possible |
| Local internal API | FastAPI + Pydantic | Typed signal contracts; private-only access |
| Local DB | SQLite with WAL and migrations | No DB/VPS administration |
| Data | Optional local MetaTrader 5 terminal adapter **if account is MT5**, otherwise officially licensed broker/data provider | Legal/reliable access; versioned data quality |
| Chart overlay | Pine Script **v6** | TradingView integration; 1 indicator |
| Android | Kotlin + Jetpack Compose (Android 13 support) | Native notification performance, no iOS baggage |
| Android persistence | Room / encrypted prefs | Offline inbox; safe settings |
| Delivery | FCM with Google project + authenticated private sync | No owned VPS, but external push service required |
| Private networking | Tailscale preferred; paired LAN as fallback | Avoid exposed public IP / router ports |
| QA | pytest, hypothesis/property tests, Pine manual check fixtures, Android unit/UI tests | Rule parity and regression prevention |
| Source / CI | GitHub monorepo + GitHub Actions | Releases, change tracking, security scans |
| Packaging | PyInstaller Windows build; signed APK Android | User installs locally |

**External cost disclaimer:** VPS not needed, but a licensed realtime market feed, certain TradingView alerts, VPN features, or third-party push/data providers may involve accounts/fees. Current entitlement/pricing must be verified before selecting vendor.

# F. Supported Markets and Profiles

**Initial watchlist:** `EURUSD`, `GBPUSD`, `USDJPY`, `AUDUSD`, `USDCAD`, `EURJPY`. Owner edits pairs and enables/disables them individually. Low spread liquid majors preferred; no blanket assertion that any pair is always cheap. Later add `NZDUSD`, `USDCHF`, `EURGBP`; avoid exotics by default. `XAUUSD`, `USOIL`, `BTCUSD` initially OFF per capital policy (not a claim they are inherently untradeable for everyone).

**Timeframes / role:**

- Weekly/Daily (optional): broad high/low ranges, macro liquidity boundaries.
- H4/H1: primary intraday higher-timeframe directional context and dealing range.
- M15: setup, important raid/displacement/PD arrays and session model.
- M5: entry confirmation/trigger (when data precise enough).
- M1: optional scalp test profile only, NOT primary intraday.

**Trade profiles:**

| Profile | Default | Usage | Risk |
|---|---|---|---|
| Intraday A+ | ON | Confirmed H1/H4 bias + M15 setup + M5 trigger | Small fixed fractional |
| Session reversal | ON but stringent | Confirmed liquidity sweep + displacement + structure shift | Very selective |
| Continuation | ON but stringent | Pullback in HTF direction + mitigated zone + market expansion | Very selective |
| Scalping | OFF | Only after separate quality evaluation; spread sensitivity high | Must not auto-raise risk |

# G. Session Engine (Four Sessions)

Sessions: **Sydney, Tokyo, London, New York**, plus overlaps. All stored UTC; display `Asia/Dhaka` in UI and optional IANA exchange-local times. Session windows **must be calculated via timezone databases**, not hardcoded UTC+offset year-round (London/New York/Sydney DST adjustments and FX broker-specific trading hours matter). Use actual market calendar: weekend closure, holidays, rollover and data-feed maintenance.

Session metrics each day: opening range, prior session high/low, Asian high/low, current session high/low, sweep/reclaim, range expansion, session direction, relative volatility, unusual spreads. Optional ICT-style London / NY 'kill-zone' windows **configurable per strategy and timezone**; never treat named windows as guaranteed behavior. Sydney-low-liquidity conditions and New York/London overlap have separate thresholds only after testing.

At each new session: refresh context, validate yesterday/weekly levels, carry over valid setup states, invalidate expired signals, avoid false duplicate notifications. Report `OPEN`, `THIN`, `ROLLOVER`, `CLOSED`, `DATA_STALE`.

# H. Price-Action Primitive Definitions — Formalized and Testable

All subjective ICT/SMC vocabulary must become measurable algorithms with controlled tolerances and published examples. Use `pip_size` and volatility-normalized thresholds where appropriate; no magic fixed 5-pip rule across every asset.

## H1. Swing highs/lows / protected pivots
- A **confirmed swing high** at candle `k` occurs only after `leftBars` earlier highs and `rightBars` later highs are available and the center high meets a deterministic tie-break rule; similarly swing low.
- Parameters `leftBars=3`, `rightBars=3` for illustrative defaults (optimize only in training window); pivot recognized **at k + rightBars**, not retroactively traded at k.
- Distinguish **external swing** (H1/H4 structural extremes) from **internal swing** (M5/M15 pullback points). Label HH/HL/LH/LL once confirmed.
- Price vs wick break choice explicitly config: structure break needs close beyond pivot + buffer; liquidity sweep uses wick-and-reclaim pattern.

## H2. BOS (Break of Structure)
- Bullish: established bullish/continuation structure, **confirmed candle close** above valid structural swing high with buffer; bearish inverse.
- Record broken level, break candle ID, body strength, relative ATR and close displacement; trivial one-tick breach blocked.
- BOS is context, not automatic trade instruction.

## H3. CHoCH / MSS (Market Structure Shift)
- CHoCH: first credible break against preceding structural direction; requires valid predecessor structure.
- MSS: CHoCH **plus displacement strength**, time window, liquidity context and follow-through definition. Reversal confirmation is provisional until continuation/other conditions.
- Multiple naming conventions exist; this system uses **these exact operational definitions** and documents them for chart/backend parity.

## H4. Liquidity pools (heuristic)
- Prior day/week highs/lows; Asia range extremes; session highs/lows; equal highs (`EQH`) and equal lows (`EQL`) within `max(pip_tolerance, ATR_factor)`; meaningful prior swing zones; conspicuous round numbers as secondary context only.
- Assign age, touch count, freshness, range context, distance to price; discard weak/old pools by rules.
- A visible equal-high zone **does not prove stop orders exist there**.

## H5. Liquidity sweep / raid and failed breakout
- Bullish reversal candidate: price prints below a recognized sell-side level by minimum penetration, then **closes back above** it within a defined number of bars; bullish displacement/MSS required subsequently.
- Bearish inverse above buy-side level. Track penetration, wick ratio, subsequent candles, time-to-reclaim; do not claim confirmed bank stop hunt.
- Break that keeps closing outside the zone is not a sweep-with-reclaim; classify genuine breakout candidate / `WAIT`.

## H6. Displacement / expansion
- Large directional body relative to ATR or rolling body median, body-to-range fraction above threshold, close position near candle end, and optional follow-through.
- Distinguish from one-off high-impact news spikes. High spread/gap flags invalidate otherwise attractive displacement.

## H7. FVG (3-candle Fair Value Gap)
- On closed candles `A, B, C`: **bullish** if `low(C) > high(A)` by at least min tick/pip/ATR-normalized gap; zone `[high(A), low(C)]`. **Bearish** if `high(C) < low(A)`; zone `[high(C), low(A)]`.
- Only valid with displacement and setup context; track creation, midpoint (consequent encroachment), partial/full mitigation, fill, expiry and invalidation.
- FVG is a chart price-imbalance proxy, **not direct proof of unfilled institutional orders**.

## H8. Inversion FVG (IFVG), BPR and rebalance
- `IFVG`: previously validated FVG decisively violated/closed through; optionally flips zone role **only after retest + confirmation**.
- `BPR` (Balanced Price Range): price-zone overlap between qualifying opposing FVGs within maximum lookback; requires temporal/structural consistency; more context, not instant entry.
- Record gap-fill % and reject zones that became fully obsolete before trigger.

## H9. Order Block (OB) / Mitigation / Breaker
- Candidate bullish OB: last qualifying bearish candle or defined cluster preceding **confirmed bullish displacement + BOS/MSS**, within agreed maximum lookback; bearish inverse.
- Zone either full candle range or body (configurable and frozen by profile). Freshness, number of taps, impulse strength, position in HTF range scored.
- Mitigation: revisit without invalidation; breaker: failed qualified OB with close beyond invalidation + subsequent retest—**not** arbitrary reversal signal.
- Do not call any opposite-color candle an OB. A chart OB is an **analytical model**, not an observed bank order.

## H10. Premium, discount, equilibrium, dealing ranges
- Form dealing range only from confirmed meaningful HTF structural swing high/low; midpoint = 50% (`EQ`).
- Longs prefer discount and shorts premium **as a preference**, while continuation profile may allow context-specific exceptions if explicitly backtested.
- OTE-style retracement band (e.g., 62–79%) is **optional** confluence and never treated as guaranteed institutional entry. Stale or redefined range invalidates related setups.

## H11. Inducement / internal liquidity
- Model as prior minor countertrend swing that attracts an earlier entry ahead of major HTF zone; only score as possible **trap susceptibility** under explicit conditions.
- Do not assert visibility into the intention of market makers. Need sweep/structure evidence before confirmation.

## H12. SMT divergence / intermarket confirmation
- Optional synchronous comparison of related pairs (`EURUSD` vs `GBPUSD`) or inverse comparison to `DXY`, with timestamps/timezone/bar alignment and data availability check.
- Example: one pair forms a new high beyond confirmed comparable high while related pair fails; label **possible relative divergence**, not certain reversal.
- Different instruments/pair correlations can change; never hard gate without validated research and real comparable feed.

## H13. Judas swing, Power of Three, AMD
- `Accumulation → possible stop run/manipulation → expansion/distribution` as **scenario labels**, backed by defined opening range, pre-session compression, raid and confirmed displacement.
- “Manipulation” is jargon only; cannot infer malicious acts or identify institutions from candles.
- Failed AMD/Judas hypothesis remains logged (not retrospectively erased).

## H14. Market microstructure and execution friction
- Distinguish bid vs ask price, real-time spread, tick/pip size, leverage/margin, quote staleness, rollover widening, slippage assumptions, order type, broker contract rules. If only candles without bid/ask available, execution-cost-sensitive signals remain **unverified**, not executable recommendations.

# I. Institutional Behavior / Market Psychology Engine — Ethical and Honest Inference

**Goal:** Retail trader avoids common false-break/low-liquidity situations and follows an observable directional trend where evidence supports it. **Not goal:** read the mind of banks, prove stop hunts, know pending institutional volume from retail OHLC.

Heuristic contexts scored with explicit uncertainty:

1. **Liquidity-target hypothesis:** Price approaching prior day/week high/low/EQH/EQL, but require confirmation beyond location.
2. **Breakout-trap risk:** Wick through level then close back inside; compare volume only if feed volume meaningful, and do not confuse OTC tick volume with centralized actual traded volume.
3. **Trend absorption / exhaustion proxy:** repeated failed closes, shrinking progress despite range expansion, wick changes; label `POSSIBLE`, no guaranteed large-player absorption.
4. **Session handoff:** Asia→London, London→NY high/low interactions and liquidity; session scheduling is informative not causal proof.
5. **News positioning:** no entry into scheduled high-impact volatility by default; news can overwhelm technical pattern.
6. **Large-player constraints:** institutions can hedge, market-make, route client orders and act for non-directional reasons; avoid monolithic “banks will buy here” narratives.
7. **Retail behavioral safeguards:** chasing an extended move, FOMO entry after late displacement, increasing risk after two losses, moving SL farther, trading outside selected sessions trigger user-facing warnings and not auto trades.
8. **Macro context (optional):** interest-rate surprises, scheduled central-bank decisions, CPI/employment, risk-on/risk-off measured with verified data, weekly COT only as lagged background (not real-time bank orders).

Every narrative must be tagged `OBSERVED_DATA`, `RULE_BASED_INFERENCE`, or `UNAVAILABLE`. Example:

> Observed: London candle briefly swept Asia low and closed back inside. Inference: possible failed breakdown. Unavailable: actual bank stop order locations.

# J. Multi-Timeframe Decision Pipeline

```text
Price/quote integrity validated?
  NO -> DATA_STALE / NO_TRADE
  YES -> Market open / allowed session / news known?
        NO -> WAIT / NO_TRADE
        YES -> H4/H1 macro structure / dealing range / bias
          -> H1/M15 external target & liquidity map
          -> Qualified liquidity raid OR continuation structure
          -> Displacement + BOS/MSS confirmation
          -> Fresh FVG / OB / IFVG location (zone)
          -> M15/M5 confirmation and controlled entry zone
          -> Spread/slippage/news/correlation and entry expiry gates
          -> USD capital + contract/pip value + lot/min-volume gate
          -> score and R:R gate
          -> only then candidate signal (no automatic orders)
```

### Concrete sample setup rules — Bullish raid reversal (mirrored for shorts)
1. Current UTC time inside approved session; pair quote fresh; spreads in acceptable band.
2. H1 bias supportive or **explicit** countertrend profile authorized (stricter penalty).
3. Recognized sell-side liquidity reference valid and swept below; closed back above within ≤ `reclaimBars`.
4. LTF bullish displacement above minimum strength; confirmed bullish MSS through a prior internal swing.
5. Valid bullish FVG or OB lies inside allowed dealing-range context and not invalidated; entry zone at tested zone boundary/50% or post-retest close (profile-specific).
6. SL beyond structural sweep low **plus broker spread/slippage safety buffer**, no artificially tight stop merely to fit capital.
7. Target 1 = next eligible internal liquidity / obstacle; Target 2 = HTF opposing liquidity when unobstructed; **net** RR after costs >= configured floor.
8. News risk within restricted band? FAIL. Minimum broker lot exceeds risk budget? FAIL. Too many correlated USD positions? FAIL.
9. Only after an eligible candle close: `READY` signal; give `ENTRY_ZONE` and invalidation/expiration; cancel if price runs away before entry.

### Concrete sample setup — Trend continuation
- H4/H1 continuation bias, confirmed BOS; retrace into fresh FVG/OB in accepted PD array; M15/M5 valid continuation CHoCH/BOS and displacement; target opposing external pool; all same safety gates. No blind OB touch entry.

### Candidate classification

| Level | Trigger | UI |
|---|---|---|
| `A_PLUS` | Hard gates pass + score ≥85 (heuristic score, **not success probability**) | Distinct but not sensational notification |
| `WATCH` | Score 70–84 / entry not confirmed | Quiet watchlist; not an entry alert |
| `IGNORE` | Score <70 | Journal only |
| `NO_TRADE` | Any risk, feed, news, invalidation, cost or close-confirmation hard failure | Explain blocker, do not raise order alert |

**Indicative score rubric** (must be validated; sum 100): HTF bias 15, structure 15, liquidity evidence 15, displacement 10, FVG/OB quality 10, session context 10, target/path 10, quote cost quality 10, contextual news integrity 5. A passing score **cannot override** hard safety gates.

# K. Risk Management — The Most Important Module

### Inputs
- Broker picker: `Exness / Custom broker`.
- Account type: `Standard / Standard Cent / Other` (owner currently Standard).
- Platform adapter: `MT5 / MT4 / No live broker connection` (not yet confirmed).
- Base currency: USD; `balance`, `equity`, `available margin`, optionally leverage and current open exposures; manually adjustable if read-only feed cannot expose.
- `risk_per_trade_percent` default **0.5%**; cap configurable up to 1% for this small-account profile; never increase because an apparently excellent setup occurs.
- Max open planned risk default 1% equity combined; per-day max realized+open theoretical loss 2%; after 2 losses or breach → pause new ideas until daily reset (override only with deliberate UI action and audit log).
- `max_spread_pips`, `max_slippage_pips`, `min_net_rr` default 2.0, allowed drawdown, session and broker trading constraints, duplicate/correlated pair exposures.

### Exact calculations

```text
risk_usd = equity_usd * (risk_per_trade_percent / 100)
stop_distance_pips = abs(entry_price - stop_price) / pip_size
loss_per_lot_usd = stop_distance_pips * pip_value_usd_per_1_lot
                 + round_trip_commission_usd_per_lot
                 + other_verified_costs_per_lot
raw_lot = risk_usd / loss_per_lot_usd
safe_lot = floor_to_broker_volume_step(raw_lot)

estimated_max_loss_usd = safe_lot * loss_per_lot_usd
net_RR = estimated_net_target_profit_usd / estimated_max_loss_usd
```

**Important:** Use broker-provided symbol contract size, volume min/step/max, **profit currency → USD conversion**, bid/ask conventions, margin formula, account leverage and realistic slippage. Spread can be captured implicitly in side-specific buy/sell fill calculations; **do not double count spread** if price/SL distance already uses side-specific executable prices. Validate stop level/freeze level and real execution availability. Prices rounded to tick increments.

### Mandatory refusal
- `safe_lot < broker.min_lot` → **NO_TRADE: MIN_LOT_EXCEEDS_RISK**; never round **up** to make trade possible.
- Market price already beyond entry expiry/slippage tolerance → `MISSED`, do not chase.
- SL unreasonably tight compared with volatility/spread/structural invalidation → NO_TRADE.
- Unknown pip value / missing contract specification → NO_TRADE.
- Unreliable network, stale quotes, market closed, macro-calendar status unknown in strict mode → NO_TRADE.
- Margin requirement exceeds allowed free margin → NO_TRADE.
- Excess USD directional exposure across correlated pairs → NO_TRADE.

### Small-capital math (illustrative, NOT live market advice)
Assume USD **$25** equity, **0.5%** risk = **$0.125**. For EURUSD, illustrative `0.01` standard lot is roughly **$0.10 per pip** in a USD quote account. A structural **8-pip** stop costs roughly **$0.80 before additional execution costs**, over **6×** the $0.125 budget. Safe desired volume is about `0.00156` standard lot, **below common 0.01 minimum**. Thus output must be **NO TRADE**, not a fake tiny-stop trade. Actual min lot / contract terms verified live with account specifications. Cent account may offer smaller exposure units but must be treated as a different symbol/lot scheme, never assumed to be compatible.

Exness contract references: <https://get.exness.help/hc/en-us/articles/17854278192284-Forex>, <https://get.exness.help/hc/en-us/articles/17537782786588-Standard-Cent-account>.

### Trade management proposal (manual)
- Default one or two targets; use transparent size allocation and RR at each target; do not claim moving SL to BE always increases expectancy.
- Time-based exit near rollover / forbidden holding period; if user selects intraday, no auto hold overnight without explicit opt-in.
- Daily loss cap and max drawdown circuit-breakers.
- Journal partial closes as manually entered outcomes; no P/L fabrication.

# L. News, Calendar, Spread and Safety Filters

- Economic calendar from permitted supported source (licensed API or import); map relevant USD/EUR/GBP/JPY/AUD/CAD news to affected currency pairs.
- Categories: Central bank rate decisions, CPI/inflation, NFP/employment, GDP, speeches, surprise events where credible data exists.
- Configurable default exclusion: high-impact scheduled event `-30 min / +30 min`, tighter profile may use wider. Late reaction/spread abnormality can extend block.
- Verify publish timezone, event revisions and timestamps. Calendar unavailable or stale -> `NEWS_UNVERIFIED` and **NO_TRADE** in strict mode; owner can choose research-only view without trade recommendation.
- Spread filter based on actual broker ask-bid when available, session-specific rolling quantile not arbitrary fixed threshold. Use pip-precision per pair.
- Rollover, open/close transition, Friday close/reopen gaps, slippage outliers, maintenance, disconnect and stale ticks disable new READY states.
- Avoid trading based on unverified headlines or static news cached as current.

# M. Signal States, Canonical IDs and Determinism

```text
OBSERVING -> CONTEXT_VALID -> ZONE_FOUND -> SETUP_PENDING ->
TRIGGER_CONFIRMED -> RISK_VALIDATED -> READY -> NOTIFIED
       |             |                 |           |
       +---- INVALIDATED / EXPIRED / DATA_STALE / NO_TRADE
READY -> USER_MARKED_PLACED (manual only) -> USER_MARKED_CLOSED
READY -> MISSED / CANCELED / EXPIRED
```

A setup may be displayed early as `WATCH`, but **entry alerts only after closed-bar rules are met and final risk gate passes**. One signal per unique scenario, no repeated alert spam across bars.

**Canonical signal key construction** (example):

`sha256(strategy_version | normalized_symbol | setup_kind | UTC_event_bar_close | structural_anchor_ID | direction | entry_zone_quantized)`.

Source feed, config hash and source candle checksum stored separately; difference must be reported. Pine may compute approximate chart-side matching ID using an agreed **short fingerprint** of its chart-derived setup, but cannot receive/read a desktop DB signal ID. Use timestamp + symbol + direction + source/anchor and visual compare; **do not falsely state they are identical**.

**Example JSON event** (fabricated values for schema illustration, not a real trade):

```json
{
  "schema_version": "1.0",
  "signal_id": "example-signal-id-not-live",
  "strategy_version": "1.0.0",
  "pair": "EURUSD",
  "broker_symbol": "EURUSD",
  "broker": "Exness",
  "direction": "BUY",
  "setup": "LIQUIDITY_SWEEP_MSS_FVG",
  "timeframe": "M15/M5",
  "event_time_utc": "2026-10-15T00:00:00Z",
  "session": "LONDON",
  "status": "WATCH",
  "entry_zone": {"low": null, "high": null},
  "stop_loss": null,
  "take_profits": [],
  "safe_lot": null,
  "risk_usd": null,
  "net_rr": null,
  "score_points": 78,
  "score_is_probability": false,
  "confidence_label": "UNVERIFIED",
  "data_provider": "DEMO_SCHEMA_ONLY",
  "source_quote_time_utc": null,
  "spread_pips": null,
  "news_verification": "UNKNOWN",
  "chart_parity": "UNVERIFIED",
  "rule_trace": ["SAMPLE_ONLY"],
  "expires_at_utc": null,
  "safe_to_alert_for_entry": false
}
```

Schema includes nullable bid/ask, execution price assumptions, margin, `costs`, rank/score breakdown, blockers, local/display time, provenance, lifecycle event history, separate broker source symbol, revision number, owner audit actions. Historical signal must never be silently edited to look successful; revisions append.

# N. TradingView Indicator — UI/UX, Colors, Drawing Rules

**Name:** `AYESHA | Smart Money & ICT Compass`  
**Type:** `indicator(..., overlay=true)` in Pine v6, **one composite indicator**.  
**Main intent:** User already understands drawings; preserve clean price chart, not 20 indicators stacked.

### Visual layout
1. Top-right compact table: `PAIR`, `SESSION`, `HTF BIAS`, `SETUP STATE`, `SCORE /100`, `RISK FLAG`, `VERSION`, `TV FEED`; no fake live equity value because Pine cannot read Exness/Android local settings.
2. Swing annotations: important **external** H1/H4 levels as slim horizontal lines; internal M15/M5 structural labels as optional tiny text.
3. Liquidity: prior day high/low dashed line, Asia H/L, EQH/EQL dotted, only near-price/relevant objects.
4. FVG: transparent zone rectangle, faded on mitigation, hidden on expiry; OB zone separate soft border.
5. MSS/BOS: one concise tag anchored at actual **confirmation bar**; never backdate visible signal without explaining detection delay.
6. Entry plan: **after readiness** translucent entry-zone band, `ENTRY`, red `SL`, cyan/teal `TP1`, blue `TP2`, right-aligned price labels and R:R; end-of-line when invalidated/expired.
7. Scenario-based reasoning: compact label such as `SELL-SIDE SWEEP → BULL MSS → FVG RETEST; NEWS NOT VERIFIED IN PINE`.
8. Optional `Clean / Analyst / Full` visual modes; default **Clean**.
9. If broker risk cannot be validated inside Pine, label clearly `CHART-ONLY / CHECK APP RISK`. Do not show Pine-estimated lot as broker-verified safe lot.
10. Overlay must work in dark and light TradingView themes; limit label/line/box count; recycle old objects.

### Semantic color palette

| Visual | Hex | Meaning |
|---|---|---|
| Bull bias / confirmed BUY candidate | `#16A34A` | Green |
| Bear bias / confirmed SELL candidate | `#DC2626` | Red |
| Watch / pending | `#EAB308` | Amber |
| FVG unfilled | `#06B6D4` opacity ~80% | Cyan zone |
| Qualified OB | `#8B5CF6` opacity ~82% | Purple zone |
| Liquidity references | `#94A3B8` | Slate dashed/dotted |
| Entry zone | `#38BDF8` opacity ~75% | Sky |
| SL line | `#EF4444` | Red |
| TP1 line | `#14B8A6` | Teal |
| TP2 line | `#2563EB` | Blue |
| Invalidated / NO TRADE | `#64748B` | Gray |

Color MUST be accompanied by text/icon meaning for color-blind use; all colors user configurable. Avoid giant neon shapes and unreadable overlapping labels.

### Pine inputs (grouped)
- **Quick:** analysis profile, clean/full view, allowed pair, chart resolution, timezones.
- **HTF:** bias TF, pivots, structural break confirmation, range lookback.
- **ICT/SMC:** sweeps, FVG minimum, MSS, displacement, OB/IFVG/BPR, EQH/EQL tolerance, PD, SMT optional.
- **Session:** four sessions, overlaps, DST-aware zone inputs.
- **Trade proposal:** entry style, structurally justified SL buffer, RR floor, expiry bars, no duplicate.
- **Visual:** visibility, alpha, label size, object count.
- **Debug/Parity:** rule version/fingerprint, source symbol, confirming candle, trace compact panel.

### Critical indicator limitations
- Pine cannot call arbitrary desktop REST APIs, access local SQLite or read Exness equity/Android settings. Therefore chart visual signals are chart-native, not true 1:1 pushes from PC scanner.
- Pine draws may not include real broker spread, licensed news calendar, actual execution margin or safe lot. Must label `VISUAL CANDIDATE` where those are unknown.
- `request.security` HTF values must use confirmed-only method. `barstate.isconfirmed` and no future leak; validate real-time vs replay parity.
- Plan quotas for running indicators, plots, external symbols, runtime and alerts vary; create a proof of concept before finalizing script complexity.
- **Free TradingView alerts cannot be assumed unlimited or webhook-enabled.** Our phone notification source is the PC scanner, not a required TradingView webhook.

Official docs: <https://www.tradingview.com/pine-script-docs/writing/limitations/>, <https://www.tradingview.com/pine-script-docs/concepts/repainting/>, <https://www.tradingview.com/pine-script-docs/faq/alerts/>.

# O. Android App (13) — Complete Screen Inventory

**Working name:** `AYESHA FX`  
**Platform:** Android 13 first; dynamic theme dark/light; typography clean, readable, compact and Bengali/English language option. No Android broker login UI.

### O1 — Welcome / Pairing
- App description, manual-trade-only warning, PC companion connection instructions, connect by Tailscale private address or approved LAN QR/pairing code.
- Encrypted pairing token, revoke session, app/device name, never expose scanner publicly.
- `POST_NOTIFICATIONS` Android 13 runtime permission request in context; test deny/re-allow behavior.

### O2 — Home Dashboard
- PC status `CONNECTED`, `LAST SEEN`, `OFFLINE`, `DATA_STALE`; current session; selected watchlist and scan count; A+ signals today, rejected over-risk, last news sync.
- `Trade-capable` vs `Analysis only` prominent. Last signal preview with no misleading green profit claims.

### O3 — Live Watchlist
- Pair cards, H4/H1 bias, session, relevant zone, bid/ask age, recent sweep/MSS/FVG, `WAIT`/`WATCH`/`READY`/`NO_TRADE`.
- Search, favorite, enable/disable pair, individual pair scan schedule; sort by readiness not manufactured likelihood.

### O4 — Signal Inbox
- Group by New / Pending / Ready / Expired / Invalidated / No Trade.
- Dedup, read/unread, precise UTC and local time, delivery lag visible; swipe/archive without deleting journal.

### O5 — Full Signal Details
- Pair, timeframe, setup family, direction, exact entry zone, invalidation, SL, TP1/TP2, estimated net RR, verified safe lot **or reason why none**, expected maximum USD loss, current spread, timestamp and expiry.
- Explain **observed vs inferred** ICT/SMC events in human language: e.g. `Asia low swept`, `M5 MSS confirmed`, `FVG half-filled`.
- `TradeView chart` deep-link with symbol/timeframe; the overlay may show **only the independently recomputed corresponding candidate**. If mismatch, banner with feed/timing/rule reason.
- `Open Exness` launch app only if installed; **no order fields auto-submitted**. Copy levels button, user confirms price staleness.
- Screenshot/share snapshot can omit sensitive balance by toggle; log screenshots local only.

### O6 — Capital & Account Settings
- `Broker` (Exness default), `Account type` Standard, quote/account currency USD, feed adapter and live/delayed status.
- Manual `Balance` and `Equity` (never silently assume balance = equity), risk % default 0.5, max per-day %/USD, max exposure, leverage/margin read-only or manual, exact symbol lot min/max/step and contract specs.
- Presets `Ultra-conservative`, `Custom`. Selecting more aggressive settings needs acknowledgment and never bypass hard broker constraints.
- In-app calculator `capital → risk USD → structural SL → lot sizing → valid/invalid`, show clear *NO TRADE* outcome.

### O7 — Strategy & Pair Settings
- Strict / balanced **research** filter (risk hard caps unchanged); enable/disable setup families; profile Intraday default, scalp OFF; parameter changes create versioned config and invalidate stale unmatched proposals.
- Require synchronization back to PC before claiming applied. Pine inputs changed manually in TradingView; app shows config-diff instructions / hash.

### O8 — Notifications
- Types `A+ ENTRY READY`, `WATCH` (optional silent), `SIGNAL INVALIDATED`, `SL/TP level reached observed` (market observation only, not broker execution), `SYSTEM OFFLINE`, `NEWS LOCKOUT`, `RISK LIMIT`.
- Per-pair preferences; quiet hours for non-critical messages; A+ notification channel; audible/vibration choices; duplicates suppressed.

### O9 — Journal & Analytics
- Manual `Taken?`, actual entry/exit/slippage/fees, partial TP, realized P&L, emotion/discipline notes, screenshots; never infer broker fill simply from price touched.
- Analytics: win rate with sample size, expectancy in R, profit factor, max drawdown, average risk/return, most rejected patterns, session results; fees included; compare paper vs manual live separately.

### O10 — Diagnostics / Safety
- Version/config hash, PC heartbeat, push permission/test, queue lag, source feed, last candle, news freshness, Tailscale status, read-only app logs, privacy/export backup, revoke pairing and emergency **Pause alerts**.

# P. Notification UI and Delivery Semantics

**Illustrative notification (NOT a live trade):**

```text
[AYESHA FX]  🟢 A+ SETUP — EURUSD
BUY | London | M15 setup / M5 confirmation
Entry: see zone  |  SL / TP: open details
Risk: 0.5%  |  Lot: requires broker validation
Observed: sweep + confirmed MSS + FVG
Tap: View reasons • Check TradingView • Risk
```

A **READY** notification can only include an executable-size suggestion after safe lot passes min/step/margin/cost checks; otherwise **show `NO TRADE` instead of ready**. For a valid one, include exact prices, safe lot and estimated max dollar risk in detail view. Phone push itself may be delayed, so on tap revalidate quote age, entry validity and signal expiry before displaying active status. Notification timestamps show **generated time** and **received time**.

Delivery options:
1. **Preferred**: PC scanner sends minimal FCM notification (with signal ID and non-sensitive preview). Android obtains detailed canonical record over encrypted paired private connection; caches record; retries when PC reachable. FCM requires third-party infrastructure and suitable credentials/project setup.
2. **Fallback**: when same Wi-Fi/Tailscale connected and app running, private WebSocket stream; reconnect and backfill.
3. **Optional backup**: Telegram channel/user notification on opt-in (not a replacement for Android app); bot token never hardcoded in Git.

Privacy: Keep private access token and FCM service credentials in Windows secure secret store; don't include account login or equity in push payload by default. All network endpoints authenticated, TLS/private-network-only; rate-limit; rotate keys after compromise.

Android API 33 permission docs: <https://developer.android.com/develop/ui/compose/notifications/notification-permission>.

# Q. PC Scanner and Dashboard

### Startup
- `AYESHA FX Desktop` tray app launch on Windows sign-in (opt-in). Health checks before scan: API/data feed, correct time, holiday, storage, FCM credentials (if enabled), paired devices.
- Two modes: `DEMO/REPLAY` (safe default) and `LIVE_ANALYSIS_ONLY`. Live still means **advisory, not order execution**.
- Watchlist editable; per-pair status, session timer, no-action reason.

### Scanner workflow
- Feed subscribe/poll with provider-supported intervals; snapshot bid+ask with timestamp, 1m/5m/15m/1h/4h OHLC aggregations anchored UTC and broker-session conventions.
- Detect gap/revision/stale candles, provider outage, timezone DST shifts; skip rather than backfill with fabricated prices.
- Evaluate pair on confirmed candle close; asynchronous background tasks with bounded concurrency; never hammer free feed rate limits.
- Every candidate persisted; run risk check; ready notifications enqueued idempotently; retry bounded, health visible.
- `Refresh now` gives a one-time current market pass; does not turn incomplete candle into confirmed history.

### Desktop UI pages
`Overview`, `Sessions`, `Pairs`, `Canonical Signal Chart`, `Signals`, `Capital/Risk`, `Rulebook`, `News/Events`, `Journal`, `Devices`, `Parity Diagnostic`, `Log/Health`, `Settings`.

### Data feed selection before build
- **Preferred if user's Exness trading account platform is MT5:** local MT5 terminal as data/contract-spec adapter; verify account and available symbols. Python client should **not implement trading APIs** (`order_send`, position close etc.). The absence of order code is verified in tests.
- **If user has MT4 only:** select supported documented exporter/read-only adapter or properly licensed market-data API. Do NOT pretend native MT5 Python adapter works with MT4.
- **No credential sharing** with developer. User logs in to terminal locally; any token stays on user device.
- Use legal, supported feed; no unauthorized TradingView browser-scraping.

# R. Chart and Scanner Parity Contract

`/contracts/strategy-spec.yaml` holds canonical algorithm parameters and definitions. Python must load it. Pine cannot read YAML at runtime; build a **generated static Pine input/default constants file** or a checked code generation step from the YAML, producing a `strategy_hash` shown in Pine UI and Android. Android reads synced hash from PC.

Rules parity:
- Same timezone, session windows, symbol alias map, timeframe anchoring, confirmed-bar policies, rounding/ticks, equal-high tolerances, pivot delays, zone lifecycle, score thresholds, expiry.
- Test with common archived OHLC fixtures: Python expected trace; Pine Bar Replay/manual export logs/screen results; Android displays PC trace only.
- `Parity confidence`: `MATCHED` if (pair, feed mapping/normalized bars, direction, setup, confirmation time, anchors and level tolerances) all match; `PARTIAL` if same candidate but adjusted quotes; `UNVERIFIED` when Pine internal result can't be retrieved reliably; `MISMATCH` if verified conflict. **Never imply live Pine state has been read by PC unless supported exchange mechanism exists.**
- Pair selected in PC and Pine must match; configurable broker-vs-TradingView feed tolerance for price levels, bar formation and weekend gaps.
- App "View on TradingView" navigates to symbol+timeframe, does **not** programmatically control TradingView logged-in UI or claim selected indicator state loaded unless user added it.
- If exact external scanner levels are critical, show local companion chart, which **can** overlay canonical signals accurately. This is the designed compromise under user no-server/free-TradingView constraints.

# S. Validation, Backtest, Walk-Forward, and Reporting

### Must not build a visually amazing but misleading bot
- Unit test all primitives on hand-labeled small candles including edge cases/tie highs, partial/revised bars and timezone changes.
- Deterministic replay with incremental candle arrival: no use of `future` pivot until right bars closed; no post-hoc data labeling as tradable in earlier bar.
- HTF non-repainting test: TradingView `request.security` confirmed values; avoid future leaks and retrospectively moved entry marker.
- Broker bid/ask execution simulation (spread varies), realistic slippage, commission (if any), market availability, gap stop fill.
- Training vs holdout ranges; out-of-sample + walk-forward, multiple volatility regimes; avoid overfitting 100 settings against short history.
- Separate evidence for intraday vs scalping and per-pair; report sample count, distributions, winning/losing streaks, drawdown and costs.
- Paper/demo forward observation with real timestamps before using capital. Illustrative release gate: >= 30 calendar days forward monitoring (may need longer for infrequent A+ setups), plus a meaningful number of historical samples spanning regimes—not a fabricated guaranteed win rate.
- No claim like "92% accuracy" without logged live out-of-sample sample size, method, costs and uncertainty.

**Metrics:** precision of pattern detections vs labeled ground truth; false positive rate; setup-to-entry conversion; realized `expectancy_R`, fees/net; MFE/MAE; win rate with confidence bounds; out-of-sample vs in-sample drift; signals/day distribution; time of signal vs phone delivery; percent rejected due to safe-lot; Pine parity coverage; alert duplicates; uptime/data gap.

# T. Config and Persistence — Data Tables

### SQLite entities

- `instruments`: provider aliases, pip/tick, USD conversion, contract, lot specs, exchange hours, status.
- `candles`: pair/provider/TF/UTC-open/UTC-close/OHLC/volume type/completeness/revision/checksum.
- `quotes`: UTC quote time, bid/ask, max-age, spread, provider.
- `session_snapshots`, `calendar_events`, `structure_events`, `liquidity_zones`, `fvg_zones`, `order_blocks`, `setup_states`, `signals`, `signal_versions`, `signal_delivery`, `risk_snapshots`, `device_pairings`, `config_versions`, `journal_trades`, `audit_log`, `engine_health`.
- Appropriate foreign keys, indexes on `(pair,timeframe,time)` and unique idempotency keys, schema migrations, sensitive encryption and DB backup/restore integrity checks.

### Key config categories
`broker`, `account`, `risk`, `sessions`, `pairs`, `timeframes`, `rules`, `entry`, `news`, `delivery`, `devices`, `privacy`, `display`, `testing`, `logging`.

No `.env` with real secrets in Git. Commit only `.env.example` and safe example datasets. Settings changes must persist version/timestamp/user intent; scanner logs start/end of evaluation and rule version.

# U. UX: Step-by-Step User Journey

1. User installs Windows scanner, signs in locally to an *optional* approved MT5 terminal or connects authorized feed.
2. User chooses Exness Standard USD, manual equity, allowed majors, 0.5% risk, confirms no autoplace orders.
3. User installs AYESHA Pine v6 script via own TradingView account's Pine Editor (no password shared), adds as only desired indicator and checks `rule version` and appropriate symbol/timeframe.
4. User installs Android 13 signed APK, grants notifications, pairs phone securely with PC on Tailscale or LAN, tests FCM and diagnostic `Test notification`.
5. PC scanner verifies current feed, calendar, spread, time sync. UI shows `RUNNING` only when qualified; otherwise clear `PAUSED / DATA_STALE`.
6. In eligible session, scan detects possible setup → WATCH. If candle-confirmed and cost/risk pass → READY and sends phone notification.
7. User taps notification, inspects reasoning and safe lot, opens TradingView to view equivalent indicator candidate (or companion chart for **exact** canonical overlay), then manually opens Exness and decides.
8. User marks order manually in journal; records actual fill/exits after trade; analytics improve understanding and may trigger research, but bot never learns by increasing risk automatically.
9. On outages, app displays last sync, no unverified fresh setup claims; PC resumes safely without repeated stale signals.

# V. GitHub-First Development Rules

### Monorepo layout (planned)

```text
ayesha-fx/
├─ README.md
├─ MASTER_PROJECT_SPEC.md                   # copy of THIS document
├─ CHANGELOG.md
├─ SECURITY.md
├─ LICENSE                                  # owner decides
├─ .gitignore
├─ .env.example
├─ .github/
│  ├─ workflows/ci.yml
│  ├─ workflows/build-android.yml
│  └─ workflows/build-desktop.yml
├─ docs/
│  ├─ 00-assumptions-and-open-questions.md
│  ├─ 01-architecture.md
│  ├─ 02-rulebook-ict-smc.md
│  ├─ 03-risk-and-contract-math.md
│  ├─ 04-signal-schema-and-state-machine.md
│  ├─ 05-tradingview-guide.md
│  ├─ 06-android-13-guide.md
│  ├─ 07-setup-and-pairing.md
│  ├─ 08-data-source-compliance.md
│  ├─ 09-testing-and-backtest-report.md
│  ├─ 10-release-and-rollback.md
│  └─ 11-source-references.md
├─ contracts/
│  ├─ strategy-spec.yaml
│  ├─ signal.schema.json
│  ├─ settings.schema.json
│  └─ version.json
├─ desktop/
│  ├─ pyproject.toml
│  ├─ ayesha/{main.py,feed/,rules/,risk/,signals/,news/,sync/,ui/,storage/}
│  ├─ migrations/
│  └─ tests/
├─ tradingview/
│  ├─ AyeshaSmartMoney.pine
│  ├─ generated/strategy_constants.pine.txt
│  └─ tests/fixtures-and-replay.md
├─ android/
│  ├─ app/src/main/
│  ├─ app/src/test/
│  └─ README.md
├─ fixtures/
│  ├─ market-candles/
│  ├─ strategy-expected/
│  └─ edge-cases/
├─ scripts/
│  ├─ generate_contracts.py
│  ├─ check_rule_parity.py
│  ├─ backup_local_db.py
│  └─ build_release.ps1
└─ releases/
   └─ README.md                              # release pointers, not unnecessary large binaries
```

### Mandatory workflow
1. Owner provides GitHub repository URL **and** authorizes access. Never push to an unrelated repo.
2. Create issues/milestones: foundation → rule engine → risk → Pine → Android → sync → QA → signed release.
3. Every feature branch has test, documentation update, checklist status, change log note and version/hash update as needed.
4. Open pull request or owner-approved direct update policy. CI builds and tests on each PR; merged changes push to owner repo.
5. Release tag `vX.Y.Z`, changelog, signed APK, Windows installer, Pine release code, SHA256 checksums, install/revert instructions.
6. No unapproved production/live action, no leaked tokens, no broker API trading scope, no dependency downloads from untrusted sources.
7. If repository connector lacks write permissions, do not claim code uploaded; request owner to connect or manually push from local.
8. Rollback to tagged known-good version. Database migrations forward/backward compatibility tested.

# W. Security and Privacy

- No broker credentials, Gmail passwords, TradingView cookies, OTP or 2FA codes collected.
- Pairing token per phone, QR expiration, revocation, signed HTTPS/private network, least-privilege; local FastAPI binds `127.0.0.1` by default until explicitly paired and firewall scoped to private network.
- Windows Credential Manager/DPAPI or suitable OS secure store for FCM/private keys; Android Keystore/Encrypted preferences for pairing secrets.
- Signed installer/APK with hash verification; protect supply-chain (dependency pinning and audit), restrict logs, sanitize crashes.
- `LIVE_ANALYSIS_ONLY` not broker execution. Automated test scans Python source for order-send use and denies any order endpoint in local API.
- User may delete journal/export encrypted JSON/SQLite backup. Do not export financial balance in public logs.
- Respect official TradingView terms, Exness API/terminal restrictions, rate limits, data-feed licenses, jurisdictional restrictions, and applicable local trading laws before real-money use.

# X. Failure Handling and Safe Fallbacks

| Failure | Expected app/desktop response |
|---|---|
| MT5 terminal closed/unavailable | `FEED_OFFLINE`; no new entry signals; reconnect retry |
| Broker disconnected/stale quote | `DATA_STALE` + suspend new READY |
| Spread exceeds allowed | `NO_TRADE: SPREAD_TOO_WIDE` |
| Calendar not fresh in strict mode | `NO_TRADE: NEWS_UNVERIFIED` |
| PC hibernates | Android shows offline heartbeat age; stale signals expire; no phantom scan |
| FCM outage/permission denied | Delivery failure logged; fallback live private sync when available; cannot promise instant push |
| Tailscale offline / phone remote | FCM preview may arrive, but detailed history sync pending; app truthfully labels `DETAILS_NOT_SYNCED` |
| TradingView free-plan quota | Indicator stays functional within quota; TV alerts not mandatory for push |
| Pine ↔ PC data disagreement | `CHART_PARITY_UNVERIFIED / MISMATCH`, show canonical PC chart |
| No safe allowed lot | `NO_TRADE: RISK_TOO_HIGH_FOR_MIN_LOT` |
| High impact surprise news | Disable new orders/signals based on spread/quality; no retrospective perfect avoidance claim |
| Weekend / holiday | `MARKET_CLOSED`; analyze historic context but no READY entry |
| More than 2 losses or limit hit | `DAILY_RISK_PAUSE`; user journal can acknowledge, not auto re-enable risk |
| Repeat app start / network retries | Idempotent signal + delivery IDs; no duplicate trade alerts |

# Y. Delivery Milestones and Acceptance Gates

**Milestone 0 — Freeze project spec (NO CODING):** owner approves THIS document and provides repo URL, platform details and data feed preference.

**Milestone 1 — Feasibility spike:** one pair EURUSD historical MT5/authorized feed; verify candle timing, broker contract specs, TradingView Basic Pine v6 compile, minimal Android FCM push and remote private pairing. Stop and revise if any integration infeasible.

**Milestone 2 — Formal rules/risk:** all primitives implemented as deterministic Python event stream; lot size and hard gates unit-tested across currency pairs and broker min-lot.

**Milestone 3 — Indicator:** Pine v6 one composite overlay; non-repaint confirmation; same fixtures; chart legend/traces; custom color inputs; visual complexity limits.

**Milestone 4 — Android:** notification permission, secure pairing, settings, signal inbox/details, safe-capital calculator, TradingView deep-link, offline cached state.

**Milestone 5 — Unified experience:** private sync; canonical signal IDs; parity warnings and exact local chart; state recovery, FCM queue, health reporting.

**Milestone 6 — QA and paper/demo forward test:** replay + out-of-sample report + false-trade checks; observe over a meaningful live period; document failure reasons; DO NOT claim profitability.

**Milestone 7 — Deliver:** source to GitHub, installable Windows app, signed APK, Pine code + installation guide, test report, sample fixtures, documented limitation list, rollback instructions. Owner acceptance required.

### Release acceptance criteria (all mandatory)
- No executable trade API integrated.
- All READY signals have valid, normalized entry/SL/TP, source quote age, estimated net RR, safe lot and loss; if not, show NO_TRADE.
- TradingView indicator does not falsely claim real broker risk confirmed or off-platform AI state displayed.
- Repeat chart playback results consistent under confirmed-bar logic; no future leak.
- Any paired phone can receive test push on Android 13; denial behavior documented.
- Local scanner truly runs without owned VPS (though Google FCM/Tailscale/authorized feed may be externally hosted).
- Airplane/offline PC tests show safe degraded state.
- Repo includes reproducible builds/tests and no secrets; release artifacts verified.

# Z. Mandatory A–Z Checklist (Must Be Checked Off with Evidence)

**Checklist convention:** `- [ ]` remains incomplete until implemented AND tested. Each completed item must link commit/PR, test evidence, screenshots as relevant. Mark `N/A` only with documented owner consent; do not check off based on intention.

## Z1 — Product decisions & approvals
- [ ] Owner reviewed and approved master specification.
- [ ] Owner provided correct GitHub repository URL and permitted access.
- [ ] Confirm OS version and PC hardware/network capabilities.
- [ ] Confirm Android 13 handset compatibility and install method.
- [ ] Confirm account base currency USD and live equity input format.
- [ ] Confirm Exness Standard contract/instrument settings from terminal.
- [ ] Confirm broker platform is MT5, MT4, or Exness Terminal; pick legal data adapter.
- [ ] Confirm TradingView Basic indicator/alert entitlements with account.
- [ ] Confirm eligible realtime authorized feed and recurring cost (if any).
- [ ] Confirm exact chart mirroring limitation and companion-chart fallback accepted.
- [ ] Confirm own-VPS-free requirement and optional external FCM/Tailscale accepted.
- [ ] Confirm manual-trade-only product scope; trading auto-order disabled.
- [ ] Approve profile defaults, allowed forex pairs and symbols.

## Z2 — Repository and CI
- [ ] Git repo initialized in owner-selected repository.
- [ ] README, MASTER_SPEC, architecture, rulebook and glossary committed.
- [ ] Gitignore and `.env.example` configured.
- [ ] Branch / PR policy, labels and milestones created.
- [ ] CI: Python lint/typecheck/unit tests.
- [ ] CI: Android lint/unit/build tests.
- [ ] CI: Pine static checklist and replay fixture documentation.
- [ ] Dependency lockfiles and vulnerability scanning enabled.
- [ ] Secrets scan passes (no passwords/tokens/private keys).
- [ ] Release tag/changelog/versioning procedure documented.
- [ ] Document + checklist update required on every feature commit.

## Z3 — Data and broker fundamentals
- [ ] Approved data connector selected and authenticated locally.
- [ ] Read-only adapter constraint verified (no `order_send`).
- [ ] Stable symbol alias mapping (e.g., account suffixes).
- [ ] Broker contract size/min/step/max data read and stored per symbol.
- [ ] Pip value converted to USD correctly for cross/JPY pairs.
- [ ] Bid/ask/spread and quote timestamps supplied and quality tested.
- [ ] Historical data integrity and sufficient lookback verified.
- [ ] All timeframe aggregations use documented UTC bar boundaries.
- [ ] Reconnect, backfill, revision and stale-quote tests pass.
- [ ] Closed market/holiday/rollover conditions verified.
- [ ] TradingView feed difference tolerance measured and documented.

## Z4 — Sessions, structure and liquidity
- [ ] IANA timezone and DST rules tested for four sessions.
- [ ] Session overlap/opening range/high-low lifecycle complete.
- [ ] Prior-day/prior-week highs/lows compute reproducibly.
- [ ] Confirmed swing detection with pivot-delay tests.
- [ ] External/internal structure distinction tested.
- [ ] BOS with close/buffer tested.
- [ ] CHoCH and displacement-qualified MSS tested.
- [ ] Liquidity pool / EQH/EQL zone formation tested.
- [ ] Wick sweep/reclaim vs breakout differentiation tested.
- [ ] Freshness, invalidation and zone expiry defined and tested.
- [ ] Price-action trace separates observation and hypothesis.

## Z5 — ICT/SMC and psychology
- [ ] Three-candle bull/bear FVG zone and mitigation tested.
- [ ] IFVG flip and retest validity tested.
- [ ] BPR intersection model tested.
- [ ] Order-block qualification requires displacement + structure break.
- [ ] Mitigation vs breaker logic tested.
- [ ] Premium/discount/OTE reference defined and tested.
- [ ] Inducement warning rules testable; no intent certainty language.
- [ ] SMT optional alignment/correlation requirements documented.
- [ ] AMD/Judas scenario tags have objective triggers.
- [ ] Fake breakout / late-chase behavioral filter tested.
- [ ] Institution/market psychology **inference label** shown everywhere.
- [ ] Nonavailable proprietary order flow explicitly disclosed.

## Z6 — Entry logic, scoring and risk
- [ ] Intraday A+ reversal complete with fixture proof.
- [ ] Intraday A+ continuation complete with fixture proof.
- [ ] Scalping default disabled.
- [ ] Optional scalping cannot enable without standalone QA evidence.
- [ ] Rule score 0–100 is not labeled win probability.
- [ ] Score cannot override hard safety gates.
- [ ] Entry zone validated and timestamped at bar close.
- [ ] Structural SL + buffer, never made artificially tight.
- [ ] TP1/TP2 target path and obstacles recorded.
- [ ] Net R:R includes execution friction without double counting.
- [ ] Lot sizing floors to minimum *step* and rejects below minimum lot.
- [ ] USD pip value and cross-currency conversion tested.
- [ ] Margin/free-margin and leverage constraints verified.
- [ ] Spread/slippage limit tested.
- [ ] News release lockout and stale-calendar refusal tested.
- [ ] Daily loss / aggregate exposure / correlated positions safety tested.
- [ ] Small $25 account example correctly produces NO_TRADE when infeasible.
- [ ] Duplicate, stale, and missed setups never send READY again.
- [ ] All manual trade outcomes distinguish simulated vs actual.

## Z7 — Pine v6 indicator and visuals
- [ ] One Pine v6 indicator compiles on owner Free/Basic plan.
- [ ] Clean/Analyst/Full modes available.
- [ ] HTF bias and confirmed structural levels shown.
- [ ] EQH/EQL and session highs/lows shown as optional lines.
- [ ] FVG/OB/IFVG/BPR zones drawn only if qualified.
- [ ] MSS/BOS marker waits for confirmation, no future leak.
- [ ] Visual Entry/SL/TP1/TP2 and setup expiry drawn.
- [ ] BUY/SELL/WAIT/NO_TRADE visual semantics accessible.
- [ ] Risk-unverified disclosure visible on chart when appropriate.
- [ ] Dark/light theme tested; readable colors and label collision reduced.
- [ ] Plot/box/line/request limits and performance on Basic tested.
- [ ] Full bar replay and live non-repaint comparison documented.
- [ ] Pine rule constants generated from canonical strategy spec.
- [ ] Pine cannot import scanner signals — limitation shown in guide.
- [ ] Chart candidate ≠ canonical PC READY unless verification conditions pass.

## Z8 — Windows scanner and local safety
- [ ] Windows tray app UI ready.
- [ ] Manual refresh works safely.
- [ ] Continuous scan across active FX sessions works while PC ON.
- [ ] Startup at login optional, disabled without consent.
- [ ] Local SQLite migrations/backup and recovery tested.
- [ ] Feed watchdog/heartbeat and reconnect tested.
- [ ] Completed candle scheduler and correct timezone tested.
- [ ] A+ / WATCH / IGNORE / NO_TRADE logic journaled.
- [ ] Full reason trace and rejected-trade blockers accessible.
- [ ] Signal state machine and idempotent delivery verified.
- [ ] No public local API binding by default.
- [ ] Correct shutdown and restart pending signal recovery tested.

## Z9 — Android 13 app
- [ ] Signed APK installs on Android 13.
- [ ] `POST_NOTIFICATIONS` request and denied permission handled.
- [ ] Secure first-run pairing and token revoke tested.
- [ ] Home heartbeat, data age and status badges correct.
- [ ] Watchlist with session, timeframe and state accurate.
- [ ] Signal inbox and filtering functional.
- [ ] Full signal details include actual rule trace and cost/risk status.
- [ ] Broker/account/capital/equity/risk settings UI functional.
- [ ] Settings version sync to PC is explicit and confirmed.
- [ ] Risk preview refuses impossible minimum lot.
- [ ] TradingView deep-link loads chosen pair/timeframe when supported.
- [ ] Exact canonical signal visible on companion chart if TV parity unavailable.
- [ ] Exness open action never submits a trade.
- [ ] Journal entry and realized-versus-simulated separation tested.
- [ ] Local notification and history available offline (cached data only).
- [ ] Dark/light mode and Bengali/English readability tested.

## Z10 — Sync, alerts and failures
- [ ] Google FCM project/credentials securely configured if accepted.
- [ ] Notification includes send and event times; delay handling tested.
- [ ] Private LAN/Tailscale address paired; no router port-forward needed.
- [ ] Authenticated FastAPI sync with rate limiting and key rotation.
- [ ] App downloads missed signals and handles duplicate event replay.
- [ ] Mobile notification opens specific verified detail, not generic app home.
- [ ] Stale push opens `EXPIRED/MISSED` safely when relevant.
- [ ] PC-off state shown accurately on phone.
- [ ] Phone-offline and reconnection queue works without duplicate push.
- [ ] FCM unavailable/permission denied gracefully degrades.
- [ ] TradingView chart mismatch is NOT hidden; parity status honest.
- [ ] No guarantee claimed of instantaneous delivery or 24/7 operation when PC off.

## Z11 — Quantitative validation and release
- [ ] Primitive fixtures and edge-case unit tests pass.
- [ ] Historical bar-by-bar replay with zero lookahead errors passes.
- [ ] Walk-forward / out-of-sample results generated and caveated.
- [ ] Spread, fees, slippage, and gap simulations included.
- [ ] Pair/session/scalping-vs-intraday breakdown produced.
- [ ] Alert delivery delay, parity and false-positive metrics captured.
- [ ] Paper/demo forward evaluation done before real-money pilot.
- [ ] Safety/no-trade cases demonstrated in screenshots.
- [ ] Full install and uninstall / secret revocation documented.
- [ ] GitHub release tags, Windows build, signed Android APK, Pine script included.
- [ ] Release hashes and rollback steps verified.
- [ ] Owner acceptance completed without unverified profit claims.

---

# Appendix 1 — Decisions Still Needed Before Coding

**Critical questions (not reasons to postpone this specification):**

1. GitHub repository URL + permission model (private recommended).
2. Owner Windows version, RAM and whether PC can stay powered on during sessions.
3. Exness account's actual **platform** (MT5 / MT4 / Exness Terminal)—account existence alone doesn't tell us.
4. Approved price feed option / subscription budget; live spread and broker specifications must be available.
5. Owner's preferred monitored pairs and capital/risk defaults (defaults above are only safe proposals).
6. Android push via Google FCM and remote pairing via Tailscale accepted? If third-party services forbidden entirely, only LAN/local alerts will be possible; **no reliable arbitrary-location phone delivery** promised.
7. Agree that TradingView chart is independent Pine analysis; external canonical signal is exactly visible on PC local chart and approximately/parity-checked on TradingView chart, not arbitrarily injected.
8. Android APK sideload-only now or eventual Play Store publication and signing key custody?
9. Economic calendar provider and handling of temporarily unavailable event data.
10. Whether the owner wants a read-only broker account equity sync later. **Never** request login details in chat.

# Appendix 2 — Developer Instruction / Execution Contract

> Read `MASTER_PROJECT_SPEC.md` before coding. Do not skip mandatory checks. Keep architecture **PC-local, no owned VPS**. Build a functioning scanner, one TradingView Pine v6 overlay, an Android 13 app and validated bridge—with honest platform limitations. Make risk and NO_TRADE rules impossible to bypass accidentally. The strategy is advisory only; never transmit trade orders. Work exclusively in the owner-approved GitHub repository. For each change, update docs, run tests, attach proof, update corresponding checkboxes, commit/push only after permissions permit. Use a single versioned rule contract; test parity instead of asserting perfect sync. Do not use guessed broker contract specs or imply A+ means a measured win probability. In case of doubt or missing market data, fail closed into WAIT/NO_TRADE, not BUY/SELL.

# Appendix 3 — Official Documentation / Verification Sources

These are technical references and are **not** evidence that a particular strategy is profitable. Verify them again during implementation because provider policies/features change.

- TradingView Pine Script v6: <https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-6/>
- Pine limitations (cloud script execution, requests, drawings): <https://www.tradingview.com/pine-script-docs/writing/limitations/>
- Pine repainting / confirmed HTF data: <https://www.tradingview.com/pine-script-docs/concepts/repainting/>
- Pine alerts: <https://www.tradingview.com/pine-script-docs/faq/alerts/>
- TradingView alert delivery choices: <https://www.tradingview.com/support/solutions/43000520149-introduction-to-tradingview-alerts/>
- TradingView external webhook limitations: <https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/>
- Android 13 notification permission: <https://developer.android.com/develop/ui/compose/notifications/notification-permission>
- Android WorkManager interval limits: <https://developer.android.com/develop/background-work/background-tasks/persistent/getting-started/define-work>
- Exness forex contract specifications: <https://get.exness.help/hc/en-us/articles/17854278192284-Forex>
- Exness Standard Cent differences: <https://get.exness.help/hc/en-us/articles/17537782786588-Standard-Cent-account>

---

**Final principle:** *NO TRADE is a valid and often essential output.* Build a transparent research/decision-support tool, not a promise of income. Finished files are only “DONE” when tests, documentation, versioning and owner-accepted checklist evidence exist.