"""Build frozen datasets from authorised read-only sources: an OANDA v20 practice download, or CSV files already
exported by `ayesha export` / `backtest-local.bat` (`<PAIR>_<TF>.csv`).

Flow per symbol/timeframe partition: raw bytes as received -> content-addressed raw artifact; tolerant parse ->
quality gate (`quality.assess`) -> normalised JSON Lines artifact + quality report; then one write-once manifest and
a registry row. Identical raw input is recognised and not stored twice. Bars are never filled in or corrected.

OANDA: only the legacy read-only candle endpoint is used, through `ayesha.feed.oanda_feed.OandaFeed` (GET, BID+ASK,
complete bars only). The token stays where install.bat put it; the raw artifact keeps response bodies and
request paths only, never headers, so the token is not on disk. Transient errors are retried with exponential
backoff; HTTP 401/403 stops at once with a message that contains no secret.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from ayesha.research.contracts import check
from ayesha.research.datasets import quality
from ayesha.research.datasets.normalize import TF_MINUTES, RawBar, from_candles, parse_csv, row_line
from ayesha.research.provenance import canonical_json, commit_sha, desktop_version, digest, iso, utc_now
from ayesha.research.workspace import Workspace

_FILE = re.compile(r"^([A-Z]{6})_(M5|M15)\.csv$")
_PROVIDER = re.compile(r"^[A-Z0-9_]{2,40}$")
NOT_EXNESS = "Prices come from the data provider, not from Exness; Exness quotes and spreads differ"
LICENSE_OANDA = ("OANDA v20 practice API data downloaded with the owner's own token for personal, non-commercial "
                 "research on this PC; not for redistribution (see OANDA's API terms)")
LICENSE_CSV = "Owner-supplied file; its licence is whatever its source allows (not verified by AYESHA)"


class IngestError(RuntimeError):
    pass


@dataclass
class Part:
    symbol: str
    timeframe: str
    raw: bytes
    raw_ext: str
    bars: list[RawBar]
    missing_columns: list[str]
    spread_basis: str


def _freeze(ws: Workspace, spec: dict[str, Any], provider: str, adapter: str, environment: str, label: str,
            parts: list[Part], observed_basis: str, downloaded_at: datetime, license_notes: str,
            limitations: list[str]) -> dict[str, Any]:
    if not _PROVIDER.match(provider):
        raise IngestError("provider label: use 2-40 capital letters, digits or _")
    if not parts:
        raise IngestError("nothing to ingest")
    policy = ws.cfg.quality
    entries = []
    for p in parts:
        raw_sha, raw_path = ws.store.put("raw", p.raw, p.raw_ext)
        ws.db.record_artifact(raw_sha, "raw", raw_path.relative_to(ws.root).as_posix(), raw_path.stat().st_size)
        bars, rep = quality.assess(p.bars, p.symbol, p.timeframe, spec, policy, p.missing_columns)
        w = ws.store.writer("normalized", ".jsonl")
        try:
            for b in bars:
                w.write(row_line(b, provider, p.symbol, p.timeframe, p.spread_basis))
            norm_sha, norm_path = w.commit()
        except BaseException:
            w.abort()
            raise
        ws.db.record_artifact(norm_sha, "normalized", norm_path.relative_to(ws.root).as_posix(),
                              norm_path.stat().st_size)
        check(rep, "research.quality_report/1")
        q_sha, q_path = ws.store.put("quality", canonical_json(rep), ".json")
        ws.db.record_artifact(q_sha, "quality", q_path.relative_to(ws.root).as_posix(), q_path.stat().st_size)
        entries.append({"symbol": p.symbol, "timeframe": p.timeframe, "rows": rep["rows_out"],
                        "start_utc": rep["start_utc"], "end_utc": rep["end_utc"], "raw_sha256": raw_sha,
                        "normalized_sha256": norm_sha, "quality_report_sha256": q_sha,
                        "quality_state": rep["decision"], "_report": rep})
    entries.sort(key=lambda e: (e["symbol"], e["timeframe"]))
    starts = [e["start_utc"] for e in entries if e["start_utc"]]
    ends = [e["end_utc"] for e in entries if e["end_utc"]]
    norm = digest([[e["symbol"], e["timeframe"], e["normalized_sha256"]] for e in entries])
    manifest = {
        "schema_version": "research.dataset_manifest/1",
        "dataset_id": "ds_" + norm[:16],
        "source": {"provider": provider, "adapter": adapter, "environment": environment, "label": label or provider},
        "symbols": sorted({e["symbol"] for e in entries}),
        "timeframes": sorted({e["timeframe"] for e in entries}, key=lambda t: TF_MINUTES[t]),
        "range_utc": {"start": min(starts) if starts else None, "end": max(ends) if ends else None},
        "downloaded_at_utc": iso(downloaded_at.replace(microsecond=0)),
        "observed_at_basis": observed_basis,
        "partitions": [{k: v for k, v in e.items() if k != "_report"} for e in entries],
        "raw_sha256": digest([[e["symbol"], e["timeframe"], e["raw_sha256"]] for e in entries]),
        "normalized_sha256": norm,
        "quality_report_sha256": digest([[e["symbol"], e["timeframe"], e["quality_report_sha256"]] for e in entries]),
        "quality_state": quality.worst([e["quality_state"] for e in entries]),
        "license_notes": license_notes,
        "limitations": limitations,
        "code": {"commit": commit_sha(), "desktop_version": desktop_version()},
    }
    check(manifest, "research.dataset_manifest/1")
    dup = ws.db.dataset_by_raw(manifest["raw_sha256"], provider)
    ds = dup["dataset_id"] if dup else manifest["dataset_id"]
    mpath = ws.manifests / f"{ds}.json"
    if dup:
        ws.db.audit("ingest", "DATASET_ALREADY_PRESENT", ds, {"raw_sha256": manifest["raw_sha256"]})
        new = False
    else:
        from ayesha.research.datasets.store import atomic_write

        mhash = digest(manifest)
        if not mpath.exists():
            atomic_write(mpath, (canonical_json(manifest).decode("utf-8") + "\n").encode("utf-8"))
        new = ws.db.add_dataset(manifest, mhash, label or provider)
    row = ws.db.dataset(ds)
    return {"dataset_id": ds, "new": new, "quality_state": row["quality_state"],
            "manifest": str(mpath), "partitions": [{
                "symbol": e["symbol"], "timeframe": e["timeframe"], "rows": e["rows"], "state": e["quality_state"],
                "coverage_percent": e["_report"]["coverage_percent"], "missing_bars": e["_report"]["missing_bars"],
                "issues": [f"{i['severity']}:{i['code']}x{i['count']}" for i in e["_report"]["issues"]]}
                for e in entries]}


def ingest_csv_dir(ws: Workspace, folder: str | Path, spec: dict[str, Any], provider: str = "CSV_IMPORT",
                   label: str = "", pairs: list[str] | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Import `<PAIR>_<TF>.csv` files (M5/M15) from one folder, as written by `ayesha export` or backtest-run."""
    d = Path(folder)
    if not d.is_dir():
        raise IngestError(f"not a folder: {d}")
    want = {p.upper() for p in pairs} if pairs else None
    now = now or utc_now()
    parts = []
    for f in sorted(d.iterdir()):
        m = _FILE.match(f.name)
        if not m or not f.is_file() or (want and m.group(1) not in want):
            continue
        sym, tf = m.group(1), m.group(2)
        raw = f.read_bytes()
        bars, missing = parse_csv(raw, sym, now)
        parts.append(Part(sym, tf, raw, ".csv", bars, missing, "CSV_WHOLE_POINTS"))
    if not parts:
        raise IngestError(f"no <PAIR>_M15.csv or <PAIR>_M5.csv files in {d}")
    return _freeze(ws, spec, provider, "ayesha.research.datasets.normalize.parse_csv (legacy CSV format)",
                   "local-file", label, parts, "IMPORT_TIME", now, LICENSE_CSV,
                   [NOT_EXNESS, "CSV import: no ASK prices; spread is the export's whole-point value at bar close",
                    "Observed time is the import time: the provider's delivery time is unknown"])


