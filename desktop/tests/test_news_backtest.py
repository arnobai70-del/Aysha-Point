"""News spec P2 / I03 / I04: legacy 30/30 vs upgraded news protection on the same candles, point-in-time
calendar, zero lookahead, and adaptive account feasibility from $20 to $5,000.
All price data here is SYNTHETIC (random walk); none of these numbers is evidence of an edge."""

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from ayesha import cli
from ayesha.backtest.asof import LOOKAHEAD, NEWS_DIRECTION, AsOfCalendar, visible
from ayesha.backtest.replay import NEWS_MODES, bar_source, run_backtest
from ayesha.backtest.report import EQUITIES, adaptive_account, build_report, news_comparison, to_markdown
from ayesha.models import Candle
from ayesha.news.calendar import NewsCalendar, NewsEvent
from ayesha.news.guard import NewsGuard
from ayesha.feed.csv_feed import save_candles
from tests.helpers import T0, synthetic

UTC = timezone.utc
M15 = timedelta(minutes=15)


def _m15(m5: list[Candle]) -> list[Candle]:
    """Closed M15 bars built from the same M5 bars, so both series describe one market."""
    out, bucket = [], []
    for b in m5:
        if bucket and b.time - bucket[0].time >= M15:
            bucket = []
        if not bucket and b.time.minute % 15:
            continue
        bucket.append(b)
        if len(bucket) == 3:
            out.append(Candle(bucket[0].time, bucket[0].open, max(x.high for x in bucket), min(x.low for x in bucket),
                              bucket[-1].close, sum(x.volume for x in bucket), max(x.spread for x in bucket)))
            bucket = []
    return out


@pytest.fixture(scope="module")
def market():
    m5 = synthetic(24000, minutes=5, vol=0.00045, seed=13)
    return m5, _m15(m5)


def _cal(events, start, end):
    return NewsCalendar(events, start, end, provider="SYNTHETIC_TEST_CALENDAR")


def _ev(t, ccy="USD", impact="HIGH", title="Retail Sales m/m", **kw):
    return NewsEvent(t, ccy, impact, title, provider="SYNTHETIC_TEST_CALENDAR", **kw)


def _signal_times(spec, m15):
    res = run_backtest("EURUSD", m15, spec)
    return res, [t.signal.bar_close_utc for t in res["trades"]]


# --- point-in-time calendar ---------------------------------------------------------------

def test_asof_hides_actual_until_published_and_rows_until_observed():
    t = datetime(2026, 3, 4, 13, 30, tzinfo=UTC)
    e = _ev(t, actual="0.5%", forecast="0.3%", previous="0.2%", revised_previous="0.1%",
            actual_published_at=t + timedelta(minutes=1))
    before, after = visible(e, t), visible(e, t + timedelta(minutes=2))
    assert before.actual is None and before.revised_previous is None and before.forecast == "0.3%"
    assert after.actual == "0.5%" and after.revised_previous == "0.1%"
    no_pub = replace(e, actual_published_at=None)
    assert visible(no_pub, t + timedelta(days=30)).actual is None, "an actual without a publication time never shows"
    late = replace(e, fetched_at=t - timedelta(minutes=10))
    assert visible(late, t - timedelta(minutes=11)) is None and visible(late, t - timedelta(minutes=10)) is not None


