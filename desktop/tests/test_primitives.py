import pytest

from ayesha.rules.primitives import ATR, Analyzer, is_displacement
from tests.helpers import bars


def rules(**kw):
    r = dict(atr_period=3, swing_left_bars=2, swing_right_bars=2, bos_buffer_atr=0.0, displacement_body_atr=1.2,
             displacement_body_frac=0.6, fvg_min_gap_atr=0.0, fvg_max_age_bars=40, eq_tolerance_atr=0.1,
             sweep_min_penetration_atr=0.0, sweep_reclaim_bars=3, mss_within_bars=12)
    r.update(kw)
    return r


def feed(a, cs):
    return [a.update(c) for c in cs]


def test_atr_wilder():
    a = ATR(3)
    out = [a.update(c) for c in bars([(1, 2, 0, 1), (1, 3, 1, 2), (2, 2.5, 1.5, 2), (2, 4, 2, 3)])]
    assert out[:2] == [None, None]
    assert out[2] == pytest.approx((2 + 2 + 1) / 3)
    assert out[3] == pytest.approx((5 / 3 * 2 + 2) / 3)


def test_swing_confirmed_only_after_right_bars():
    a = Analyzer(rules())
    cs = bars([(1, 1.1, 0.9, 1), (1, 1.2, 0.95, 1.1), (1.1, 1.5, 1.0, 1.2), (1.2, 1.3, 1.0, 1.1), (1.1, 1.2, 1.0, 1.05)])
    evs = feed(a, cs)
    highs = [(e.index, s.index) for e in evs for s in e.swings if s.kind == "HIGH"]
    assert highs == [(4, 2)]  # pivot at bar 2, known at bar 4


def test_swing_tie_break_earliest_wins():
    a = Analyzer(rules())
    cs = bars([(1, 1.1, 0.9, 1), (1, 1.2, 0.9, 1.1), (1.1, 1.5, 1.0, 1.2), (1.2, 1.5, 1.0, 1.1),
               (1.1, 1.2, 1.0, 1.05), (1.0, 1.1, 0.95, 1.0)])
    evs = feed(a, cs)
    highs = [s.index for e in evs for s in e.swings if s.kind == "HIGH"]
    assert highs == [2]


def test_bullish_and_bearish_fvg():
    a = Analyzer(rules())
    cs = bars([(1.0, 1.01, 0.99, 1.0), (1.0, 1.01, 0.99, 1.0), (1.0, 1.01, 0.99, 1.0),
               (1.0, 1.01, 0.995, 1.008), (1.008, 1.05, 1.007, 1.048), (1.048, 1.06, 1.02, 1.055)])
    evs = feed(a, cs)
    f = [g for e in evs for g in e.fvgs]
    assert len(f) == 1 and f[0].direction == 1
    assert (f[0].bottom, f[0].top) == (1.01, 1.02)
    a2 = Analyzer(rules())
    cs2 = bars([(1.0, 1.01, 0.99, 1.0)] * 3 + [(1.0, 1.005, 0.99, 0.992), (0.992, 0.993, 0.95, 0.952),
                                             (0.952, 0.98, 0.94, 0.945)])
    f2 = [g for e in feed(a2, cs2) for g in e.fvgs]
    assert len(f2) == 1 and f2[0].direction == -1 and (f2[0].bottom, f2[0].top) == (0.98, 0.99)


def test_fvg_mitigation_and_invalidation():
    a = Analyzer(rules())
    cs = bars([(1.0, 1.01, 0.99, 1.0)] * 3 + [(1.0, 1.01, 0.995, 1.008), (1.008, 1.05, 1.007, 1.048),
                                            (1.048, 1.06, 1.02, 1.055), (1.055, 1.056, 1.015, 1.03),
                                            (1.03, 1.031, 1.0, 1.005)])
    feed(a, cs)
    f = a.fvgs[0]
    assert f.mitigated and f.invalidated


def test_displacement():
    c = bars([(1.0, 1.021, 0.999, 1.02)])[0]
    assert is_displacement(c, 0.01, 1.2, 0.6) == 1
    assert is_displacement(c, 0.03, 1.2, 0.6) == 0
    assert is_displacement(c, None, 1.2, 0.6) == 0


def _uptrend_then_break():
    # builds a swing high, a swing low, then closes below the swing low (bearish CHoCH after bullish BOS)
    return bars([
        (1.00, 1.01, 0.99, 1.00), (1.00, 1.02, 0.995, 1.015), (1.015, 1.03, 1.01, 1.025),
        (1.025, 1.04, 1.02, 1.035), (1.035, 1.036, 1.02, 1.022), (1.022, 1.025, 1.012, 1.015),
        (1.015, 1.018, 1.005, 1.016), (1.016, 1.03, 1.014, 1.028), (1.028, 1.045, 1.026, 1.044),
        (1.044, 1.046, 1.03, 1.032), (1.032, 1.034, 1.02, 1.022), (1.022, 1.023, 0.99, 0.992),
    ])


def test_bos_then_choch():
    a = Analyzer(rules())
    evs = feed(a, _uptrend_then_break())
    br = [b for e in evs for b in e.breaks]
    kinds = [(b.kind, b.direction) for b in br]
    assert ("BOS", 1) in kinds
    assert kinds[-1] == ("CHOCH", -1)
    assert br[-1].displacement and br[-1].is_mss


def test_sweep_reclaim_vs_breakout():
    a = Analyzer(rules())
    feed(a, bars([(1.0, 1.01, 0.99, 1.0)] * 4))
    lv = a.add_level("PDL", -1, 0.985)
    e = a.update(bars([(1.0, 1.002, 0.98, 0.995)], start=a.bars[-1].time.replace(hour=2))[0])
    assert e.sweeps and e.sweeps[0].level is lv and e.sweeps[0].extreme == 0.98 and e.sweeps[0].direction == 1

    b = Analyzer(rules(sweep_reclaim_bars=1))
    feed(b, bars([(1.0, 1.01, 0.99, 1.0)] * 4))
    lv2 = b.add_level("PDL", -1, 0.985)
    t = b.bars[-1].time
    from datetime import timedelta
    evs = [b.update(c) for c in bars([(0.99, 0.991, 0.975, 0.978), (0.978, 0.98, 0.97, 0.972),
                                      (0.972, 0.99, 0.97, 0.988)], start=t + timedelta(minutes=15))]
    assert not any(e.sweeps for e in evs)  # kept closing below: breakout, not a sweep
    assert lv2.consumed
