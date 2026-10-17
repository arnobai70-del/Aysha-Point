"""Sanitised run reports (Markdown and JSON) for `ayesha research report` and the dashboard export.

The body is the unchanged legacy `ayesha.backtest.report.to_markdown` for the stored legacy report, so numbers and
layout match `ayesha report` on the same bars; a research header pins every input and says what the numbers are
not. Text is redacted before it leaves the program (no token, pairing code, Bearer header or Windows user name).
"""

from __future__ import annotations

import json
from typing import Any

from ayesha.research.redact import redact, redact_obj
from ayesha.research.simulation.baseline import load_result
from ayesha.research.workspace import Workspace

DISCLAIMER = ("RESEARCH ONLY. A historical simulation on frozen data: not a forecast, not a trade signal, never READY "
              "and never sent to the phone. No validated trading edge exists yet; small samples prove nothing.")


def run_json(ws: Workspace, run_id: str) -> dict[str, Any]:
    res = load_result(ws, run_id)
    ds = ws.db.dataset(res["dataset_id"])
    out = dict(res)
    out["dataset"] = json.loads(ds["manifest_json"]) if ds is not None else None
    out["disclaimer"] = DISCLAIMER
    return redact_obj(out)


def run_markdown(ws: Workspace, run_id: str) -> str:
    from ayesha.backtest.report import to_markdown

    res = load_result(ws, run_id)
    ds = ws.db.dataset(res["dataset_id"])
    m = json.loads(ds["manifest_json"]) if ds is not None else {}
    src = m.get("source", {})
    rng = m.get("range_utc", {})
    inputs = [
        ("Strategy", f"{res['strategy_id']} {res['strategy_version']} (hash {res['strategy_hash']}), parameters "
                     f"{res['parameters_hash'][:12]}"),
        ("Dataset", f"{res['dataset_id']}: {src.get('provider', '?')} ({src.get('label', '')}), "
                    f"{', '.join(m.get('symbols', []))} {', '.join(m.get('timeframes', []))}, "
                    f"{rng.get('start')} to {rng.get('end')}, quality {res['dataset_quality']}"),
        ("Data licence", m.get("license_notes", "?")),
        ("Costs", res["cost_model_id"]),
        ("Account scenario", res["account_scenario_id"]),
        ("News", res["news_snapshot_id"] + (f" ({res['metrics']['news']['mode']} handling)"
                                             if (res["metrics"].get("news") or {}).get("mode", "none") != "none"
                                             else "")),
        ("Split", res["split_plan_id"]),
        ("Code", f"commit {res['commit_sha'][:12]}, desktop {res['desktop_version']}"),
        ("Hashes", f"inputs {res['inputs_hash'][:16]}, result {res['result_sha256'][:16]}, candidates "
                   f"{res['candidates_sha256'][:16]}, environment {res['environment_hash'][:16]}"),
        ("Run", f"{res['started_at_utc']} to {res['completed_at_utc']}"),
    ]
    lines = [f"# AYESHA research run {res['run_id']}", "", f"> {DISCLAIMER}", "", "| Input | Value |", "|---|---|"]
    lines += [f"| {k} | {str(v).replace('|', '/')} |" for k, v in inputs]
    lines += ["", "## Limitations", ""] + [f"- {x}" for x in res["limitations"]]
    lines += [f"- Data: {x}" for x in m.get("limitations", [])]
    if res["warnings"]:
        lines += ["", "## Warnings", ""] + [f"- {x}" for x in res["warnings"]]
    mt = res["metrics"]
    if res.get("engine") == "research-runner-1":
        return redact("\n".join(lines + _lab_sections(res)) + "\n")
    lines += ["", "## Research summary", "",
              f"Signals {mt['summary']['signals']}, closed {mt['summary']['closed_trades']}, blocked share "
              f"{mt['no_trade_share']}, not filled share {mt['not_filled_share']}, rejected setups "
              f"{mt['rejections']}, bars {mt['bars']} ({mt['base_timeframe']} base, confirmation "
              f"{mt['confirm_timeframe'] or 'none'}).", ""]
    body = to_markdown(mt["legacy_report"]).replace("# AYESHA backtest report", "## Legacy replay report "
                                                                                 "(same code as `ayesha report`)", 1)
    return redact("\n".join(lines) + "\n" + body)


# --- Strategy Lab runs and comparisons (v1.0.0) -------------------------------------------------

def _v(x: Any) -> str:
    if x is None:
        return "-"
    if isinstance(x, list):
        return "[" + ", ".join(_v(y) for y in x) + "]"
    return str(x).replace("|", "/")


def _table(head: list[str], rows: list[list[Any]]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(_v(c) for c in r) + " |" for r in rows]
    return out


