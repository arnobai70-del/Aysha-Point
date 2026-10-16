"""Baseline A: the frozen live rule set SWEEP_MSS_FVG, replayed unchanged on a frozen dataset (plan §6.1, AI-005).

This is an adapter, not a second implementation: candles come from a verified snapshot, the replay is the legacy
`ayesha.backtest.replay.run_backtest`, and the metrics are the legacy `ayesha.backtest.report.build_report`, so the
numbers equal `ayesha report` on the same bars (`evaluation.parity` proves the input side). It is a benchmark, not
a proven edge. Every output is RESEARCH and not executable; nothing here can produce READY, write the live signal
registry or reach the phone.

Run identity is the hash of every input (dataset, strategy version and hash, parameters, cost model, account
scenario, news snapshot, split plan, code version), so the same inputs always give the same run id, and
`verify=True` recomputes a completed run and compares its result hashes (plan T01).
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from ayesha.research.contracts import check
from ayesha.research.datasets.normalize import parse_line, to_candle
from ayesha.research.provenance import (canonical_json, commit_sha, desktop_version, digest, environment_hash, iso,
                                         sha256_bytes, utc_now)
from ayesha.research.storage.db import ResearchDBError
from ayesha.research.workspace import Workspace

STRATEGY_ID = "baseline-sweep-mss-fvg"
COST_MODEL_ID = "legacy-replay-v1"
COST_MODEL = ("bar spread from the data feed on every fill, slippage buffer from the spec on the plan and on stop "
              "exits, stop wins a bar that touches both, a fill bar cannot take profit, gaps through the stop exit at "
              "the open, flat before the New York rollover, commission 0 (Exness Standard assumption)")
MODES = {"m15": ("M15", None), "m5confirm": ("M5", "M5")}
APPROX_USD_RATES = {"JPY": 1 / 150.0, "GBP": 1.27, "CAD": 1 / 1.37, "CHF": 1 / 0.88}  # same as ayesha.cli
STATE = {"CLOSED": "HYPOTHETICAL_CLOSED", "BLOCKED": "BLOCKED", "EXPIRED": "NOT_FILLED", "MISSED": "NOT_FILLED",
         "UNCONFIRMED": "NOT_FILLED", "INVALIDATED": "INVALIDATED"}
MIN_SAMPLE = 100


class RunRefused(RuntimeError):
    """The inputs do not allow a run (rejected or degraded data, missing partition, unknown mode)."""


def strategy_manifest(spec: dict[str, Any]) -> dict[str, Any]:
    return check({
        "schema_version": "research.strategy/1",
        "strategy_id": STRATEGY_ID,
        "version": spec["strategy_version"],
        "strategy_hash": spec["strategy_hash"],
        "explanation": "Frozen live rule set SWEEP_MSS_FVG (H4 context, H1 bias, M15 setup, optional M5 "
                       "confirmation) replayed unchanged by the legacy replay engine. A benchmark, not a proven edge.",
        "timeframes": ["H4", "H1", "M15", "M5"],
        "symbols": list(spec["pairs"]["enabled"]),
        "parameters": {k: spec[k] for k in ("rules", "entry", "mtf", "risk", "scoring", "sessions")},
        "lookback_bars": 0,
        "stateful": True,
        "research_only": True,
        "execution_level": "NONE",
        "news_source": "NOT_MODELLED: no point-in-time historical calendar in v0.9.0",
        "cost_source": COST_MODEL_ID,
        "kind": "BASELINE",
    }, "research.strategy/1")


def spec_for(spec: dict[str, Any], mode: str) -> dict[str, Any]:
    sp = copy.deepcopy(spec)
    sp["mtf"]["confirm_timeframe"] = MODES[mode][1]
    sp["strategy_hash"] = spec["strategy_hash"]  # the live identity; the mode is part of the run parameters
    return sp


def load_candles(ws: Workspace, dataset_id: str, symbol: str, timeframe: str) -> list:
    """Candles of one partition, read through the hash check: corrupted data raises before anything uses it."""
    part = ws.db.partition(dataset_id, symbol, timeframe)
    if part is None:
        raise RunRefused(f"{dataset_id} has no {symbol} {timeframe} partition")
    rows = [parse_line(x) for x in ws.store.iter_lines("normalized", part["artifact_sha"], ".jsonl")]
    return [to_candle(r) for r in rows]


def run_inputs(ws: Workspace, spec: dict[str, Any], dataset_id: str, symbol: str, mode: str,
               split: str | None, folds: int, account_type: str, allow_degraded: bool) -> dict[str, Any]:
    if mode not in MODES:
        raise RunRefused(f"mode must be one of {sorted(MODES)}")
    params = {"mode": mode, "symbol": symbol, "folds": folds, "split": split,
              "spec": {k: spec[k] for k in sorted(spec) if k != "strategy_hash"}}
    return {
        "dataset_id": dataset_id, "symbol": symbol, "mode": mode,
        "strategy_id": STRATEGY_ID, "strategy_version": spec["strategy_version"], "strategy_hash": spec["strategy_hash"],
        "parameters_hash": digest(params),
        "cost_model_id": COST_MODEL_ID,
        "account_scenario_id": f"HYPOTHETICAL:{account_type}:USD20-5000",
        "news_snapshot_id": "NONE:NEWS_NOT_MODELLED",
        "split_plan_id": f"split={split or 'none'};folds={folds}",
        "commit_sha": commit_sha(), "desktop_version": desktop_version(),
        "allow_degraded": bool(allow_degraded),
    }


def _candidates(trades: list, inputs: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    out = []
    for t in trades:
        s = t.signal
        state = STATE.get(t.status, "UNRESOLVED")
        out.append(check({
            "schema_version": "research.candidate/1",
            "research_candidate_id": "rc_" + digest([run_id, s.signal_id])[:16],
            "source_type": "RESEARCH",
            "executable": False,
            "run_id": run_id,
            "strategy_id": inputs["strategy_id"], "strategy_version": inputs["strategy_version"],
            "strategy_hash": inputs["strategy_hash"], "dataset_id": inputs["dataset_id"],
            "asof_utc": iso(s.bar_close_utc), "pair": s.symbol, "direction": s.direction,
            "levels": {"entry": s.entry, "stop": s.stop, "targets": list(s.targets)},
            "proposed_state": state, "replay_status": t.status, "outcome_r": t.r,
            "rejection_codes": list(t.blockers),
            "explanation": f"{s.setup} grade {s.grade}, {s.score} rule points (not a probability); "
                           f"replay {t.status}{' ' + t.exit_reason if t.exit_reason else ''}",
        }, "research.candidate/1"))
    return out


def _compute(ws: Workspace, spec: dict[str, Any], inputs: dict[str, Any], run_id: str,
             quality_state: str) -> tuple[dict[str, Any], bytes, list[tuple], list[tuple]]:
    """Everything a run produces, without side effects: (core result, candidates JSON Lines, decision rows, metric
    rows). `core` holds no timestamps, so its hash is the run's reproducible identity of the outcome."""
    from ayesha.backtest.replay import run_backtest
    from ayesha.backtest.report import build_report

    symbol, mode = inputs["symbol"], inputs["mode"]
    tf = MODES[mode][0]
    candles = load_candles(ws, inputs["dataset_id"], symbol, tf)
    if not candles:
        raise RunRefused("the partition has no accepted bars")
    sp = spec_for(spec, mode)
    acct = inputs["account_scenario_id"].split(":")[1]
    res = run_backtest(symbol, candles, sp, account_type=acct, usd_rates=APPROX_USD_RATES)
    split = inputs["split_plan_id"].split(";")[0].split("=", 1)[1]
    split_at = None if split == "none" else datetime.fromisoformat(split).replace(tzinfo=timezone.utc)
    folds = int(inputs["split_plan_id"].split("folds=")[1])
    key = f"{symbol}|{mode}"
    rep = build_report({key: res}, sp, split_at=split_at, folds=folds, data_label=inputs["dataset_id"],
                       usd_rates=APPROX_USD_RATES)
    run = rep["runs"][key]
    trades = res["trades"]
    cands = _candidates(trades, inputs, run_id)
    n = len(trades)
    by = run["summary"]["by_status"]
    metrics = {
        "summary": run["summary"],
        "no_trade_share": round(by.get("BLOCKED", 0) / n, 3) if n else None,
        "not_filled_share": round(sum(by.get(k, 0) for k in ("EXPIRED", "MISSED", "UNCONFIRMED")) / n, 3) if n else None,
        "by_session": run["by_session"], "by_direction": run["by_direction"], "by_h4_context": run["by_h4_context"],
        "walk_forward": run["walk_forward"],
        "in_vs_out_of_sample": run.get("in_vs_out_of_sample"),
        "capital_exness_standard": run["capital_exness_standard"],
        "adaptive_account": rep["adaptive_account"].get(mode, []),
        "rejections": len(res["rejections"]),
        "bars": res["bars"], "start": str(res["start"]), "end": str(res["end"]),
        "base_timeframe": res["base_timeframe"], "confirm_timeframe": res["confirm_timeframe"],
        "report_notes": rep["notes"],
        "legacy_report": rep,  # the exact `ayesha report` structure for these bars (rendered by research report)
    }
    closed = run["summary"]["closed_trades"]
    limitations = ["HISTORICAL_SIMULATION_NOT_A_FORECAST", "NEWS_NOT_MODELLED", "PRICES_NOT_EXNESS",
                   "ASSUMED_EXNESS_STANDARD_CONTRACT", "NOT_EXECUTABLE_RESEARCH_ONLY"]
    if closed < MIN_SAMPLE:
        limitations.append("SMALL_SAMPLE")
    if quality_state == "DEGRADED":
        limitations.append("DEGRADED_INPUT_DATA")
    if symbol not in spec["pairs"]["enabled"]:
        limitations.append("SYMBOL_NOT_ENABLED_LIVE")
    warnings = []
    if closed < MIN_SAMPLE:
        warnings.append(f"Only {closed} closed trades: far too few to conclude anything (need {MIN_SAMPLE}+).")
    warnings.append("News was not modelled: the live strict news gate would block some of these setups.")
    decisions = [(c["research_candidate_id"], c["asof_utc"], c["pair"], c["proposed_state"],
                  canonical_json({k: c[k] for k in ("replay_status", "outcome_r", "rejection_codes", "direction",
                                                    "levels", "explanation")}).decode()) for c in cands]
    rows = [("ALL", "ALL", closed, canonical_json(run["summary"]).decode(), canonical_json(limitations).decode())]
    if run.get("in_vs_out_of_sample"):
        io_ = run["in_vs_out_of_sample"]
        for per in ("in_sample", "out_of_sample"):
            rows.append((per.upper(), "ALL", io_[per]["closed_trades"], canonical_json(io_[per]).decode(),
                         canonical_json(limitations).decode()))
    for i, f in enumerate(run["walk_forward"]["folds"], start=1):
        rows.append((f"FOLD_{i}", "ALL", f["closed_trades"], canonical_json(f).decode(),
                     canonical_json(limitations).decode()))
    for group, key2 in (("session", "by_session"), ("direction", "by_direction"), ("h4", "by_h4_context")):
        for k, v in run[key2].items():
            rows.append(("ALL", f"{group}={k}", v["closed_trades"], canonical_json(v).decode(),
                         canonical_json(limitations).decode()))
    c_bytes = b"".join(canonical_json(c) + b"\n" for c in cands)
    core = {"inputs": inputs, "metrics": metrics, "limitations": limitations, "warnings": warnings,
            "candidates_sha256": sha256_bytes(c_bytes)}
    return core, c_bytes, decisions, rows


