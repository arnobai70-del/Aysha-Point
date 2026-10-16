"""Side-by-side comparison of Strategy Lab runs (plan §6.4; ticket AI-009).

A comparison is only made between runs that share every input that could change the numbers apart from the
strategy itself: dataset, symbols, split plan (and whether the holdout was revealed), base and sensitivity cost
models, account scenario and news snapshot. Anything else is refused, so a "better" strategy can never come from a
friendlier cost model or a different period.

The comparison never promotes anything. Ranking is `NO_RANKING` unless every strategy has at least `MIN_SAMPLE`
closed trades, and even then it is only the order of after-cost expectancy on the data shown, labelled
`IN_SAMPLE_ORDER_ONLY`. Differences to the baseline carry an approximate 95 % interval; overlapping intervals read
`NOT_DISTINGUISHABLE`. The document is research only (`executable: false`) and is stored as an artifact with an
audit event; the comparison id is the hash of its content without the creation time. It uses the existing `exports`
artifact kind (file suffix `.comparison.json`) and no new registry table, so a rollback to 0.9.0 still reads and
verifies the whole research folder.
"""

from __future__ import annotations

import json
from typing import Any

from ayesha.research.contracts import check
from ayesha.research.evaluation import metrics as M
from ayesha.research.provenance import canonical_json, digest, iso, utc_now
from ayesha.research.simulation import lab
from ayesha.research.simulation.baseline import RunRefused
from ayesha.research.strategies import loader

SAME = ("dataset_id", "symbols", "split_plan_id", "reveal_holdout", "cost_model_id", "sensitivity_models",
        "account_scenario_id", "news_snapshot_id")
ROW_SCENARIOS = (20.0, 100.0, 1000.0)
KIND, EXT = "exports", ".comparison.json"


def _row(res: dict[str, Any]) -> dict[str, Any]:
    m = res["metrics"]
    s = m["summary"]
    row = {"strategy_id": res["strategy_id"], "kind": res["inputs_kind"], "run_id": res["run_id"],
           **M.compact(s), "planned_net_rr_median": s["planned_net_rr_median"], "median_r": s["median_r"],
           "not_filled_share": s["not_filled_share"], "longest_losing_streak": s["longest_losing_streak"],
           "exposure_share": s["exposure_share"],
           "positive_folds": f"{m['positive_folds']}/{m['folds_with_trades']}",
           "out_of_sample_expectancy_r": (m.get("out_of_sample") or {}).get("expectancy_r"),
           "intrabar_flags": s["intrabar_flags"]}
    rob = m.get("robustness")
    if rob:
        costs = {k: v["expectancy_r"] for k, v in rob["costs"].items()}
        vals = [v for v in costs.values() if v is not None]
        row["cost_sensitivity_expectancy_r"] = costs
        row["worst_cost_case_expectancy_r"] = min(vals) if vals else None
        row["without_best_5_percent_expectancy_r"] = rob["without_best_5_percent"]["expectancy_r"]
    row["accounts"] = [{"equity_usd": a["equity_start_usd"], "taken": a["taken"], "end_usd": a["equity_end_usd"],
                        "return_percent": a["return_percent"], "max_drawdown_percent": a["max_drawdown_percent"],
                        "first_blockers": a["skipped"]}
                       for a in m["account_scenarios"] if a["equity_start_usd"] in ROW_SCENARIOS]
    return row


def _load(ws, run_id: str) -> dict[str, Any]:
    res = lab.load_result(ws, run_id)
    if not lab.is_lab(res):
        raise RunRefused(f"{run_id} is a v0.9.0 baseline run (legacy replay), not a Strategy Lab run: "
                         "run the strategies with `ayesha research lab` to compare them")
    inputs = json.loads(ws.db.run(run_id)["inputs_json"])
    res["inputs"], res["inputs_kind"] = inputs, inputs["strategy_kind"]
    return res


