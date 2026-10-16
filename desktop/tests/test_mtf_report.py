"""Multi-timeframe engine and validation report. All data here is SYNTHETIC (random walk)."""

import copy
from datetime import timedelta

import pytest

from ayesha.backtest.replay import run_backtest
from ayesha.backtest.report import build_report, capital_feasibility, to_markdown, walk_forward
from ayesha.rules.mtf import Event, MtfEngine, ScalpModeNotValidated, _Pending, check_scalp
from ayesha.rules.strategy import Signal
from tests.helpers import T0, bars, synthetic


def _m5spec(spec):
    s = copy.deepcopy(spec)
    s["mtf"]["confirm_timeframe"] = "M5"
    return s


def _events(candles, spec):
    eng = MtfEngine("EURUSD", spec)
    out = []
    for c in candles:
        out += eng.on_bar(c)
    return out


def test_scalp_m1_refused_until_validated(spec):
    check_scalp(spec)
    bad = copy.deepcopy(spec)
    bad["mtf"]["scalp_m1"]["enabled"] = True
    with pytest.raises(ScalpModeNotValidated):
        check_scalp(bad)
    with pytest.raises(ScalpModeNotValidated):
        MtfEngine("EURUSD", bad)


def test_confirm_tf_must_be_lower(spec):
    bad = copy.deepcopy(spec)
    bad["mtf"]["confirm_timeframe"] = "H1"
    with pytest.raises(ValueError):
        MtfEngine("EURUSD", bad)


def test_default_is_m15_only_with_full_mtf_text(spec):
    eng = MtfEngine("EURUSD", spec)
    assert eng.base_tf == "M15" and eng.confirm_tf is None
    evs = _events(synthetic(6000), spec)
    assert evs and all(e.kind == "SETUP" and not e.needs_confirmation for e in evs)
    for e in evs:
        assert {"H4", "H1", "H1_ZONE", "M15", "M5"} <= set(e.signal.mtf)
        assert e.signal.mtf["M5"] == "OFF"


def test_one_signal_per_setup_not_per_timeframe(spec):
    evs = _events(synthetic(18000, minutes=5, vol=0.00035, seed=5), _m5spec(spec))
    setups = [e for e in evs if e.kind == "SETUP"]
    assert setups
    assert len({e.signal.signal_id for e in setups}) == len(setups)
    ends = [e for e in evs if e.kind != "SETUP"]
    # every setup ends at most once (confirmed or failed), never twice
    assert len({e.signal.signal_id for e in ends}) == len(ends)
    assert {e.signal.signal_id for e in ends} <= {e.signal.signal_id for e in setups}


def test_mtf_confirmation_is_causal(spec):
    sp = _m5spec(spec)
    data = synthetic(14000, minutes=5, vol=0.00035, seed=9)
    full = _events(data, sp)
    assert full
    def key(e):
        return (e.kind, e.signal.signal_id, round(e.signal.entry, 6), e.reason)
    idx = []
    eng = MtfEngine("EURUSD", sp)
    for i, c in enumerate(data):
        for e in eng.on_bar(c):
            idx.append((i, key(e)))
    for k in sorted({i for i, _ in idx})[:6]:
        prefix = [key(e) for e in _events(data[:k + 1], sp)]
        assert prefix == [x for i, x in idx if i <= k]


def _armed(spec, direction="BUY"):
    eng = MtfEngine("EURUSD", _m5spec(spec))
    eng.i = 0
    eng.atr.value = 0.0005
    if direction == "BUY":
        sig = Signal("s1", "EURUSD", "BUY", "T", 0, T0, 1.0800, 1.0780, (1.0900,), 0.00008, 0.001, 80, "A_PLUS",
                     10, ["LONDON"], 0)
    else:
        sig = Signal("s1", "EURUSD", "SELL", "T", 0, T0, 1.0800, 1.0820, (1.0700,), 0.00008, 0.001, 80, "A_PLUS",
                     10, ["LONDON"], 0)
    sig.mtf["M5"] = "PENDING"
    eng.pending["s1"] = _Pending(sig, 0)
    return eng


def _feed(eng, ohlc):
    out = []
    for c in bars(ohlc, start=T0 + timedelta(hours=9), minutes=5):
        eng.i += 1
        eng.atr.value = 0.0005
        out += eng._confirm_step(c, 0.0005)
    return out


def test_buy_confirms_after_touch_with_strong_close(spec):
    eng = _armed(spec)
    ev = _feed(eng, [(1.0806, 1.0808, 1.0798, 1.0801),    # touches entry, extreme high 1.0808
                     (1.0801, 1.0815, 1.0800, 1.0814)])   # bullish, body 13 pips >= 0.8*ATR, closes beyond
    assert [e.kind for e in ev] == ["CONFIRMED"]
    s = ev[0].signal
    assert s.entry == pytest.approx(1.0814) and s.mtf["M5"] == "CONFIRMED_UP"
    assert s.bar_close_utc > T0 and "M5 confirmation" in s.trace[-1]