def run_baseline(ws: Workspace, spec: dict[str, Any], dataset_id: str, symbol: str, mode: str = "m15",
                 split: str | None = None, folds: int = 4, account_type: str = "Standard",
                 allow_degraded: bool = False, verify: bool = False) -> dict[str, Any]:
    ds = ws.db.dataset(dataset_id)
    if ds is None:
        raise RunRefused(f"unknown dataset {dataset_id}")
    if ds["quality_state"] == "REJECTED":
        raise RunRefused(f"{dataset_id} is REJECTED by its quality report: no metrics from it")
    if ds["quality_state"] == "DEGRADED" and not allow_degraded:
        raise RunRefused(f"{dataset_id} is DEGRADED: inspect it first; run with --allow-degraded to use it anyway "
                         "(the result is then marked DEGRADED_INPUT_DATA)")
    if split is not None:
        datetime.fromisoformat(split)  # raises ValueError on a bad date
    inputs = run_inputs(ws, spec, dataset_id, symbol, mode, split, folds, account_type, allow_degraded)
    run_id = "run_" + digest(inputs)[:16]
    old = ws.db.run(run_id)
    if old is not None and old["status"] == "COMPLETED":
        stored = load_result(ws, run_id)
        if not verify:
            return {"run_id": run_id, "status": "COMPLETED", "existing": True,
                    "result_sha256": stored["result_sha256"], "artifact_sha256": old["result_sha"]}
        core, c_bytes, _, _ = _compute(ws, spec, inputs, run_id, ds["quality_state"])
        rec = digest(core)
        ws.store.get("candidates", old["candidates_sha"], ".jsonl")  # the stored candidates still match their hash
        ok = rec == stored["result_sha256"] and core["candidates_sha256"] == stored["candidates_sha256"]
        ws.db.audit("research", "RUN_VERIFIED" if ok else "RUN_VERIFY_MISMATCH", run_id,
                    {"stored": stored["result_sha256"], "recomputed": rec})
        return {"run_id": run_id, "status": "COMPLETED", "verified": ok,
                "stored_result_sha256": stored["result_sha256"], "recomputed_result_sha256": rec}
    ws.db.register_strategy(strategy_manifest(spec), inputs["parameters_hash"])
    started = utc_now()
    ws.db.start_run(run_id, inputs)
    try:
        core, c_bytes, decisions, rows = _compute(ws, spec, inputs, run_id, ds["quality_state"])
        result_sha = digest(core)
        c_sha, c_path = ws.store.put("candidates", c_bytes, ".jsonl")
        result = check({
            "schema_version": "research.result/1", "run_id": run_id, "source_type": "RESEARCH", "executable": False,
            "commit_sha": inputs["commit_sha"], "desktop_version": inputs["desktop_version"],
            "dataset_id": dataset_id, "dataset_quality": ds["quality_state"],
            "strategy_id": inputs["strategy_id"], "strategy_version": inputs["strategy_version"],
            "strategy_hash": inputs["strategy_hash"], "parameters_hash": inputs["parameters_hash"],
            "cost_model_id": COST_MODEL_ID, "account_scenario_id": inputs["account_scenario_id"],
            "news_snapshot_id": inputs["news_snapshot_id"], "split_plan_id": inputs["split_plan_id"],
            "environment_hash": environment_hash(), "inputs_hash": digest(inputs),
            "started_at_utc": iso(started.replace(microsecond=0)),
            "completed_at_utc": iso(utc_now().replace(microsecond=0)),
            "metrics": core["metrics"], "limitations": core["limitations"], "warnings": core["warnings"],
            "candidates_sha256": c_sha, "result_sha256": result_sha, "status": "COMPLETED",
        }, "research.result/1")
        r_sha, r_path = ws.store.put("runs", canonical_json(result), ".json")
        for sha, kind, p in ((c_sha, "candidates", c_path), (r_sha, "runs", r_path)):
            ws.db.record_artifact(sha, kind, p.relative_to(ws.root).as_posix(), p.stat().st_size)
        ws.db.complete_run(run_id, r_sha, c_sha, decisions, rows)
    except (RunRefused, ResearchDBError):
        ws.db.fail_run(run_id, "refused")
        raise
    except Exception as e:
        ws.db.fail_run(run_id, f"{type(e).__name__}: {e}")
        raise
    return {"run_id": run_id, "status": "COMPLETED", "existing": False, "result_sha256": result_sha,
            "artifact_sha256": r_sha, "closed_trades": core["metrics"]["summary"]["closed_trades"],
            "signals": core["metrics"]["summary"]["signals"], "limitations": core["limitations"]}


def load_result(ws: Workspace, run_id: str) -> dict[str, Any]:
    """The stored result document (`research.result/1`), read through its hash check."""
    import json

    r = ws.db.run(run_id)
    if r is None or r["status"] != "COMPLETED":
        raise RunRefused(f"no completed run {run_id}")
    return json.loads(ws.store.get("runs", r["result_sha"], ".json"))


def load_candidates(ws: Workspace, run_id: str) -> list[dict[str, Any]]:
    import json

    r = ws.db.run(run_id)
    if r is None or r["status"] != "COMPLETED":
        raise RunRefused(f"no completed run {run_id}")
    return [json.loads(x) for x in ws.store.get("candidates", r["candidates_sha"], ".jsonl").splitlines()]
