"""AI-008 / AI-009 / T01 / T03: Strategy Lab runs and comparisons on a frozen dataset. Same inputs give the same run
and comparison ids; every strategy is cut by the same split plan; the holdout stays sealed until it is revealed (and
that is audited); comparisons refuse different inputs; nothing is READY or executable; the CLI and the read-only
dashboard show it. All prices are SYNTHETIC."""

import json
from datetime import datetime, timezone

import pytest

from ayesha.config import load_spec
from ayesha.research.datasets.ingest import ingest_csv_dir
from ayesha.research.evaluation import comparison as C
from ayesha.research.simulation import lab
from ayesha.research.simulation.baseline import RunRefused, load_candidates, run_baseline
from ayesha.research.strategies import loader
from tests.research import synth

NOW = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
A, B, X = loader.LAB_ORDER


@pytest.fixture
def two(ws, tmp_path):
    f = synth.csv_dir(tmp_path / "csv", m15=4000, seed=11)
    synth.write_csv(f, "GBPUSD", "M15", synth.fx_week(4000, seed=12))
    return ingest_csv_dir(ws, f, load_spec(), now=NOW)["dataset_id"]


def _walk(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)
    else:
        yield obj


def test_lab_runs_every_strategy_on_the_same_inputs_and_compares_them(ws, two):
    spec = load_spec()
    r = C.run_lab(ws, spec, two, "EURUSD,GBPUSD", holdout="2025-04-05")
    assert [x["strategy_id"] for x in r["runs"]] == list(loader.LAB_ORDER)
    assert r["benchmark_parity"] == "MATCHED"
    doc = C.load(ws, r["comparison_id"])
    assert doc["executable"] is False and doc["source_type"] == "RESEARCH"
    assert doc["ranking"]["state"] == "NO_RANKING"  # far too few trades on synthetic weeks
    assert set(doc["differences_vs_baseline"]) == {B, X}
    results = [lab.load_result(ws, x["run_id"]) for x in r["runs"]]
    assert len({res["split_plan_id"] for res in results}) == 1
    assert len({res["cost_model_id"] for res in results}) == 1
    assert all(res["symbols"] == ["EURUSD", "GBPUSD"] and res["engine"] == "research-runner-1" for res in results)
    for res in results:
        assert "READY" not in set(map(str, _walk(res)))
        for c in load_candidates(ws, res["run_id"]):
            assert c["executable"] is False and c["proposed_state"] != "READY"
            assert c["asof_utc"] < "2025-04-05"  # sealed holdout: not shown
    assert "READY" not in set(map(str, _walk(doc)))
    again = C.run_lab(ws, spec, two, "EURUSD,GBPUSD", holdout="2025-04-05")
    assert again["comparison_id"] == r["comparison_id"] and all(x["existing"] for x in again["runs"])
    assert len(C.comparisons(ws)) == 1
    for x in r["runs"]:
        v = lab.run_strategy(ws, spec, x["strategy_id"], two, "EURUSD,GBPUSD", holdout="2025-04-05", verify=True)
        assert v["verified"] is True
    assert ws.db.verify_chain()[0]


def test_revealing_the_holdout_is_a_new_audited_run(ws, two):
    spec = load_spec()
    sealed = lab.run_strategy(ws, spec, B, two, "EURUSD", holdout="2025-04-01", robustness=False)
    shown = lab.run_strategy(ws, spec, B, two, "EURUSD", holdout="2025-04-01", reveal_holdout=True,
                             robustness=False)
    assert shown["run_id"] != sealed["run_id"]
    assert lab.load_result(ws, sealed["run_id"])["metrics"]["holdout"]["state"] == "SEALED"
    assert lab.load_result(ws, shown["run_id"])["metrics"]["holdout"]["state"] == "REVEALED"
    ops = [e["operation"] for e in ws.db.events(200)]
    assert ops.count("HOLDOUT_REVEALED") == 1
    with pytest.raises(RunRefused):
        C.compare(ws, [sealed["run_id"], shown["run_id"]])  # different holdout state is a different input


def test_comparison_refuses_different_inputs(ws, two):
    spec = load_spec()
    a = lab.run_strategy(ws, spec, A, two, "EURUSD", robustness=False)
    b = lab.run_strategy(ws, spec, B, two, "EURUSD", robustness=False)
    for other in (lab.run_strategy(ws, spec, B, two, "EURUSD", folds=3, robustness=False),
                  lab.run_strategy(ws, spec, B, two, "EURUSD,GBPUSD", robustness=False),
                  lab.run_strategy(ws, spec, B, two, "EURUSD", robustness=True),
                  lab.run_strategy(ws, spec, B, two, "EURUSD", account_type="StandardCent", robustness=False)):
        with pytest.raises(RunRefused):
            C.compare(ws, [a["run_id"], other["run_id"]])
    with pytest.raises(RunRefused):
        C.compare(ws, [a["run_id"]])
    with pytest.raises(RunRefused):
        C.compare(ws, [b["run_id"], lab.run_strategy(ws, spec, B, two, "EURUSD", folds=3,
                                                     robustness=False)["run_id"]])
    legacy = run_baseline(ws, spec, two, "EURUSD")
    with pytest.raises(RunRefused, match="not a Strategy Lab run"):
        C.compare(ws, [legacy["run_id"], b["run_id"]])
    doc = C.compare(ws, [b["run_id"], a["run_id"]])
    assert [r["strategy_id"] for r in doc["runs"]] == [A, B]  # stable order, baseline first


