"""Validation report across pairs, modes and time (master spec section S).

Everything here is computed from replayed trades; nothing is assumed or filled in. A report
says which data it used, whether news was modelled, and flags small samples. There is no
parameter search: "walk-forward" here means the same frozen rules evaluated on consecutive,
non-overlapping time folds, so you can see whether results hold up over time.

News comparison (News spec P2, I04): the same candles and the same signals replayed with news not
modelled, the legacy 30/30 window and the upgraded guard on a point-in-time calendar. Only the
news gate differs, so every difference is a signal one mode blocked and another took. Money
figures are hypothetical replays at assumed Exness Standard contract values, never forecasts.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import datetime
from typing import Any

from ayesha.backtest.asof import NEWS_DIRECTION
from ayesha.backtest.replay import NEWS_MODES, Trade, summarize
from ayesha.feed.static_specs import assumed_fx_spec

MIN_SAMPLE = 100
EQUITIES = (20.0, 25.0, 30.0, 100.0, 500.0, 1000.0, 5000.0)
NEWS_BLOCKERS = ("NEWS_", "INVALIDATED")
REGIMES = {"CLEAR": "CLEAR", "UPCOMING": "UPCOMING", "PRE_EVENT_LOCKOUT": "IN_WINDOW", "EVENT_LIVE": "IN_WINDOW",
           "POST_EVENT_COOLDOWN": "IN_WINDOW", "REACTION_WATCH": "REACTION_WATCH", "NEWS_UNVERIFIED": "NEWS_UNVERIFIED"}


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
                        equities=EQUITIES, risks=(0.5, 1.0), account_type: str = "Standard",
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


def news_regime(t: Trade) -> str:
    """Where the signal sat relative to news, by the upgraded guard (also annotated when not gating)."""
    return REGIMES.get(t.news_phase, t.news_phase)


def _news_blocked(t: Trade) -> bool:
    return t.status in ("BLOCKED", "INVALIDATED") and any(b.startswith(NEWS_BLOCKERS) for b in t.blockers) \
        or t.exit_reason == "NEWS_LOCKOUT_BEFORE_EXPIRY"


def news_comparison(variants: dict[str, dict[str, Any]], split_at: datetime | None, slip: float) -> dict[str, Any]:
    """`variants` maps a news mode to run_backtest() output on the same candles."""
    out: dict[str, Any] = {"news_direction": NEWS_DIRECTION, "modes": {}}
    by_mode = {m: {t.signal.signal_id: t for t in variants[m]["trades"]} for m in NEWS_MODES if m in variants}
    for m, res in variants.items():
        tr = res["trades"]
        s = _compact(full_summary(tr, slip))
        s["stopped_by_news"] = sum(1 for t in tr if _news_blocked(t))
        if split_at:
            s["out_of_sample"] = _compact(full_summary([t for t in tr if t.signal.bar_close_utc >= split_at], slip))
        out["modes"][m] = s
    base = by_mode.get("none")
    for m in ("legacy", "upgraded"):
        if base is None or m not in by_mode:
            continue
        # signals the protection stopped, scored by what they did with news not modelled
        gone = [base[k] for k, t in by_mode[m].items() if k in base and base[k].status == "CLOSED" and t.status != "CLOSED"]
        rs = [t.r for t in gone]
        out[f"stopped_by_{m}"] = {"closed_without_news_model": len(rs), "their_total_r": round(sum(rs), 2),
                                 "their_expectancy_r": round(sum(rs) / len(rs), 3) if rs else None,
                                 "small_sample_warning": len(rs) < MIN_SAMPLE}
    return out


def adaptive_account(trades: list[Trade], spec: dict[str, Any], start_equity: float, risk_percent: float,
                     account_type: str = "Standard", usd_rates: dict[str, float] | None = None) -> dict[str, Any]:
    """One hypothetical account replayed in time order. Not predicted income.

    Each executed replay trade is sized from the equity after every earlier exit at `risk_percent`
    (the risk engine refuses anything above the 1% hard cap), floored to the 0.01 step, with the
    live hard gates: 2% daily loss, two losses per trading day, 1% total open risk, one position per
    currency direction. A trade the 0.01 minimum lot cannot fit is skipped (NO_TRADE), never sized
    up. Equity changes only through trade results (no deposits). Margin is not modelled here.
    """
    from ayesha.models import AccountState
    from ayesha.risk.engine import RiskConfig, TradeProposal, evaluate
    from ayesha.sessions import SessionEngine

    cfg = replace(RiskConfig.from_spec(spec), risk_per_trade_percent=risk_percent)
    done = sorted((t for t in trades if t.status == "CLOSED"), key=lambda t: (t.fill_time, t.signal.signal_id))
    eq = peak = float(start_equity)
    max_dd = worst_day = 0.0
    open_: list[tuple[datetime, float, float, str, str, datetime]] = []  # exit, usd, risk, pair, dir, day
    day_loss: dict[datetime, list[float]] = {}
    skipped: Counter = Counter()
    lots: list[float] = []

    def settle(until: datetime | None) -> None:
        nonlocal eq, peak, max_dd
        for o in sorted([o for o in open_ if until is None or o[0] <= until]):
            open_.remove(o)
            eq += o[1]
            if o[1] < 0:
                day_loss.setdefault(SessionEngine.trading_day(o[0]), []).append(-o[1])
            peak = max(peak, eq)
            max_dd = max(max_dd, (peak - eq) / peak * 100 if peak > 0 else 0.0)

    for t in done:
        settle(t.fill_time)
        if eq <= 0:
            skipped["EQUITY_EXHAUSTED"] += 1
            continue
        pair = getattr(t, "_pair", t.signal.symbol)
        s = t.signal
        losses = day_loss.get(SessionEngine.trading_day(t.fill_time), [])
        acct = AccountState(equity_usd=eq, realized_loss_today_usd=sum(losses), losses_today=len(losses),
                            open_risk_usd=sum(o[2] for o in open_), open_positions=[(o[3], o[4]) for o in open_])
        inst = assumed_fx_spec(pair, s.entry, account_type, usd_rates)
        d = evaluate(TradeProposal(pair, s.direction, s.entry, s.stop, s.targets, s.spread, s.atr, 0.0, True, "CLEAR"),
                     inst, acct, cfg, live=False)
        if not d.ok:
            skipped[d.blockers[0]] += 1
            continue
        usd = t.r * d.lot * t.planned_loss * inst.tick_value / inst.tick_size
        open_.append((t.exit_time or t.fill_time, usd, d.max_loss_usd, pair, s.direction,
                      SessionEngine.trading_day(t.fill_time)))
        lots.append(d.lot)
    settle(None)
    for day, ls in day_loss.items():
        worst_day = max(worst_day, sum(ls))
    return {"start_equity_usd": start_equity, "risk_percent": risk_percent, "executed_in_replay": len(done),
            "taken": len(lots), "skipped": dict(skipped), "final_equity_usd": round(eq, 2),
            "net_usd": round(eq - start_equity, 2), "return_percent": round((eq / start_equity - 1) * 100, 1),
            "max_drawdown_percent": round(max_dd, 1), "worst_day_loss_usd": round(worst_day, 2),
            "lot_range": [min(lots), max(lots)] if lots else None,
            "small_sample_warning": len(lots) < MIN_SAMPLE}


def build_report(results: dict[str, dict[str, Any]], spec: dict[str, Any], *, split_at: datetime | None,
                 folds: int, data_label: str, usd_rates: dict[str, float] | None = None,
                 comparisons: dict[str, dict[str, dict[str, Any]]] | None = None,
                 risks: tuple[float, ...] = (0.5, 1.0)) -> dict[str, Any]:
    """`results` maps "<PAIR>|<mode>" to run_backtest() output (the strictest news mode run).
    `comparisons` maps the same keys to {news mode: run_backtest() output} on the same candles."""
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
               "news_modelled": res["news_modelled"], "news_mode": res.get("news_mode", "none"),
               "news_integrity": res.get("news_integrity"), "news_stability_bars": res.get("news_stability_bars"),
               "summary": full_summary(tr, slip),
               "by_session": breakdown(tr, _key_session, slip),
               "by_direction": breakdown(tr, lambda t: t.signal.direction, slip),
               "by_h4_context": breakdown(tr, lambda t: t.signal.mtf.get("H4", "?"), slip),
               "walk_forward": walk_forward(tr, folds),
               "capital_exness_standard": capital_feasibility(tr, pair, slip, usd_rates=usd_rates)}
        if split_at:
            run["in_vs_out_of_sample"] = in_out_sample(tr, split_at, slip)
        if comparisons and key in comparisons:
            run["news_comparison"] = news_comparison(comparisons[key], split_at, slip)
            unprotected = comparisons[key].get("none")
            if unprotected is not None:
                run["by_news_regime_without_news_model"] = breakdown(unprotected["trades"], news_regime, slip)
        per_run[key] = run
    closed = sum(1 for t in all_trades if t.status == "CLOSED")
    modes = sorted({k.split("|")[1] for k in results})
    accounts = {m: [adaptive_account([t for t in all_trades if t._mode == m], spec, eq, rk, usd_rates=usd_rates)
                    for eq in EQUITIES for rk in risks] for m in modes}
    modelled = [r for r in per_run.values() if r["news_modelled"]]
    notes = [
        "Historical simulation on bar data with conservative fills (stop wins ties, fill bar cannot take profit).",
        "R includes spread and the slippage buffer. Scores are rule points, not probabilities.",
        "Lot feasibility uses assumed Exness Standard contract values (100,000 units, 0.01 min lot).",
        "No parameters were fitted; walk-forward folds show stability of frozen rules, not optimisation.",
        f"Fewer than {MIN_SAMPLE} closed trades is too small to conclude anything.",
        "Adaptive account rows are hypothetical replays of the hard risk rules, not predicted income; "
        "real fills, gaps and news slippage can lose more than the modelled stop.",
        f"{NEWS_DIRECTION}: no point-in-time actual/forecast history is used; news only blocks trades.",
    ]
    if not modelled:
        notes.append("NEWS NOT MODELLED: no historical calendar given, so the legacy vs upgraded news comparison "
                     "was NOT RUN (BLOCKED BY DATA); live strict mode blocks more setups than this replay.")
    return {
        "strategy_version": spec["strategy_version"], "strategy_hash": spec["strategy_hash"],
        "data": data_label,
        "news": {"modelled": bool(modelled), "direction": NEWS_DIRECTION,
                 "comparison_run": bool(comparisons),
                 "warnings": sorted({w for r in modelled for w in (r["news_integrity"] or {}).get("warnings", [])})},
        "overall": {"by_pair": breakdown(all_trades, lambda t: t._pair), "by_mode": breakdown(all_trades, lambda t: t._mode),
                    "closed_trades": closed, "sample_ok": closed >= MIN_SAMPLE},
        "adaptive_account": accounts,
        "runs": per_run,
        "notes": notes,
    }


def _na(v: Any) -> Any:
    return "n/a" if v is None else v


def to_markdown(rep: dict[str, Any]) -> str:
    L = [f"# AYESHA backtest report", "",
         f"Strategy {rep['strategy_version']} #{rep['strategy_hash']} · data: **{rep['data']}**", ""]
    ov = rep["overall"]
    L += [f"Closed trades overall: **{ov['closed_trades']}** " + ("" if ov["sample_ok"] else "(**too small to conclude**)"), ""]
    nw = rep.get("news", {})
    L += [f"News: {'modelled' if nw.get('modelled') else '**NOT modelled** (no historical calendar)'}; "
          f"legacy vs upgraded comparison {'run' if nw.get('comparison_run') else '**NOT RUN (BLOCKED BY DATA)**'}; "
          f"**{nw.get('direction', 'NEWS DIRECTION NOT BACKTESTED')}**.", ""]
    for w in nw.get("warnings", []):
        L.append(f"- ⚠️ {w}")
    if nw.get("warnings"):
        L.append("")
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
        if "news_comparison" in r:
            nc = r["news_comparison"]
            L += ["", f"News comparison on the same candles ({nc['news_direction']}):", "",
                  "| News mode | Signals | Stopped by news | Closed | Win rate (95% CI) | Expectancy R | Total R | Max DD R | OOS closed | OOS expectancy R |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
            for m, v in nc["modes"].items():
                oos = v.get("out_of_sample") or {}
                ci = v["win_rate_95ci"]
                wr = f"{v['win_rate']} ({ci[0]}–{ci[1]})" if v["win_rate"] is not None else "n/a"
                L.append(f"| {m} | {v['signals']} | {v['stopped_by_news']} | {v['closed_trades']} | {wr} | "
                         f"{_na(v['expectancy_r'])} | {v['total_r']} | {v['max_drawdown_r']} | {oos.get('closed_trades', '-')} | "
                         f"{_na(oos.get('expectancy_r', '-'))} |")
            for m in ("legacy", "upgraded"):
                g = nc.get(f"stopped_by_{m}")
                if g:
                    L.append(f"- {m} stopped {g['closed_without_news_model']} trades that closed with news not modelled: "
                             f"total {g['their_total_r']}R, expectancy {_na(g['their_expectancy_r'])}R"
                             + (" (sample too small)" if g["small_sample_warning"] else ""))
        if "by_news_regime_without_news_model" in r:
            L += ["News regime at the signal (news not modelled, so every regime traded): " + ", ".join(
                f"{k2} {v['closed_trades']}t/{v['expectancy_r']}R" for k2, v in r["by_news_regime_without_news_model"].items())]
        ni = r.get("news_integrity")
        if ni:
            L += [f"As-of calendar: {ni['provider']}, {ni['rows']} rows, coverage {ni['coverage_utc'][0][:10]}…"
                  f"{ni['coverage_utc'][1][:10]}, point-in-time schedule: {'yes' if ni['point_in_time_schedule'] else 'NO'}, "
                  f"decisions outside coverage {ni['decisions_outside_coverage']}/{ni['decisions']}; "
                  f"post-news stability from {r.get('news_stability_bars')}"]
        L += ["", "| Exness Standard equity | Risk % | Budget $ | Allowed by 0.01 lot | USD if taken | Verdict |", "|---|---|---|---|---|---|"]
        for c in r["capital_exness_standard"]:
            L.append(f"| ${c['equity_usd']:,.0f} | {c['risk_percent']} | {c['budget_usd']} | {c['allowed_by_min_lot']}/{c['closed_trades']} | "
                     f"{c['usd_result_if_taken']} | {c['verdict']} |")
    for m, rows in rep.get("adaptive_account", {}).items():
        L += ["", f"## Adaptive account, all pairs, mode {m} (hypothetical, not predicted income)", "",
              "| Start equity | Risk % | Taken / executed | Skipped (main reasons) | Final equity | Return % | Max DD % | Worst day $ | Lots |",
              "|---|---|---|---|---|---|---|---|---|"]
        for a in rows:
            sk = ", ".join(f"{k} {v}" for k, v in sorted(a["skipped"].items(), key=lambda kv: -kv[1])[:3]) or "-"
            lots = f"{a['lot_range'][0]:.2f}–{a['lot_range'][1]:.2f}" if a["lot_range"] else "-"
            L.append(f"| ${a['start_equity_usd']:,.0f} | {a['risk_percent']} | {a['taken']}/{a['executed_in_replay']} | {sk} | "
                     f"${a['final_equity_usd']:,.2f} | {a['return_percent']} | {a['max_drawdown_percent']} | "
                     f"{a['worst_day_loss_usd']} | {lots} |")
    L += ["", "## Notes", ""] + [f"- {n}" for n in rep["notes"]]
    return "\n".join(L) + "\n"