CELLS = ("closed_trades", "win_rate", "expectancy_r", "expectancy_r_95ci", "total_r", "profit_factor",
         "max_drawdown_r", "sample")


def _lab_sections(res: dict[str, Any]) -> list[str]:
    mt = res["metrics"]
    s = mt["summary"]
    out = ["", "## Summary (after costs, in R)", "",
           f"Symbols {', '.join(res.get('symbols', []))}; bars {mt['bars']} (M15); engine {mt['engine']}.", ""]
    keys = ("signals", "closed_trades", "no_trade_share", "not_filled_share", "win_rate", "win_rate_95ci",
            "expectancy_r", "expectancy_r_95ci", "median_r", "total_r", "avg_win_r", "avg_loss_r",
            "planned_net_rr_median", "profit_factor", "max_drawdown_r", "longest_losing_streak",
            "longest_trades_below_peak", "r_p05", "r_p95", "worst_r", "best_r", "sharpe_per_trade",
            "exposure_share", "exit_reasons", "intrabar_flags")
    out += _table(["Metric", "Value"], [[k, s[k]] for k in keys])
    out += ["", f"Rejected setups: {mt['rejections'] or 'none'}"]
    out += ["", "## Walk-forward folds", ""]
    out += _table(["From", "To", "Signals", *CELLS, "Ending after fold"],
                  [[f["from"], f["to"], f["signals"], *[f[c] for c in CELLS], f["orders_ending_after_fold"]]
                   for f in mt["folds"]])
    out += ["", f"Positive folds: {mt['positive_folds']} of {mt['folds_with_trades']} with trades."]
    for name in ("in_sample", "out_of_sample"):
        if mt.get(name):
            out += ["", f"{name.replace('_', ' ').capitalize()}: " + ", ".join(f"{c} {_v(mt[name][c])}"
                                                                              for c in CELLS)]
    if mt.get("holdout"):
        h = mt["holdout"]
        out += ["", f"Holdout: {h['state']}" + (f", {h['orders']} orders sealed ({h['note']})" if h["state"] ==
                                                 "SEALED" else ": " + ", ".join(f"{c} {_v(h[c])}" for c in CELLS))]
    out += ["", "## Breakdowns", ""]
    for group, cells in mt["breakdowns"].items():
        rows = [[f"{group}={k}", *[v.get(c) for c in CELLS]] for k, v in cells.items() if "closed_trades" in v]
        if rows:
            out += _table(["Cell", *CELLS], rows) + [""]
    reg = mt.get("regime")
    if reg:
        det = reg["detector"]
        out += ["## Strategy x regime (label known when each order was decided)", "",
                f"Detector {det['detector_id']} {det['version']} (code {det['code_sha256'][:12]}): {reg['note']}.", ""]
        out += _table(["Regime", *CELLS, "Sample"], [[k, *[v.get(c) for c in CELLS], v["sample"]]
                                                     for k, v in reg["matrix"].items()])
    else:
        out += ["Regime: not recorded by this program version."]
    nc = mt.get("news_comparison")
    if nc:
        out += ["", f"## News comparison: {nc['status']}", "", nc["note"], ""]
        if nc.get("modes"):
            out += _table(["News handling", *CELLS, "Sample"], [[k, *[v.get(c) for c in CELLS], v["sample"]]
                                                                for k, v in nc["modes"].items()])
    rob = mt.get("robustness")
    if rob:
        out += ["", "## Robustness", "", "Cost sensitivity (one change at a time):", ""]
        out += _table(["Cost model", *CELLS], [[k, *[v[c] for c in CELLS]] for k, v in rob["costs"].items()])
        out += ["", "Parameter perturbation (one step either side, within bounds):", ""]
        if "note" in rob["parameters"]:
            out += [rob["parameters"]["note"]]
        else:
            out += _table(["Parameter", *CELLS], [[k, *[v.get(c) for c in CELLS]] if "error" not in v else
                                                  [k, v["error"], *[None] * (len(CELLS) - 1)]
                                                  for k, v in rob["parameters"].items()])
        w = rob["without_best_5_percent"]
        out += ["", f"Without the best {w['removed_best_trades']} trades (5 %): expectancy {_v(w['expectancy_r'])}, "
                    f"total {_v(w['total_r'])}.",
                f"Without stop-and-target-on-one-bar trades: expectancy "
                f"{_v(rob['excluding_intrabar_ambiguous']['expectancy_r'])}."]
    out += ["", "## Hypothetical accounts (live risk engine, ASSUMED contract values)", ""]
    out += _table(["Equity USD", "Taken", "Closed", "End USD", "Return %", "Max DD %", "Worst day USD",
                   "First blockers"],
                  [[a["equity_start_usd"], a["taken"], a["closed"], a["equity_end_usd"], a["return_percent"],
                    a["max_drawdown_percent"], a["worst_day_usd"], a["skipped"]] for a in mt["account_scenarios"]])
    if mt.get("benchmark_parity"):
        bp = mt["benchmark_parity"]
        out += ["", f"## Benchmark parity: {bp['status']}", "", bp["note"], ""]
        out += _table(["Symbol", "Orders (runner, legacy)", "Equal"],
                      [[k, v["orders"], v["equal"]] for k, v in bp["per_symbol"].items()])
    return out