def test_asof_window_gives_the_same_guard_decisions_as_the_whole_calendar(spec, market):
    m5, _ = market
    start, end = m5[0].time, m5[-1].time + timedelta(days=1)
    evs = []
    for k in range(40):  # an event every ~half day, mixed tiers and currencies
        t = (start + timedelta(hours=7 + 13 * k)).replace(minute=30 if k % 2 else 0)
        evs.append(_ev(t, ccy=("USD", "EUR", "JPY", "GBP")[k % 4], impact=("HIGH", "MEDIUM", "LOW")[k % 3],
                       title=("CPI m/m", "Retail Sales m/m", "Trade Balance", "Federal Funds Rate")[k % 4]))
    cal = _cal(evs, start, end)
    asof, guard, src = AsOfCalendar(cal), NewsGuard(spec), bar_source(m5)
    full = _cal([visible(e, start) for e in evs], start, end)  # nothing has an actual here, so this is exact
    horizon = LOOKAHEAD - timedelta(hours=1)  # setups expire within hours (expiry_bars), far inside this

    def near(t, now):
        return t if t is not None and t - now < horizon else None
    for k in range(0, 2000, 7):
        now = start + timedelta(minutes=5 * k)
        a = guard.assess("EURUSD", now, asof.at(now), m5=src, live=False)
        b = guard.assess("EURUSD", now, full, m5=src, live=False)
        assert (a.phase, a.reasons, near(a.next_block_start, now)) == (b.phase, b.reasons, near(b.next_block_start, now)), now


def test_bar_source_never_returns_an_unclosed_or_future_bar(market):
    m5, _ = market
    src = bar_source(m5)
    now = m5[500].time + timedelta(minutes=2)  # in the middle of bar 500
    got = src(m5[0].time, now)
    assert got and got[-1].time == m5[499].time and all(b.time + timedelta(minutes=5) <= now for b in got)


# --- I04: same candles, same signals, only the news gate differs ------------------------------

@pytest.fixture(scope="module")
def runs(spec, market):
    m5, m15 = market
    base, times = _signal_times(spec, m15)
    assert len(times) >= 6, "synthetic data must give a few signals"
    evs = [
        _ev(times[0] + timedelta(minutes=10)),                       # HIGH inside both windows
        _ev(times[1], impact="MEDIUM", title="Trade Balance"),       # MEDIUM: upgraded only (+-10)
        _ev(times[2] + timedelta(minutes=50), title="CPI m/m"),      # TOP_DATA lockout starts in 5 min: upgraded only
        _ev(times[3] + timedelta(minutes=20), ccy="CHF"),            # other currency: neither blocks
        _ev(times[4] + timedelta(minutes=75)),                       # HIGH lockout in 45 min: the order is cut short
    ]
    cal = _cal(evs, m15[0].time, m15[-1].time + timedelta(days=1))
    out = {m: run_backtest("EURUSD", m15, spec, calendar=cal, news_mode=m, m5_candles=m5) for m in NEWS_MODES}
    return out, times, cal


def _news_stopped(res):
    return {t.signal.signal_id for t in res["trades"]
            if any(b.startswith(("NEWS_", "INVALIDATED")) for b in t.blockers) or t.exit_reason == "NEWS_LOCKOUT_BEFORE_EXPIRY"}


def test_news_modes_share_candles_and_signals(runs):
    out, times, _ = runs
    ids = {m: [t.signal.signal_id for t in r["trades"]] for m, r in out.items()}
    assert ids["none"] == ids["legacy"] == ids["upgraded"]
    assert [r["bars"] for r in out.values()] == [out["none"]["bars"]] * 3
    assert {r["news_mode"] for r in out.values()} == set(NEWS_MODES)
    assert not _news_stopped(out["none"]) and not out["none"]["news_modelled"]


def test_upgraded_blocks_everything_legacy_blocks_and_more(runs):
    out, times, _ = runs
    legacy, upgraded = _news_stopped(out["legacy"]), _news_stopped(out["upgraded"])
    by_time = {t.signal.bar_close_utc: t for t in out["upgraded"]["trades"]}
    leg_time = {t.signal.bar_close_utc: t for t in out["legacy"]["trades"]}
    assert legacy and legacy <= upgraded and len(upgraded) > len(legacy)
    assert "NEWS_LOCKOUT" in leg_time[times[0]].blockers and by_time[times[0]].status == "BLOCKED"
    assert "NEWS_" not in "".join(leg_time[times[1]].blockers) and "NEWS_EVENT_LIVE" in by_time[times[1]].blockers
    assert "NEWS_LOCKOUT_BEFORE_EXPIRY" in by_time[times[2]].blockers, "a READY must expire before the next lockout"
    assert by_time[times[3]].news_phase in ("CLEAR", "UPCOMING") and "NEWS_" not in "".join(by_time[times[3]].blockers)
    assert by_time[times[4]].expires_at == times[4] + timedelta(minutes=45) and leg_time[times[4]].expires_at is None