def compare(ws, run_ids: list[str]) -> dict[str, Any]:
    ids = list(dict.fromkeys(run_ids))
    if len(ids) < 2:
        raise RunRefused("give at least two different completed lab runs")
    results = [_load(ws, r) for r in ids]
    first = results[0]["inputs"]
    for res in results[1:]:
        diff = [k for k in SAME if res["inputs"].get(k) != first.get(k)]
        if diff:
            raise RunRefused(f"{res['run_id']} differs from {results[0]['run_id']} in {', '.join(diff)}: "
                             "strategies are only compared on exactly the same data, split, costs and account")
    seen = [r["strategy_id"] for r in results]
    if len(set(seen)) != len(seen):
        raise RunRefused("the same strategy appears twice: compare one run per strategy")
    order = {sid: i for i, sid in enumerate(loader.LAB_ORDER)}
    results.sort(key=lambda r: (order.get(r["strategy_id"], 99), r["strategy_id"]))
    rows = [_row(r) for r in results]
    base = next((r for r in results if r["inputs_kind"] == "BASELINE"), None)
    if base is not None:
        b = lab.closed_r(ws, base["run_id"])
        diffs: dict[str, Any] = {r["strategy_id"]: {"vs": base["strategy_id"],
                                                    **M.mean_diff(lab.closed_r(ws, r["run_id"]), b)}
                                 for r in results if r is not base}
        parity = base["metrics"].get("benchmark_parity") or {"status": "NOT_CHECKED"}
    else:
        diffs = {"note": "no baseline run in this comparison"}
        parity = {"status": "NOT_INCLUDED", "note": "the baseline was not part of this comparison"}
    closed = [row["closed_trades"] for row in rows]
    if min(closed) >= M.MIN_SAMPLE:
        ranked = sorted(rows, key=lambda row: (-(row["expectancy_r"] if row["expectancy_r"] is not None else -9e9),
                                               row["strategy_id"]))
        ranking = {"state": "IN_SAMPLE_ORDER_ONLY", "order": [row["strategy_id"] for row in ranked],
                   "note": "order of after-cost expectancy on the shown data only; not a recommendation and never a "
                           "reason to trade a strategy live"}
    else:
        ranking = {"state": "NO_RANKING", "order": [],
                   "note": f"at least one strategy has fewer than {M.MIN_SAMPLE} closed trades: no order is shown"}
    limitations = sorted({x for r in results for x in r["limitations"]})
    warnings = ["Historical simulation on research data, not a forecast; no strategy here is validated.",
                "Differences assume independent trades, so their intervals are optimistic."]
    if len({r["commit_sha"] for r in results}) > 1:
        warnings.append("The runs were made by different program versions (commit differs).")
    if parity.get("status") == "DIFFERENT":
        warnings.append("The baseline through the common runner differs from the legacy replay: do not trust this "
                        "comparison until that is explained.")
    core = {
        "schema_version": "research.comparison/1", "source_type": "RESEARCH", "executable": False,
        "dataset_id": first["dataset_id"], "symbols": first["symbols"], "split_plan_id": first["split_plan_id"],
        "cost_model_id": first["cost_model_id"], "account_scenario_id": first["account_scenario_id"],
        "runs": [{"run_id": r["run_id"], "strategy_id": r["strategy_id"], "strategy_version": r["strategy_version"],
                  "strategy_hash": r["strategy_hash"], "kind": r["inputs_kind"], "result_sha256": r["result_sha256"]}
                 for r in results],
        "rows": rows, "differences_vs_baseline": diffs, "ranking": ranking, "benchmark_parity": parity,
        "limitations": limitations, "warnings": warnings,
    }
    cid = "cmp_" + digest(core)[:16]
    old = find(ws, cid)
    if old is not None:
        return old
    doc = check({**core, "comparison_id": cid, "created_at_utc": iso(utc_now().replace(microsecond=0)),
                 "comparison_sha256": digest(core)}, "research.comparison/1")
    sha, p = ws.store.put(KIND, canonical_json(doc), EXT)
    ws.db.record_artifact(sha, KIND, p.relative_to(ws.root).as_posix(), p.stat().st_size)
    ws.db.audit("research", "COMPARISON_CREATED", cid, {"runs": [r["run_id"] for r in results], "artifact": sha})
    return doc


def run_lab(ws, spec: dict[str, Any], dataset_id: str, symbols, folds: int = 4, split: str | None = None,
            holdout: str | None = None, reveal_holdout: bool = False, account_type: str = "Standard",
            allow_degraded: bool = False, robustness: bool = True) -> dict[str, Any]:
    """Every registered strategy (baseline, control, experimental) on the same inputs, then their comparison."""
    runs = [lab.run_strategy(ws, spec, sid, dataset_id, symbols, folds, split, holdout, reveal_holdout,
                             account_type, allow_degraded, robustness) for sid in loader.LAB_ORDER]
    doc = compare(ws, [r["run_id"] for r in runs])
    return {"comparison_id": doc["comparison_id"], "runs": runs, "ranking": doc["ranking"]["state"],
            "benchmark_parity": doc["benchmark_parity"].get("status")}


def comparisons(ws) -> list[dict[str, Any]]:
    out = []
    for a in ws.db.artifacts():
        if a["kind"] == KIND and a["relpath"].endswith(EXT + ".gz"):
            out.append(json.loads(ws.store.get(KIND, a["sha256"], EXT)))
    out.sort(key=lambda d: (d["created_at_utc"], d["comparison_id"]), reverse=True)
    return out


def find(ws, comparison_id: str) -> dict[str, Any] | None:
    return next((d for d in comparisons(ws) if d["comparison_id"] == comparison_id), None)


def load(ws, comparison_id: str) -> dict[str, Any]:
    d = find(ws, comparison_id)
    if d is None:
        raise RunRefused(f"no comparison {comparison_id}")
    return d
