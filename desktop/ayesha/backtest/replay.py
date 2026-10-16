"""Bar-by-bar replay backtester (master spec section S).

Causality: at bar i the strategy sees bars 0..i only; orders it creates can first fill on
bar i+1. Fill model matches the risk engine: every order triggers when the BID touches its
level and the round trip pays one spread (the spread recorded on the fill bar).
Conservative choices: if a bar touches both stop and target, the stop wins; a fill bar
can stop out but cannot take profit; gaps through the stop exit at the bar open;
stop exits pay extra slippage. Open trades are closed before the New York rollover.
Results are in R (1R = planned loss incl. spread and slippage buffer), not money.

News (`news_mode`), on the same candles and the same signals:
- "none": news not modelled (research only; live strict mode would block these).
- "legacy": the v0.7 fixed window, HIGH impact 30 min before/after, checked at the signal bar.
- "upgraded": the live NewsGuard on a point-in-time calendar (ayesha.backtest.asof) with closed M5
  bars only up to each decision: tiers, overlaps, reaction watch, a setup expiring before the next
  lockout, and a pending order cancelled when news turns against it (N10).
News direction is never used and never backtested.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from ayesha.backtest.asof import AsOfCalendar
from ayesha.models import AccountState, Candle
from ayesha.feed.static_specs import assumed_fx_spec
from ayesha.news.calendar import NewsCalendar
from ayesha.news.guard import NewsAssessment, NewsGuard
from ayesha.risk.engine import RiskConfig, TradeProposal, evaluate
from ayesha.rules.mtf import MtfEngine
from ayesha.rules.strategy import TF_MINUTES, Signal

NY = ZoneInfo("America/New_York")
FLAT_TIME = time(16, 45)
NEWS_MODES = ("none", "legacy", "upgraded")
M5 = timedelta(minutes=5)


@dataclass
class Trade:
    signal: Signal
    # PENDING | PENDING_MARKET | OPEN | CLOSED | MISSED | EXPIRED | BLOCKED | UNCONFIRMED | INVALIDATED
    status: str = "PENDING"
    fill_index: int | None = None
    fill_price: float | None = None
    exit_index: int | None = None
    exit_reason: str | None = None
    r: float | None = None
    blockers: list[str] = field(default_factory=list)
    planned_loss: float = 0.0
    fill_time: datetime | None = None
    exit_time: datetime | None = None  # close of the exit bar
    expires_at: datetime | None = None  # pending order cancelled before a bar that would end after this
    news_phase: str = "NOT_MODELLED"  # upgraded-guard phase at the signal (also annotated in other modes)


def _after_flat_time(t: datetime) -> bool:
    return t.astimezone(NY).time() >= FLAT_TIME


def bar_source(bars: list[Candle], minutes: int = 5) -> Callable[[datetime, datetime], list[Candle]]:
    """Bars with lo <= open time that have CLOSED by `hi`. Never returns a bar from after `hi`."""
    bars = sorted(bars, key=lambda b: b.time)
    times = [b.time for b in bars]
    width = timedelta(minutes=minutes)

    def get(lo: datetime, hi: datetime) -> list[Candle]:
        return bars[bisect.bisect_left(times, lo):bisect.bisect_right(times, hi - width)]
    return get


def _phase_code(phase: str) -> str:
    return phase if phase.startswith("NEWS_") else "NEWS_" + phase


def run_backtest(symbol: str, candles: list[Candle], spec: dict[str, Any], *,
                 calendar: NewsCalendar | None = None, news_mode: str | None = None,
                 m5_candles: list[Candle] | None = None, equity_usd: float | None = None,
                 account_type: str = "Standard", usd_rates: dict[str, float] | None = None) -> dict[str, Any]:
    """`candles` are closed bars of the engine's base timeframe: M15, or M5 when M5 confirmation is on.
    `m5_candles` feed the upgraded guard's post-news stability check (default: `candles` when they are M5)."""
    mode = news_mode or ("legacy" if calendar is not None else "none")
    if mode not in NEWS_MODES:
        raise ValueError(f"news_mode must be one of {NEWS_MODES}")
    if mode != "none" and calendar is None:
        raise ValueError(f"news_mode {mode!r} needs a historical calendar")
    eng = MtfEngine(symbol, spec)
    cfg = RiskConfig.from_spec(spec)
    if mode == "none":
        # News is NOT modelled. Report says so; strict gate is relaxed for research only.
        cfg = RiskConfig(**{**cfg.__dict__, "strict_news": False})
    pip = eng.strat.pip
    slip = cfg.slippage_buffer_pips * pip
    tf = timedelta(minutes=TF_MINUTES[eng.base_tf])
    trades: list[Trade] = []
    awaiting: dict[str, Trade] = {}
    capital_checks: list[list[str]] = []

    guard = asof = None
    m5 = None
    if calendar is not None:
        guard, asof = NewsGuard(spec), AsOfCalendar(calendar)
        src = m5_candles if m5_candles is not None else (candles if eng.base_tf == "M5" else None)
        m5 = bar_source(src) if src else None
    seen: dict[datetime, NewsAssessment] = {}
    decision_times: list[datetime] = []

    def news_at(t: datetime) -> NewsAssessment:
        """Upgraded guard at `t`: the calendar as known then and M5 bars closed by then."""
        if t not in seen:
            decision_times.append(t)
            seen[t] = guard.assess(symbol, t, asof.at(t), m5=m5, pip=pip, live=False)
        return seen[t]

    def gate(sig: Signal, c: Candle, tr: Trade) -> tuple[list[str], list[str] | None]:
        t = sig.bar_close_utc
        news, extra = "CLEAR", []
        na = news_at(t) if guard is not None else None
        if na is not None:
            tr.news_phase = na.phase
        if mode == "legacy":
            news, _ = asof.at(t).status(symbol, t)  # same point-in-time view, legacy fixed window
        elif mode == "upgraded":
            news = na.status
            if not na.allows_entry:
                extra = [_phase_code(na.phase)] + [r for r in na.reasons if r != na.phase]
            elif na.next_block_start is not None:
                tr.expires_at = na.next_block_start  # the order must be gone before the next lockout
                if na.next_block_start - t < tf:
                    extra = ["NEWS_LOCKOUT_BEFORE_EXPIRY"]
        if mode != "none" and news == "CLEAR" and sig.score_breakdown.get("news_integrity", 0) == 0:
            sig.score_breakdown["news_integrity"] = 5
            sig.score += 5
        prop = TradeProposal(symbol, sig.direction, sig.entry, sig.stop, sig.targets, sig.spread, sig.atr,
                             0.0, True, news)
        inst = assumed_fx_spec(symbol, c.close, account_type, usd_rates)
        # sizing-independent gates (news, spread, stop tightness, RR) at a notional large equity
        blockers = evaluate(prop, inst, AccountState(equity_usd=1e6), cfg, live=False).blockers
        blockers += [b for b in extra if b not in blockers]
        cap = evaluate(prop, inst, AccountState(equity_usd=equity_usd), cfg, live=False).blockers \
            if equity_usd is not None else None
        return blockers, cap

    for i, c in enumerate(candles):
        # 1) manage existing orders on this bar (created on earlier bars only)
        for t in trades:
            if t.status == "PENDING":
                if mode == "upgraded":
                    na = news_at(c.time)  # what was known when this bar opened (N10)
                    if not na.allows_entry:
                        t.status = "INVALIDATED"
                        t.blockers = ["INVALIDATED", _phase_code(na.phase)] + [r for r in na.reasons if r != na.phase]
                        continue
                if t.expires_at is not None and c.time + tf > t.expires_at:
                    t.status, t.exit_reason = "EXPIRED", "NEWS_LOCKOUT_BEFORE_EXPIRY"
                    continue
                _pending(t, c, i, slip)
            elif t.status == "PENDING_MARKET":
                _market(t, c, i, slip)
            elif t.status == "OPEN":
                _open(t, c, i, slip, tf)
            if t.status == "CLOSED" and t.exit_time is None:
                t.exit_time = c.time + tf
        # 2) the engine sees the closed bar and may propose, confirm or drop setups
        for ev in eng.on_bar(c):
            sig = ev.signal
            if ev.kind == "SETUP":
                tr = Trade(sig, planned_loss=abs(sig.entry - sig.stop) + sig.spread + slip)
                blockers, cap = gate(sig, c, tr)
                if blockers:
                    tr.status, tr.blockers = "BLOCKED", blockers
                elif ev.needs_confirmation:
                    tr.status = "AWAITING_CONFIRMATION"
                    awaiting[sig.signal_id] = tr
                trades.append(tr)
                if cap is not None and not ev.needs_confirmation:
                    capital_checks.append(cap)
            elif ev.kind == "CONFIRM_FAILED":
                tr = awaiting.pop(sig.signal_id, None)
                if tr is not None:
                    tr.status, tr.exit_reason = "UNCONFIRMED", ev.reason
            elif ev.kind == "CONFIRMED":
                tr = awaiting.pop(sig.signal_id, None)
                if tr is None:
                    continue
                tr.signal = sig
                tr.planned_loss = abs(sig.entry - sig.stop) + sig.spread + slip
                blockers, cap = gate(sig, c, tr)  # re-check gates at the refined entry
                if cap is not None:
                    capital_checks.append(cap)
                if blockers:
                    tr.status, tr.blockers = "BLOCKED", blockers
                else:
                    tr.status = "PENDING_MARKET"  # market order fills at the NEXT bar's open

    for t in trades:
        if t.status in ("PENDING", "OPEN", "PENDING_MARKET", "AWAITING_CONFIRMATION"):
            t.status, t.exit_reason = "UNRESOLVED_END_OF_DATA", "END"
    return {"symbol": symbol, "trades": trades, "rejections": eng.rejections,
            "capital_checks": capital_checks, "news_modelled": mode != "none", "news_mode": mode,
            "news_integrity": asof.integrity(decision_times) if asof is not None else None,
            "news_stability_bars": "M5 closed bars" if m5 is not None else (
                "none: reaction watch held to its maximum" if guard is not None else None),
            "base_timeframe": eng.base_tf, "confirm_timeframe": eng.confirm_tf,
            "bars": len(candles), "start": candles[0].time if candles else None,
            "end": candles[-1].time if candles else None}


