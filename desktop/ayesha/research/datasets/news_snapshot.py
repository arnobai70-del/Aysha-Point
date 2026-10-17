"""Frozen historical news snapshots (plan §7.3, v1.1.0, ticket AI-011), research only.

A snapshot is a calendar file the owner is allowed to use, frozen like a market dataset: the raw bytes are kept as
received (content-addressed), parsed with the legacy CSV reader (`ayesha.news.calendar.NewsCalendar.from_csv`,
the same format `ayesha report --news` takes) and described by a manifest with its provenance and an integrity
report. Replays only ever see it through the legacy point-in-time view (`ayesha.backtest.asof.AsOfCalendar`):
rows appear after their `observed_utc`, actuals only after `actual_published_utc`.

Fail closed: no snapshot means news is `NOT_MODELLED` and any news comparison is `BLOCKED_BY_DATA`; a file without
a stated licence or source is refused; a file that does not parse, has no events or has rows with an unknown
currency or impact is `REJECTED`; a schedule without `observed_utc` (the file's final view, not what was known at
the time) or actuals without a publication time are `DEGRADED` and say so on every result. News direction (actual
vs forecast) is never backtested.

Stored without a registry table (raw file as a `raw` artifact, manifest as an `exports` artifact, plus an audit
event), so an older program still opens the research folder.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from ayesha.backtest.asof import NEWS_DIRECTION
from ayesha.news.calendar import NewsCalendar
from ayesha.news.classify import currency_known
from ayesha.research.contracts import check
from ayesha.research.provenance import canonical_json, commit_sha, desktop_version, iso, sha256_bytes, utc_now

RAW_EXT, MAN_EXT = ".news.csv", ".news.json"
IMPACTS = ("HIGH", "MEDIUM", "LOW", "HOLIDAY", "NONE")
REQUIRED = ("time_utc", "currency", "impact", "title")
MAX_BYTES = 50 * 1024 * 1024


class NewsSnapshotError(ValueError):
    """The calendar file cannot be frozen (missing licence, unreadable, too large)."""


def _parse(raw: bytes, name: str) -> NewsCalendar:
    fd, tmp = tempfile.mkstemp(suffix=".csv")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        return NewsCalendar.from_csv(tmp, provider=f"RESEARCH:{name}", fetched_at=None)
    finally:
        os.unlink(tmp)


def integrity(raw: bytes, name: str) -> tuple[dict[str, Any], NewsCalendar | None]:
    issues: list[dict[str, Any]] = []
    cal = None
    head = raw.decode("utf-8", errors="replace").splitlines()[:1]
    cols = [c.strip() for c in head[0].split(",")] if head else []
    missing = [c for c in REQUIRED if c not in cols]
    if missing:
        issues.append({"code": "MISSING_COLUMNS", "severity": "ERROR", "count": len(missing), "examples": missing})
    else:
        try:
            cal = _parse(raw, name)
        except (ValueError, KeyError, UnicodeDecodeError) as e:
            issues.append({"code": "UNPARSEABLE", "severity": "ERROR", "count": 1, "examples": [str(e)[:200]]})
    rep: dict[str, Any] = {"rows": 0, "coverage_utc": None, "currencies": {}, "impacts": {}}
    if cal is not None:
        evs = cal.events
        rep.update(rows=len(evs), coverage_utc=[iso(cal.coverage[0]), iso(cal.coverage[1])],
                   currencies=dict(sorted(Counter(e.currency for e in evs).items())),
                   impacts=dict(sorted(Counter(e.impact for e in evs).items())))
        bad_ccy = sorted({e.currency for e in evs if not currency_known(e.currency)})
        bad_imp = sorted({e.impact for e in evs if e.impact not in IMPACTS})
        if bad_ccy:
            issues.append({"code": "UNKNOWN_CURRENCY", "severity": "ERROR", "count": len(bad_ccy),
                           "examples": bad_ccy[:5]})
        if bad_imp:
            issues.append({"code": "UNKNOWN_IMPACT", "severity": "ERROR", "count": len(bad_imp),
                           "examples": bad_imp[:5]})
        observed = sum(1 for e in evs if e.fetched_at is not None)
        with_actual = sum(1 for e in evs if e.actual is not None)
        with_pub = sum(1 for e in evs if e.actual is not None and e.actual_published_at is not None)
        rep.update(rows_with_observed_utc=observed, rows_with_actual=with_actual,
                   rows_with_actual_publication_time=with_pub)
        if observed < len(evs):
            issues.append({"code": "SCHEDULE_NOT_POINT_IN_TIME", "severity": "WARN", "count": len(evs) - observed,
                           "examples": ["rows without observed_utc show the file's final schedule"]})
        if with_actual > with_pub:
            issues.append({"code": "ACTUAL_WITHOUT_PUBLICATION_TIME", "severity": "WARN",
                           "count": with_actual - with_pub, "examples": ["these actuals are never shown"]})
    errors = [i for i in issues if i["severity"] == "ERROR"]
    warns = [i for i in issues if i["severity"] == "WARN"]
    rep["decision"] = "REJECTED" if errors or cal is None else ("DEGRADED" if warns else "PASS")
    rep["issues"] = issues
    rep["news_direction"] = NEWS_DIRECTION
    return rep, (cal if not errors else None)


def ingest(ws, path: str | Path, provider: str, license_notes: str, label: str = "",
           now: datetime | None = None) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise NewsSnapshotError(f"not a file: {p}")
    if not (provider or "").strip():
        raise NewsSnapshotError("say who produced the calendar (--provider)")
    if len((license_notes or "").strip()) < 10:
        raise NewsSnapshotError("state the licence or permission under which you may use this calendar "
                                "(--license, at least a short sentence); without it the file is not imported")
    if p.stat().st_size > MAX_BYTES:
        raise NewsSnapshotError(f"{p.name} is larger than {MAX_BYTES >> 20} MB")
    raw = p.read_bytes()
    rep, _ = integrity(raw, p.name)
    raw_sha = sha256_bytes(raw)
    ns_id = "ns_" + raw_sha[:16]
    old = find(ws, ns_id)
    if old is not None:
        return {"news_snapshot_id": ns_id, "new": False, "decision": old["integrity"]["decision"],
                "rows": old["integrity"]["rows"]}
    r_sha, r_path = ws.store.put("raw", raw, RAW_EXT)
    man = check({
        "schema_version": "research.news-snapshot/1", "news_snapshot_id": ns_id, "source_type": "RESEARCH",
        "provider": provider.strip(), "label": label, "license_notes": license_notes.strip(),
        "file_name": p.name, "raw_sha256": raw_sha, "imported_at_utc": iso((now or utc_now()).replace(microsecond=0)),
        "parser": "ayesha.news.calendar.NewsCalendar.from_csv (legacy CSV format)",
        "point_in_time_view": "ayesha.backtest.asof.AsOfCalendar", "integrity": rep,
        "code": {"commit": commit_sha(), "desktop_version": desktop_version()},
    }, "research.news-snapshot/1")
    m_sha, m_path = ws.store.put("exports", canonical_json(man), MAN_EXT)
    ws.db.record_artifact(r_sha, "raw", r_path.relative_to(ws.root).as_posix(), r_path.stat().st_size)
    ws.db.record_artifact(m_sha, "exports", m_path.relative_to(ws.root).as_posix(), m_path.stat().st_size)
    ws.db.audit("research", "NEWS_SNAPSHOT_FROZEN", ns_id, {"raw": raw_sha, "manifest": m_sha,
                                                           "decision": rep["decision"]})
    return {"news_snapshot_id": ns_id, "new": True, "decision": rep["decision"], "rows": rep["rows"],
            "issues": [f"{i['severity']} {i['code']} x{i['count']}" for i in rep["issues"]]}


def snapshots(ws) -> list[dict[str, Any]]:
    out = []
    for a in ws.db.artifacts():
        if a["kind"] == "exports" and a["relpath"].endswith(MAN_EXT + ".gz"):
            out.append(json.loads(ws.store.get("exports", a["sha256"], MAN_EXT)))
    out.sort(key=lambda d: (d["imported_at_utc"], d["news_snapshot_id"]), reverse=True)
    return out


def find(ws, ns_id: str) -> dict[str, Any] | None:
    return next((d for d in snapshots(ws) if d["news_snapshot_id"] == ns_id), None)


def load(ws, ns_id: str) -> tuple[dict[str, Any], NewsCalendar]:
    """Manifest and calendar of a usable snapshot. REJECTED or unknown snapshots raise NewsSnapshotError."""
    man = find(ws, ns_id)
    if man is None:
        raise NewsSnapshotError(f"unknown news snapshot {ns_id}: news comparison is BLOCKED_BY_DATA")
    if man["integrity"]["decision"] == "REJECTED":
        raise NewsSnapshotError(f"{ns_id} is REJECTED by its integrity report: it cannot be used")
    raw = ws.store.get("raw", man["raw_sha256"], RAW_EXT)
    _, cal = integrity(raw, man["file_name"])
    if cal is None:
        raise NewsSnapshotError(f"{ns_id} no longer parses: it cannot be used")
    return man, cal
