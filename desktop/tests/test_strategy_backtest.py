from datetime import timedelta

import pytest

from ayesha.backtest.replay import Trade, _open, _pending, run_backtest, summarize, wilson
from ayesha.rules.strategy import Aggregator, Signal, SweepMssFvg
from tests.helpers import T0, bars, synthetic


def _signals(candles, spec):
    s = SweepMssFvg("EURUSD", spec)
    out = []
    for c in candles:
        out.extend(s.on_bar(c))
    return out


def test_synthetic_data_produces_signals(spec):
    sigs = _signals(synthetic(6000), spec)
    assert len(sigs) > 0
    for s in sigs:
        assert (s.entry - s.stop) * (1 if s.direction == "BUY" else -1) > 0
        assert (s.targets[0] - s.entry) * (1 if s.direction == "BUY" else -1) > 0
        assert not s.score_breakdown["news_integrity"]
        assert any(t.startswith("UNAVAILABLE") for t in s.trace)


def test_zero_lookahead(spec):
    """Signals produced up to bar k must be identical whether or not later bars exist."""
    data = synthetic(4000, seed=11)
    full = _signals(data, spec)
    assert full, "need signals for a meaningful test"
    for k in sorted({s.created_index for s in full})[:8]:
        prefix = _signals(data[:k + 1], spec)
        assert [x.signal_id for x in prefix] == [x.signal_id for x in full if x.created_index <= k]


def test_signal_ids_unique_and_deterministic(spec):
    data = synthetic(5000, seed=3)
    a, b = _signals(data, spec), _signals(data, spec)
    assert [s.signal_id for s in a] == [s.signal_id for s in b]
    assert len({s.signal_id for s in a}) == len(a)


def test_aggregator_closed_bars_only():
    agg = Aggregator(15, 60)
    cs = bars([(1, 1.1, 0.9, 1.0)] * 9, start=T0)
    out = [agg.update(c) for c in cs]
    h = [x for x in out if x]
    assert len(h) == 2 and h[0].time == T0 and h[1].time == T0 + timedelta(hours=1)
    assert out[3] is not None and out[8] is None  # 9th bar starts a new hour that is not complete


def _sig(direction="BUY", entry=1.0800, stop=1.0780, target=1.0860):
    return Signal("x", "EURUSD", direction, "T", 0, T0, entry, stop, (target,), 0.0001, 0.001, 80, "WATCH", 10,
                  ["LONDON"], 0)


SLIP = 0.00003


def _run(sig, ohlc):
    t = Trade(sig, planned_loss=abs(sig.entry - sig.stop) + sig.spread + SLIP)
    for i, c in enumerate(bars(ohlc, start=T0.replace(hour=9), spread=0.0001), start=1):
        if t.status == "PENDING":
            _pending(t, c, i, SLIP)
        elif t.status == "OPEN":
            _open(t, c, i, SLIP, timedelta(minutes=15))
    return t


def test_buy_take_profit_r():
    t = _run(_sig(), [(1.0810, 1.0812, 1.0799, 1.0805), (1.0805, 1.0870, 1.0804, 1.0865)])
    assert t.exit_reason == "TP"
    assert t.r == pytest.approx((0.0060 - 0.0001) / (0.0020 + 0.0001 + SLIP), abs=1e-3)


def test_buy_stop_is_minus_one_r():
    t = _run(_sig(), [(1.0810, 1.0812, 1.0799, 1.0805), (1.0805, 1.0806, 1.0775, 1.0777)])
    assert t.exit_reason == "SL" and t.r == pytest.approx(-1.0, abs=1e-6)


def test_same_bar_stop_and_target_counts_as_loss():
    t = _run(_sig(), [(1.0810, 1.0812, 1.0799, 1.0805), (1.0805, 1.0870, 1.0770, 1.0800)])
    assert t.exit_reason == "SL"


def test_fill_bar_cannot_take_profit_but_can_stop():
    t = _run(_sig(), [(1.0810, 1.0870, 1.0775, 1.0800)])
    assert t.exit_reason == "SL"


def test_gap_through_stop_exits_at_open():
    t = _run(_sig(), [(1.0810, 1.0812, 1.0799, 1.0805), (1.0760, 1.0765, 1.0750, 1.0755)])
    assert t.r < -1.0


def test_sell_mirror():
    t = _run(_sig("SELL", 1.0800, 1.0820, 1.0740), [(1.0790, 1.0801, 1.0788, 1.0795), (1.0795, 1.0796, 1.0735, 1.0738)])
    assert t.exit_reason == "TP"
    assert t.r == pytest.approx((0.0060 - 0.0001) / (0.0020 + 0.0001 + SLIP), abs=1e-3)
    t2 = _run(_sig("SELL", 1.0800, 1.0820, 1.0740), [(1.0790, 1.0801, 1.0788, 1.0795), (1.0795, 1.0825, 1.0790, 1.0815)])
    assert t2.exit_reason == "SL" and t2.r == pytest.approx(-1.0, abs=1e-6)


def test_missed_when_target_hit_before_fill():
    t = _run(_sig(), [(1.0820, 1.0865, 1.0815, 1.0860)])
    assert t.status == "MISSED"


def test_expiry():
    t = _run(_sig(), [(1.0820, 1.0825, 1.0815, 1.0820)] * 12)
    assert t.status == "EXPIRED"


def test_summary_and_wilson():
    assert wilson(0, 0) == (0.0, 0.0)
    lo, hi = wilson(50, 100)
    assert lo == pytest.approx(0.404, abs=1e-3) and hi == pytest.approx(0.596, abs=1e-3)
    ts = []
    for r in (2.0, -1.0, -1.0, 3.0):
        t = Trade(_sig())
        t.status, t.r, t.exit_reason = "CLOSED", r, "TP" if r > 0 else "SL"
        ts.append(t)
    s = summarize(ts)
    assert s["expectancy_r"] == 0.75 and s["profit_factor"] == 2.5 and s["max_drawdown_r"] == 2.0
    assert s["longest_losing_streak"] == 2 and s["small_sample_warning"]


def test_backtest_end_to_end(spec):
    res = run_backtest("EURUSD", synthetic(6000), spec, equity_usd=20)
    assert res["trades"]
    assert not res["news_modelled"]
    # at $20 on Standard, nearly every signal must be refused by the min-lot gate
    blocked = sum(1 for b in res["capital_checks"] if "MIN_LOT_EXCEEDS_RISK" in b)
    assert blocked == len(res["capital_checks"])
