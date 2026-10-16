"""AI-003 / T01: frozen datasets. Content-addressed and reproducible, quality-gated, never repaired, fail closed on
malformed or gapped data, OANDA access read-only with the token never written anywhere."""

import gzip
import json
import math
import os
from datetime import datetime, timedelta, timezone

import pytest

from ayesha.research.datasets import quality
from ayesha.research.datasets.ingest import IngestError, ingest_csv_dir, ingest_oanda
from ayesha.research.datasets.normalize import RawBar, parse_csv
from ayesha.research.datasets.store import ArtifactStore, IntegrityError, atomic_write
from ayesha.research.simulation.baseline import load_candles
from ayesha.research.workspace import Workspace
from tests.research import synth

UTC = timezone.utc
NOW = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
POLICY = {"max_gap_bars": 8, "min_coverage_percent": 98.0, "stale_run_bars": 6}
TOKEN = "0123456789abcdef" * 2 + "-" + "fedcba9876543210" * 2  # fake, in OANDA's shape; built so no token literal is committed


def _bars(n=200, **kw):
    return [RawBar(None, c.time, c.open, c.high, c.low, c.close, c.volume, c.spread, None, True, NOW)
            for c in synth.fx_week(n, seed=3, **kw)]


def _assess(bars, tf="M15", missing=None):
    from ayesha.config import load_spec

    return quality.assess(bars, "EURUSD", tf, load_spec(), POLICY, missing)


def _codes(rep):
    return {i["code"] for i in rep["issues"]}


def test_clean_fx_week_series_passes():
    bars, rep = _assess(_bars())
    assert rep["decision"] == "PASS" and rep["coverage_percent"] == 100.0 and len(bars) == 200
    assert rep["policy"]["repair"] == "NONE"


@pytest.mark.parametrize("mutate, code, decision", [
    (lambda b: b.__setitem__(50, RawBar(None, b[50].time, math.nan, 1, 1, 1, 0, 0, None, True, NOW)),
     "NON_FINITE_PRICE", "REJECTED"),
    (lambda b: setattr(b[50], "low", b[50].high + 0.001), "OHLC_INCONSISTENT", "REJECTED"),
    (lambda b: setattr(b[50], "spread", -0.0001), "NEGATIVE_SPREAD", "REJECTED"),
    (lambda b: setattr(b[50], "close", -1.0), "NON_POSITIVE_PRICE", "REJECTED"),
    (lambda b: setattr(b[50], "time", b[50].time + timedelta(minutes=7)), "MISALIGNED_TIMESTAMP", "REJECTED"),
    (lambda b: setattr(b[-1], "observed_at", b[-1].time + timedelta(minutes=5)), "FUTURE_BAR", "REJECTED"),
    (lambda b: setattr(b[50], "complete", False), "INCOMPLETE_BAR", "REJECTED"),
    (lambda b: b.insert(51, RawBar(None, b[50].time, b[50].open, b[50].high, b[50].low, b[50].close + 0.0001,
                                   b[50].volume, b[50].spread, None, True, NOW)), "DUPLICATE_CONFLICT", "REJECTED"),
    (lambda b: b.insert(51, RawBar(**{**b[50].__dict__})), "DUPLICATE_IDENTICAL", "DEGRADED"),
    (lambda b: b.reverse(), "OUT_OF_ORDER_SORTED", "DEGRADED"),
    (lambda b: b.__delitem__(slice(60, 75)), "GAP_OVER_POLICY", "DEGRADED"),
    (lambda b: b.append(RawBar(None, None, None, None, None, None, None, None, None, True, NOW, "line 9: ValueError")),
     "PARSE_ERROR", "REJECTED"),
])
def test_defects_fail_closed_and_nothing_is_repaired(mutate, code, decision):
    bars = _bars()
    mutate(bars)
    valid = {b.time for b in bars if b.error is None}
    kept, rep = _assess(bars)
    assert code in _codes(rep), rep["issues"]
    assert rep["decision"] == decision
    assert len(kept) <= len(valid)  # never a bar that was not in the input (no forward fill, no synthetic bars)
    assert all(k.time in valid for k in kept)


def test_stale_feed_run_is_degraded():
    bars = _bars()
    for b in bars[80:90]:
        b.open = b.high = b.low = b.close = bars[79].close
    _, rep = _assess(bars)
    assert "STALE_RUN" in _codes(rep) and rep["decision"] == "DEGRADED"


