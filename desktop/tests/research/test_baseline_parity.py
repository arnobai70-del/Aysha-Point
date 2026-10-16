"""AI-005 / T01 / T02: the baseline replays the frozen live rules unchanged on a frozen snapshot. Same inputs give the
same run id and result hash; the numbers equal the legacy `ayesha report`; nothing is executable or READY; future
bars cannot change earlier decisions; parity with the legacy CSV path is MATCHED or DIFFERENT with an explanation."""

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from ayesha.config import load_spec
from ayesha.research.datasets.ingest import ingest_csv_dir, ingest_oanda
from ayesha.research.evaluation.parity import parity
from ayesha.research.simulation.baseline import (APPROX_USD_RATES, RunRefused, load_candidates, load_candles,
                                                 load_result, run_baseline)
from tests.research import synth

NOW = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def ds(ws, csv_folder):
    return ingest_csv_dir(ws, csv_folder, load_spec(), now=NOW)["dataset_id"]


def test_same_inputs_same_run_id_and_hashes_and_verify(ws, ds):
    spec = load_spec()
    a = run_baseline(ws, spec, ds, "EURUSD", split="2025-03-20")
    assert a["status"] == "COMPLETED" and not a["existing"]
    b = run_baseline(ws, spec, ds, "EURUSD", split="2025-03-20")
    assert b["existing"] and b["run_id"] == a["run_id"] and b["result_sha256"] == a["result_sha256"]
    v = run_baseline(ws, spec, ds, "EURUSD", split="2025-03-20", verify=True)
    assert v["verified"] is True
    c = run_baseline(ws, spec, ds, "EURUSD", split="2025-03-21")  # one input changed -> a different run
    assert c["run_id"] != a["run_id"]
    assert ws.db.verify_chain()[0]


def test_numbers_equal_the_legacy_report_on_the_same_bars(ws, ds, csv_folder):
    from ayesha.backtest.replay import run_backtest
    from ayesha.backtest.report import build_report
    from ayesha.feed.csv_feed import load_candles as legacy_load

    spec = load_spec()
    r = run_baseline(ws, spec, ds, "EURUSD", split="2025-03-20", folds=3)
    res = load_result(ws, r["run_id"])
    sp = copy.deepcopy(spec)
    sp["mtf"]["confirm_timeframe"] = None
    legacy = run_backtest("EURUSD", legacy_load(csv_folder / "EURUSD_M15.csv", 0.00001), sp,
                          account_type="Standard", usd_rates=APPROX_USD_RATES)
    rep = build_report({"EURUSD|m15": legacy}, spec, split_at=datetime(2025, 3, 20, tzinfo=timezone.utc), folds=3,
                       data_label=ds, usd_rates=APPROX_USD_RATES)
    assert json.loads(json.dumps(rep, default=str)) == res["metrics"]["legacy_report"]


def test_outputs_are_research_only_never_ready_or_executable(ws, ds):
    from ayesha.research.contracts import validate

    spec = load_spec()
    r = run_baseline(ws, spec, ds, "EURUSD", mode="m5confirm")
    res = load_result(ws, r["run_id"])
    assert res["source_type"] == "RESEARCH" and res["executable"] is False
    assert "NOT_EXECUTABLE_RESEARCH_ONLY" in res["limitations"] and "NEWS_NOT_MODELLED" in res["limitations"]
    cands = load_candidates(ws, r["run_id"])
    assert cands, "the scenario should produce signals"
    for c in cands:
        assert validate(c, "research.candidate/1") == []
        assert c["executable"] is False and c["proposed_state"] != "READY"
    states = {d["proposed_state"] for d in ws.db.decisions(r["run_id"])}
    assert "READY" not in states and states


def test_small_samples_are_labelled(ws, ds):
    r = run_baseline(ws, load_spec(), ds, "EURUSD")
    res = load_result(ws, r["run_id"])
    assert "SMALL_SAMPLE" in res["limitations"]
    assert any("far too few" in w for w in res["warnings"])


def test_rejected_degraded_and_missing_inputs_are_refused(ws, tmp_path):
    spec = load_spec()
    bars = synth.fx_week(3000, seed=5)
    gappy = bars[:1000] + bars[1100:]  # a 25-hour hole: DEGRADED
    synth.write_csv(tmp_path / "g", "EURUSD", "M15", gappy)
    g = ingest_csv_dir(ws, tmp_path / "g", spec, now=NOW)
    assert g["quality_state"] == "DEGRADED"
    with pytest.raises(RunRefused, match="DEGRADED"):
        run_baseline(ws, spec, g["dataset_id"], "EURUSD")
    ok = run_baseline(ws, spec, g["dataset_id"], "EURUSD", allow_degraded=True)
    assert "DEGRADED_INPUT_DATA" in ok["limitations"]
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "EURUSD_M15.csv").write_text("time,open,high,low,close\n2025-03-03T00:00:00Z,1,0.5,1,1\n",
                                                     encoding="utf-8")
    bad = ingest_csv_dir(ws, tmp_path / "bad", spec, now=NOW)
    assert bad["quality_state"] == "REJECTED"
    with pytest.raises(RunRefused, match="REJECTED"):
        run_baseline(ws, spec, bad["dataset_id"], "EURUSD", allow_degraded=True)
    with pytest.raises(RunRefused, match="partition"):
        run_baseline(ws, spec, g["dataset_id"], "GBPUSD", allow_degraded=True)
    with pytest.raises(RunRefused):
        run_baseline(ws, spec, "ds_0000000000000000", "EURUSD")
    with pytest.raises(ValueError):
        run_baseline(ws, spec, g["dataset_id"], "EURUSD", split="not-a-date", allow_degraded=True)


