"""`ayesha research ...`: the research plane's own command line (reached only through `ayesha.cli.cmd_research`).

Research is research-only: nothing here can place, change or close an order, produce READY, write the live signal
registry or reach the phone. It is OFF by default (legacy_only); `ayesha research enable` turns it on. Heavy jobs
(ingest, run, lab, compare, parity) run in a separate low-priority worker process.

Exit codes: 0 OK, 1 failed (job failed/crashed/timed out, or a doctor check FAILED), 2 refused (research off,
invalid input, rejected or degraded data), 75 busy (another research job is running).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ayesha.research.config import (ResearchConfig, ResearchConfigError, ResearchDisabled, config_path, load,
                                    require_enabled, research_home, save_enabled)

EXIT_OK, EXIT_FAILED, EXIT_REFUSED, EXIT_BUSY = 0, 1, 2, 75
OFF = ("Research is OFF (legacy_only). The live scanner, phone alerts and READY rules are not affected.\n"
       "Turn research on with: ayesha research enable")
BANNER = "AYESHA research (research-only: never READY, never sent to the phone, no orders)"


def _p(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def _cfg() -> ResearchConfig:
    return load(config_path())


def _ws(cfg: ResearchConfig | None = None):
    from ayesha.research.workspace import Workspace

    return Workspace(cfg or _cfg(), research_home())


def _job(kind: str, args: dict[str, Any], need_enabled: bool = True) -> tuple[int, dict[str, Any] | None]:
    from ayesha.research.worker import WorkerBusy, run_job

    cfg = _cfg()
    if need_enabled:
        require_enabled(cfg)
    ws = _ws(cfg)
    try:
        r = run_job(ws, kind, args, echo=lambda line: print(f"  | {line}"))
    except WorkerBusy as e:
        print(f"BUSY: {e}")
        return EXIT_BUSY, None
    finally:
        ws.close()
    if r["status"] == "OK":
        return EXIT_OK, r["result"]
    print(f"{r['status']}: {r.get('error', 'see the log')}  (log: research/{r['log']})")
    return (EXIT_REFUSED if r["status"] == "REFUSED" else EXIT_FAILED), None


# --- commands -------------------------------------------------------------------------------

def cmd_status(a) -> int:
    from ayesha import __version__
    from ayesha.research import RESEARCH_VERSION
    from ayesha.research.readonly import open_ro
    from ayesha.research.worker import lock_for

    root = research_home()
    print(BANNER)
    print(f"Version: research {RESEARCH_VERSION}, desktop {__version__}")
    try:
        cfg = _cfg()
        print("State: " + ("ON (research-only)" if cfg.enabled else "OFF (legacy_only)"))
    except ResearchConfigError as e:
        print(f"State: OFF (config invalid: {e})")
    print(f"Folder: {root}" + ("" if root.exists() else " (not created yet)"))
    dbp = root / "research.db"
    if not dbp.exists():
        print("No research data yet.")
        return EXIT_OK
    con = open_ro(dbp)
    try:
        q = lambda sql: con.execute(sql).fetchall()  # noqa: E731
        ds = {r[0]: r[1] for r in q("SELECT quality_state, COUNT(*) FROM datasets GROUP BY quality_state")}
        runs = {r[0]: r[1] for r in q("SELECT status, COUNT(*) FROM research_runs GROUP BY status")}
        last = q("SELECT job_id, kind, status, started_utc FROM research_jobs ORDER BY started_utc DESC, rowid DESC "
                 "LIMIT 1")
        print(f"Datasets: {sum(ds.values())} " + (f"({', '.join(f'{k} {v}' for k, v in sorted(ds.items()))})"
                                                  if ds else ""))
        print(f"Runs: {sum(runs.values())} " + (f"({', '.join(f'{k} {v}' for k, v in sorted(runs.items()))})"
                                                if runs else ""))
        if last:
            j = last[0]
            print(f"Last job: {j['kind']} {j['status']} at {j['started_utc']} ({j['job_id']})")
    finally:
        con.close()
    print("Worker: " + ("busy (a research job is running)" if lock_for(root).held_by_other() else "idle"))
    backups = sorted((root / "backups").glob("research-*.db")) if (root / "backups").exists() else []
    print(f"Last backup: {backups[-1].name if backups else 'none yet (ayesha research backup)'}")
    size = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
    print(f"Disk used by research: {size / (1 << 20):.1f} MB")
    print("No validated trading edge exists yet: research results are evidence to inspect, not advice.")
    return EXIT_OK


def cmd_enable(a) -> int:
    cfg = save_enabled(True)
    print(f"Research is ON (research-only). Settings: {cfg.path}")
    print("Unchanged: the live scanner, the strategy spec, READY/NO_TRADE rules, phone alerts and your capital file.")
    print("Turn it off any time with: ayesha research disable")
    return EXIT_OK


def cmd_disable(a) -> int:
    p = config_path()
    try:
        save_enabled(False)
    except ResearchConfigError:
        bad = p.with_name(f"config.invalid-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.yaml")
        p.replace(bad)
        save_enabled(False)
        print(f"The old settings file was invalid; it was kept as {bad.name} and safe defaults were written.")
    print("Research is OFF (legacy_only). Research data is kept; the live scanner was never affected.")
    return EXIT_OK


def cmd_doctor(a) -> int:
    from ayesha.research.doctor import FAIL, as_json, run_doctor

    checks = run_doctor(deep=a.deep, selftest=a.selftest)
    if a.json:
        print(as_json(checks))
    else:
        print(BANNER)
        for c in checks:
            print(f"{c.state:<4}  {c.name}: {c.detail}")
    bad = [c for c in checks if c.state == FAIL]
    if not a.json:
        print("\nAll research checks passed (warnings are advice)." if not bad else
              f"\n{len(bad)} research check(s) failed. The live scanner is not affected.")
    return EXIT_FAILED if bad else EXIT_OK


def _pairs(v: str | None) -> list[str] | None:
    return [x.strip().upper() for x in v.split(",") if x.strip()] if v else None


def cmd_ingest(a) -> int:
    if bool(a.from_csv_dir) == bool(a.provider):
        print("Give exactly one source: --from-csv-dir FOLDER, or --provider oanda")
        return EXIT_REFUSED
    if a.from_csv_dir:
        args = {"folder": str(Path(a.from_csv_dir).resolve()), "pairs": _pairs(a.pairs), "label": a.label or "",
                "provider": a.provider_label or "CSV_IMPORT", "spec": a.spec}
        kind = "ingest_csv"
    else:
        if a.provider != "oanda":
            print("Only --provider oanda is supported (OANDA v20 practice, your own token, read-only).")
            return EXIT_REFUSED
        from ayesha.config import load_spec

        pairs = _pairs(a.pairs) or list(load_spec(a.spec)["pairs"]["enabled"])
        tfs = [x.strip().upper() for x in a.tf.split(",") if x.strip()]
        args = {"pairs": pairs, "days": a.days, "timeframes": tfs, "environment": "practice",
                "label": a.label or "", "spec": a.spec}
        kind = "ingest_oanda"
        print(f"Downloading closed bars from OANDA practice (read-only) for {', '.join(pairs)} "
              f"{', '.join(tfs)}, {a.days} days. The token stays on this PC.")
    rc, r = _job(kind, args)
    if r is None:
        return rc
    print(f"\nDataset {r['dataset_id']}: {'new' if r['new'] else 'already frozen (same raw data)'}, "
          f"quality {r['quality_state']}")
    for p in r["partitions"]:
        print(f"  {p['symbol']} {p['timeframe']}: {p['rows']} bars, {p['state']}, coverage {p['coverage_percent']}%, "
              f"missing {p['missing_bars']}" + (f", issues {'; '.join(p['issues'])}" if p["issues"] else ""))
    if r["quality_state"] == "REJECTED":
        print("REJECTED: this dataset is kept for inspection only; runs refuse it. See: ayesha research inspect "
              + r["dataset_id"])
        return EXIT_REFUSED
    if r["quality_state"] == "DEGRADED":
        print("DEGRADED: inspect it first; a run needs --allow-degraded and is then marked DEGRADED_INPUT_DATA.")
    print(f"Next: ayesha research lab --dataset {r['dataset_id']} --symbols "
          f"{','.join(sorted({p['symbol'] for p in r['partitions']}))}")
    return EXIT_OK


def _registry():
    from ayesha.research.readonly import open_ro

    dbp = research_home() / "research.db"
    return open_ro(dbp) if dbp.exists() else None


def cmd_datasets(a) -> int:
    con = _registry()
    if con is None:
        print("No research data yet.")
        return EXIT_OK
    try:
        rows = [dict(r) for r in con.execute("SELECT dataset_id, provider, label, symbols, timeframes, start_utc, "
                                             "end_utc, quality_state, created_utc FROM datasets ORDER BY created_utc "
                                             "DESC, dataset_id")]
    finally:
        con.close()
    if a.json:
        _p(rows)
        return EXIT_OK
    if not rows:
        print("No datasets yet. Import one with: ayesha research ingest --provider oanda (or --from-csv-dir)")
    for r in rows:
        print(f"{r['dataset_id']}  {r['quality_state']:<8}  {r['provider']}  {r['symbols']} {r['timeframes']}  "
              f"{r['start_utc']} .. {r['end_utc']}  ({r['label']})")
    return EXIT_OK


def cmd_inspect(a) -> int:
    from ayesha.research.datasets.store import ArtifactStore

    con = _registry()
    if con is None:
        print("No research data yet.")
        return EXIT_REFUSED
    try:
        ds = con.execute("SELECT * FROM datasets WHERE dataset_id=?", (a.dataset,)).fetchone()
        if ds is None:
            print(f"Unknown dataset {a.dataset}")
            return EXIT_REFUSED
        parts = con.execute("SELECT * FROM dataset_partitions WHERE dataset_id=? ORDER BY symbol, timeframe",
                            (a.dataset,)).fetchall()
    finally:
        con.close()
    store = ArtifactStore(research_home())
    manifest = json.loads(ds["manifest_json"])
    reports = {f"{p['symbol']} {p['timeframe']}": json.loads(store.get("quality", p["quality_sha"], ".json"))
               for p in parts}
    if a.json:
        _p({"manifest": manifest, "quality_reports": reports})
        return EXIT_OK
    src = manifest["source"]
    print(f"Dataset {ds['dataset_id']} ({ds['quality_state']})")
    print(f"Source: {src['provider']} via {src['adapter']} [{src['environment']}] label: {src['label']}")
    print(f"Range: {manifest['range_utc']['start']} .. {manifest['range_utc']['end']}; downloaded "
          f"{manifest['downloaded_at_utc']}; observed time basis {manifest['observed_at_basis']}")
    print(f"Licence: {manifest['license_notes']}")
    for x in manifest["limitations"]:
        print(f"Limitation: {x}")
    for key, rep in reports.items():
        print(f"\n{key}: {rep['decision']}, {rep['rows_out']}/{rep['rows_in']} rows kept, coverage "
              f"{rep['coverage_percent']}%, missing {rep['missing_bars']} of {rep['expected_bars']} expected, "
              f"longest gap {rep['longest_gap_bars']} bars")
        for i in rep["issues"]:
            ex = f" e.g. {'; '.join(i['examples'][:3])}" if i["examples"] else ""
            print(f"  {i['severity']:<6} {i['code']} x{i['count']}{ex}")
    return EXIT_OK


def cmd_strategies(a) -> int:
    from ayesha.config import load_spec
    from ayesha.research.strategies.loader import available

    mans = available(load_spec(a.spec))
    if a.json:
        _p(mans)
        return EXIT_OK
    for m in mans:
        print(f"{m['strategy_id']} {m['version']}  {m['kind']:<12}  hash {m['strategy_hash']}")
        print(f"    {m['explanation']}")
        if m.get("parameter_bounds"):
            print("    parameters: " + ", ".join(f"{k}={b['default']:g} [{b['low']:g}..{b['high']:g} step {b['step']:g}]"
                                                for k, b in m["parameter_bounds"].items()))
    print("Research only: none of these is a live rule, none can produce READY or reach the phone.")
    return EXIT_OK


def _lab_args(a) -> dict[str, Any]:
    return {"dataset_id": a.dataset, "symbols": a.symbols or a.symbol, "split": a.split or None, "folds": a.folds,
            "holdout": a.holdout or None, "reveal_holdout": a.reveal_holdout, "account_type": a.account_type,
            "allow_degraded": a.allow_degraded, "quick": a.quick, "spec": a.spec}


def _print_lab_run(r: dict[str, Any]) -> None:
    print(f"Run {r['run_id']} ({r['strategy_id']}): {r['status']}" +
          (" (already done with exactly these inputs)" if r.get("existing") else ""))
    if not r.get("existing"):
        print(f"  Signals {r['signals']}, closed trades {r['closed_trades']}, expectancy after costs "
              f"{r['expectancy_r'] if r['expectancy_r'] is not None else '-'} R; limitations: "
              f"{', '.join(r['limitations'])}")


def cmd_run(a) -> int:
    from ayesha.research.strategies.loader import LAB_ORDER

    legacy = a.strategy == LAB_ORDER[0] and not a.symbols and not a.holdout and not a.quick
    if legacy:
        if not a.symbol:
            print("Give --symbol (one pair) or --symbols (comma list)")
            return EXIT_REFUSED
        args = {"dataset_id": a.dataset, "symbol": a.symbol.upper(), "mode": a.mode, "split": a.split or None,
                "folds": a.folds, "account_type": a.account_type, "allow_degraded": a.allow_degraded,
                "verify": a.verify, "spec": a.spec}
        rc, r = _job("baseline", args)
    else:
        if a.strategy not in LAB_ORDER:
            print(f"Unknown research strategy {a.strategy}. See: ayesha research strategies")
            return EXIT_REFUSED
        if a.mode != "m15":
            print("Strategy Lab runs use M15 bars; --mode m5confirm exists for the baseline's legacy path only.")
            return EXIT_REFUSED
        if not (a.symbols or a.symbol):
            print("Give --symbol (one pair) or --symbols (comma list)")
            return EXIT_REFUSED
        rc, r = _job("strategy", {**_lab_args(a), "strategy_id": a.strategy, "verify": a.verify})
    if r is None:
        return rc
    if a.verify and "verified" in r:
        print(f"{r['run_id']}: {'VERIFIED: the recomputed result has the same hash' if r['verified'] else 'MISMATCH'}"
              f" ({r['recomputed_result_sha256'][:16]})")
        return EXIT_OK if r["verified"] else EXIT_FAILED
    if legacy:
        print(f"Run {r['run_id']}: {r['status']}" + (" (already done with exactly these inputs)" if r.get("existing")
                                                     else ""))
        if not r.get("existing"):
            print(f"Signals {r['signals']}, closed trades {r['closed_trades']}; limitations: "
                  f"{', '.join(r['limitations'])}")
    else:
        _print_lab_run(r)
    print(f"Report: ayesha research report {r['run_id']} --md report.md")
    return EXIT_OK


def cmd_lab(a) -> int:
    rc, r = _job("lab", _lab_args(a))
    if r is None:
        return rc
    for run in r["runs"]:
        _print_lab_run(run)
    print(f"\nComparison {r['comparison_id']}: ranking {r['ranking']}, benchmark parity {r['benchmark_parity']}")
    print(f"Report: ayesha research report {r['comparison_id']} --md lab.md")
    print("Research only: a strategy that looks better here is not validated and is never traded automatically.")
    return EXIT_OK if r["benchmark_parity"] in ("MATCHED", "NOT_INCLUDED") else EXIT_FAILED


def cmd_compare(a) -> int:
    rc, r = _job("compare", {"run_ids": a.run_ids, "spec": a.spec})
    if r is None:
        return rc
    print(f"Comparison {r['comparison_id']}: ranking {r['ranking']}, benchmark parity {r['benchmark_parity']}")
    print(f"Report: ayesha research report {r['comparison_id']} --md lab.md")
    return EXIT_OK


def cmd_comparisons(a) -> int:
    from ayesha.research.evaluation.comparison import comparisons
    from ayesha.research.readonly import ReadOnlyWorkspace

    if not (research_home() / "research.db").exists():
        print("No research data yet.")
        return EXIT_OK
    ws = ReadOnlyWorkspace(research_home())
    try:
        docs = comparisons(ws)
    finally:
        ws.close()
    rows = [{"comparison_id": d["comparison_id"], "dataset_id": d["dataset_id"], "symbols": d["symbols"],
             "strategies": [r["strategy_id"] for r in d["runs"]], "ranking": d["ranking"]["state"],
             "created_at_utc": d["created_at_utc"]} for d in docs]
    if a.json:
        _p(rows)
        return EXIT_OK
    if not rows:
        print("No comparisons yet. Run: ayesha research lab --dataset DS --symbols EURUSD,GBPUSD")
    for r in rows:
        print(f"{r['comparison_id']}  {r['dataset_id']} {','.join(r['symbols'])}  {len(r['strategies'])} strategies  "
              f"{r['ranking']}  {r['created_at_utc']}")
    return EXIT_OK


def cmd_runs(a) -> int:
    con = _registry()
    if con is None:
        print("No research data yet.")
        return EXIT_OK
    try:
        rows = [dict(r) for r in con.execute(
            "SELECT r.run_id, r.dataset_id, r.strategy_id, r.version, r.status, r.created_utc, r.inputs_json, "
            "(SELECT count FROM evaluation_metrics m WHERE m.run_id=r.run_id AND period='ALL' AND regime='ALL') "
            "AS closed FROM research_runs r ORDER BY r.created_utc DESC, r.run_id LIMIT ?", (a.limit,))]
    finally:
        con.close()
    for r in rows:
        inp = json.loads(r.pop("inputs_json"))
        r["symbol"], r["mode"] = inp.get("symbol") or ",".join(inp.get("symbols", [])), inp.get("mode")
    if a.json:
        _p(rows)
        return EXIT_OK
    if not rows:
        print("No runs yet.")
    for r in rows:
        print(f"{r['run_id']}  {r['status']:<17}  {r['strategy_id']} {r['version']}  {r['dataset_id']} {r['symbol']} "
              f"{r['mode']}  closed {r['closed'] if r['closed'] is not None else '-'}  {r['created_utc']}")
    return EXIT_OK


def cmd_report(a) -> int:
    from ayesha.research.evaluation import comparison
    from ayesha.research.evaluation.report import comparison_json, comparison_markdown, run_json, run_markdown
    from ayesha.research.readonly import ReadOnlyWorkspace
    from ayesha.research.simulation.baseline import RunRefused

    if not (research_home() / "research.db").exists():
        print("No research data yet.")
        return EXIT_REFUSED
    ws = ReadOnlyWorkspace(research_home())
    try:
        if a.run_id.startswith("cmp_"):
            c = comparison.load(ws, a.run_id)
            md, doc = comparison_markdown(c), comparison_json(c)
        else:
            md = run_markdown(ws, a.run_id)
            doc = run_json(ws, a.run_id) if a.json else None
    except RunRefused as e:
        print(str(e))
        return EXIT_REFUSED
    finally:
        ws.close()
    if a.md:
        Path(a.md).write_text(md, encoding="utf-8")
        print(f"Wrote {a.md}")
    if a.json:
        Path(a.json).write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {a.json}")
    if not a.md and not a.json:
        print(md)
    return EXIT_OK


def cmd_parity(a) -> int:
    args = {"dataset_id": a.dataset, "symbol": a.symbol.upper(), "mode": a.mode, "account_type": a.account_type,
            "legacy_csv": str(Path(a.legacy_csv).resolve()) if a.legacy_csv else None, "spec": a.spec}
    rc, r = _job("parity", args)
    if r is None:
        return rc
    if a.out:
        Path(a.out).write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
    c, s = r["candles"], r["signals"]
    print(f"Parity {r['status']} ({r['legacy_input']}): bars {c['bars'][0]} vs {c['bars'][1]}, "
          f"signals {s['signals'][0]} vs {s['signals'][1]}, changed outcomes {s['changed_count']}")
    for code, text in r["explanations"].items():
        print(f"  {code}: {text}")
    print(f"  {r['note']}")
    return EXIT_OK if r["status"] in ("MATCHED", "MATCHED_WITH_EXPLAINED_DIFFERENCES") else EXIT_FAILED


def _locked_ws():
    from ayesha.research.worker import WorkerBusy, lock_for

    ws = _ws()
    lock = lock_for(ws.root)
    if not lock.acquire():
        ws.close()
        raise WorkerBusy("a research job is running; try again when it has finished")
    return ws, lock


def cmd_backup(a) -> int:
    from ayesha.research.worker import WorkerBusy

    if not (research_home() / "research.db").exists():
        print("No research data yet: nothing to back up.")
        return EXIT_OK
    try:
        ws, lock = _locked_ws()
    except WorkerBusy as e:
        print(f"BUSY: {e}")
        return EXIT_BUSY
    try:
        r = ws.db.backup(ws.backups, keep=int(ws.cfg.r["backup_keep"]))
    finally:
        lock.release()
        ws.close()
    print(f"Backup: {r['path']} (sha256 {r['sha256'][:16]}, integrity ok)" +
          (f"; rotated {len(r['rotated'])} old backup(s)" if r["rotated"] else ""))
    print("Frozen data files are write-once; to move research to another PC copy the whole research folder.")
    return EXIT_OK


def cmd_restore(a) -> int:
    from ayesha.research.storage.db import ResearchDBError
    from ayesha.research.worker import WorkerBusy

    src = Path(a.file)
    if not src.is_file():
        print(f"Not a file: {src}")
        return EXIT_REFUSED
    if not a.yes:
        print(f"This replaces the research registry with {src.name}. The current one is saved first "
              "(backups/pre-restore). Research data files are not touched; the live scanner is not affected.")
        if input("Type RESTORE to continue: ").strip() != "RESTORE":
            print("Not restored.")
            return EXIT_REFUSED
    try:
        ws, lock = _locked_ws()
    except WorkerBusy as e:
        print(f"BUSY: {e}")
        return EXIT_BUSY
    try:
        r = ws.db.restore(src, ws.backups / "pre-restore")
    except ResearchDBError as e:
        print(f"NOT RESTORED: {e}")
        return EXIT_REFUSED
    finally:
        lock.release()
        ws.close()
    print(f"Restored from {src.name}; the previous registry is saved as {Path(r['pre_restore_backup']).name}")
    return EXIT_OK


def cmd_dashboard(a) -> int:
    from ayesha.research.dashboard.server import check_server, serve

    if a.check:
        return check_server()
    return serve(port=a.port, open_browser=not a.no_browser)


def cmd_selftest(a) -> int:
    rc, r = _job("selftest", {"mode": a.mode}, need_enabled=False)
    if r is not None:
        print(f"selftest {a.mode}: OK")
    return rc


def build_parser(prog: str = "ayesha research") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog, description=BANNER)
    p.add_argument("--spec", help="path to strategy-spec.yaml (default: the repository's)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="research on/off, data, runs, worker and backups")
    s.set_defaults(fn=cmd_status)
    s = sub.add_parser("enable", help="turn research on (research-only; the scanner is not affected)")
    s.set_defaults(fn=cmd_enable)
    s = sub.add_parser("disable", help="turn research off (legacy_only); research data is kept")
    s.set_defaults(fn=cmd_disable)

    s = sub.add_parser("doctor", help="research health and isolation checks")
    s.add_argument("--deep", action="store_true", help="verify the hash of every stored file (slower)")
    s.add_argument("--selftest", action="store_true", help="also start a worker selftest in its own process")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("ingest", help="freeze a dataset: OANDA practice download or exported CSV files")
    s.add_argument("--from-csv-dir", help="folder with <PAIR>_M15.csv / <PAIR>_M5.csv (ayesha export format)")
    s.add_argument("--provider", choices=["oanda"], help="download from OANDA v20 practice (read-only)")
    s.add_argument("--pairs", help="comma list (default: the enabled pairs)")
    s.add_argument("--days", type=int, default=1095, help="history length for --provider oanda (1..3650)")
    s.add_argument("--tf", default="M15,M5", help="timeframes for --provider oanda (M15, M5)")
    s.add_argument("--label", help="your description of the data")
    s.add_argument("--provider-label", help="CSV only: who produced the files (capital letters, e.g. MY_EXPORT)")
    s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("datasets", help="list frozen datasets")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_datasets)
    s = sub.add_parser("inspect", help="show a dataset's manifest and quality reports")
    s.add_argument("dataset")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_inspect)

    s = sub.add_parser("strategies", help="list the research strategies (baseline, control, experimental)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_strategies)

    def lab_opts(s, symbol_required: bool) -> None:
        s.add_argument("--dataset", required=True)
        if not symbol_required:
            s.add_argument("--symbol", help="one pair")
        s.add_argument("--symbols", required=symbol_required, help="comma list of pairs (one account across them)")
        s.add_argument("--split", help="in-sample / out-of-sample split date, e.g. 2025-01-01")
        s.add_argument("--folds", type=int, default=4, choices=range(2, 13), metavar="2..12")
        s.add_argument("--holdout", help="seal the data from this date (results hidden until --reveal-holdout)")
        s.add_argument("--reveal-holdout", action="store_true",
                       help="show the sealed holdout results (recorded in the audit trail; do it once, at the end)")
        s.add_argument("--account-type", default="Standard", choices=["Standard", "StandardCent"])
        s.add_argument("--allow-degraded", action="store_true", help="use a DEGRADED dataset (marked in the result)")
        s.add_argument("--quick", action="store_true", help="skip the robustness re-runs (costs, parameters)")

    s = sub.add_parser("run", help="run one research strategy on a frozen dataset")
    s.add_argument("strategy", help="see: ayesha research strategies")
    lab_opts(s, symbol_required=False)
    s.add_argument("--mode", default="m15", choices=["m15", "m5confirm"],
                   help="m5confirm: baseline only, legacy replay path (v0.9.0)")
    s.add_argument("--verify", action="store_true", help="recompute a finished run and compare its hashes")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("lab", help="Strategy Lab: run every research strategy on the same inputs and compare them")
    lab_opts(s, symbol_required=True)
    s.set_defaults(fn=cmd_lab, symbol=None)
    s = sub.add_parser("compare", help="compare finished lab runs (same dataset, symbols, split, costs, account)")
    s.add_argument("run_ids", nargs="+")
    s.set_defaults(fn=cmd_compare)
    s = sub.add_parser("comparisons", help="list Strategy Lab comparisons")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_comparisons)

    s = sub.add_parser("runs", help="list research runs")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_runs)
    s = sub.add_parser("report", help="sanitised run or comparison report (Markdown / JSON)")
    s.add_argument("run_id", help="a run id (run_...) or a comparison id (cmp_...)")
    s.add_argument("--md", help="write Markdown here")
    s.add_argument("--json", help="write JSON here")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("parity", help="compare a snapshot replay with the legacy CSV replay (plan AI-005)")
    s.add_argument("--dataset", required=True)
    s.add_argument("--symbol", required=True)
    s.add_argument("--mode", default="m15", choices=["m15", "m5confirm"])
    s.add_argument("--legacy-csv", help="your original CSV file (default: the legacy save/load round trip)")
    s.add_argument("--account-type", default="Standard", choices=["Standard", "StandardCent"])
    s.add_argument("--out", help="write the parity result as JSON")
    s.set_defaults(fn=cmd_parity)

    s = sub.add_parser("backup", help="verified copy of the research registry (rotating)")
    s.set_defaults(fn=cmd_backup)
    s = sub.add_parser("restore", help="restore the research registry from a backup file")
    s.add_argument("file")
    s.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    s.set_defaults(fn=cmd_restore)

    s = sub.add_parser("dashboard", help="read-only local dashboard on 127.0.0.1 (this PC only)")
    s.add_argument("--port", type=int, default=0, help="default: a free port")
    s.add_argument("--no-browser", action="store_true")
    s.add_argument("--check", action="store_true", help="start, self-test the security rules, stop")
    s.set_defaults(fn=cmd_dashboard)

    s = sub.add_parser("selftest", help="worker isolation selftest (works with research off)")
    s.add_argument("mode", choices=["ok", "crash", "hang", "memory"])
    s.set_defaults(fn=cmd_selftest)
    return p


def main(argv: list[str] | None = None, spec: str | None = None) -> int:
    a = build_parser().parse_args(argv)
    a.spec = a.spec or spec
    try:
        return a.fn(a)
    except ResearchDisabled:
        print(OFF)
        return EXIT_REFUSED
    except ResearchConfigError as e:
        print(f"Research settings are invalid, so research stays off: {e}\n"
              "Fix the file, or reset it with: ayesha research disable")
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
