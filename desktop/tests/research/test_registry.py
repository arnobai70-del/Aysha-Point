"""AI-004 / AI-015: the separate research registry, its audit trail, crash reconciliation, backup and restore."""

import sqlite3

import pytest

from ayesha.research.storage.db import MIGRATIONS, ResearchDB, ResearchDBError


def _inputs(run_id="run_0000000000000001", ds="ds_0000000000000001"):
    return {"dataset_id": ds, "strategy_id": "baseline-sweep-mss-fvg", "strategy_version": "0.4.0",
            "strategy_hash": "9bb5e8ed5937", "commit_sha": "UNKNOWN", "parameters_hash": "p" * 64,
            "cost_model_id": "legacy-replay-v1", "split_plan_id": "split=none;folds=4"}


def _dataset(db, ds="ds_0000000000000001"):
    db.add_dataset({"dataset_id": ds, "source": {"provider": "CSV_IMPORT"}, "normalized_sha256": "n" * 64,
                    "raw_sha256": "r" * 64, "quality_state": "PASS", "symbols": ["EURUSD"], "timeframes": ["M15"],
                    "range_utc": {"start": None, "end": None}, "downloaded_at_utc": "2026-01-01T00:00:00Z",
                    "partitions": []}, "m" * 64, "test")


def test_separate_file_own_schema_and_idempotent_migration(tmp_path):
    db = ResearchDB(tmp_path / "research.db")
    assert db.schema_version() == len(MIGRATIONS) == 1
    tables = {r[0] for r in db.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"datasets", "research_runs", "research_decisions", "research_events"} <= tables
    assert not tables & {"signals", "signal_events", "deliveries", "journal"}  # nothing of the live registry
    db.close()
    db = ResearchDB(tmp_path / "research.db")
    assert db.schema_version() == 1 and db.verify_chain()[0]
    db.db.execute("UPDATE research_schema_version SET v=99")
    db.db.commit()
    db.close()
    with pytest.raises(ResearchDBError):
        ResearchDB(tmp_path / "research.db")


def test_a_research_decision_can_never_be_ready(tmp_path):
    db = ResearchDB(tmp_path / "research.db")
    _dataset(db)
    db.start_run("run_0000000000000001", _inputs())
    with pytest.raises(sqlite3.IntegrityError):
        db.db.execute("INSERT INTO research_decisions VALUES (?,?,?,?,?,?)",
                      ("run_0000000000000001", "rc_1", "2026-01-01T00:00:00Z", "EURUSD", "READY", "{}"))
    with pytest.raises(sqlite3.IntegrityError):
        db.db.execute("INSERT INTO strategy_definitions VALUES (?,?,?,?,?,?,?)",
                      ("x", "1", "h", "p", "LIVE", "{}", "2026-01-01T00:00:00Z"))


def test_audit_chain_detects_edits_and_deletions(tmp_path):
    db = ResearchDB(tmp_path / "research.db")
    for i in range(5):
        db.audit("test", "OP", f"t{i}", {"i": i})
    assert db.verify_chain() == (True, "6 events, chain intact")
    db.db.execute("UPDATE research_events SET detail_json='{\"i\":99}' WHERE target='t2'")
    assert db.verify_chain()[0] is False
    db.db.rollback()
    db.db.execute("UPDATE research_events SET detail_json='{\"i\":2}' WHERE target='t2'")
    assert db.verify_chain()[0] is True
    db.db.execute("DELETE FROM research_events WHERE target='t1'")
    ok, msg = db.verify_chain()
    assert not ok and "broken" in msg