def test_t02_future_bars_cannot_change_earlier_decisions(ws, tmp_path):
    """Change every bar after index K: signals decided before K and trades that ended before K stay identical."""
    from ayesha.backtest.replay import run_backtest

    spec = load_spec()
    sp = copy.deepcopy(spec)
    sp["mtf"]["confirm_timeframe"] = None
    bars = synth.fx_week(6000, seed=11)
    k = 4000
    changed = bars[:k] + [b.__class__(b.time, b.open * 1.01, b.high * 1.01, b.low * 1.01, b.close * 1.01, b.volume,
                                      b.spread) for b in bars[k:]]
    synth.write_csv(tmp_path / "a", "EURUSD", "M15", bars)
    synth.write_csv(tmp_path / "b", "EURUSD", "M15", changed)
    da = ingest_csv_dir(ws, tmp_path / "a", spec, now=NOW)["dataset_id"]
    db_ = ingest_csv_dir(ws, tmp_path / "b", spec, now=NOW)["dataset_id"]
    assert da != db_
    ta = run_backtest("EURUSD", load_candles(ws, da, "EURUSD", "M15"), sp)["trades"]
    tb = run_backtest("EURUSD", load_candles(ws, db_, "EURUSD", "M15"), sp)["trades"]
    cut = bars[k].time
    early_a = [t for t in ta if t.signal.bar_close_utc <= cut]
    early_b = [t for t in tb if t.signal.bar_close_utc <= cut]
    assert early_a, "need signals before the mutation point"
    assert [t.signal.signal_id for t in early_a] == [t.signal.signal_id for t in early_b]
    done_a = [(t.signal.signal_id, t.status, t.r) for t in early_a if t.exit_index is not None and t.exit_index < k]
    done_b = [(t.signal.signal_id, t.status, t.r) for t in early_b if t.exit_index is not None and t.exit_index < k]
    assert done_a == done_b


def test_parity_matched_on_the_legacy_csv_round_trip(ws, ds, csv_folder):
    spec = load_spec()
    for mode in ("m15", "m5confirm"):
        p = parity(ws, spec, ds, "EURUSD", mode=mode)
        assert p["status"] == "MATCHED", p
        assert p["candles"]["equal"] and p["signals"]["equal"] and p["explanations"] == {}
    p = parity(ws, spec, ds, "EURUSD", legacy_csv=csv_folder / "EURUSD_M15.csv")
    assert p["status"] == "MATCHED" and p["legacy_input"] == "OWNER_CSV"


def test_parity_explains_whole_point_spread_rounding_on_provider_data(ws):
    """OANDA spreads are ask - bid in floating point (e.g. 7.99999...e-05); the legacy CSV stores whole points."""
    spec = load_spec()
    series = {"M15": synth.fx_week(3000, seed=31)}
    fake = synth.FakeOanda(series)
    end = series["M15"][-1].time + timedelta(minutes=20)
    d = ingest_oanda(ws, spec, ["EURUSD"], days=40, timeframes=("M15",), token="t" * 10, http_get=fake,
                     clock=lambda: end, sleep=lambda s: None, min_interval_s=0)["dataset_id"]
    p = parity(ws, spec, d, "EURUSD")
    assert p["status"] in ("MATCHED_WITH_EXPLAINED_DIFFERENCES", "DIFFERENT")
    assert p["candles"]["price_or_time_differences"] == 0 and p["candles"]["spread_rounding_differences"] > 0
    assert set(p["explanations"]) == {"SPREAD_ROUNDED_TO_WHOLE_POINTS"}
    if p["status"] == "DIFFERENT":  # only allowed when an outcome really moved, and then it is listed
        assert p["signals"]["changed_count"] or p["signals"]["only_in_snapshot"] or p["signals"]["only_in_legacy"]


def test_parity_reports_real_differences(ws, csv_folder, tmp_path):
    spec = load_spec()
    d = ingest_csv_dir(ws, csv_folder, spec, now=NOW)["dataset_id"]
    bars = synth.fx_week(4000, seed=11)
    other = bars[:2000] + [b.__class__(b.time, b.open + 0.001, b.high + 0.001, b.low + 0.001, b.close + 0.001,
                                       b.volume, b.spread) for b in bars[2000:]]
    f = synth.write_csv(tmp_path / "o", "EURUSD", "M15", other)
    p = parity(ws, spec, d, "EURUSD", legacy_csv=f)
    assert p["status"] == "DIFFERENT" and "PRICE_OR_TIME_DIFFERENT" in p["explanations"]
