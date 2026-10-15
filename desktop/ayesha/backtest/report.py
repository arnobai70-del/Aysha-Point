"""Validation report across pairs, modes and time (master spec section S).

Everything here is computed from replayed trades; nothing is assumed or filled in. A report
says which data it used, whether news was modelled, and flags small samples. There is no
parameter search: "walk-forward" here means the same frozen rules evaluated on consecutive,
non-overlapping time folds, so you can see whether results hold up over time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ayesha.backtest.replay import Trade, summarize
from ayesha.feed.static_specs import assumed_fx_spec

MIN_SAMPLE = 100


def _planned_rr(t: Trade, slip: float) -> float:
    s = t.signal
    loss = abs(s.entry - s.stop) + s.spread + slip
    return (abs(s.targets[-1] - s.entry) - s.spread) / loss if loss > 0 else 0.0


def full_summary(trades: list[Trade], slip: float = 0.0) -> dict[str, Any]:
    base = summarize(trades)
    closed = [t for t in trades if t.status == "CLOSED"]
    rs = [t.r for t in closed]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    base.update({
        "losses": len(losses),
        "loss_rate": round(len(losses) / len(rs), 3) if rs else None,
        "avg_win_r": round(sum(wins) / len(wins), 3) if wins else None,
        "avg_loss_r": round(sum(losses) / len(losses), 3) if losses else None,
        "avg_planned_net_rr": round(sum(_planned_rr(t, slip) for t in closed) / len(closed), 2) if closed else None,
        "net_expectancy_r_after_costs": base["expectancy_r"],  # R already includes spread + slippage
    })
    return base


def _key_session(t: Trade) -> str:
    s = set(t.signal.session)
    if {"LONDON", "NEW_YORK"} <= s:
        return "LONDON+NEW_YORK"
    return "+".join(sorted(s)) or "NONE"


def breakdown(trades: list[Trade], key, slip: float = 0.0) -> dict[str, Any]:
    groups: dict[str, list[Trade]] = {}
    for t in trades:
        groups.setdefault(key(t), []).append(t)
    return {k: _compact(full_summary(v, slip)) for k, v in sorted(groups.items())}


def _compact(s: dict[str, Any]) -> dict[str, Any]:
    keep = ("signals", "closed_trades", "win_rate", "win_rate_95ci", "expectancy_r", "total_r", "profit_factor",
            "max_drawdown_r", "small_sample_warning")
    return {k: s[k] for k in keep}


def walk_forward(trades: list[Trade], folds: int = 4) -> dict[str, Any]:
    """Frozen rules, consecutive time folds. No fitting happens on any fold."""
    ts = sorted(trades, key=lambda t: t.signal.bar_close_utc)
    if not ts or folds < 2:
        return {"folds": []}
    lo, hi = ts[0].signal.bar_close_utc, ts[-1].signal.bar_close_utc
    span = (hi - lo) / folds
    out = []
    for k in range(folds):
        a, b = lo + span * k, lo + span * (k + 1)
        part = [t for t in ts if a <= t.signal.bar_close_utc < b or (k == folds - 1 and t.signal.bar_close_utc == hi)]
        s = _compact(summarize(part))
        s.update({"from": a.isoformat(), "to": b.isoformat()})
        out.append(s)
    pos = [f for f in out if f["expectancy_r"] is not None]
    return {"folds": out, "positive_folds": sum(1 for f in pos if f["expectancy_r"] > 0), "folds_with_trades": len(pos)}


def in_out_sample(trades: list[Trade], split_at: datetime, slip: float = 0.0) -> dict[str, Any]:
    ins = [t for t in trades if t.signal.bar_close_utc < split_at]
    oos = [t for t in trades if t.signal.bar_close_utc >= split_at]
    return {"split_at": split_at.isoformat(), "in_sample": _compact(full_summary(ins, slip)),
            "out_of_sample": _compact(full_summary(oos, slip))}


def capital_feasibility(trades: list[Trade], symbol: str, slip: float,
                        equities=(20.0, 25.0, 30.0), risks=(0.5, 1.0), account_type: str = "Standard",
                        usd_rates: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """For each $ equity and risk %: how many executed trades the 0.01 minimum lot allowed, and the
    USD result if only those were taken at the floored lot. Uses ASSUMED Exness contract values."""
    closed = [t for t in trades if t.status == "CLOSED"]
    rows = []
    for eq in equities:
        for rk in risks:
            budget = eq * rk / 100
            allowed = 0
            usd = 0.0
            for t in closed:
                inst = assumed_fx_spec(symbol, t.signal.entry, account_type, usd_rates)
                per_lot = t.planned_loss / inst.tick_size * inst.tick_value
                lot = int(budget / per_lot / inst.volume_step + 1e-9) * inst.volume_step
                if lot >= inst.volume_min:
                    allowed += 1
                    usd += t.r * lot * per_lot
            rows.append({"equity_usd": eq, "risk_percent": rk, "budget_usd": round(budget, 3),
                         "closed_trades": len(closed), "allowed_by_min_lot": allowed,
                         "usd_result_if_taken": round(usd, 2),
                         "verdict": "NO_TRADE almost always" if closed and allowed / len(closed) < 0.1 else
                                    ("feasible for some setups" if allowed else "no trades possible")})
    return rows


def build_report(results: dict[str, dict[str, Any]], spec: dict[str, Any], *, split_at: datetime | None,
                 folds: int, data_label: str, usd_rates: dict[str, float] | None = None) -> dict[str, Any]:
    """`results` maps "<PAIR>|<mode>" to run_backtest() output."""
    from ayesha.models import pip_size_for

    all_trades: list[Trade] = []
    per_run = {}
    for key, res in results.items():
        pair, mode = key.split("|")
        slip = spec["risk"]["slippage_buffer_pips"] * pip_size_for(pair)
        tr = res["trades"]
        for t in tr:
            t._pair, t._mode = pair, mode  # type: ignore[attr-defined]
        all_trades += tr
        run = {"pair": pair, "mode": mode, "bars": res["bars"], "start": str(res["start"]), "end": str(res["end"]),
               "news_modelled": res["news_modelled"], "summary": full_summary(tr, slip),
               "by_session": breakdown(tr, _key_session, slip),
               "by_direction": breakdown(tr, lambda t: t.signal.direction, slip),
               "by_h4_context": breakdown(tr, lambda t: t.signal.mtf.get("H4", "?"), slip),
               "walk_forward": walk_forward(tr, folds),
               "capital_exness_standard": capital_feasibility(tr, pair, slip, usd_rates=usd_rates)}
        if split_at:
            run["in_vs_out_of_sample"] = in_out_sample(tr, split_at, slip)
        per_run[key] = run
    closed = sum(1 for t in all_trades if t.status == "CLOSED")
    return {
        "strategy_version": spec["strategy_version"], "strategy_hash": spec["strategy_hash"],
        "data": data_label,
        "overall": {"by_pair": breakdown(all_trades, lambda t: t._pair), "by_mode": breakdown(all_trades, lambda t: t._mode),
                    "closed_trades": closed, "sample_ok": closed >= MIN_SAMPLE},
        "runs": per_run,
        "notes": [
            "Historical simulation on bar data with conservative fills (stop wins ties, fill bar cannot take profit).",
            "R includes spread and the slippage buffer. Scores are rule points, not probabilities.",
            "Lot feasibility uses assumed Exness Standard contract values (100,000 units, 0.01 min lot).",
            "No parameters were fitted; walk-forward folds show stability of frozen rules, not optimisation.",
            f"Fewer than {MIN_SAMPLE} closed trades is too small to conclude anything.",
        ],
    }


def to_markdown(rep: dict[str, Any]) -> str:
    L = [f"# AYESHA backtest report", "",
         f"Strategy {rep['strategy_version']} #{rep['strategy_hash']} · data: **{rep['data']}**", ""]
    ov = rep["overall"]
    L += [f"Closed trades overall: **{ov['closed_trades']}** " + ("" if ov["sample_ok"] else "(**too small to conclude**)"), ""]
    L += ["| Run | Bars | Closed | Win rate (95% CI) | Expectancy R | PF | Max DD R | News |", "|---|---|---|---|---|---|---|---|"]
    for k, r in rep["runs"].items():
        s = r["summary"]
        ci = s["win_rate_95ci"]
        L.append(f"| {k} | {r['bars']} | {s['closed_trades']} | {s['win_rate']} ({ci[0]}–{ci[1]}) | {s['expectancy_r']} | "
                 f"{s['profit_factor']} | {s['max_drawdown_r']} | {'yes' if r['news_modelled'] else 'NO'} |")
    for k, r in rep["runs"].items():
        L += ["", f"## {k}", "", f"{r['start']} → {r['end']}", ""]
        s = r["summary"]
        L.append(f"Signals {s['signals']}, closed {s['closed_trades']}, wins {s['wins']}, losses {s['losses']}, "
                 f"avg win {s['avg_win_r']}R, avg loss {s['avg_loss_r']}R, avg planned net RR {s['avg_planned_net_rr']}, "
                 f"longest losing streak {s['longest_losing_streak']}. Status counts: {s['by_status']}")
        if "in_vs_out_of_sample" in r:
            io = r["in_vs_out_of_sample"]
            L += ["", f"In-sample vs out-of-sample (split {io['split_at'][:10]}):",
                  f"- in: {io['in_sample']}", f"- out: {io['out_of_sample']}"]
        wf = r["walk_forward"]
        if wf["folds"]:
            L += ["", f"Walk-forward folds (frozen rules): {wf['positive_folds']}/{wf['folds_with_trades']} with positive expectancy"]
            for f in wf["folds"]:
                L.append(f"- {f['from'][:10]}…{f['to'][:10]}: closed {f['closed_trades']}, exp {f['expectancy_r']}R, PF {f['profit_factor']}")
        L += ["", "By session: " + ", ".join(f"{k2} {v['closed_trades']}t/{v['expectancy_r']}R" for k2, v in r["by_session"].items())]
        L += ["By H4 context: " + ", ".join(f"{k2} {v['closed_trades']}t/{v['expectancy_r']}R" for k2, v in r["by_h4_context"].items())]
        L += ["", "| Exness Standard equity | Risk % | Budget $ | Allowed by 0.01 lot | USD if taken | Verdict |", "|---|---|---|---|---|---|"]
        for c in r["capital_exness_standard"]:
            L.append(f"| ${c['equity_usd']:.0f} | {c['risk_percent']} | {c['budget_usd']} | {c['allowed_by_min_lot']}/{c['closed_trades']} | "
                     f"{c['usd_result_if_taken']} | {c['verdict']} |")
    L += ["", "## Notes", ""] + [f"- {n}" for n in rep["notes"]]
    return "\n".join(L) + "\n"