def test_every_trade_carries_its_news_regime(runs):
    out, times, _ = runs
    for m in NEWS_MODES:  # annotated in every mode, gating only in legacy / upgraded
        assert all(t.news_phase != "NOT_MODELLED" for t in out[m]["trades"])
    assert out["none"]["trades"][0].news_phase in ("EVENT_LIVE", "PRE_EVENT_LOCKOUT")


def test_pending_order_is_cancelled_when_a_new_event_appears(spec, market):
    """N10 in the replay: an event first seen after the signal cancels the not-yet-filled order."""
    m5, m15 = market
    base, _ = _signal_times(spec, m15)
    late = next(t for t in base["trades"] if t.status in ("EXPIRED", "MISSED") or
                (t.status == "CLOSED" and t.fill_index >= t.signal.created_index + 2))
    s = late.signal.bar_close_utc
    ev = _ev(s + timedelta(minutes=40), fetched_at=s + timedelta(minutes=1))  # published in the calendar after the signal
    cal = _cal([ev], m15[0].time, m15[-1].time + timedelta(days=1))
    up = run_backtest("EURUSD", m15, spec, calendar=cal, news_mode="upgraded", m5_candles=m5)
    lg = run_backtest("EURUSD", m15, spec, calendar=cal, news_mode="legacy", m5_candles=m5)
    tu = next(t for t in up["trades"] if t.signal.signal_id == late.signal.signal_id)
    tl = next(t for t in lg["trades"] if t.signal.signal_id == late.signal.signal_id)
    assert tu.status == "INVALIDATED" and tu.blockers[:2] == ["INVALIDATED", "NEWS_PRE_EVENT_LOCKOUT"]
    assert tl.status != "BLOCKED", "legacy checks only the signal bar"