HttpGet = Callable[[str, dict[str, str]], dict[str, Any]]


def _http_get(url: str, headers: dict[str, str]) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _retrying(get: HttpGet, sleep: Callable[[float], None] = time.sleep, attempts: int = 4) -> HttpGet:
    def call(url: str, headers: dict[str, str]) -> dict[str, Any]:
        delay = 1.0
        for i in range(attempts):
            try:
                return get(url, headers)
            except urllib.error.HTTPError as e:
                if e.code in (401, 403) or (e.code < 500 and e.code != 429) or i == attempts - 1:
                    raise
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if i == attempts - 1:
                    raise
            sleep(delay)
            delay *= 2
        raise AssertionError("unreachable")
    return call


def ingest_oanda(ws: Workspace, spec: dict[str, Any], pairs: list[str], days: int,
                 timeframes: tuple[str, ...] = ("M15", "M5"), environment: str = "practice",
                 token: str | None = None, http_get: HttpGet | None = None, label: str = "",
                 clock: Callable[[], datetime] | None = None, sleep: Callable[[float], None] = time.sleep,
                 min_interval_s: float = 0.2) -> dict[str, Any]:
    """Download closed BID+ASK bars through the legacy read-only adapter and freeze them."""
    from ayesha.feed.oanda_feed import OandaFeed, parse_time

    if environment != "practice":
        raise IngestError("research downloads use the OANDA practice environment only (data_source "
                          "OANDA_V20_PRACTICE)")
    pairs = [p.strip().upper() for p in pairs if p.strip()]
    if not pairs or any(not re.fullmatch(r"[A-Z]{6}", p) for p in pairs):
        raise IngestError("pairs: give 6-letter FX pairs, e.g. EURUSD,GBPUSD")
    if not 1 <= int(days) <= 3650:
        raise IngestError("days: 1..3650")
    if not timeframes or any(tf not in TF_MINUTES for tf in timeframes):
        raise IngestError(f"timeframes: choose from {', '.join(TF_MINUTES)}")
    clock = clock or utc_now
    base = _retrying(http_get or _http_get, sleep=sleep)
    captured: list[tuple[str, datetime, dict[str, Any]]] = []

    def capture(url: str, headers: dict[str, str]) -> dict[str, Any]:
        body = base(url, headers)
        captured.append((url.split("://", 1)[-1].split("/", 1)[-1], clock(), body))  # path + query, never headers
        return body

    feed = OandaFeed(token=token, environment=environment, http_get=capture, clock=clock,
                     min_interval_s=min_interval_s)
    end = clock()
    start = end - timedelta(days=days)
    parts = []
    for pair in pairs:
        for tf in timeframes:
            captured.clear()
            bars = [b for b in feed.candles(pair, tf, start, end) if b.time + timedelta(minutes=TF_MINUTES[tf]) <= end]
            ask, seen = {}, {}
            for _, at, body in captured:
                for c in body.get("candles", []):
                    if c.get("complete") and "ask" in c:
                        t = parse_time(c["time"])
                        ask.setdefault(t, float(c["ask"]["c"]))
                        seen.setdefault(t, at)
            raw = b"".join(canonical_json({"path": p, "received_at_utc": iso(at), "body": b}) + b"\n"
                           for p, at, b in captured)
            parts.append(Part(pair, tf, raw, ".jsonl", from_candles(bars, ask, seen, end), [],
                              "ASK_CLOSE_MINUS_BID_CLOSE"))
    return _freeze(ws, spec, feed.source_name, "ayesha.feed.oanda_feed.OandaFeed (read-only GET candles, price=BA)",
                   environment, label, parts, "PROVIDER_RESPONSE_TIME", end, LICENSE_OANDA,
                   [NOT_EXNESS, "OANDA BID OHLC with ASK close only; ASK high/low are not known and are not invented"])