def comparison_json(doc: dict[str, Any]) -> dict[str, Any]:
    return redact_obj({**doc, "disclaimer": DISCLAIMER})


def comparison_markdown(doc: dict[str, Any]) -> str:
    lines = [f"# AYESHA Strategy Lab comparison {doc['comparison_id']}", "", f"> {DISCLAIMER}", "",
             f"Dataset {doc['dataset_id']}, symbols {', '.join(doc['symbols'])}, split {doc['split_plan_id']}, "
             f"costs {doc['cost_model_id']}, accounts {doc['account_scenario_id']}, created {doc['created_at_utc']}.",
             ""]
    lines += _table(["Run", "Strategy", "Kind", "Version", "Hash"],
                    [[r["run_id"], r["strategy_id"], r["kind"], r["strategy_version"], r["strategy_hash"]]
                     for r in doc["runs"]])
    cols = ("signals", "closed_trades", "no_trade_share", "win_rate", "expectancy_r", "expectancy_r_95ci",
            "total_r", "profit_factor", "max_drawdown_r", "positive_folds", "out_of_sample_expectancy_r",
            "worst_cost_case_expectancy_r", "without_best_5_percent_expectancy_r", "sample")
    lines += ["", "## Side by side (after costs, in R)", ""]
    lines += _table(["Metric", *[r["strategy_id"] for r in doc["rows"]]],
                    [[c, *[r.get(c) for r in doc["rows"]]] for c in cols])
    reg_rows = [r for r in doc["rows"] if r.get("regimes")]
    if reg_rows:
        labels = list(reg_rows[0]["regimes"])
        lines += ["", f"## Strategy x regime (expectancy R / closed trades; detector {doc.get('regime_detector')})", ""]
        lines += _table(["Regime", *[r["strategy_id"] for r in reg_rows]],
                        [[k, *[(f"{_v(r['regimes'][k]['expectancy_r'])} / {r['regimes'][k]['closed_trades']}" +
                                (" (INSUFFICIENT_SAMPLE)" if r["regimes"][k]["sample"] != "OK" else ""))
                               for r in reg_rows]] for k in labels])
    news_rows = [r for r in doc["rows"] if r.get("news_comparison")]
    if news_rows:
        st = news_rows[0]["news_comparison"]["status"]
        lines += ["", f"## News comparison: {st} (snapshot {doc.get('news_snapshot_id')}, mode "
                      f"{doc.get('news_mode', 'none')})", ""]
        if st == "COMPARED":
            lines += _table(["News handling", *[r["strategy_id"] for r in news_rows]],
                            [[m, *[f"{_v(r['news_comparison'][m]['expectancy_r'])} / "
                                   f"{r['news_comparison'][m]['closed_trades']} closed, blocked "
                                   f"{_v(r['news_comparison'][m]['no_trade_share'])}" for r in news_rows]]
                             for m in ("none", "legacy", "upgraded")])
        else:
            lines += ["No historical news snapshot was used: news is not modelled (BLOCKED_BY_DATA)."]
    lines += ["", "## Hypothetical accounts", ""]
    for r in doc["rows"]:
        lines += [f"{r['strategy_id']}: " + "; ".join(
            f"${a['equity_usd']:g}: taken {a['taken']}, end {a['end_usd']}, max DD {a['max_drawdown_percent']} %"
            for a in r["accounts"])]
    lines += ["", "## Difference to the baseline (mean R, approximate 95 % interval)", ""]
    d = doc["differences_vs_baseline"]
    if "note" in d:
        lines += [d["note"]]
    else:
        lines += _table(["Strategy", "vs", "Difference R", "95 % interval", "Verdict"],
                        [[k, v["vs"], v["difference_r"], v["ci95"], v["verdict"]] for k, v in d.items()])
    rk = doc["ranking"]
    lines += ["", f"## Ranking: {rk['state']}", "", rk["note"] + (f": {', '.join(rk['order'])}" if rk["order"] else "")]
    lines += ["", f"Benchmark parity (baseline through the common runner vs legacy replay): "
                  f"{doc['benchmark_parity'].get('status')}"]
    lines += ["", "## Limitations", ""] + [f"- {x}" for x in doc["limitations"]]
    lines += ["", "## Warnings", ""] + [f"- {x}" for x in doc["warnings"]]
    return redact("\n".join(lines) + "\n")