def test_missing_column_and_empty_input_are_rejected():
    _, rep = _assess([], missing=["close"])
    assert {"MISSING_COLUMN", "NO_ROWS"} <= _codes(rep) and rep["decision"] == "REJECTED"
    bars, missing = parse_csv(b"time,open,high,low\n2025-03-03T00:00:00Z,1,1,1\n", "EURUSD", NOW)
    assert missing == ["close"] and bars == []


def test_weekend_and_rollover_bars_are_flagged_not_counted_missing():
    bars = _bars(700)  # crosses the weekend of 8-9 March 2025
    assert bars[0].time < datetime(2025, 3, 8, tzinfo=UTC) < bars[-1].time
    sat = datetime(2025, 3, 8, 12, 0, tzinfo=UTC)
    bars.append(RawBar(None, sat, 1.08, 1.081, 1.079, 1.0805, 100, 0.0001, None, True, NOW))
    _, rep = _assess(sorted(bars, key=lambda b: b.time))
    assert "BAR_OUTSIDE_MARKET_HOURS" in _codes(rep)
    assert rep["missing_bars"] == 0


def test_csv_ingest_is_content_addressed_and_idempotent(ws, csv_folder):
    from ayesha.config import load_spec

    spec = load_spec()
    a = ingest_csv_dir(ws, csv_folder, spec, now=NOW)
    assert a["new"] and a["quality_state"] == "PASS"
    b = ingest_csv_dir(ws, csv_folder, spec, now=NOW + timedelta(hours=1))
    assert b["dataset_id"] == a["dataset_id"] and b["new"] is False
    assert len(ws.db.datasets()) == 1
    manifest = json.loads((ws.manifests / f"{a['dataset_id']}.json").read_text(encoding="utf-8"))
    from ayesha.research.contracts import validate

    assert validate(manifest, "research.dataset_manifest/1") == []
    assert {p["symbol"] + p["timeframe"] for p in manifest["partitions"]} == {"EURUSDM15", "EURUSDM5"}
    for p in manifest["partitions"]:
        raw = ws.store.get("raw", p["raw_sha256"], ".csv")
        assert raw == (csv_folder / f"{p['symbol']}_{p['timeframe']}.csv").read_bytes()  # kept exactly as received


def test_same_input_gives_the_same_dataset_id_in_another_workspace(ws, csv_folder, tmp_path):
    from ayesha.config import load_spec
    from ayesha.research.config import DEFAULTS, ResearchConfig

    a = ingest_csv_dir(ws, csv_folder, load_spec(), now=NOW)
    other = Workspace(ResearchConfig(DEFAULTS, tmp_path / "x.yaml", False), tmp_path / "other")
    try:
        b = ingest_csv_dir(other, csv_folder, load_spec(), now=NOW)
    finally:
        other.close()
    assert a["dataset_id"] == b["dataset_id"]


def test_candles_round_trip_exactly_like_the_legacy_csv_loader(ws, csv_folder):
    from ayesha.config import load_spec
    from ayesha.feed.csv_feed import load_candles as legacy_load

    ds = ingest_csv_dir(ws, csv_folder, load_spec(), now=NOW)["dataset_id"]
    for tf in ("M15", "M5"):
        assert load_candles(ws, ds, "EURUSD", tf) == legacy_load(csv_folder / f"EURUSD_{tf}.csv", 0.00001)


def test_tampered_artifact_is_detected_before_use(ws, csv_folder):
    from ayesha.config import load_spec

    ds = ingest_csv_dir(ws, csv_folder, load_spec(), now=NOW)["dataset_id"]
    part = ws.db.partition(ds, "EURUSD", "M15")
    path = ws.store.path_for("normalized", part["artifact_sha"], ".jsonl")
    lines = gzip.decompress(path.read_bytes()).splitlines(keepends=True)
    lines[10] = lines[10].replace(b'"bid_close":', b'"bid_close":1.2,"x":')
    path.write_bytes(gzip.compress(b"".join(lines)))
    with pytest.raises(IntegrityError):
        load_candles(ws, ds, "EURUSD", "M15")