def test_completion_is_atomic_and_never_overwrites_a_finished_run(tmp_path):
    db = ResearchDB(tmp_path / "research.db")
    _dataset(db)
    rid = "run_0000000000000001"
    db.start_run(rid, _inputs())
    dup = [("rc_1", "2026-01-01T00:00:00Z", "EURUSD", "BLOCKED", "{}")] * 2  # second insert violates the key
    with pytest.raises(sqlite3.IntegrityError):
        db.complete_run(rid, "a" * 64, "b" * 64, dup, [])
    assert db.run(rid)["status"] == "RUNNING" and db.decisions(rid) == []  # nothing partial was committed
    db.complete_run(rid, "a" * 64, "b" * 64, dup[:1], [("ALL", "ALL", 0, "{}", "[]")])
    assert db.run(rid)["status"] == "COMPLETED" and len(db.decisions(rid)) == 1
    db.fail_run(rid, "late failure from an orphan worker")
    assert db.run(rid)["status"] == "COMPLETED"
    with pytest.raises(ResearchDBError):
        db.complete_run(rid, "a" * 64, "b" * 64, [], [])
    with pytest.raises(ResearchDBError):
        db.start_run(rid, _inputs())


def test_reconcile_marks_what_a_dead_worker_left_running(tmp_path):
    db = ResearchDB(tmp_path / "research.db")
    _dataset(db)
    db.start_run("run_0000000000000001", _inputs())
    db.job_start("job_1", "baseline", {})
    assert db.reconcile() == ["run_0000000000000001"]
    assert db.run("run_0000000000000001")["status"] == "FAILED_INCOMPLETE"
    assert db.job("job_1")["status"] == "CRASHED"
    assert db.reconcile() == []
    db.start_run("run_0000000000000001", _inputs())  # a retry of the same inputs is allowed
    assert db.run("run_0000000000000001")["status"] == "RUNNING"


def test_strategy_hash_collision_needs_a_new_version(tmp_path):
    db = ResearchDB(tmp_path / "research.db")
    m = {"strategy_id": "s", "version": "1", "strategy_hash": "aaaaaaaaaaaa"}
    db.register_strategy(m, "p")
    db.register_strategy(m, "p")  # idempotent
    with pytest.raises(ResearchDBError):
        db.register_strategy({**m, "strategy_hash": "bbbbbbbbbbbb"}, "p")


def test_backup_is_verified_self_contained_and_rotates_only_research_backups(tmp_path):
    db = ResearchDB(tmp_path / "research.db")
    _dataset(db)
    keep_me = tmp_path / "bk" / "capital-backup.json"
    keep_me.parent.mkdir()
    keep_me.write_text("{}", encoding="utf-8")
    made = [db.backup(tmp_path / "bk", keep=2) for _ in range(3)]
    files = sorted((tmp_path / "bk").glob("research-*.db"))
    assert len(files) == 2 and keep_me.exists()
    assert not list((tmp_path / "bk").glob("*-wal")) and not list((tmp_path / "bk").glob("*-shm"))
    from ayesha.research.provenance import sha256_file

    last = made[-1]
    assert sha256_file(last["path"]) == last["sha256"]
    assert (tmp_path / "bk" / (files[-1].name[:-3] + ".db.sha256")).exists()


def test_restore_is_verified_and_can_be_undone(tmp_path):
    db = ResearchDB(tmp_path / "research.db")
    _dataset(db, "ds_0000000000000001")
    b = db.backup(tmp_path / "bk")
    _dataset(db, "ds_0000000000000002")
    assert len(db.datasets()) == 2
    r = db.restore(__import__("pathlib").Path(b["path"]), tmp_path / "bk" / "pre-restore")
    assert [d["dataset_id"] for d in db.datasets()] == ["ds_0000000000000001"]
    assert db.verify_chain()[0]
    pre = ResearchDB(r["pre_restore_backup"])
    assert len(pre.datasets()) == 2  # the state before the restore is kept
    pre.close()


def test_tampered_or_foreign_backup_is_refused(tmp_path):
    from pathlib import Path

    db = ResearchDB(tmp_path / "research.db")
    _dataset(db)
    b = Path(db.backup(tmp_path / "bk")["path"])
    with open(b, "r+b") as f:
        f.seek(200)
        f.write(b"\x00garbage\x00")
    with pytest.raises(ResearchDBError, match="does not match"):
        db.restore(b, tmp_path / "pre")
    foreign = tmp_path / "other.db"
    con = sqlite3.connect(foreign)
    con.execute("CREATE TABLE signals (x)")
    con.commit()
    con.close()
    with pytest.raises(ResearchDBError, match="not a research registry"):
        db.restore(foreign, tmp_path / "pre")
    assert len(db.datasets()) == 1
