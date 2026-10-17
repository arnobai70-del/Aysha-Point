"""After-cost metrics and split plans for the Strategy Lab (plan §6.4, §12; ticket AI-009).

All numbers are in R after the modelled costs (1R = planned loss including spread and slippage buffer). Every summary
keeps the denominator visible: signals, blocked (NO_TRADE) share and not-filled share, not just the trades that
survived. Confidence intervals are approximations (Wilson for win rate, normal for mean R) and are printed so a
small sample looks as uncertain as it is. Cells with fewer than `CELL_MIN` closed trades are `INSUFFICIENT_SAMPLE`.

Split plans are defined on the DATASET's time range, never on a strategy's trades, so every strategy in a
comparison is cut at exactly the same times: optional in-sample / out-of-sample date, `folds` equal consecutive
periods, and an optional sealed holdout (trades from that date on are counted but their results are not computed
until a run asks for them with `reveal_holdout`, which is written to the audit trail).
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta
from typing import Any, Callable

from ayesha.backtest.replay import wilson
from ayesha.research.provenance import digest, iso
from ayesha.research.simulation.runner import LabTrade

MIN_SAMPLE = 100   # same rule as the legacy report: fewer closed trades prove nothing
CELL_MIN = 30
NOT_FILLED = ("EXPIRED", "MISSED", "UNCONFIRMED")


def _r(x: float | None, n: int = 3) -> float | None:
    return None if x is None else round(x, n)


def summary(lts: list[LabTrade], bars: int | None = None) -> dict[str, Any]:
    n = len(lts)
    by: dict[str, int] = {}
    for lt in lts:
        by[lt.trade.status] = by.get(lt.trade.status, 0) + 1
    closed = [lt for lt in lts if lt.trade.status == "CLOSED"]
    rs = [lt.trade.r for lt in closed]
    k = len(rs)
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    lo, hi = wilson(len(wins), k)
    mean = sum(rs) / k if k else None
    sd = statistics.stdev(rs) if k >= 2 else None
    half = 1.96 * sd / math.sqrt(k) if sd is not None else None
    eq = peak = dd = 0.0
    streak = worst = 0
    since_peak = longest_under = 0
    for r in rs:
        eq += r
        if eq >= peak:
            peak, since_peak = eq, 0
        else:
            since_peak += 1
            longest_under = max(longest_under, since_peak)
        dd = max(dd, peak - eq)
        streak = streak + 1 if r < 0 else 0
        worst = max(worst, streak)
    gw, gl = sum(wins), -sum(r for r in rs if r < 0)
    srt = sorted(rs)
    q = (lambda p: srt[min(k - 1, max(0, int(round(p * (k - 1)))))]) if k else (lambda p: None)
    planned = [(abs(lt.trade.signal.targets[-1] - lt.trade.signal.entry) - lt.trade.signal.spread)
               / lt.trade.planned_loss for lt in closed if lt.trade.planned_loss > 0]
    held = sum((lt.trade.exit_index - lt.trade.fill_index + 1) for lt in closed
               if lt.trade.exit_index is not None and lt.trade.fill_index is not None)
    flags: dict[str, int] = {}
    for lt in lts:
        for f in lt.flags:
            flags[f] = flags.get(f, 0) + 1
    out = {
        "signals": n, "by_status": dict(sorted(by.items())), "closed_trades": k,
        "no_trade_share": _r(by.get("BLOCKED", 0) / n) if n else None,
        "not_filled_share": _r(sum(by.get(s, 0) for s in NOT_FILLED) / n) if n else None,
        "wins": len(wins), "losses": len(losses),
        "win_rate": _r(len(wins) / k) if k else None, "win_rate_95ci": [_r(lo), _r(hi)],
        "expectancy_r": _r(mean), "expectancy_r_95ci": [_r(mean - half), _r(mean + half)] if half is not None else None,
        "median_r": _r(statistics.median(rs)) if k else None, "total_r": _r(sum(rs), 2),
        "avg_win_r": _r(sum(wins) / len(wins)) if wins else None,
        "avg_loss_r": _r(sum(losses) / len(losses)) if losses else None,
        "planned_net_rr_mean": _r(sum(planned) / len(planned), 2) if planned else None,
        "planned_net_rr_median": _r(statistics.median(planned), 2) if planned else None,
        "profit_factor": _r(gw / gl, 2) if gl else None,
        "max_drawdown_r": _r(dd, 2), "longest_losing_streak": worst,
        "longest_trades_below_peak": longest_under,
        "r_p05": _r(q(0.05)), "r_p95": _r(q(0.95)), "worst_r": _r(srt[0]) if k else None,
        "best_r": _r(srt[-1]) if k else None,
        "sharpe_per_trade": _r(mean / sd, 3) if k >= CELL_MIN and sd else None,
        "exposure_share": _r(held / bars) if bars else None,
        "exit_reasons": {x: sum(1 for lt in closed if lt.trade.exit_reason == x) for x in ("TP", "SL", "TIME")},
        "intrabar_flags": dict(sorted(flags.items())),
        "small_sample": k < MIN_SAMPLE,
    }
    return out


def compact(s: dict[str, Any]) -> dict[str, Any]:
    keep = ("signals", "closed_trades", "no_trade_share", "win_rate", "win_rate_95ci", "expectancy_r",
            "expectancy_r_95ci", "total_r", "profit_factor", "max_drawdown_r", "small_sample")
    out = {k: s[k] for k in keep}
    out["sample"] = "INSUFFICIENT_SAMPLE" if s["closed_trades"] < CELL_MIN else "OK"
    return out


# --- split plans -------------------------------------------------------------------------------

def split_plan(start: datetime, end: datetime, folds: int = 4, split_at: datetime | None = None,
               holdout_from: datetime | None = None) -> dict[str, Any]:
    if folds < 2:
        raise ValueError("folds must be at least 2")
    stop = holdout_from or end
    if split_at is not None and not start < split_at < stop:
        raise ValueError("the in-sample / out-of-sample date must lie inside the data (before any holdout)")
    if holdout_from is not None and not start < holdout_from < end:
        raise ValueError("the holdout date must lie inside the data")
    span = (stop - start) / folds
    bounds = [(start + span * k, start + span * (k + 1)) for k in range(folds)]
    plan = {"range": [iso(start), iso(end)], "folds": [[iso(a), iso(b)] for a, b in bounds],
            "split_at": iso(split_at), "holdout_from": iso(holdout_from),
            "assignment": "each order belongs to the period of the bar close that produced it"}
    plan["split_plan_id"] = "sp_" + digest(plan)[:16]
    return plan


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def periods(lts: list[LabTrade], plan: dict[str, Any], reveal_holdout: bool = False,
            bars: int | None = None) -> dict[str, Any]:
    hold = _t(plan["holdout_from"]) if plan["holdout_from"] else None
    visible = [lt for lt in lts if hold is None or lt.created_at < hold]
    sealed = [lt for lt in lts if hold is not None and lt.created_at >= hold]
    out: dict[str, Any] = {"all": summary(visible, bars)}
    folds = []
    for a, b in plan["folds"]:
        ta, tb = _t(a), _t(b)
        last = b == plan["folds"][-1][1]
        part = [lt for lt in visible if ta <= lt.created_at < tb or (last and lt.created_at == tb)]
        straddle = sum(1 for lt in part if lt.ended_at is not None and lt.ended_at > tb)
        f = compact(summary(part))
        f.update({"from": a, "to": b, "orders_ending_after_fold": straddle})
        folds.append(f)
    with_trades = [f for f in folds if f["expectancy_r"] is not None]
    out["folds"] = folds
    out["positive_folds"] = sum(1 for f in with_trades if f["expectancy_r"] > 0)
    out["folds_with_trades"] = len(with_trades)
    if plan["split_at"]:
        s = _t(plan["split_at"])
        out["in_sample"] = compact(summary([lt for lt in visible if lt.created_at < s]))
        out["out_of_sample"] = compact(summary([lt for lt in visible if lt.created_at >= s]))
    if hold is not None:
        out["holdout"] = ({"state": "REVEALED", **compact(summary(sealed))} if reveal_holdout else
                          {"state": "SEALED", "orders": len(sealed),
                           "note": "results not computed; reveal once, after every decision about the rules is made"})
    return out


def breakdown(lts: list[LabTrade], key: Callable[[LabTrade], str]) -> dict[str, Any]:
    groups: dict[str, list[LabTrade]] = {}
    for lt in lts:
        groups.setdefault(key(lt), []).append(lt)
    return {k: compact(summary(v)) for k, v in sorted(groups.items())}


def session_key(lt: LabTrade) -> str:
    s = set(lt.trade.signal.session)
    if {"LONDON", "NEW_YORK"} <= s:
        return "LONDON+NEW_YORK"
    return "+".join(sorted(s)) or "NONE"


def breakdowns(lts: list[LabTrade]) -> dict[str, Any]:
    return {"symbol": breakdown(lts, lambda lt: lt.symbol),
            "session": breakdown(lts, session_key),
            "direction": breakdown(lts, lambda lt: lt.trade.signal.direction),
            "timeframe": breakdown(lts, lambda lt: "M15"),
            "regime": breakdown(lts, lambda lt: lt.regime),
            "news_phase": breakdown(lts, lambda lt: lt.trade.news_phase)}


def regime_matrix(lts: list[LabTrade], labels) -> dict[str, Any]:
    """One cell per regime label (empty ones included), each marked INSUFFICIENT_SAMPLE below `CELL_MIN`."""
    return {k: compact(summary([lt for lt in lts if lt.regime == k])) for k in labels}


def without_best(lts: list[LabTrade], share: float = 0.05) -> dict[str, Any]:
    closed = sorted((lt for lt in lts if lt.trade.status == "CLOSED"), key=lambda lt: lt.trade.r, reverse=True)
    n = max(1, int(math.ceil(len(closed) * share))) if closed else 0
    drop = {id(lt) for lt in closed[:n]}
    s = compact(summary([lt for lt in lts if id(lt) not in drop]))
    s["removed_best_trades"] = n
    return s


def mean_diff(a: list[float], b: list[float]) -> dict[str, Any]:
    """Difference of mean R (a - b) with an approximate 95 % interval (Welch). Trades are treated as independent,
    which overlapping trades are not, so the interval is optimistic rather than conservative."""
    if len(a) < 2 or len(b) < 2:
        return {"difference_r": None, "ci95": None, "verdict": "INSUFFICIENT_SAMPLE"}
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    se = math.sqrt(statistics.variance(a) / len(a) + statistics.variance(b) / len(b))
    d = ma - mb
    lo, hi = d - 1.96 * se, d + 1.96 * se
    verdict = "NOT_DISTINGUISHABLE" if lo <= 0 <= hi else ("HIGHER_IN_THIS_SAMPLE" if lo > 0 else
                                                           "LOWER_IN_THIS_SAMPLE")
    if min(len(a), len(b)) < MIN_SAMPLE:
        verdict = "INSUFFICIENT_SAMPLE"
    return {"difference_r": round(d, 3), "ci95": [round(lo, 3), round(hi, 3)], "verdict": verdict}


def closed_rs(lts: list[LabTrade]) -> list[float]:
    return [lt.trade.r for lt in lts if lt.trade.status == "CLOSED"]


def time_range(candle_sets: list[list]) -> tuple[datetime, datetime]:
    starts = [c[0].time for c in candle_sets if c]
    ends = [c[-1].time + timedelta(minutes=15) for c in candle_sets if c]
    if not starts:
        raise ValueError("no bars")
    return min(starts), max(ends)
