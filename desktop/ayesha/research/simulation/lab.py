"""Strategy Lab runs (plan §6, v1.0.0): one research strategy, one frozen dataset, one or more symbols, through the
common runner, with after-cost metrics, robustness checks and hypothetical account scenarios.

Like the v0.9.0 baseline run, the run id is the hash of every input (dataset, symbols, strategy id/version/hash,
parameters, cost models, account scenario, news snapshot and news mode, regime detector, split plan, code version),
so the same inputs give the
same run id and `verify=True` recomputes a finished run and compares the result hash (plan T01). The result document
holds no timestamps inside its hashed core. Everything is research only: candidates are `executable: false`, the
decision states have no live value, nothing reaches the phone.

v1.1.0: every order carries the as-of regime label known when it was decided (`ayesha.research.regimes`) and the
result has a strategy x regime matrix. News is modelled only from a frozen news snapshot
(`ayesha.research.datasets.news_snapshot`); then each run also shows the same strategy with news off, with the
legacy fixed window and with the upgraded guard. Without a snapshot that comparison is `BLOCKED_BY_DATA`.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from ayesha.research.contracts import check
from ayesha.research.datasets import news_snapshot
from ayesha.research.evaluation import metrics as M
from ayesha.research.provenance import (canonical_json, commit_sha, desktop_version, digest, environment_hash, iso,
                                         parse_iso, sha256_bytes, utc_now)
from ayesha.research.regimes import detector
from ayesha.research.simulation import portfolio, runner
from ayesha.research.simulation.baseline import STATE, RunRefused, load_candles
from ayesha.research.simulation.costs import BASE, SENSITIVITY
from ayesha.research.storage.db import ResearchDBError
from ayesha.research.strategies import loader
from ayesha.research.workspace import Workspace

LIMITATIONS = ["HISTORICAL_SIMULATION_NOT_A_FORECAST", "PRICES_NOT_EXNESS", "ASSUMED_EXNESS_STANDARD_CONTRACT",
               "NOT_EXECUTABLE_RESEARCH_ONLY"]
NO_NEWS = "NONE:NEWS_NOT_MODELLED"
NEWS_COMPARE = ("none", "legacy", "upgraded")


def _symbols(symbols: list[str] | str) -> list[str]:
    out = sorted({s.strip().upper() for s in (symbols.split(",") if isinstance(symbols, str) else symbols) if s.strip()})
    if not out:
        raise RunRefused("give at least one symbol")
    return out


def check_dataset(ws: Workspace, dataset_id: str, allow_degraded: bool):
    ds = ws.db.dataset(dataset_id)
    if ds is None:
        raise RunRefused(f"unknown dataset {dataset_id}")
    if ds["quality_state"] == "REJECTED":
        raise RunRefused(f"{dataset_id} is REJECTED by its quality report: no metrics from it")
    if ds["quality_state"] == "DEGRADED" and not allow_degraded:
        raise RunRefused(f"{dataset_id} is DEGRADED: inspect it first; run with --allow-degraded to use it anyway "
                         "(the result is then marked DEGRADED_INPUT_DATA)")
    return ds


def plan_for(ws: Workspace, dataset_id: str, symbols: list[str], folds: int, split: str | None,
             holdout: str | None) -> tuple[dict[str, Any], dict[str, list]]:
    candles = {s: load_candles(ws, dataset_id, s, "M15") for s in symbols}
    for s, cs in candles.items():
        if not cs:
            raise RunRefused(f"{dataset_id} {s} M15 has no accepted bars")
    start, end = M.time_range(list(candles.values()))
    try:
        plan = M.split_plan(start, end, folds, parse_iso(split + ("T00:00:00Z" if "T" not in split else ""))
                            if split else None,
                            parse_iso(holdout + ("T00:00:00Z" if "T" not in holdout else "")) if holdout else None)
    except ValueError as e:
        raise RunRefused(str(e)) from None
    return plan, candles


def news_for(ws: Workspace, news_snapshot_id: str | None, news_mode: str, dataset_id: str,
             symbols: list[str]) -> tuple[dict[str, Any] | None, dict[str, runner.NewsInput] | None]:
    """The snapshot's manifest and one point-in-time news input per symbol (with the dataset's M5 bars for the
    reaction watch when it has them), or (None, None) when news is not modelled."""
    if not news_snapshot_id:
        return None, None
    if news_mode not in runner.NEWS_MODES:
        raise RunRefused(f"news mode must be one of {', '.join(runner.NEWS_MODES)}")
    try:
        man, cal = news_snapshot.load(ws, news_snapshot_id)
    except news_snapshot.NewsSnapshotError as e:
        raise RunRefused(str(e)) from None
    out = {}
    for s in symbols:
        try:
            m5 = load_candles(ws, dataset_id, s, "M5") or None
        except RunRefused:
            m5 = None
        out[s] = runner.NewsInput(cal, news_mode, m5)
    return man, out


def lab_inputs(ws: Workspace, spec: dict[str, Any], strategy_id: str, dataset_id: str, symbols: list[str],
               plan: dict[str, Any], account_type: str, allow_degraded: bool, robustness: bool,
               reveal_holdout: bool, news_snapshot_id: str | None = None,
               news_mode: str = "upgraded") -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        man = loader.manifest(strategy_id, spec)
    except loader.StrategyError as e:
        raise RunRefused(str(e)) from None
    inputs = {
        "engine": runner.ENGINE, "dataset_id": dataset_id, "symbols": symbols, "mode": "m15",
        "strategy_id": strategy_id, "strategy_version": man["version"], "strategy_hash": man["strategy_hash"],
        "strategy_kind": man["kind"], "parameters_hash": digest(man["parameters"]),
        "cost_model_id": f"{BASE.model_id}#{BASE.hash}",
        "sensitivity_models": [f"{c.model_id}#{c.hash}" for c in SENSITIVITY] if robustness else [],
        "account_scenario_id": f"HYPOTHETICAL:{account_type}:USD20-5000",
        "news_snapshot_id": news_snapshot_id or NO_NEWS, "news_mode": news_mode if news_snapshot_id else "none",
        "regime_detector": f"{detector.DETECTOR_ID}@{detector.VERSION}#{detector.manifest()['code_sha256'][:16]}",
        "split_plan_id": plan["split_plan_id"], "split_plan": plan,
        "reveal_holdout": bool(reveal_holdout), "robustness": bool(robustness),
        "commit_sha": commit_sha(), "desktop_version": desktop_version(), "allow_degraded": bool(allow_degraded),
    }
    return inputs, man


def _replay(spec, strategy_id, candles, cost=BASE, overrides=None, account_type="Standard", news=None,
            info=None) -> tuple[list, int, list]:
    lts, bars, rej = [], 0, []
    for s in sorted(candles):
        st, _ = loader.load(strategy_id, s, spec, overrides)
        r = runner.run(s, candles[s], spec, st, cost, account_type=account_type,
                       news=news.get(s) if news else None)
        lts += r["trades"]
        bars += r["bars"]
        rej += r["rejections"]
        if info is not None:
            info[s] = {"news_integrity": r["news_integrity"], "news_stability_bars": r["news_stability_bars"]}
    lts.sort(key=lambda lt: (lt.created_at, lt.symbol, lt.trade.signal.signal_id))
    return lts, bars, rej


def _modes(news: dict[str, runner.NewsInput], mode: str) -> dict[str, runner.NewsInput] | None:
    if mode == "none":
        return None
    return {s: runner.NewsInput(n.calendar, mode, n.m5) for s, n in news.items()}


def _visible(lts, plan, reveal):
    if not plan["holdout_from"] or reveal:
        return lts
    h = parse_iso(plan["holdout_from"])
    return [lt for lt in lts if lt.created_at < h]


def benchmark_parity(spec: dict[str, Any], candles: dict[str, list], lab_trades: list,
                     account_type: str = "Standard", news: dict[str, runner.NewsInput] | None = None
                     ) -> dict[str, Any]:
    """Baseline A through the common runner versus the unchanged legacy replay on the same bars (and the same news
    calendar and mode): every order's id, status, fill and exit bar, exit reason, R and blockers must be equal."""
    from ayesha.backtest.replay import run_backtest

    sp = copy.deepcopy(spec)
    sp["mtf"]["confirm_timeframe"] = None
    row = lambda t: [t.signal.signal_id, t.status, t.fill_index, t.exit_index, t.exit_reason, t.r,  # noqa: E731
                     list(t.blockers)]
    per = {}
    for s in sorted(candles):
        n = news.get(s) if news else None
        leg = run_backtest(s, candles[s], sp, account_type=account_type, usd_rates=runner.APPROX_USD_RATES,
                           calendar=n.calendar if n else None, news_mode=n.mode if n else None,
                           m5_candles=n.m5 if n else None)
        a = [row(lt.trade) for lt in lab_trades if lt.symbol == s]
        b = [row(t) for t in leg["trades"]]
        diff = [x[0] for x, y in zip(a, b) if x != y]
        per[s] = {"orders": [len(a), len(b)], "equal": a == b, "different_orders": diff[:10],
                  "sha256": [digest(a), digest(b)]}
    ok = all(v["equal"] for v in per.values())
    return {"status": "MATCHED" if ok else "DIFFERENT", "per_symbol": per,
            "legacy_engine": "ayesha.backtest.replay.run_backtest (unchanged 0.8.0 code), " + (
                f"news mode {next(iter(news.values())).mode} on the same calendar" if news else "news not modelled"),
            "note": "Parity shows the common runner replays the frozen rules exactly like the legacy path. "
                    "It says nothing about whether any strategy has an edge."}


