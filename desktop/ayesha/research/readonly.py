"""Read-only views for the doctor and the dashboard: the live signal registry and the research registry.

Both are opened with SQLite `mode=ro`, so a bug here cannot write: SQLite itself refuses (`attempt to write a
readonly database`). The live registry summary shows states, times and counts only: no lot sizes, no risk or equity
amounts, no pairing code, no token.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ayesha.research.redact import redact

_MONEY = re.compile(r"(?i)(\$|usd|usc)\s?-?\d[\d,]*(\.\d+)?|-?\d[\d,]*(\.\d+)?\s?(usd|usc)\b")


def open_ro(path: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def legacy_db_path() -> Path:
    from ayesha.paths import home

    return home() / "ayesha.db"


def hide_amounts(text: str) -> str:
    return _MONEY.sub("[amount hidden]", redact(text or ""))


def legacy_summary(path: Path | None = None, days: int = 7, now: datetime | None = None) -> dict[str, Any]:
    p = Path(path) if path else legacy_db_path()
    if not p.exists():
        return {"present": False, "path_name": p.name}
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat(timespec="seconds")
    try:
        con = open_ro(p)
    except sqlite3.Error as e:
        return {"present": True, "readable": False, "error": type(e).__name__}
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        out: dict[str, Any] = {"present": True, "readable": True, "path_name": p.name, "days": days}
        if "schema_version" in tables:
            row = con.execute("SELECT v FROM schema_version").fetchone()
            out["schema_version"] = row[0] if row else None
        if "engine_health" in tables:
            out["health"] = [{"at_utc": r["at_utc"], "symbol": r["symbol"], "state": r["state"],
                              "detail": hide_amounts(r["detail"])[:200]}
                             for r in con.execute("SELECT at_utc, symbol, state, detail FROM engine_health "
                                                  "ORDER BY id DESC LIMIT 20")]
        if "signals" in tables:
            out["signals_by_status"] = {r[0]: r[1] for r in con.execute(
                "SELECT status, COUNT(*) FROM signals WHERE event_time_utc >= ? GROUP BY status ORDER BY status",
                (since,))}
            out["last_signal_by_pair"] = {r[0]: r[1] for r in con.execute(
                "SELECT symbol, MAX(event_time_utc) FROM signals GROUP BY symbol ORDER BY symbol")}
            out["recent_signals"] = [dict(r) for r in con.execute(
                "SELECT signal_id, symbol, direction, grade, status, event_time_utc FROM signals "
                "ORDER BY event_time_utc DESC LIMIT 20")]
        if "deliveries" in tables:
            r = con.execute("SELECT COUNT(*), SUM(ok), MAX(sent_at_utc) FROM deliveries WHERE sent_at_utc >= ?",
                            (since,)).fetchone()
            out["deliveries"] = {"count": r[0], "ok": r[1] or 0, "last_utc": r[2]}
        return out
    except sqlite3.Error as e:
        return {"present": True, "readable": False, "error": type(e).__name__}
    finally:
        con.close()


class ReadOnlyRegistry:
    """The read methods of `ResearchDB` over a `mode=ro` connection (dashboard, reports): it cannot write."""

    def __init__(self, path: str | Path) -> None:
        self.db = open_ro(path)

    def close(self) -> None:
        self.db.close()

    def _one(self, sql: str, *args: Any) -> sqlite3.Row | None:
        return self.db.execute(sql, args).fetchone()

    def _all(self, sql: str, *args: Any) -> list[sqlite3.Row]:
        return self.db.execute(sql, args).fetchall()

    def schema_version(self) -> int:
        return self._one("SELECT v FROM research_schema_version")[0]

    def dataset(self, dataset_id: str) -> sqlite3.Row | None:
        return self._one("SELECT * FROM datasets WHERE dataset_id=?", dataset_id)

    def datasets(self) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM datasets ORDER BY created_utc DESC, dataset_id")

    def partitions(self, dataset_id: str) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM dataset_partitions WHERE dataset_id=? ORDER BY symbol, timeframe", dataset_id)

    def run(self, run_id: str) -> sqlite3.Row | None:
        return self._one("SELECT * FROM research_runs WHERE run_id=?", run_id)

    def runs(self, limit: int = 100) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM research_runs ORDER BY created_utc DESC, run_id LIMIT ?", limit)

    def metrics(self, run_id: str) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM evaluation_metrics WHERE run_id=? ORDER BY period, regime", run_id)

    def jobs(self, limit: int = 30) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM research_jobs ORDER BY started_utc DESC, rowid DESC LIMIT ?", limit)

    def job(self, job_id: str) -> sqlite3.Row | None:
        return self._one("SELECT * FROM research_jobs WHERE job_id=?", job_id)

    def events(self, limit: int = 50) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM research_events ORDER BY id DESC LIMIT ?", limit)


class ReadOnlyWorkspace:
    """Duck-typed `Workspace` for readers: registry opened read-only, artifacts read through their hash check."""

    def __init__(self, root: Path) -> None:
        from ayesha.research.datasets.store import ArtifactStore

        self.root = Path(root)
        self.store = ArtifactStore(self.root)
        p = self.root / "research.db"
        self.db = ReadOnlyRegistry(p) if p.exists() else None

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
