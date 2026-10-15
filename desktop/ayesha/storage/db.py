"""SQLite signal registry and journal (master spec sections M and T).

History is append-only: a signal row stores the latest state for fast lookup, and every
change is also written to `signal_events`. Rows are never edited to look better later.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MIGRATIONS = [
    """
    CREATE TABLE signals (
        signal_id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        direction TEXT NOT NULL,
        setup TEXT NOT NULL,
        grade TEXT NOT NULL,
        status TEXT NOT NULL,
        strategy_version TEXT NOT NULL,
        strategy_hash TEXT NOT NULL,
        event_time_utc TEXT NOT NULL,
        expires_at_utc TEXT,
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_signals_symbol_time ON signals(symbol, event_time_utc);
    CREATE TABLE signal_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id TEXT NOT NULL REFERENCES signals(signal_id),
        at_utc TEXT NOT NULL,
        from_status TEXT,
        to_status TEXT NOT NULL,
        note TEXT
    );
    CREATE TABLE deliveries (
        signal_id TEXT NOT NULL,
        channel TEXT NOT NULL,
        sent_at_utc TEXT NOT NULL,
        ok INTEGER NOT NULL,
        detail TEXT,
        PRIMARY KEY (signal_id, channel)
    );
    CREATE TABLE engine_health (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at_utc TEXT NOT NULL,
        symbol TEXT,
        state TEXT NOT NULL,
        detail TEXT
    );
    CREATE TABLE journal (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id TEXT,
        at_utc TEXT NOT NULL,
        action TEXT NOT NULL,
        pnl_usd REAL,
        note TEXT
    );
    """,
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Registry:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        self.db.execute("CREATE TABLE IF NOT EXISTS schema_version (v INTEGER NOT NULL)")
        row = self.db.execute("SELECT v FROM schema_version").fetchone()
        v = row["v"] if row else 0
        for i, sql in enumerate(MIGRATIONS[v:], start=v + 1):
            self.db.executescript(sql)
            self.db.execute("DELETE FROM schema_version")
            self.db.execute("INSERT INTO schema_version VALUES (?)", (i,))
        self.db.commit()

    # --- signals ---------------------------------------------------------------------------
    def insert_signal(self, rec: dict[str, Any]) -> bool:
        """Idempotent: returns False if the signal_id already exists."""
        t = now_utc()
        try:
            self.db.execute(
                "INSERT INTO signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rec["signal_id"], rec["pair"], rec["direction"], rec["setup"], rec["grade"], rec["status"],
                 rec["strategy_version"], rec["strategy_hash"], rec["event_time_utc"], rec.get("expires_at_utc"),
                 json.dumps(rec, default=str), t, t),
            )
        except sqlite3.IntegrityError:
            return False
        self.db.execute("INSERT INTO signal_events (signal_id, at_utc, from_status, to_status, note) VALUES (?,?,?,?,?)",
                        (rec["signal_id"], t, None, rec["status"], "|".join(rec.get("blockers", []))))
        self.db.commit()
        return True

    def get(self, signal_id: str) -> dict[str, Any] | None:
        r = self.db.execute("SELECT payload, status FROM signals WHERE signal_id=?", (signal_id,)).fetchone()
        if not r:
            return None
        rec = json.loads(r["payload"])
        rec["status"] = r["status"]
        return rec

    def set_status(self, signal_id: str, to_status: str, note: str = "") -> None:
        r = self.db.execute("SELECT status FROM signals WHERE signal_id=?", (signal_id,)).fetchone()
        if r is None:
            raise KeyError(signal_id)
        t = now_utc()
        self.db.execute("UPDATE signals SET status=?, updated_at=? WHERE signal_id=?", (to_status, t, signal_id))
        self.db.execute("INSERT INTO signal_events (signal_id, at_utc, from_status, to_status, note) VALUES (?,?,?,?,?)",
                        (signal_id, t, r["status"], to_status, note))
        self.db.commit()

    def update_signal(self, rec: dict[str, Any], note: str = "") -> None:
        """Replace the latest state of a signal (e.g. WATCH_M5 -> READY after M5 confirmation).
        The previous state stays in signal_events; the new payload is the one the phone receives."""
        r = self.db.execute("SELECT status FROM signals WHERE signal_id=?", (rec["signal_id"],)).fetchone()
        if r is None:
            raise KeyError(rec["signal_id"])
        t = now_utc()
        self.db.execute("UPDATE signals SET grade=?, status=?, expires_at_utc=?, payload=?, updated_at=? WHERE signal_id=?",
                        (rec["grade"], rec["status"], rec.get("expires_at_utc"), json.dumps(rec, default=str), t,
                         rec["signal_id"]))
        self.db.execute("INSERT INTO signal_events (signal_id, at_utc, from_status, to_status, note) VALUES (?,?,?,?,?)",
                        (rec["signal_id"], t, r["status"], rec["status"], note))
        self.db.commit()

    def active(self, statuses: tuple[str, ...] = ("READY", "NOTIFIED", "WATCH")) -> list[dict[str, Any]]:
        q = f"SELECT signal_id FROM signals WHERE status IN ({','.join('?' * len(statuses))})"
        return [self.get(r["signal_id"]) for r in self.db.execute(q, statuses)]

    def recent(self, limit: int = 20) -> list[sqlite3.Row]:
        return self.db.execute("SELECT signal_id, symbol, direction, grade, status, event_time_utc FROM signals "
                               "ORDER BY event_time_utc DESC LIMIT ?", (limit,)).fetchall()

    def events(self, signal_id: str) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM signal_events WHERE signal_id=? ORDER BY id", (signal_id,)).fetchall()

    # --- delivery --------------------------------------------------------------------------
    # One row per (signal, channel, status): a WATCH_M5 archive push does not count as the READY push.
    # Rows written by 0.6.x used the bare channel name; they count as the READY delivery.
    def was_delivered(self, signal_id: str, channel: str, status: str = "READY") -> bool:
        keys = (f"{channel}:{status}", channel) if status == "READY" else (f"{channel}:{status}",)
        q = f"SELECT 1 FROM deliveries WHERE signal_id=? AND ok=1 AND channel IN ({','.join('?' * len(keys))})"
        return self.db.execute(q, (signal_id, *keys)).fetchone() is not None

    def record_delivery(self, signal_id: str, channel: str, ok: bool, detail: str = "", status: str = "READY") -> None:
        key = f"{channel}:{status}"
        if ok or not self.was_delivered(signal_id, channel, status):
            self.db.execute("INSERT OR REPLACE INTO deliveries VALUES (?,?,?,?,?)",
                            (signal_id, key, now_utc(), int(ok), detail))
            self.db.commit()

    def deliveries(self, signal_id: str) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM deliveries WHERE signal_id=? ORDER BY sent_at_utc", (signal_id,)).fetchall()

    # --- health / journal ------------------------------------------------------------------
    def health(self, state: str, symbol: str | None = None, detail: str = "") -> None:
        self.db.execute("INSERT INTO engine_health (at_utc, symbol, state, detail) VALUES (?,?,?,?)",
                        (now_utc(), symbol, state, detail))
        self.db.commit()

    def journal(self, action: str, signal_id: str | None = None, pnl_usd: float | None = None, note: str = "") -> None:
        self.db.execute("INSERT INTO journal (signal_id, at_utc, action, pnl_usd, note) VALUES (?,?,?,?,?)",
                        (signal_id, now_utc(), action, pnl_usd, note))
        if signal_id and action in ("PLACED", "CLOSED"):
            self.set_status(signal_id, f"USER_MARKED_{action}", note)
        self.db.commit()

    def day_stats(self, day_start_utc: datetime) -> tuple[int, float]:
        """(losses, realized loss USD) from the manual journal since the trading-day start."""
        rows = self.db.execute("SELECT pnl_usd FROM journal WHERE action='CLOSED' AND at_utc >= ? AND pnl_usd IS NOT NULL",
                               (day_start_utc.isoformat(timespec="seconds"),)).fetchall()
        losses = [r["pnl_usd"] for r in rows if r["pnl_usd"] < 0]
        return len(losses), -sum(losses)

    def open_positions(self) -> list[tuple[str, str]]:
        rows = self.db.execute("SELECT symbol, direction FROM signals WHERE status='USER_MARKED_PLACED'").fetchall()
        return [(r["symbol"], r["direction"]) for r in rows]