def _candidate(lt, inputs, run_id) -> dict[str, Any]:
    t, s = lt.trade, lt.trade.signal
    return check({
        "schema_version": "research.candidate/1",
        "research_candidate_id": "rc_" + digest([run_id, s.signal_id])[:16],
        "source_type": "RESEARCH", "executable": False, "run_id": run_id,
        "strategy_id": inputs["strategy_id"], "strategy_version": inputs["strategy_version"],
        "strategy_hash": inputs["strategy_hash"], "dataset_id": inputs["dataset_id"],
        "asof_utc": iso(lt.created_at), "pair": lt.symbol, "direction": s.direction,
        "levels": {"entry": s.entry, "stop": s.stop, "targets": list(s.targets)},
        "proposed_state": STATE.get(t.status, "UNRESOLVED"), "replay_status": t.status, "outcome_r": t.r,
        "rejection_codes": list(t.blockers), "explanation": " | ".join(s.trace[:3])[:600],
        "flags": list(lt.flags), "fill_utc": iso(t.fill_time), "exit_utc": iso(t.exit_time),
        "exit_reason": t.exit_reason, "regime": lt.regime,
        "news_phase": None if t.news_phase == "NOT_MODELLED" else t.news_phase,
    }, "research.candidate/1")


def _compute(ws: Workspace, spec: dict[str, Any], inputs: dict[str, Any], run_id: str, quality: str,
             candles: dict[str, list], news: dict[str, runner.NewsInput] | None = None,
             news_man: dict[str, Any] | None = None) -> tuple[dict[str, Any], bytes, list[tuple], list[tuple]]:
    sid, plan, acct = inputs["strategy_id"], inputs["split_plan"], inputs["account_scenario_id"].split(":")[1]
    reveal = inputs["reveal_holdout"]
    info: dict[str, Any] = {}
    lts, bars, rej = _replay(spec, sid, candles, account_type=acct, news=news, info=info)
    vis = _visible(lts, plan, reveal)
    per = M.periods(lts, plan, reveal, bars)
    met: dict[str, Any] = {
        "engine": runner.ENGINE, "summary": per["all"], "folds": per["folds"],
        "positive_folds": per["positive_folds"], "folds_with_trades": per["folds_with_trades"],
        "in_sample": per.get("in_sample"), "out_of_sample": per.get("out_of_sample"), "holdout": per.get("holdout"),
        "breakdowns": M.breakdowns(vis), "bars": bars,
        "rejections": {}, "cost_model": BASE.as_dict(),
        "account_scenarios": portfolio.scenarios(vis, spec, acct),
        "regime": {"detector": detector.manifest(), "matrix": M.regime_matrix(vis, detector.LABELS),
                   "note": "label known when each order was decided; context only, never a gate or a permission"},
    }
    for r in rej:
        met["rejections"][r.reason] = met["rejections"].get(r.reason, 0) + 1
    met["rejections"] = dict(sorted(met["rejections"].items()))
    if inputs["robustness"]:
        rob: dict[str, Any] = {"costs": {}, "without_best_5_percent": M.without_best(vis),
                               "excluding_intrabar_ambiguous": M.compact(M.summary(
                                   [lt for lt in vis if "AMBIGUOUS_STOP_AND_TARGET_SAME_BAR" not in lt.flags]))}
        for cm in SENSITIVITY:
            v, _, _ = _replay(spec, sid, candles, cm, account_type=acct, news=news)
            rob["costs"][cm.model_id] = M.compact(M.summary(_visible(v, plan, reveal)))
        params = {}
        cls = loader.REGISTRY[sid]
        for k, d in getattr(cls, "params_def", {}).items():
            for v in (d.value - d.step, d.value + d.step):
                if not d.ok(v):
                    continue
                try:
                    pv, _, _ = _replay(spec, sid, candles, overrides={k: v}, account_type=acct, news=news)
                except (ValueError, loader.StrategyError) as e:
                    params[f"{k}={v:g}"] = {"error": str(e)}
                    continue
                params[f"{k}={v:g}"] = M.compact(M.summary(_visible(pv, plan, reveal)))
        rob["parameters"] = params or {"note": "frozen strategy: parameters are not perturbed"}
        met["robustness"] = rob
    if news:
        mode = inputs["news_mode"]
        met["news"] = {"news_snapshot_id": inputs["news_snapshot_id"], "mode": mode,
                       "snapshot_decision": news_man["integrity"]["decision"], "provider": news_man["provider"],
                       "per_symbol": info, "news_direction": news_snapshot.NEWS_DIRECTION}
        cmp_rows = {}
        for m in NEWS_COMPARE:
            v = lts if m == mode else _replay(spec, sid, candles, account_type=acct, news=_modes(news, m))[0]
            cmp_rows[m] = M.compact(M.summary(_visible(v, plan, reveal)))
        met["news_comparison"] = {"status": "COMPARED", "modes": cmp_rows,
                                  "note": "same strategy, data and costs; only the news handling differs. "
                                          "News direction is never backtested."}
    else:
        met["news"] = {"news_snapshot_id": NO_NEWS, "mode": "none"}
        met["news_comparison"] = {"status": "BLOCKED_BY_DATA",
                                  "note": "no historical news snapshot was given (research news-ingest): news is "
                                          "not modelled and no news comparison is possible"}
    if sid == loader.LAB_ORDER[0]:
        met["benchmark_parity"] = benchmark_parity(spec, candles, lts, acct, news)
    shown = vis
    cands = [_candidate(lt, inputs, run_id) for lt in shown]
    closed = per["all"]["closed_trades"]
    limitations = list(LIMITATIONS)
    integ = [w for d in info.values() if d["news_integrity"] for w in d["news_integrity"]["warnings"]]
    if news:
        limitations.append("NEWS_DIRECTION_NOT_BACKTESTED")
        if news_man["integrity"]["decision"] == "DEGRADED":
            limitations.append("DEGRADED_NEWS_DATA")
        if any(w.startswith("INCOMPLETE_NEWS_DATA") for w in integ):
            limitations.append("NEWS_COVERAGE_INCOMPLETE")
        no_m5 = any(d["news_stability_bars"] != "M5 closed bars" for d in info.values())
        if no_m5 and inputs["news_mode"] == "upgraded":
            limitations.append("NEWS_REACTION_WATCH_WITHOUT_M5")
    else:
        limitations.append("NEWS_NOT_MODELLED")
    if closed < M.MIN_SAMPLE:
        limitations.append("SMALL_SAMPLE")
    if quality == "DEGRADED":
        limitations.append("DEGRADED_INPUT_DATA")
    if any(s not in spec["pairs"]["enabled"] for s in inputs["symbols"]):
        limitations.append("SYMBOL_NOT_ENABLED_LIVE")
    if inputs["strategy_kind"] != "BASELINE":
        limitations.append(f"{inputs['strategy_kind']}_STRATEGY_NOT_PART_OF_THE_LIVE_RULES")
    warnings = []
    if closed < M.MIN_SAMPLE:
        warnings.append(f"Only {closed} closed trades: far too few to conclude anything (need {M.MIN_SAMPLE}+).")
    if news:
        warnings.append(f"News: {inputs['news_mode']} handling on snapshot {inputs['news_snapshot_id']} "
                        f"({news_man['integrity']['decision']}); {news_snapshot.NEWS_DIRECTION}.")
        warnings += [f"{s}: {w}" for s, d in sorted(info.items()) if d["news_integrity"]
                     for w in d["news_integrity"]["warnings"]]
    else:
        warnings.append("News was not modelled: the live strict news gate would block some of these orders.")
    if plan["holdout_from"] and not reveal:
        warnings.append(f"Holdout from {plan['holdout_from']} is sealed: {per['holdout']['orders']} orders not shown.")
    decisions = [(c["research_candidate_id"], c["asof_utc"], c["pair"], c["proposed_state"],
                  canonical_json({k: c[k] for k in ("replay_status", "outcome_r", "rejection_codes", "direction",
                                                    "levels", "flags")}).decode()) for c in cands]
    lim = canonical_json(limitations).decode()
    rows = [("ALL", "ALL", closed, canonical_json(per["all"]).decode(), lim)]
    for per_name in ("in_sample", "out_of_sample"):
        if per.get(per_name):
            rows.append((per_name.upper(), "ALL", per[per_name]["closed_trades"], canonical_json(per[per_name]).decode(),
                         lim))
    for i, f in enumerate(per["folds"], start=1):
        rows.append((f"FOLD_{i}", "ALL", f["closed_trades"], canonical_json(f).decode(), lim))
    for group, cells in met["breakdowns"].items():
        for k, v in cells.items():
            if "closed_trades" in v:
                rows.append(("ALL", f"{group}={k}", v["closed_trades"], canonical_json(v).decode(), lim))
    c_bytes = b"".join(canonical_json(c) + b"\n" for c in cands)
    core = {"inputs": inputs, "metrics": met, "limitations": limitations, "warnings": warnings,
            "candidates_sha256": sha256_bytes(c_bytes)}
    return core, c_bytes, decisions, rows