def test_lab_runs_refuse_bad_inputs(ws, two):
    spec = load_spec()
    for kw in ({"symbols": ""}, {"symbols": "USDJPY"}, {"holdout": "2030-01-01"}, {"split": "2001-01-01"}):
        with pytest.raises(RunRefused):
            lab.run_strategy(ws, spec, B, two, **{"symbols": "EURUSD", **kw})
    with pytest.raises(RunRefused):
        lab.run_strategy(ws, spec, "made-up", two, "EURUSD")
    with pytest.raises(RunRefused):
        lab.run_strategy(ws, spec, B, "ds_0000000000000000", "EURUSD")


def test_cli_lab_compare_report_and_dashboard(home, tmp_path, capsys):
    from ayesha.cli import main as ayesha
    from ayesha.research.dashboard.server import App

    synth.csv_dir(tmp_path / "csv", m15=3000, seed=4)
    assert ayesha(["research", "enable"]) == 0
    assert ayesha(["research", "strategies"]) == 0
    out = capsys.readouterr().out
    assert all(s in out for s in loader.LAB_ORDER) and "EXPERIMENTAL" in out
    assert ayesha(["research", "ingest", "--from-csv-dir", str(tmp_path / "csv")]) == 0
    assert "ayesha research lab --dataset" in capsys.readouterr().out
    assert ayesha(["research", "datasets", "--json"]) == 0
    ds = json.loads(capsys.readouterr().out)[0]["dataset_id"]
    assert ayesha(["research", "lab", "--dataset", ds, "--symbols", "EURUSD", "--quick"]) == 0
    out = capsys.readouterr().out
    cid = next(w for w in out.split() if w.startswith("cmp_")).rstrip(":")
    assert "benchmark parity MATCHED" in out
    assert ayesha(["research", "run", B, "--dataset", ds, "--symbol", "EURUSD", "--quick"]) == 0
    assert "already done" in capsys.readouterr().out
    assert ayesha(["research", "run", B, "--dataset", ds, "--symbol", "EURUSD", "--quick", "--verify"]) == 0
    assert "VERIFIED" in capsys.readouterr().out
    assert ayesha(["research", "run", B, "--dataset", ds, "--symbol", "EURUSD", "--mode", "m5confirm"]) == 2
    capsys.readouterr()
    assert ayesha(["research", "comparisons", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["comparison_id"] == cid
    md, js = tmp_path / "lab.md", tmp_path / "lab.json"
    assert ayesha(["research", "report", cid, "--md", str(md), "--json", str(js)]) == 0
    text = md.read_text(encoding="utf-8")
    assert "RESEARCH ONLY" in text and "Side by side" in text and "NO_RANKING" in text
    assert json.loads(js.read_text(encoding="utf-8"))["executable"] is False
    capsys.readouterr()
    assert ayesha(["research", "runs", "--json"]) == 0
    runs = json.loads(capsys.readouterr().out)
    run_b = next(r["run_id"] for r in runs if r["strategy_id"] == B)
    assert ayesha(["research", "report", run_b, "--md", str(md)]) == 0
    assert "Hypothetical accounts" in md.read_text(encoding="utf-8")

    app = App(home / "research", "k")
    for path in ("/lab", f"/lab/{cid}", f"/runs/{run_b}", "/runs", "/"):
        status, _, body, _ = app.route(path)
        assert status == 200, path
        assert b"<script" not in body and b"RESEARCH ONLY" in body
    assert b"Side by side" in app.route(f"/lab/{cid}")[2]
    assert b"Hypothetical accounts" in app.route(f"/runs/{run_b}")[2]
    status, ctype, body, head = app.route(f"/lab/{cid}/report.json")
    assert status == 200 and json.loads(body)["comparison_id"] == cid and "attachment" in head["Content-Disposition"]
    assert app.route(f"/lab/{cid}/report.md")[0] == 200
    assert app.route("/lab/cmp_0000000000000000")[0] == 200  # a page saying "unknown", not an error
    assert app.route("/lab/x/report.md")[0] == 404
    assert ayesha(["research", "compare", run_b]) == 2  # one run is not a comparison