def test_zero_lookahead_future_bars_and_future_actuals_change_nothing(spec, market):
    """I03/N07: decisions before T are identical whether or not the data after T exists, and an actual
    published later (or never timestamped) is invisible to them."""
    m5, m15 = market
    _, times = _signal_times(spec, m15)
    cut = times[len(times) // 2]
    evs = [_ev(t + timedelta(minutes=k), title="CPI m/m", forecast="0.3%", previous="0.2%",
               actual="9.9%", actual_published_at=None if k % 2 else t + timedelta(days=3))
           for k, t in zip((5, 20, 35, 50), times)]
    cal = _cal(evs, m15[0].time, m15[-1].time + timedelta(days=1))
    clean = _cal([replace(e, actual=None, actual_published_at=None) for e in evs], *cal.coverage)
    full = run_backtest("EURUSD", m15, spec, calendar=cal, news_mode="upgraded", m5_candles=m5)
    short = run_backtest("EURUSD", [b for b in m15 if b.time + M15 <= cut], spec, calendar=cal, news_mode="upgraded",
                         m5_candles=[b for b in m5 if b.time + timedelta(minutes=5) <= cut])
    no_actual = run_backtest("EURUSD", m15, spec, calendar=clean, news_mode="upgraded", m5_candles=m5)

    def decisions(res, before=None):
        return {t.signal.signal_id: (t.news_phase, t.status == "BLOCKED", tuple(t.blockers if t.status == "BLOCKED" else ()))
                for t in res["trades"] if before is None or t.signal.bar_close_utc < before}
    assert decisions(full, cut) == decisions(short, cut)
    assert decisions(full) == decisions(no_actual)


# --- I03: report integrity -------------------------------------------------------------------

def test_report_compares_news_modes_with_integrity_and_sample_sizes(spec, runs):
    out, times, cal = runs
    split = out["none"]["start"] + (out["none"]["end"] - out["none"]["start"]) / 2
    rep = build_report({"EURUSD|m15": out["upgraded"]}, spec, split_at=split, folds=3,
                       data_label="SYNTHETIC random walk (test)", comparisons={"EURUSD|m15": out})
    run = rep["runs"]["EURUSD|m15"]
    nc = run["news_comparison"]
    assert set(nc["modes"]) == set(NEWS_MODES) and nc["news_direction"] == NEWS_DIRECTION
    assert len({v["signals"] for v in nc["modes"].values()}) == 1
    assert nc["modes"]["none"]["stopped_by_news"] == 0 < nc["modes"]["legacy"]["stopped_by_news"] \
        < nc["modes"]["upgraded"]["stopped_by_news"]
    assert all("out_of_sample" in v for v in nc["modes"].values())
    for v in nc["modes"].values():  # sample counts are real; no win rate without closed trades
        assert (v["win_rate"] is None) == (v["closed_trades"] == 0)
    ni = run["news_integrity"]
    assert ni["provider"] == "SYNTHETIC_TEST_CALENDAR" and not ni["point_in_time_schedule"]
    assert any(w.startswith("SCHEDULE_NOT_POINT_IN_TIME") for w in rep["news"]["warnings"])
    assert rep["news"]["modelled"] and rep["news"]["comparison_run"]
    assert "by_news_regime_without_news_model" in run
    md = to_markdown(rep)
    assert "News comparison on the same candles" in md and NEWS_DIRECTION in md and "SYNTHETIC" in md
    assert "point-in-time schedule: NO" in md


def test_incomplete_calendar_is_reported_and_fails_closed(spec, market):
    m5, m15 = market
    mid = m15[len(m15) // 2].time
    cal = _cal([_ev(mid + timedelta(days=1))], m15[0].time, mid)  # calendar ends halfway through the data
    res = run_backtest("EURUSD", m15, spec, calendar=cal, news_mode="upgraded", m5_candles=m5)
    late = [t for t in res["trades"] if t.signal.bar_close_utc >= mid]
    assert late and all(t.status == "BLOCKED" and "NEWS_UNVERIFIED" in t.blockers for t in late)
    assert any(w.startswith("INCOMPLETE_NEWS_DATA") for w in res["news_integrity"]["warnings"])


def test_news_mode_needs_a_calendar(spec, market):
    with pytest.raises(ValueError):
        run_backtest("EURUSD", market[1][:500], spec, news_mode="upgraded")
    with pytest.raises(ValueError):
        run_backtest("EURUSD", market[1][:500], spec, news_mode="tomorrow")


def test_news_comparison_scores_what_the_protection_removed(runs):
    out, _, _ = runs
    nc = news_comparison(out, None, 0.00003)
    g = nc["stopped_by_upgraded"]
    removed = [t for t in out["none"]["trades"] if t.status == "CLOSED"
               and next(u for u in out["upgraded"]["trades"] if u.signal.signal_id == t.signal.signal_id).status != "CLOSED"]
    assert g["closed_without_news_model"] == len(removed)
    assert g["their_total_r"] == round(sum(t.r for t in removed), 2)


# --- P2: adaptive account feasibility $20 .. $5,000 ----------------------------------------------

@pytest.fixture(scope="module")
def many_trades(spec):
    trades = []
    for seed in (3, 7, 9):
        res = run_backtest("EURUSD", synthetic(9000, seed=seed), spec)
        for t in res["trades"]:
            t._pair = "EURUSD"
        trades += res["trades"]
    assert sum(1 for t in trades if t.status == "CLOSED") >= 5
    return trades


def test_adaptive_account_scales_with_verified_equity_not_a_fixed_ceiling(spec, many_trades):
    rows = {eq: adaptive_account(many_trades, spec, eq, 0.5) for eq in EQUITIES}
    taken = [rows[eq]["taken"] for eq in EQUITIES]
    assert taken == sorted(taken), "more equity never makes fewer setups feasible at the same 0.5%"
    assert rows[20.0]["skipped"].get("MIN_LOT_EXCEEDS_RISK", 0) > 0, "$20 cannot fit 0.01 lot on most stops"
    assert rows[5000.0]["taken"] > rows[20.0]["taken"]
    for r in rows.values():
        assert r["net_usd"] == pytest.approx(r["final_equity_usd"] - r["start_equity_usd"], abs=0.01)
        if r["lot_range"]:
            assert r["lot_range"][0] >= 0.01 and round(r["lot_range"][0] * 100, 6) == int(round(r["lot_range"][0] * 100))
    assert {r["executed_in_replay"] for r in rows.values()} == {rows[20.0]["executed_in_replay"]}


def test_adaptive_account_never_exceeds_the_hard_cap(spec, many_trades):
    over = adaptive_account(many_trades, spec, 5000.0, 1.5)
    assert over["taken"] == 0 and set(over["skipped"]) == {"CONFIG_RISK_ABOVE_CAP"}
    at_cap = adaptive_account(many_trades, spec, 5000.0, 1.0)
    assert at_cap["worst_day_loss_usd"] <= 5000.0 * 0.02 * 1.5 + 1e-6  # 2% daily cap (gaps can add a little)


def test_report_has_adaptive_accounts_for_every_mode(spec):
    res = run_backtest("EURUSD", synthetic(6000), spec)
    rep = build_report({"EURUSD|m15": res}, spec, split_at=None, folds=2, data_label="SYNTHETIC (test)")
    rows = rep["adaptive_account"]["m15"]
    assert [(r["start_equity_usd"], r["risk_percent"]) for r in rows] == [(e, k) for e in EQUITIES for k in (0.5, 1.0)]
    md = to_markdown(rep)
    assert "Adaptive account, all pairs, mode m15 (hypothetical, not predicted income)" in md and "$5,000" in md


# --- CLI ------------------------------------------------------------------------------------------

def test_report_cli_runs_the_news_comparison(tmp_path, spec, market):
    m5, m15 = market
    d = tmp_path / "data"
    d.mkdir()
    save_candles(d / "EURUSD_M15.csv", m15, 0.00001)
    save_candles(d / "EURUSD_M5.csv", m5, 0.00001)
    _, times = _signal_times(spec, m15)
    news = tmp_path / "calendar.csv"
    rows = ["time_utc,currency,impact,title"] + [f"{(t + timedelta(minutes=10)).isoformat()},USD,HIGH,CPI m/m" for t in times[:3]]
    rows.append(f"{m15[-1].time.isoformat()},EUR,LOW,Bank Holiday")
    news.write_text("\n".join(rows) + "\n", encoding="utf-8")
    out, md = tmp_path / "r.json", tmp_path / "r.md"
    rc = cli.main(["report", "--data-dir", str(d), "--pairs", "EURUSD", "--modes", "m15", "--folds", "2",
                   "--news", str(news), "--label", "SYNTHETIC test data", "--out", str(out), "--md", str(md)])
    assert rc == 0
    rep = json.loads(out.read_text())
    run = rep["runs"]["EURUSD|m15"]
    assert run["news_mode"] == "upgraded" and set(run["news_comparison"]["modes"]) == set(NEWS_MODES)
    assert rep["news"]["calendar_file"] == "calendar.csv" and len(rep["news"]["calendar_sha256"]) == 64
    assert run["news_stability_bars"] == "M5 closed bars"
    assert "News comparison on the same candles" in md.read_text()


def test_backtest_run_rejects_a_missing_news_file(tmp_path, capsys):
    rc = cli.main(["backtest-run", "--pairs", "EURUSD", "--days", "365", "--folds", "4", "--validate-only",
                   "--news", str(tmp_path / "nope.csv")])
    assert rc == cli.EXIT_CONFIG and "INVALID INPUT: news" in capsys.readouterr().out
