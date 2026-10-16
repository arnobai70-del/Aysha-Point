"""Research registry: `%AYESHA_HOME%/research/research.db`, a separate SQLite file with its own migration chain.

It never shares a file, a table or a connection with the live signal registry (`ayesha.db`). Every change is also
written to `research_events`, a hash-linked audit trail: each row's `resulting_hash` covers the previous row's hash,
so an edited or deleted history row is detectable (`verify_chain`). No column holds a token, password, pairing code
or equity. A research decision can never be READY: the column has a CHECK constraint.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ayesha.research.provenance import canonical_json, iso, sha256_bytes, sha256_file

GENESIS = "0" * 64
DECISION_STATES = ("HYPOTHETICAL_CLOSED", "BLOCKED", "NOT_FILLED", "INVALIDATED", "UNRESOLVED")
JOB_STATES = ("RUNNING", "OK", "FAILED", "CRASHED", "TIMEOUT", "RESOURCE_LIMIT", "REFUSED", "CANCELLED")

MIGRATIONS = [
    f"""
    CREATE TABLE datasets (
        dataset_id TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        manifest_hash TEXT NOT NULL,
        data_hash TEXT NOT NULL,
        raw_hash TEXT NOT NULL,
        quality_state TEXT NOT NULL CHECK (quality_state IN ('PASS', 'DEGRADED', 'REJECTED')),
        symbols TEXT NOT NULL,
        timeframes TEXT NOT NULL,
        start_utc TEXT,
        end_utc TEXT,
        label TEXT NOT NULL,
        manifest_json TEXT NOT NULL,
        created_utc TEXT NOT NULL
    );
    CREATE TABLE dataset_partitions (
        dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id),
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        start_utc TEXT,
        end_utc TEXT,
        rows INTEGER NOT NULL,
        raw_sha TEXT NOT NULL,
        artifact_sha TEXT NOT NULL,
        quality_sha TEXT NOT NULL,
        quality_state TEXT NOT NULL CHECK (quality_state IN ('PASS', 'DEGRADED', 'REJECTED')),
        PRIMARY KEY (dataset_id, symbol, timeframe)
    );
    CREATE TABLE strategy_definitions (
        strategy_id TEXT NOT NULL,
        version TEXT NOT NULL,
        strategy_hash TEXT NOT NULL,
        parameters_hash TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('RESEARCH_ONLY')),
        manifest TEXT NOT NULL,
        registered_utc TEXT NOT NULL,
        PRIMARY KEY (strategy_id, version, strategy_hash)
    );
    CREATE TABLE research_runs (
        run_id TEXT PRIMARY KEY,
        dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id),
        strategy_id TEXT NOT NULL,
        version TEXT NOT NULL,
        strategy_hash TEXT NOT NULL,
        commit_sha TEXT NOT NULL,
        config_hash TEXT NOT NULL,
        cost_hash TEXT NOT NULL,
        split_hash TEXT NOT NULL,
        inputs_json TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED', 'FAILED_INCOMPLETE')),
        result_sha TEXT,
        candidates_sha TEXT,
        error TEXT,
        created_utc TEXT NOT NULL,
        completed_utc TEXT
    );
    CREATE TABLE research_decisions (
        run_id TEXT NOT NULL REFERENCES research_runs(run_id),
        decision_id TEXT PRIMARY KEY,
        observed_at_utc TEXT NOT NULL,
        pair TEXT NOT NULL,
        proposed_state TEXT NOT NULL CHECK (proposed_state IN {DECISION_STATES!r}),
        reasons_json TEXT NOT NULL
    );
    CREATE INDEX idx_decisions_run ON research_decisions(run_id, observed_at_utc);
    CREATE TABLE evaluation_metrics (
        run_id TEXT NOT NULL REFERENCES research_runs(run_id),
        period TEXT NOT NULL,
        regime TEXT NOT NULL,
        count INTEGER NOT NULL,
        metrics_json TEXT NOT NULL,
        limitations_json TEXT NOT NULL,
        PRIMARY KEY (run_id, period, regime)
    );
    CREATE TABLE artifacts (
        sha256 TEXT NOT NULL,
        kind TEXT NOT NULL,
        relpath TEXT NOT NULL,
        bytes INTEGER NOT NULL,
        created_utc TEXT NOT NULL,
        PRIMARY KEY (sha256, kind)
    );
    CREATE TABLE research_jobs (
        job_id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        args_json TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN {JOB_STATES!r}),
        started_utc TEXT NOT NULL,
        finished_utc TEXT,
        exit_code INTEGER,
        result_json TEXT,
        log_relpath TEXT
    );
    CREATE TABLE research_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at_utc TEXT NOT NULL,
        actor TEXT NOT NULL,
        operation TEXT NOT NULL,
        target TEXT NOT NULL,
        detail_json TEXT NOT NULL,
        prior_hash TEXT NOT NULL,
        resulting_hash TEXT NOT NULL
    );
    """,
]


class ResearchDBError(RuntimeError):
    pass


def _now() -> str:
    return iso(datetime.now(timezone.utc).replace(microsecond=0))


def _event_hash(prior: str, at: str, actor: str, op: str, target: str, detail: str) -> str:
    return sha256_bytes(prior.encode() + canonical_json([at, actor, op, target, detail]))


class ResearchDB:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=5000")
        self._migrate()

    def close(self) -> None:
        self.db.close()

    # --- schema -----------------------------------------------------------------------------
    def _migrate(self) -> None:
        self.db.execute("CREATE TABLE IF NOT EXISTS research_schema_version (v INTEGER NOT NULL)")
        row = self.db.execute("SELECT v FROM research_schema_version").fetchone()
        v = row["v"] if row else 0
        if v > len(MIGRATIONS):
            raise ResearchDBError(f"research.db schema v{v} is newer than this program (v{len(MIGRATIONS)})")
        for i, sql in enumerate(MIGRATIONS[v:], start=v + 1):
            # one transaction: the tables and the version number change together or not at all
            self.db.executescript(f"BEGIN; {sql} DELETE FROM research_schema_version; "
                                  f"INSERT INTO research_schema_version VALUES ({int(i)}); COMMIT;")
            self.audit("system", "MIGRATE", "research.db", {"to_version": i})

    def schema_version(self) -> int:
        return self.db.execute("SELECT v FROM research_schema_version").fetchone()["v"]

    def integrity_check(self) -> str:
        return self.db.execute("PRAGMA integrity_check").fetchone()[0]

    # --- audit trail ------------------------------------------------------------------------
    def audit(self, actor: str, operation: str, target: str, detail: dict[str, Any] | None = None,
              commit: bool = True) -> str:
        last = self.db.execute("SELECT resulting_hash FROM research_events ORDER BY id DESC LIMIT 1").fetchone()
        prior = last["resulting_hash"] if last else GENESIS
        at, d = _now(), canonical_json(detail or {}).decode("utf-8")
        h = _event_hash(prior, at, actor, operation, target, d)
        self.db.execute("INSERT INTO research_events (at_utc, actor, operation, target, detail_json, prior_hash, "
                        "resulting_hash) VALUES (?,?,?,?,?,?,?)", (at, actor, operation, target, d, prior, h))
        if commit:
            self.db.commit()
        return h

    def verify_chain(self) -> tuple[bool, str]:
        prior = GENESIS
        n = 0
        for r in self.db.execute("SELECT * FROM research_events ORDER BY id"):
            n += 1
            if r["prior_hash"] != prior:
                return False, f"event {r['id']}: chain broken (row missing or reordered)"
            if _event_hash(prior, r["at_utc"], r["actor"], r["operation"], r["target"], r["detail_json"]) != \
                    r["resulting_hash"]:
                return False, f"event {r['id']}: content changed after it was written"
            prior = r["resulting_hash"]
        return True, f"{n} events, chain intact"

    def events(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM research_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    # --- datasets ---------------------------------------------------------------------------
    def add_dataset(self, manifest: dict[str, Any], manifest_hash: str, label: str) -> bool:
        """Register a frozen dataset. Returns False when the same content is already registered (idempotent)."""
        ds = manifest["dataset_id"]
        old = self.db.execute("SELECT manifest_hash FROM datasets WHERE dataset_id=?", (ds,)).fetchone()
        if old is not None:
            self.audit("ingest", "DATASET_ALREADY_PRESENT", ds, {"downloaded_at_utc": manifest["downloaded_at_utc"]})
            return False
        with self.db:
            self.db.execute("INSERT INTO datasets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                ds, manifest["source"]["provider"], manifest_hash, manifest["normalized_sha256"],
                manifest["raw_sha256"], manifest["quality_state"], ",".join(manifest["symbols"]),
                ",".join(manifest["timeframes"]), manifest["range_utc"]["start"], manifest["range_utc"]["end"],
                label, canonical_json(manifest).decode("utf-8"), _now()))
            for p in manifest["partitions"]:
                self.db.execute("INSERT INTO dataset_partitions VALUES (?,?,?,?,?,?,?,?,?,?)", (
                    ds, p["symbol"], p["timeframe"], p["start_utc"], p["end_utc"], p["rows"], p["raw_sha256"],
                    p["normalized_sha256"], p["quality_report_sha256"], p["quality_state"]))
            self.audit("ingest", "DATASET_REGISTERED", ds, {"manifest_hash": manifest_hash,
                                                             "quality_state": manifest["quality_state"]}, commit=False)
        return True

    def dataset(self, dataset_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM datasets WHERE dataset_id=?", (dataset_id,)).fetchone()

    def datasets(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM datasets ORDER BY created_utc DESC, dataset_id").fetchall()

    def dataset_by_raw(self, raw_hash: str, provider: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM datasets WHERE raw_hash=? AND provider=?", (raw_hash, provider)).fetchone()

    def partition(self, dataset_id: str, symbol: str, timeframe: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM dataset_partitions WHERE dataset_id=? AND symbol=? AND timeframe=?",
                               (dataset_id, symbol, timeframe)).fetchone()

    def partitions(self, dataset_id: str) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM dataset_partitions WHERE dataset_id=? ORDER BY symbol, timeframe",
                               (dataset_id,)).fetchall()

    # --- strategies -------------------------------------------------------------------------
    def register_strategy(self, manifest: dict[str, Any], parameters_hash: str) -> None:
        sid, ver, h = manifest["strategy_id"], manifest["version"], manifest["strategy_hash"]
        clash = self.db.execute("SELECT strategy_hash FROM strategy_definitions WHERE strategy_id=? AND version=? "
                                "AND strategy_hash<>?", (sid, ver, h)).fetchone()
        if clash:
            raise ResearchDBError(f"strategy {sid} {ver} is already registered with hash {clash['strategy_hash']}; "
                                  "a changed rule set needs a new version")
        if self.db.execute("SELECT 1 FROM strategy_definitions WHERE strategy_id=? AND version=? AND strategy_hash=?",
                           (sid, ver, h)).fetchone():
            return
        with self.db:
            self.db.execute("INSERT INTO strategy_definitions VALUES (?,?,?,?,?,?,?)",
                            (sid, ver, h, parameters_hash, "RESEARCH_ONLY", canonical_json(manifest).decode(), _now()))
            self.audit("research", "STRATEGY_REGISTERED", f"{sid}@{ver}#{h}", {"parameters_hash": parameters_hash},
                       commit=False)

    def strategies(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM strategy_definitions ORDER BY strategy_id, version").fetchall()

    # --- runs -------------------------------------------------------------------------------
    def run(self, run_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM research_runs WHERE run_id=?", (run_id,)).fetchone()

    def runs(self, limit: int = 100) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM research_runs ORDER BY created_utc DESC, run_id LIMIT ?",
                               (limit,)).fetchall()

    def start_run(self, run_id: str, inputs: dict[str, Any]) -> None:
        old = self.run(run_id)
        with self.db:
            if old is None:
                self.db.execute("INSERT INTO research_runs (run_id, dataset_id, strategy_id, version, strategy_hash, "
                                "commit_sha, config_hash, cost_hash, split_hash, inputs_json, status, created_utc) "
                                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                                    run_id, inputs["dataset_id"], inputs["strategy_id"], inputs["strategy_version"],
                                    inputs["strategy_hash"], inputs["commit_sha"], inputs["parameters_hash"],
                                    inputs["cost_model_id"], inputs["split_plan_id"],
                                    canonical_json(inputs).decode(), "RUNNING", _now()))
            elif old["status"] == "COMPLETED":
                raise ResearchDBError(f"{run_id} is already complete")
            else:  # an earlier attempt failed or was cut off: no decisions were committed for it
                self.db.execute("UPDATE research_runs SET status='RUNNING', error=NULL WHERE run_id=?", (run_id,))
            self.audit("research", "RUN_STARTED", run_id, {"dataset_id": inputs["dataset_id"],
                                                           "strategy_id": inputs["strategy_id"]}, commit=False)

    def complete_run(self, run_id: str, result_sha: str, candidates_sha: str, decisions: Iterable[tuple],
                     metrics: Iterable[tuple]) -> None:
        """One transaction: decisions, metrics and the COMPLETED status land together or not at all.
        `result_sha` / `candidates_sha` are the artifact ids (SHA-256 of the stored bytes) of the result document
        and of the candidates file; the result document carries the reproducible outcome hash itself."""
        with self.db:
            cur = self.db.execute("SELECT status FROM research_runs WHERE run_id=?", (run_id,)).fetchone()
            if cur is None or cur["status"] != "RUNNING":
                raise ResearchDBError(f"{run_id} is not running (status {cur['status'] if cur else 'missing'})")
            self.db.executemany("INSERT INTO research_decisions VALUES (?,?,?,?,?,?)",
                                ((run_id, *d) for d in decisions))
            self.db.executemany("INSERT INTO evaluation_metrics VALUES (?,?,?,?,?,?)",
                                ((run_id, *m) for m in metrics))
            self.db.execute("UPDATE research_runs SET status='COMPLETED', result_sha=?, candidates_sha=?, "
                            "completed_utc=? WHERE run_id=?", (result_sha, candidates_sha, _now(), run_id))
            self.audit("research", "RUN_COMPLETED", run_id, {"result_sha256": result_sha}, commit=False)

    def fail_run(self, run_id: str, error: str) -> None:
        with self.db:
            self.db.execute("UPDATE research_runs SET status='FAILED', error=? WHERE run_id=? AND status<>'COMPLETED'",
                            (error[:500], run_id))
            self.audit("research", "RUN_FAILED", run_id, {"error": error[:200]}, commit=False)

    def decisions(self, run_id: str, limit: int = 1000, offset: int = 0) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM research_decisions WHERE run_id=? ORDER BY observed_at_utc, decision_id "
                               "LIMIT ? OFFSET ?", (run_id, limit, offset)).fetchall()

    def metrics(self, run_id: str) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM evaluation_metrics WHERE run_id=? ORDER BY period, regime",
                               (run_id,)).fetchall()

    def reconcile(self) -> list[str]:
        """After a crash: a run left RUNNING by a dead worker is marked FAILED_INCOMPLETE (its partial data was
        never committed). Returns the run ids it marked."""
        stuck = [r["run_id"] for r in self.db.execute("SELECT run_id FROM research_runs WHERE status='RUNNING'")]
        busy = [r["job_id"] for r in self.db.execute("SELECT job_id FROM research_jobs WHERE status='RUNNING'")]
        if stuck or busy:
            with self.db:
                for rid in stuck:
                    self.db.execute("UPDATE research_runs SET status='FAILED_INCOMPLETE', error=? WHERE run_id=?",
                                    ("worker stopped before the run finished", rid))
                    self.audit("system", "RUN_RECONCILED", rid, {"status": "FAILED_INCOMPLETE"}, commit=False)
                for jid in busy:
                    self.db.execute("UPDATE research_jobs SET status='CRASHED', finished_utc=? WHERE job_id=?",
                                    (_now(), jid))
                    self.audit("system", "JOB_RECONCILED", jid, {"status": "CRASHED"}, commit=False)
        return stuck

    # --- artifacts / jobs -------------------------------------------------------------------
    def record_artifact(self, sha: str, kind: str, relpath: str, size: int) -> None:
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO artifacts VALUES (?,?,?,?,?)", (sha, kind, relpath, size, _now()))

    def artifacts(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM artifacts ORDER BY created_utc, kind, sha256").fetchall()

    def job_start(self, job_id: str, kind: str, args: dict[str, Any]) -> None:
        with self.db:
            self.db.execute("INSERT INTO research_jobs (job_id, kind, args_json, status, started_utc) VALUES "
                            "(?,?,?,?,?)", (job_id, kind, canonical_json(args).decode(), "RUNNING", _now()))
            self.audit("worker", "JOB_STARTED", job_id, {"kind": kind}, commit=False)

    def job_finish(self, job_id: str, status: str, exit_code: int | None, result: dict[str, Any] | None,
                   log_relpath: str | None) -> None:
        with self.db:
            self.db.execute("UPDATE research_jobs SET status=?, finished_utc=?, exit_code=?, result_json=?, "
                            "log_relpath=? WHERE job_id=?", (status, _now(), exit_code,
                                                             canonical_json(result or {}).decode(), log_relpath,
                                                             job_id))
            self.audit("worker", "JOB_FINISHED", job_id, {"status": status, "exit_code": exit_code}, commit=False)

    def jobs(self, limit: int = 30) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM research_jobs ORDER BY started_utc DESC, rowid DESC LIMIT ?",
                               (limit,)).fetchall()

    def job(self, job_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM research_jobs WHERE job_id=?", (job_id,)).fetchone()

    # --- backup / restore -------------------------------------------------------------------
    def backup(self, dest_dir: Path, keep: int = 7, tag: str = "") -> dict[str, Any]:
        """Consistent online copy (SQLite backup API), integrity-checked, with its SHA-256 next to it.
        Only older research backups in `dest_dir` are rotated away; nothing else is ever deleted."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        out = dest_dir / f"research-{stamp}{('-' + tag) if tag else ''}.db"
        tmp = out.with_suffix(".db.partial")
        dst = sqlite3.connect(str(tmp))
        try:
            self.db.backup(dst)
            dst.execute("PRAGMA journal_mode=DELETE")  # one self-contained file (no -wal / -shm next to it)
            ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            dst.close()
        if ok != "ok":
            tmp.unlink(missing_ok=True)
            raise ResearchDBError(f"backup failed its integrity check: {ok}")
        os.replace(tmp, out)
        sha = sha256_file(out)
        out.with_suffix(".db.sha256").write_text(f"{sha}  {out.name}\n", encoding="utf-8")
        self.audit("backup", "BACKUP_CREATED", out.name, {"sha256": sha})
        olds = sorted(dest_dir.glob("research-*.db"))[:-keep] if keep > 0 else []
        for f in olds:
            f.unlink(missing_ok=True)
            f.with_suffix(".db.sha256").unlink(missing_ok=True)
        return {"path": str(out), "sha256": sha, "rotated": [f.name for f in olds]}

    def restore(self, src: Path, safety_dir: Path) -> dict[str, Any]:
        """Replace this registry's content with a verified backup. The current content is first saved as a
        pre-restore backup, so a restore can itself be undone."""
        sidecar = src.with_suffix(".db.sha256")
        if sidecar.exists():
            want = sidecar.read_text(encoding="utf-8").split()[0]
            if sha256_file(src) != want:
                raise ResearchDBError(f"{src.name} does not match its .sha256 file: not restored")
        s = sqlite3.connect(Path(src).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            try:
                if s.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ResearchDBError(f"{src.name} failed its integrity check: not restored")
                ver = s.execute("SELECT v FROM research_schema_version").fetchone()
            except sqlite3.Error:
                raise ResearchDBError(f"{src.name} is not a research registry: not restored") from None
            if ver is None or ver[0] > len(MIGRATIONS):
                raise ResearchDBError(f"{src.name} is not a research registry this program can read")
            pre = self.backup(safety_dir, keep=0, tag="pre-restore")
            s.backup(self.db)
        finally:
            s.close()
        self.db.execute("PRAGMA journal_mode=WAL")
        self._migrate()
        self.audit("backup", "RESTORED", src.name, {"pre_restore_backup": Path(pre["path"]).name})
        return {"restored_from": str(src), "pre_restore_backup": pre["path"]}


def as_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def loads(s: str | None) -> Any:
    return json.loads(s) if s else None
