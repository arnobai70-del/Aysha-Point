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
        ("News", res["news_snapshot_id"]),
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
    lines += ["", "## Research summary", "",
              f"Signals {mt['summary']['signals']}, closed {mt['summary']['closed_trades']}, blocked share "
              f"{mt['no_trade_share']}, not filled share {mt['not_filled_share']}, rejected setups "
              f"{mt['rejections']}, bars {mt['bars']} ({mt['base_timeframe']} base, confirmation "
              f"{mt['confirm_timeframe'] or 'none'}).", ""]
    body = to_markdown(mt["legacy_report"]).replace("# AYESHA backtest report", "## Legacy replay report "
                                                                                 "(same code as `ayesha report`)", 1)
    return redact("\n".join(lines) + "\n" + body)