def run_strategy(ws: Workspace, spec: dict[str, Any], strategy_id: str, dataset_id: str, symbols, folds: int = 4,
                 split: str | None = None, holdout: str | None = None, reveal_holdout: bool = False,
                 account_type: str = "Standard", allow_degraded: bool = False, robustness: bool = True,
                 verify: bool = False, news_snapshot_id: str | None = None,
                 news_mode: str = "upgraded") -> dict[str, Any]:
    ds = check_dataset(ws, dataset_id, allow_degraded)
    syms = _symbols(symbols)
    plan, candles = plan_for(ws, dataset_id, syms, folds, split, holdout)
    news_man, news = news_for(ws, news_snapshot_id, news_mode, dataset_id, syms)
    inputs, man = lab_inputs(ws, spec, strategy_id, dataset_id, syms, plan, account_type, allow_degraded,
                             robustness, reveal_holdout, news_snapshot_id, news_mode)
    run_id = "run_" + digest(inputs)[:16]
    old = ws.db.run(run_id)
    if old is not None and old["status"] == "COMPLETED":
        stored = load_result(ws, run_id)
        if not verify:
            return {"run_id": run_id, "status": "COMPLETED", "existing": True, "strategy_id": strategy_id,
                    "result_sha256": stored["result_sha256"], "artifact_sha256": old["result_sha"]}
        core, _, _, _ = _compute(ws, spec, inputs, run_id, ds["quality_state"], candles, news, news_man)
        rec = digest(core)
        ws.store.get("candidates", old["candidates_sha"], ".jsonl")
        ok = rec == stored["result_sha256"] and core["candidates_sha256"] == stored["candidates_sha256"]
        ws.db.audit("research", "RUN_VERIFIED" if ok else "RUN_VERIFY_MISMATCH", run_id,
                    {"stored": stored["result_sha256"], "recomputed": rec})
        return {"run_id": run_id, "status": "COMPLETED", "verified": ok, "strategy_id": strategy_id,
                "stored_result_sha256": stored["result_sha256"], "recomputed_result_sha256": rec}
    ws.db.register_strategy(man, inputs["parameters_hash"])
    if reveal_holdout and plan["holdout_from"]:
        ws.db.audit("research", "HOLDOUT_REVEALED", run_id, {"strategy_id": strategy_id, "dataset_id": dataset_id,
                                                              "holdout_from": plan["holdout_from"]})
    started = utc_now()
    ws.db.start_run(run_id, inputs)
    try:
        core, c_bytes, decisions, rows = _compute(ws, spec, inputs, run_id, ds["quality_state"], candles, news,
                                                  news_man)
        result_sha = digest(core)
        c_sha, c_path = ws.store.put("candidates", c_bytes, ".jsonl")
        result = check({
            "schema_version": "research.result/1", "run_id": run_id, "source_type": "RESEARCH", "executable": False,
            "engine": runner.ENGINE, "symbols": syms,
            "commit_sha": inputs["commit_sha"], "desktop_version": inputs["desktop_version"],
            "dataset_id": dataset_id, "dataset_quality": ds["quality_state"],
            "strategy_id": strategy_id, "strategy_version": inputs["strategy_version"],
            "strategy_hash": inputs["strategy_hash"], "parameters_hash": inputs["parameters_hash"],
            "cost_model_id": inputs["cost_model_id"], "account_scenario_id": inputs["account_scenario_id"],
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
    s = core["metrics"]["summary"]
    return {"run_id": run_id, "status": "COMPLETED", "existing": False, "strategy_id": strategy_id,
            "result_sha256": result_sha, "artifact_sha256": r_sha, "closed_trades": s["closed_trades"],
            "signals": s["signals"], "expectancy_r": s["expectancy_r"], "limitations": core["limitations"]}


def load_result(ws, run_id: str) -> dict[str, Any]:
    from ayesha.research.simulation.baseline import load_result as _lr

    return _lr(ws, run_id)


def is_lab(result: dict[str, Any]) -> bool:
    return result.get("engine") == runner.ENGINE


def closed_r(ws, run_id: str) -> list[float]:
    from ayesha.research.simulation.baseline import load_candidates

    return [c["outcome_r"] for c in load_candidates(ws, run_id)
            if c["proposed_state"] == "HYPOTHETICAL_CLOSED" and c["outcome_r"] is not None]


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