def test_atomic_writes_leave_no_partial_files(tmp_path):
    store = ArtifactStore(tmp_path)
    w = store.writer("normalized", ".jsonl")
    w.write(b'{"a":1}\n')
    w.abort()  # e.g. a crash or an error mid-write
    assert store.files("normalized") == [] and not list((tmp_path / "normalized").glob(".tmp-*"))
    target = tmp_path / "x.json"
    atomic_write(target, b"old")
    real_replace = os.replace

    def boom(*a, **k):
        raise OSError("disk full")
    os.replace = boom
    try:
        with pytest.raises(OSError):
            atomic_write(target, b"new")
    finally:
        os.replace = real_replace
    assert target.read_bytes() == b"old" and not list(tmp_path.glob(".tmp-*"))
    sha, p = store.put("quality", b"same", ".json")
    assert store.put("quality", b"same", ".json") == (sha, p)


def _fake_oanda(n15=1200, n5=0):
    series = {"M15": synth.fx_week(n15, seed=21)}
    if n5:
        series["M5"] = synth.fx_week(n5, seed=22, minutes=5)
    end = series["M15"][-1].time + timedelta(minutes=20)
    return synth.FakeOanda(series), end


def test_oanda_ingest_keeps_ask_close_and_never_writes_the_token(ws):
    from ayesha.config import load_spec

    fake, end = _fake_oanda()
    r = ingest_oanda(ws, load_spec(), ["EURUSD"], days=14, timeframes=("M15",), token=TOKEN, http_get=fake,
                     clock=lambda: end, sleep=lambda s: None, min_interval_s=0)
    assert r["quality_state"] in ("PASS", "DEGRADED")
    assert all("/v3/instruments/EUR_USD/candles" in u and "price=BA" in u for u, _ in fake.calls)
    assert all(h["Authorization"] == f"Bearer {TOKEN}" for _, h in fake.calls)  # only ever in the header
    m = json.loads(ws.db.dataset(r["dataset_id"])["manifest_json"])
    assert m["source"]["provider"] == "OANDA_V20_PRACTICE" and m["observed_at_basis"] == "PROVIDER_RESPONSE_TIME"
    part = ws.db.partition(r["dataset_id"], "EURUSD", "M15")
    rows = [json.loads(x) for x in ws.store.iter_lines("normalized", part["artifact_sha"], ".jsonl")]
    assert rows and all(x["ask_close"] is not None and x["spread_basis"] == "ASK_CLOSE_MINUS_BID_CLOSE" for x in rows)
    assert rows[-1]["bar_open_utc"] != fake.series["M15"][-1].time.strftime("%Y-%m-%dT%H:%M:%SZ")  # incomplete bar
    for f in ws.root.rglob("*"):
        if f.is_file():
            data = f.read_bytes()
            data = gzip.decompress(data) if f.suffix == ".gz" else data
            assert TOKEN.encode() not in data and b"Bearer" not in data, f


def test_oanda_rejected_token_stops_at_once_and_transient_errors_retry(ws):
    from ayesha.config import load_spec
    from ayesha.feed.oanda_feed import AuthRejected

    fake, end = _fake_oanda()
    fake.fail = [401]
    sleeps = []
    with pytest.raises(AuthRejected) as ei:
        ingest_oanda(ws, load_spec(), ["EURUSD"], days=14, timeframes=("M15",), token=TOKEN, http_get=fake,
                     clock=lambda: end, sleep=sleeps.append, min_interval_s=0)
    assert len(fake.calls) == 1 and sleeps == [] and TOKEN not in str(ei.value)
    fake, end = _fake_oanda()
    fake.fail = [503, 503]
    r = ingest_oanda(ws, load_spec(), ["EURUSD"], days=14, timeframes=("M15",), token=TOKEN, http_get=fake,
                     clock=lambda: end, sleep=sleeps.append, min_interval_s=0)
    assert sleeps == [1.0, 2.0] and r["dataset_id"].startswith("ds_")


@pytest.mark.parametrize("kw", [{"environment": "live"}, {"pairs": ["XAU-USD"]}, {"days": 0},
                                {"timeframes": ("H1",)}])
def test_oanda_ingest_refuses_bad_inputs(ws, kw):
    from ayesha.config import load_spec

    fake, end = _fake_oanda(100)
    args = {"pairs": ["EURUSD"], "days": 14, "timeframes": ("M15",), "environment": "practice", **kw}
    with pytest.raises(IngestError):
        ingest_oanda(ws, load_spec(), args.pop("pairs"), args.pop("days"), token=TOKEN, http_get=fake,
                     clock=lambda: end, min_interval_s=0, **args)
    assert fake.calls == []