def _market(t: Trade, c: Candle, i: int, slip: float) -> None:
    """Confirmed entry: fill at this bar's open (BUY pays the spread), then a same-bar stop can hit."""
    s = t.signal
    if _after_flat_time(c.time):
        t.status = "EXPIRED"
        return
    t.status, t.fill_index, t.fill_time = "OPEN", i, c.time
    if s.direction == "BUY":
        t.fill_price = c.open + c.spread
        if c.low <= s.stop:
            _close(t, i, "SL", min(c.open, s.stop) - slip)
    else:
        t.fill_price = c.open
        if c.high >= s.stop:
            _close(t, i, "SL", max(c.open, s.stop) + c.spread + slip)


def _pending(t: Trade, c: Candle, i: int, slip: float) -> None:
    s = t.signal
    if i > s.expires_index or _after_flat_time(c.time):
        t.status = "EXPIRED"
        return
    tgt = s.targets[-1]
    if s.direction == "BUY":
        if c.low <= s.entry:
            t.status, t.fill_index, t.fill_time = "OPEN", i, c.time
            t.fill_price = min(c.open, s.entry) + c.spread  # gap-down opens fill at the better open
            if c.low <= s.stop:
                _close(t, i, "SL", min(c.open, s.stop) - slip)
        elif c.high >= tgt:
            t.status = "MISSED"
    else:
        if c.high >= s.entry:
            t.status, t.fill_index, t.fill_time = "OPEN", i, c.time
            t.fill_price = max(c.open, s.entry)
            if c.high >= s.stop:
                _close(t, i, "SL", max(c.open, s.stop) + c.spread + slip)
        elif c.low <= tgt:
            t.status = "MISSED"


