"""AI-006 / T07: research jobs run in a separate, limited worker process. A crash, a hang or a memory blow-up ends as a
recorded status, releases the single-writer lock and leaves nothing partial; the live scanner keeps producing exactly
the 0.8.0 results while a research worker misbehaves."""

import json
import sys
import tempfile
import threading
from pathlib import Path

import pytest

from ayesha.research.worker import JobLock, WorkerBusy, lock_for, run_job


def test_selftest_ok_runs_in_another_process_with_limits(ws):
    import os

    r = run_job(ws, "selftest", {"mode": "ok"})
    assert r["status"] == "OK" and r["exit_code"] == 0
    assert r["result"]["pid"] != os.getpid()
    assert r["limits_applied"], "the worker must report the limits it runs under"
    if sys.platform.startswith("linux"):
        assert "nice+10" in r["limits_applied"] and "RLIMIT_AS=256MB" in r["limits_applied"]
    if sys.platform == "win32":
        assert "below-normal-priority" in r["limits_applied"]
        assert "job-memory=256MB" in r["limits_applied"] and "kill-on-close" in r["limits_applied"]
    assert ws.db.job(r["job_id"])["status"] == "OK"


def test_crash_is_recorded_and_the_lock_is_released(ws):
    r = run_job(ws, "selftest", {"mode": "crash"})
    assert r["status"] == "CRASHED" and r["exit_code"] == 13
    assert not lock_for(ws.root).held_by_other()
    assert run_job(ws, "selftest", {"mode": "ok"})["status"] == "OK"


def test_hang_is_stopped_by_the_timeout(ws):
    r = run_job(ws, "selftest", {"mode": "hang"}, timeout=2)
    assert r["status"] == "TIMEOUT" and ws.db.job(r["job_id"])["status"] == "TIMEOUT"
    assert not lock_for(ws.root).held_by_other()


@pytest.mark.skipif(sys.platform == "darwin", reason="macOS has no enforceable address-space limit")
def test_memory_blow_up_hits_the_limit_not_the_pc(ws):
    r = run_job(ws, "selftest", {"mode": "memory"}, timeout=120)
    assert r["status"] == "RESOURCE_LIMIT", r
    assert ws.db.job(r["job_id"])["status"] == "RESOURCE_LIMIT"


def test_one_writer_at_a_time(ws):
    hold = lock_for(ws.root)
    assert hold.acquire()
    try:
        with pytest.raises(WorkerBusy):
            run_job(ws, "selftest", {"mode": "ok"})
        assert JobLock(ws.root / "jobs" / "worker.lock").held_by_other()
    finally:
        hold.release()
    assert run_job(ws, "selftest", {"mode": "ok"})["status"] == "OK"


def test_a_run_left_running_by_a_dead_worker_becomes_failed_incomplete(ws, csv_folder):
    from ayesha.config import load_spec
    from ayesha.research.datasets.ingest import ingest_csv_dir
    from ayesha.research.simulation.baseline import run_inputs

    spec = load_spec()
    ds = ingest_csv_dir(ws, csv_folder, spec)["dataset_id"]
    inputs = run_inputs(ws, spec, ds, "EURUSD", "m15", None, 4, "Standard", False)
    ws.db.start_run("run_00000000000000aa", inputs)  # as if a worker died in the middle of this run
    r = run_job(ws, "selftest", {"mode": "ok"})
    assert r["status"] == "OK"
    row = ws.db.run("run_00000000000000aa")
    assert row["status"] == "FAILED_INCOMPLETE" and ws.db.decisions("run_00000000000000aa") == []


def test_refusals_and_failures_are_statuses_not_tracebacks(ws):
    r = run_job(ws, "baseline", {"dataset_id": "ds_0000000000000000", "symbol": "EURUSD"})
    assert r["status"] == "REFUSED" and "unknown dataset" in r["error"]
    r = run_job(ws, "ingest_csv", {"folder": str(ws.root / "nowhere")})
    assert r["status"] == "REFUSED"


def test_jobs_need_research_on_except_the_selftest(home):
    from ayesha.research.config import load
    from ayesha.research.workspace import Workspace

    w = Workspace(load(home / "research" / "config.yaml"), home / "research")
    try:
        assert run_job(w, "selftest", {"mode": "ok"})["status"] == "OK"
        r = run_job(w, "baseline", {"dataset_id": "ds_0000000000000000", "symbol": "EURUSD"})
        assert r["status"] == "REFUSED" and "Research is off" in r["error"]
    finally:
        w.close()


def test_worker_logs_and_records_are_redacted(ws):
    secret = "0123456789abcdef" * 2 + "-" + "fedcba9876543210" * 2
    r = run_job(ws, "ingest_csv", {"folder": str(ws.root / "nowhere"), "label": f"token={secret}"})
    blob = json.dumps([dict(j) for j in ws.db.jobs()]) + (ws.root / r["log"]).read_text(encoding="utf-8")
    assert secret not in blob


def test_scanner_results_are_unchanged_while_a_research_worker_hangs(ws, tmp_path):
    """T07: the live path is a different process with its own registry; a stuck research job cannot touch it."""
    import copy

    from ayesha.config import load_spec
    from tests.research import golden

    expected = json.loads(golden.FIXTURE.read_text(encoding="utf-8"))["scanner"]["equity_100000_no_news"]
    from ayesha.research.workspace import Workspace

    stop = threading.Event()
    box = {}

    def research_job():  # its own registry connection, in its own thread
        w = Workspace(ws.cfg, ws.root)
        try:
            box["r"] = run_job(w, "selftest", {"mode": "hang"}, timeout=300, stop=stop)
        except Exception as e:  # noqa: BLE001 - reported by the assertion below
            box["error"] = repr(e)
        finally:
            w.close()
    t = threading.Thread(target=research_job)
    t.start()
    log = ws.root / "logs"
    for _ in range(300):  # wait until the worker says it is hanging (it holds the research lock by then)
        if log.exists() and any("simulating a hang" in f.read_text(encoding="utf-8", errors="replace")
                                for f in log.glob("*.log")):
            break
        threading.Event().wait(0.1)
    try:
        spec = copy.deepcopy(load_spec())
        spec["pairs"]["enabled"] = ["EURUSD"]
        spec["feed"]["warmup_days"] = 3
        spec["delivery"]["notify_grades"] = ["A_PLUS", "WATCH"]
        with tempfile.TemporaryDirectory() as d:
            got = golden._scan(spec, golden.market(12000, seed=20251016), 100_000, [], Path(d) / "live.db")
        assert lock_for(ws.root).held_by_other(), "the research worker was running during the scan"
    finally:
        stop.set()
        t.join(60)
    assert "error" not in box, box
    assert got == expected
    assert box["r"]["status"] == "CANCELLED"
