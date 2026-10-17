"""AI-010 / AI-011 (v1.1.0): as-of regime labels and the historical news path of the Strategy Lab.

Regimes: labels come from closed H4 bars only, so a changed future never changes an earlier label; warm-up and data
gaps are UNKNOWN; the volatility percentile uses past values only; every order carries the label known when it was
decided and results have a strategy x regime matrix with INSUFFICIENT_SAMPLE cells. News: a calendar is only used as
a frozen snapshot with a stated licence; its integrity report decides PASS / DEGRADED / REJECTED; the runner gates
news exactly like the legacy replay (both modes, trade for trade with the baseline); without a snapshot the news
comparison is BLOCKED_BY_DATA. All prices and calendar rows are SYNTHETIC: nothing here is market evidence.
"""

import copy
from datetime import datetime, timedelta, timezone

import pytest

from ayesha.backtest.asof import AsOfCalendar
from ayesha.backtest.replay import run_backtest
from ayesha.config import load_spec
from ayesha.models import Candle
from ayesha.news.calendar import NewsCalendar, NewsEvent
from ayesha.research.contracts import validate
from ayesha.research.datasets import news_snapshot as NS
from ayesha.research.datasets.ingest import ingest_csv_dir
from ayesha.research.evaluation import comparison as C
from ayesha.research.regimes import detector as D
from ayesha.research.simulation import lab, runner
from ayesha.research.simulation.baseline import RunRefused, load_candidates
from ayesha.research.strategies import loader
from ayesha.research.strategies.protocol import AsOfContext
from tests.research import synth

A, B, X = loader.LAB_ORDER
NOW = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
LICENCE = "synthetic rows written by this test; no third-party data"


@pytest.fixture(scope="module")
def spec():
    return load_spec()


@pytest.fixture(scope="module")
def bars():
    return synth.fx_week(8000, seed=3)


def _row(t):
    return [t.signal.signal_id, t.status, t.fill_index, t.exit_index, t.exit_reason, t.r, list(t.blockers),
            t.news_phase]


def _events(start, end, hours=3, observed=True, actual=True):
    out, t = [], start.replace(minute=30)
    while t < end:
        pub = t + timedelta(minutes=1)
        out.append(NewsEvent(t, "USD" if t.hour % 2 else "EUR", "HIGH" if t.hour % 6 < 3 else "MEDIUM",
                             f"Synthetic {t:%H}", provider="SYNTHETIC", forecast="1.0",
                             actual="1.2" if actual else None, actual_published_at=pub if actual else None,
                             fetched_at=t - timedelta(days=2) if observed else None))
        t += timedelta(hours=hours)
    return out


def _calendar(bars, **kw):
    lo = bars[0].time.replace(hour=0, minute=0)
    hi = bars[-1].time.replace(hour=0, minute=0) + timedelta(days=1)
    return NewsCalendar(_events(lo, hi, **kw), lo, hi, provider="SYNTHETIC_TEST_CALENDAR")


