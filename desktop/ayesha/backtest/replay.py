"""Bar-by-bar replay backtester (master spec section S).

Causality: at bar i the strategy sees bars 0..i only; orders it creates can first fill on
bar i+1. Fill model matches the risk engine: every order triggers when the BID touches its
level and the round trip pays one spread (the spread recorded on the fill bar).
Conservative choices: if a bar touches both stop and target, the stop wins; a fill bar
can stop out but cannot take profit; gaps through the stop exit at the bar open;
stop exits pay extra slippage. Open trades are closed before the New York rollover.
Results are in R (1R = planned loss incl. spread and slippage buffer), not money.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ayesha.models import AccountState, Candle
from ayesha.feed.static_specs import assumed_fx_spec
from ayesha.news.calendar import NewsCalendar
from ayesha.risk.engine import RiskConfig, TradeProposal, evaluate
from ayesha.rules.strategy import TF_MINUTES, Signal, SweepMssFvg

NY = ZoneInfo("America/New_York")
FLAT_TIME = time(16, 45)


@dataclass
class Trade:
    signal: Signal
    status: str = "PENDING"  # PENDING | OPEN | CLOSED | MISSED | EXPIRED | BLOCKED
    fill_index: int | None = None
    fill_price: float | None = None
    exit_index: int | None = None
    exit_reason: str | None = None
    r: float | None = None
    blockers: list[str] = field(default_factory=list)
    planned_loss: float = 0.0
    fill_time: datetime | None = None


def _after_flat_time(t: datetime) -> bool:
    return t.astimezone(NY).time() >= FLAT_TIME


def run_backtest(symbol: str, candles: list[Candle], spec: dict[str, Any], *,
                 calendar: NewsCalendar | None = None, equity_usd: float | None = None,
                 account_type: str = "Standard", usd_rates: dict[str, float] | None = None) -> dict[str, Any]:
    strat = SweepMssFvg(symbol, spec)
    cfg = RiskConfig.from_spec(spec)
    if calendar is None:
        # No calendar => news is NOT modelled. Report says so; strict gate is relaxed for research only.
        cfg = RiskConfig(**{**cfg.__dict__, "strict_news": False})
    pip = strat.pip
    slip = cfg.slippage_buffer_pips * pip
    tf = timedelta(minutes=TF_MINUTES[spec["entry"]["setup_timeframe"]])
    trades: list[Trade] = []
    capital_checks: list[list[str]] = []

    for i, c in enumerate(candles):
        # 1) manage existing orders on this bar (created on earlier bars only)
        for t in trades:
            if t.status == "PENDING":
                _pending(t, c, i, slip)
            elif t.status == "OPEN":
                _open(t, c, i, slip, tf)
        # 2) strategy sees the closed bar and may propose new orders
        for sig in strat.on_bar(c):
            news = "CLEAR"
            if calendar is not None:
                news, _ = calendar.status(symbol, sig.bar_close_utc)
                if news == "CLEAR":
                    sig.score_breakdown["news_integrity"] = 5
                    sig.score += 5
            prop = TradeProposal(symbol, sig.direction, sig.entry, sig.stop, sig.targets, sig.spread, sig.atr,
                                 0.0, True, news)
            inst = assumed_fx_spec(symbol, c.close, account_type, usd_rates)
            # sizing-independent gates (news, spread, stop tightness, RR) at a notional large equity
            d = evaluate(prop, inst, AccountState(equity_usd=1e6), cfg, live=False)
            tr = Trade(sig, planned_loss=abs(sig.entry - sig.stop) + sig.spread + slip)
            if d.blockers:
                tr.status, tr.blockers = "BLOCKED", d.blockers
            trades.append(tr)
            if equity_usd is not None:
                capital_checks.append(evaluate(prop, inst, AccountState(equity_usd=equity_usd), cfg, live=False).blockers)

    for t in trades:
        if t.status in ("PENDING", "OPEN"):
            t.status, t.exit_reason = "UNRESOLVED_END_OF_DATA", "END"
    return {"symbol": symbol, "trades": trades, "rejections": strat.rejections,
            "capital_checks": capital_checks, "news_modelled": calendar is not None,
            "bars": len(candles), "start": candles[0].time if candles else None,
            "end": candles[-1].time if candles else None}


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