def _open(t: Trade, c: Candle, i: int, slip: float, tf: timedelta) -> None:
    s = t.signal
    tgt = s.targets[-1]
    if s.direction == "BUY":
        if c.low <= s.stop:
            return _close(t, i, "SL", min(c.open, s.stop) - slip)
        if c.high >= tgt:
            return _close(t, i, "TP", tgt)
        if _after_flat_time(c.time + tf):
            return _close(t, i, "TIME", c.close)
    else:
        if c.high >= s.stop:
            return _close(t, i, "SL", max(c.open, s.stop) + c.spread + slip)
        if c.low <= tgt:
            return _close(t, i, "TP", tgt + c.spread)
        if _after_flat_time(c.time + tf):
            return _close(t, i, "TIME", c.close + c.spread)


def _close(t: Trade, i: int, reason: str, price: float) -> None:
    sgn = 1 if t.signal.direction == "BUY" else -1
    t.status, t.exit_index, t.exit_reason = "CLOSED", i, reason
    t.r = round(sgn * (price - t.fill_price) / t.planned_loss, 4)


# --- reporting ----------------------------------------------------------------------------

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, mid - half), min(1.0, mid + half))


def summarize(trades: list[Trade]) -> dict[str, Any]:
    closed = [t for t in trades if t.status == "CLOSED"]
    rs = [t.r for t in closed]
    wins = sum(1 for r in rs if r > 0)
    gross_win = sum(r for r in rs if r > 0)
    gross_loss = -sum(r for r in rs if r < 0)
    eq = peak = dd = 0.0
    streak = worst = 0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        streak = streak + 1 if r < 0 else 0
        worst = max(worst, streak)
    by_status: dict[str, int] = {}
    for t in trades:
        by_status[t.status] = by_status.get(t.status, 0) + 1
    lo, hi = wilson(wins, len(rs))
    return {
        "signals": len(trades),
        "by_status": by_status,
        "closed_trades": len(rs),
        "wins": wins,
        "win_rate": round(wins / len(rs), 3) if rs else None,
        "win_rate_95ci": (round(lo, 3), round(hi, 3)),
        "expectancy_r": round(sum(rs) / len(rs), 3) if rs else None,
        "total_r": round(sum(rs), 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "max_drawdown_r": round(dd, 2),
        "longest_losing_streak": worst,
        "exit_reasons": {k: sum(1 for t in closed if t.exit_reason == k) for k in ("TP", "SL", "TIME")},
        "small_sample_warning": len(rs) < 100,
    }


def split_report(trades: list[Trade], split_at: datetime) -> dict[str, Any]:
    ins = [t for t in trades if t.signal.bar_close_utc < split_at]
    oos = [t for t in trades if t.signal.bar_close_utc >= split_at]
    return {"in_sample": summarize(ins), "out_of_sample": summarize(oos), "split_at": split_at.isoformat()}


def capital_report(checks: list[list[str]]) -> dict[str, Any]:
    n = len(checks)
    min_lot = sum(1 for b in checks if "MIN_LOT_EXCEEDS_RISK" in b)
    return {"evaluated": n, "blocked_by_min_lot": min_lot,
            "tradeable_fraction": round((n - min_lot) / n, 3) if n else None}