def test_weak_candle_does_not_confirm_and_times_out(spec):
    eng = _armed(spec)
    weak = (1.0801, 1.0803, 1.0799, 1.0802)
    ev = _feed(eng, [(1.0806, 1.0808, 1.0798, 1.0801)] + [weak] * 7)
    assert [e.reason for e in ev] == ["NO_M5_CONFIRMATION"]


def test_stop_before_confirmation(spec):
    eng = _armed(spec)
    ev = _feed(eng, [(1.0806, 1.0808, 1.0798, 1.0801), (1.0801, 1.0802, 1.0775, 1.0778)])
    assert ev[0].kind == "CONFIRM_FAILED" and ev[0].reason == "STOP_BEFORE_CONFIRMATION"


def test_target_before_entry(spec):
    eng = _armed(spec)
    ev = _feed(eng, [(1.0830, 1.0902, 1.0825, 1.0898)])
    assert ev[0].reason == "TARGET_REACHED_BEFORE_ENTRY"


def test_rr_rechecked_after_confirmation(spec):
    eng = _armed(spec)
    # confirmation close far above entry: RR to 1.0900 collapses below 2
    ev = _feed(eng, [(1.0806, 1.0808, 1.0798, 1.0801), (1.0801, 1.0866, 1.0800, 1.0865)])
    assert ev[0].reason == "RR_BELOW_MIN_AFTER_CONFIRMATION"


def test_sell_mirror_confirms(spec):
    eng = _armed(spec, "SELL")
    ev = _feed(eng, [(1.0794, 1.0802, 1.0792, 1.0799), (1.0799, 1.0800, 1.0785, 1.0786)])
    assert ev[0].kind == "CONFIRMED" and ev[0].signal.mtf["M5"] == "CONFIRMED_DOWN"


def test_expired_unconfirmed(spec):
    eng = _armed(spec)
    ev = _feed(eng, [(1.0820, 1.0825, 1.0815, 1.0820)] * (eng.window + 2))
    assert ev and ev[0].reason == "SETUP_EXPIRED_UNCONFIRMED"


def test_replay_with_m5_confirmation_runs(spec):
    res = run_backtest("EURUSD", synthetic(18000, minutes=5, vol=0.00035, seed=5), _m5spec(spec))
    assert res["base_timeframe"] == "M5" and res["confirm_timeframe"] == "M5"
    st = {t.status for t in res["trades"]}
    assert st & {"UNCONFIRMED", "CLOSED", "BLOCKED", "EXPIRED", "UNRESOLVED_END_OF_DATA"}
    for t in res["trades"]:
        assert t.status != "AWAITING_CONFIRMATION"
        if t.status == "CLOSED" and t.signal.mtf.get("M5", "").startswith("CONFIRMED"):
            assert t.fill_time > t.signal.bar_close_utc - timedelta(minutes=5)


def test_report_on_synthetic_data_is_labelled(spec):
    res = run_backtest("EURUSD", synthetic(8000), spec, equity_usd=25)
    split = res["start"] + (res["end"] - res["start"]) / 2
    rep = build_report({"EURUSD|m15": res}, spec, split_at=split, folds=3, data_label="SYNTHETIC random walk (test)")
    run = rep["runs"]["EURUSD|m15"]
    s = run["summary"]
    assert s["closed_trades"] == s["wins"] + s["losses"]
    assert run["in_vs_out_of_sample"]["in_sample"]["signals"] + run["in_vs_out_of_sample"]["out_of_sample"]["signals"] \
        == s["signals"]
    assert len(run["walk_forward"]["folds"]) == 3
    assert sum(f["signals"] for f in run["walk_forward"]["folds"]) == s["signals"]
    # News spec P2: the same feasibility table from $20 to $5,000 (adaptive capital, no fixed ceiling)
    assert {r["equity_usd"] for r in run["capital_exness_standard"]} == {20.0, 25.0, 30.0, 100.0, 500.0, 1000.0, 5000.0}
    md = to_markdown(rep)
    assert "SYNTHETIC" in md and "too small" in md.lower() or rep["overall"]["sample_ok"]
    assert not run["news_modelled"] and "| NO |" in md
    # I03: no calendar => the report says news was not modelled and the comparison was not run
    assert not rep["news"]["modelled"] and "NOT RUN (BLOCKED BY DATA)" in md and "NEWS DIRECTION NOT BACKTESTED" in md


def test_capital_feasibility_respects_min_lot(spec):
    res = run_backtest("EURUSD", synthetic(6000), spec)
    rows = capital_feasibility(res["trades"], "EURUSD", 0.00003, equities=(20.0, 100000.0), risks=(0.5,))
    small, big = rows
    assert small["allowed_by_min_lot"] <= big["allowed_by_min_lot"]
    assert big["allowed_by_min_lot"] == big["closed_trades"]


def test_walk_forward_empty():
    assert walk_forward([], 4) == {"folds": []}