def _csv(path, events):
    lines = ["time_utc,currency,impact,title,forecast,actual,actual_published_utc,observed_utc"]
    z = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ") if t else ""  # noqa: E731
    for e in events:
        lines.append(f"{z(e.time)},{e.currency},{e.impact},{e.title},{e.forecast or ''},{e.actual or ''},"
                     f"{z(e.actual_published_at)},{z(e.fetched_at)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# --- regimes -------------------------------------------------------------------------------------

def _labels(cs):
    ctx, det = AsOfContext("EURUSD"), D.RegimeDetector()
    for c in cs:
        ctx.advance(c)
        det.update(ctx)
    return det.history


def test_regime_labels_are_causal(bars):
    k = 6000
    changed = bars[:k] + [Candle(b.time, b.open * 1.03, b.high * 1.05, b.low * 1.01, b.close * 1.03, b.volume,
                                 b.spread) for b in bars[k:]]
    a, b = _labels(bars), _labels(changed)
    cut = bars[k].time
    early = [[x for x in h if x.detected_at <= cut] for h in (a, b)]
    assert early[0] and early[0] == early[1]
    assert any(x.label != "UNKNOWN" for x in early[0])
    assert all(x.detected_at.minute == 0 and x.detected_at.hour % 4 == 0 for x in a)  # only at H4 closes
    assert a != b  # the mutation does change later labels


def test_regime_warmup_and_labels(bars):
    h = _labels(bars)
    assert all(x.label == "UNKNOWN" and x.reason == "WARMUP" for x in h[:D.VOL_WINDOW])
    assert {x.label for x in h} <= set(D.LABELS)
    assert len({x.label for x in h}) >= 4
    assert _labels(bars[:500]) and {x.label for x in _labels(bars[:500])} == {"UNKNOWN"}
    tl = D.timeline("EURUSD", bars)
    assert tl["h4_bars"] == len(h) and sum(tl["counts"].values()) == len(h)
    assert tl["detector"]["version"] == D.VERSION and len(tl["detector"]["code_sha256"]) == 64
    assert "never a gate" in tl["detector"]["note"]


def test_regime_data_gap_restarts_the_warmup(bars):
    gap = bars[:5000] + [Candle(b.time + timedelta(days=14), b.open, b.high, b.low, b.close, b.volume, b.spread)
                         for b in bars[5000:]]
    h = _labels(gap)
    cut = bars[5000].time + timedelta(days=14)
    after = [x for x in h if x.detected_at > cut]
    assert after[0].label == "UNKNOWN" and after[0].reason == "DATA_GAP"
    assert all(x.label == "UNKNOWN" for x in after[:D.VOL_WINDOW])


def test_high_vol_percentile_uses_past_values_only():
    det = D.RegimeDetector()
    t = datetime(2025, 3, 3, tzinfo=timezone.utc)
    lab_ = None
    for i in range(D.WARMUP_H4 + 5):
        p = 1.1 + 0.0001 * (i % 3)
        lab_ = det._on_h4(Candle(t, p, p + 0.001, p - 0.001, p, 0, 0.0001), t + timedelta(hours=4))
        t += timedelta(hours=4)
    assert lab_.label != "HIGH_VOL" and lab_.atr_percentile < D.HIGH_VOL_PCT
    big = det._on_h4(Candle(t, 1.1, 1.13, 1.07, 1.1, 0, 0.0001), t + timedelta(hours=4))
    assert big.label == "HIGH_VOL" and big.atr_percentile == 1.0


def test_lab_orders_carry_the_regime_known_at_decision(spec, bars):
    st, _ = loader.load(B, "EURUSD", spec)
    r = runner.run("EURUSD", bars, spec, st)
    hist = _labels(bars)
    for lt in r["trades"]:
        known = [x for x in hist if x.detected_at <= lt.created_at]
        assert lt.regime == (known[-1].label if known else "UNKNOWN")


# --- news snapshots --------------------------------------------------------------------------------

def test_news_snapshot_needs_a_licence_and_is_content_addressed(ws, tmp_path, bars):
    p = _csv(tmp_path / "cal.csv", _calendar(bars[:2000]).events)
    with pytest.raises(NS.NewsSnapshotError, match="licence"):
        NS.ingest(ws, p, "SYNTHETIC", "")
    with pytest.raises(NS.NewsSnapshotError, match="provider"):
        NS.ingest(ws, p, " ", LICENCE)
    r = NS.ingest(ws, p, "SYNTHETIC", LICENCE, now=NOW)
    assert r["new"] and r["decision"] == "PASS" and r["news_snapshot_id"].startswith("ns_")
    again = NS.ingest(ws, p, "SYNTHETIC", LICENCE, now=NOW)
    assert not again["new"] and again["news_snapshot_id"] == r["news_snapshot_id"]
    man = NS.find(ws, r["news_snapshot_id"])
    assert validate(man, "research.news-snapshot/1") == []
    assert man["license_notes"] == LICENCE and man["integrity"]["news_direction"] == "NEWS DIRECTION NOT BACKTESTED"
    assert [e["operation"] for e in ws.db.events()].count("NEWS_SNAPSHOT_FROZEN") == 1
    m, cal = NS.load(ws, r["news_snapshot_id"])
    assert len(cal.events) == man["integrity"]["rows"]
    # actuals stay hidden until their publication time in the point-in-time view
    e0 = cal.events[0]
    assert AsOfCalendar(cal).at(e0.time).events[0].actual is None
    assert AsOfCalendar(cal).at(e0.actual_published_at).events[0].actual == "1.2"


def test_news_snapshot_integrity_decisions(ws, tmp_path, bars):
    evs = _calendar(bars[:2000]).events
    degraded = NS.ingest(ws, _csv(tmp_path / "d.csv", _calendar(bars[:2000], observed=False).events), "S", LICENCE)
    assert degraded["decision"] == "DEGRADED" and any("SCHEDULE_NOT_POINT_IN_TIME" in i for i in degraded["issues"])
    bad = tmp_path / "bad.csv"
    bad.write_text("time_utc,currency,impact,title\n2025-03-03T12:30:00Z,USD,EXTREME,x\n", encoding="utf-8")
    rej = NS.ingest(ws, bad, "S", LICENCE)
    assert rej["decision"] == "REJECTED"
    with pytest.raises(NS.NewsSnapshotError, match="REJECTED"):
        NS.load(ws, rej["news_snapshot_id"])
    cols = tmp_path / "cols.csv"
    cols.write_text("when,ccy\n2025-03-03T12:30:00Z,USD\n", encoding="utf-8")
    assert NS.ingest(ws, cols, "S", LICENCE)["decision"] == "REJECTED"
    with pytest.raises(NS.NewsSnapshotError, match="BLOCKED_BY_DATA"):
        NS.load(ws, "ns_0000000000000000")
    assert evs and len(NS.snapshots(ws)) == 3


# --- news in the runner and the lab -------------------------------------------------------------

@pytest.mark.parametrize("mode", runner.NEWS_MODES)
@pytest.mark.parametrize("seed", [3, 21])
def test_baseline_with_news_equals_the_legacy_replay(spec, seed, mode):
    cs = synth.fx_week(8000, seed=seed)
    cal = _calendar(cs)
    sp = copy.deepcopy(spec)
    sp["mtf"]["confirm_timeframe"] = None
    leg = run_backtest("EURUSD", cs, sp, account_type="Standard", usd_rates=runner.APPROX_USD_RATES, calendar=cal,
                       news_mode=mode)
    st, _ = loader.load(A, "EURUSD", spec)
    r = runner.run("EURUSD", cs, spec, st, news=runner.NewsInput(cal, mode))
    assert [_row(lt.trade) for lt in r["trades"]] == [_row(t) for t in leg["trades"]]
    assert r["news_integrity"] == leg["news_integrity"]
    assert any(b.startswith("NEWS") or b == "NEWS_BLOCKED" for lt in r["trades"] for b in lt.trade.blockers) or \
        any(lt.trade.status == "BLOCKED" for lt in r["trades"])
    plain = runner.run("EURUSD", cs, spec, loader.load(A, "EURUSD", spec)[0])
    assert [_row(lt.trade)[:7] for lt in plain["trades"]] != [_row(lt.trade)[:7] for lt in r["trades"]]


@pytest.mark.parametrize("sid", (B, X))
def test_news_gate_blocks_research_strategies_too(spec, bars, sid):
    cal = _calendar(bars)
    st, _ = loader.load(sid, "EURUSD", spec)
    off = runner.run("EURUSD", bars, spec, st)
    st, _ = loader.load(sid, "EURUSD", spec)
    on = runner.run("EURUSD", bars, spec, st, news=runner.NewsInput(cal, "upgraded"))
    assert len(on["trades"]) == len(off["trades"])  # news never changes what the strategy proposes
    blocked = [lt for lt in on["trades"] if lt.trade.status in ("BLOCKED", "INVALIDATED")]
    assert len(blocked) > len([lt for lt in off["trades"] if lt.trade.status == "BLOCKED"])
    assert all(lt.trade.news_phase != "NOT_MODELLED" for lt in on["trades"])
    with pytest.raises(ValueError):
        runner.NewsInput(cal, "none")


@pytest.fixture
def ds_ns(ws, tmp_path):
    f = synth.csv_dir(tmp_path / "csv", m15=4000, m5=6000, seed=11)
    ds = ingest_csv_dir(ws, f, load_spec(), now=NOW)["dataset_id"]
    cs = synth.fx_week(4000, seed=11)
    ns = NS.ingest(ws, _csv(tmp_path / "cal.csv", _calendar(cs, hours=2).events), "SYNTHETIC", LICENCE, now=NOW)
    return ds, ns["news_snapshot_id"]


def test_lab_without_a_snapshot_blocks_the_news_comparison(ws, ds_ns):
    ds, _ = ds_ns
    r = lab.run_strategy(ws, load_spec(), B, ds, "EURUSD", robustness=False)
    res = lab.load_result(ws, r["run_id"])
    assert res["news_snapshot_id"] == "NONE:NEWS_NOT_MODELLED"
    assert res["metrics"]["news_comparison"]["status"] == "BLOCKED_BY_DATA"
    assert "NEWS_NOT_MODELLED" in res["limitations"] and "REGIME_NOT_MODELLED" not in res["limitations"]
    m = res["metrics"]["regime"]["matrix"]
    assert set(m) == set(D.LABELS) and all(v["sample"] == "INSUFFICIENT_SAMPLE" for v in m.values())
    for c in load_candidates(ws, r["run_id"]):
        assert c["regime"] in D.LABELS and c["news_phase"] is None


def test_lab_with_a_snapshot_compares_news_modes(ws, ds_ns):
    ds, ns = ds_ns
    spec = load_spec()
    with pytest.raises(RunRefused, match="news mode"):
        lab.run_strategy(ws, spec, B, ds, "EURUSD", news_snapshot_id=ns, news_mode="none")
    with pytest.raises(RunRefused, match="BLOCKED_BY_DATA"):
        lab.run_strategy(ws, spec, B, ds, "EURUSD", news_snapshot_id="ns_0000000000000000")
    r = C.run_lab(ws, spec, ds, "EURUSD", news_snapshot_id=ns)
    assert r["benchmark_parity"] == "MATCHED"
    doc = C.load(ws, r["comparison_id"])
    assert doc["news_snapshot_id"] == ns and doc["news_mode"] == "upgraded"
    assert validate(doc, "research.comparison/1") == []
    for row in doc["rows"]:
        assert row["news_comparison"]["status"] == "COMPARED"
        assert set(row["news_comparison"]) == {"status", "none", "legacy", "upgraded"}
        assert set(row["regimes"]) == set(D.LABELS)
    res = lab.load_result(ws, next(x["run_id"] for x in r["runs"] if x["strategy_id"] == B))
    nc = res["metrics"]["news_comparison"]["modes"]
    assert nc["upgraded"]["no_trade_share"] > nc["none"]["no_trade_share"]
    assert "NEWS_DIRECTION_NOT_BACKTESTED" in res["limitations"] and "NEWS_NOT_MODELLED" not in res["limitations"]
    assert res["metrics"]["news"]["per_symbol"]["EURUSD"]["news_stability_bars"] == "M5 closed bars"
    phases = {c["news_phase"] for c in load_candidates(ws, res["run_id"])}
    assert phases and None not in phases
    # a run without news is never compared with runs that had news
    plain = lab.run_strategy(ws, spec, X, ds, "EURUSD")
    with pytest.raises(RunRefused, match="news_snapshot_id"):
        C.compare(ws, [res["run_id"], plain["run_id"]])
    legacy = lab.run_strategy(ws, spec, X, ds, "EURUSD", news_snapshot_id=ns, news_mode="legacy")
    with pytest.raises(RunRefused, match="news_mode"):
        C.compare(ws, [res["run_id"], legacy["run_id"]])
    v = lab.run_strategy(ws, spec, B, ds, "EURUSD", news_snapshot_id=ns, verify=True)
    assert v["verified"] is True


# --- feed audit ------------------------------------------------------------------------------------

def test_feed_audit_measures_two_feeds(ws, tmp_path):
    from ayesha.research.datasets import feed_audit as FA

    spec = load_spec()
    a = ingest_csv_dir(ws, synth.csv_dir(tmp_path / "a", m15=2000, seed=5), spec, provider="FEED_A",
                       now=NOW)["dataset_id"]
    shifted = tmp_path / "b"
    shifted.mkdir()
    synth.write_csv(shifted, "EURUSD", "M15", [Candle(b.time, b.open + 0.0003, b.high + 0.0003, b.low + 0.0003,
                                                      b.close + 0.0003, b.volume, b.spread)
                                               for b in synth.fx_week(2000, seed=5)])
    b = ingest_csv_dir(ws, shifted, spec, provider="FEED_B", now=NOW)["dataset_id"]
    same = ingest_csv_dir(ws, synth.csv_dir(tmp_path / "c", m15=2000, seed=5), spec, provider="FEED_C",
                          now=NOW)["dataset_id"]
    diff = FA.audit(ws, a, b, "EURUSD", now=NOW)
    assert diff["status"] == "DIFFERENT" and diff["differences"]["close"]["median"] == pytest.approx(3.0, abs=0.01)
    assert diff["overlap"]["common_bars"] == 2000 and diff["overlap"]["missing_share"] == 0
    assert validate(diff, "research.feed-audit/1") == []
    if same != a:  # identical bars from another provider
        ok = FA.audit(ws, a, same, "EURUSD", now=NOW)
        assert ok["status"] == "MATCHED" and ok["differences"]["close"]["max"] == 0
    assert any("UNVERIFIED" in n for n in diff["notes"])
    assert FA.audit(ws, a, b, "EURUSD", now=NOW)["feed_audit_id"] == diff["feed_audit_id"]  # idempotent
    short = FA.compare(synth.fx_week(100, seed=5), synth.fx_week(100, seed=5), "EURUSD", "M15")
    assert short["status"] == "INSUFFICIENT_OVERLAP"
    gaps = FA.compare(synth.fx_week(2000, seed=5), synth.fx_week(2000, seed=5)[::2], "EURUSD", "M15")
    assert gaps["status"] == "DIFFERENT" and gaps["overlap"]["missing_in_b"] > 900
    with pytest.raises(RunRefused):
        FA.audit(ws, a, a, "EURUSD")
    with pytest.raises(RunRefused):
        FA.audit(ws, a, b, "EURUSD", "H1")


# --- CLI and dashboard -----------------------------------------------------------------------------

def test_cli_news_regime_feed_audit_and_dashboard(home, tmp_path, capsys):
    import json

    from ayesha.cli import main as ayesha
    from ayesha.research.dashboard.server import App

    synth.csv_dir(tmp_path / "csv", m15=3000, m5=4000, seed=4)
    cal = _csv(tmp_path / "cal.csv", _calendar(synth.fx_week(3000, seed=4), hours=2).events)
    assert ayesha(["research", "news-ingest", "--csv", str(cal), "--provider", "SYNTHETIC",
                   "--license", LICENCE]) == 2  # research is off
    assert ayesha(["research", "enable"]) == 0
    assert ayesha(["research", "ingest", "--from-csv-dir", str(tmp_path / "csv")]) == 0
    capsys.readouterr()
    assert ayesha(["research", "datasets", "--json"]) == 0
    ds = json.loads(capsys.readouterr().out)[0]["dataset_id"]
    assert ayesha(["research", "news-ingest", "--csv", str(cal), "--provider", "SYNTHETIC", "--license", "x"]) == 2
    capsys.readouterr()
    assert ayesha(["research", "news-ingest", "--csv", str(cal), "--provider", "SYNTHETIC",
                   "--license", LICENCE]) == 0
    out = capsys.readouterr().out
    ns = next(w for w in out.split() if w.startswith("ns_")).rstrip(":")
    assert "PASS" in out and "never backtested" in out
    assert ayesha(["research", "news", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["news_snapshot_id"] == ns
    assert ayesha(["research", "regime", "--dataset", ds, "--symbol", "EURUSD"]) == 0
    out = capsys.readouterr().out
    assert "regime-h4-er-slope-vol" in out and "never a gate" in out
    assert ayesha(["research", "regime", "--dataset", ds, "--symbol", "USDCHF"]) == 2
    capsys.readouterr()
    assert ayesha(["research", "lab", "--dataset", ds, "--symbols", "EURUSD", "--quick", "--news", ns]) == 0
    out = capsys.readouterr().out
    cid = next(w for w in out.split() if w.startswith("cmp_")).rstrip(":")
    assert "benchmark parity MATCHED" in out
    assert ayesha(["research", "lab", "--dataset", ds, "--symbols", "EURUSD", "--quick", "--news",
                   "ns_0000000000000000"]) == 2
    capsys.readouterr()
    md = tmp_path / "lab.md"
    assert ayesha(["research", "report", cid, "--md", str(md)]) == 0
    text = md.read_text(encoding="utf-8")
    assert "Strategy x regime" in text and "News comparison: COMPARED" in text
    capsys.readouterr()
    assert ayesha(["research", "runs", "--json"]) == 0
    run_b = next(r["run_id"] for r in json.loads(capsys.readouterr().out) if r["strategy_id"] == B)
    assert ayesha(["research", "report", run_b, "--md", str(md)]) == 0
    text = md.read_text(encoding="utf-8")
    assert "## Strategy x regime" in text and "## News comparison: COMPARED" in text and "upgraded handling" in text
    assert ayesha(["research", "feed-audit", "--a", ds, "--b", ds, "--symbol", "EURUSD"]) == 2
    assert ayesha(["research", "feed-audits"]) == 0
    capsys.readouterr()

    app = App(home / "research", "k")
    for path in ("/data", f"/lab/{cid}", f"/runs/{run_b}"):
        status, _, body, _ = app.route(path)
        assert status == 200 and b"<script" not in body, path
    assert ns.encode() in app.route("/data")[2] and b"Feed audits" in app.route("/data")[2]
    assert b"Strategy \xc3\x97 regime" in app.route(f"/lab/{cid}")[2]
    assert b"News comparison" in app.route(f"/runs/{run_b}")[2] and b"By regime" in app.route(f"/runs/{run_b}")[2]
