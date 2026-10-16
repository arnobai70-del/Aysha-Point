"""AI-008 / AI-009: the strategy contract and loader, the common runner (same fills and costs as the legacy replay,
trade for trade with the baseline), causality for every strategy, intrabar flags, cost models, the account
simulation and the split plan. All prices are SYNTHETIC: nothing here says anything about a real edge."""

import copy
from datetime import timedelta

import pytest

from ayesha.backtest.replay import Trade, run_backtest
from ayesha.config import load_spec
from ayesha.models import Candle
from ayesha.research.contracts import validate
from ayesha.research.evaluation import metrics as M
from ayesha.research.simulation import portfolio, runner
from ayesha.research.simulation.costs import BASE, SENSITIVITY
from ayesha.research.strategies import loader
from ayesha.research.strategies.protocol import research_signal, target_for
from tests.research import synth

A, B, C = loader.LAB_ORDER


@pytest.fixture(scope="module")
def spec():
    return load_spec()


@pytest.fixture(scope="module")
def bars():
    return synth.fx_week(8000, seed=3)


def _row(t):
    return [t.signal.signal_id, t.status, t.fill_index, t.exit_index, t.exit_reason, t.r, list(t.blockers)]


# --- contract and loader -------------------------------------------------------------------------

def test_registry_has_baseline_control_and_exactly_one_experimental(spec):
    kinds = [loader.REGISTRY[s].kind if s != A else "BASELINE" for s in loader.LAB_ORDER]
    assert kinds == ["BASELINE", "CONTROL", "EXPERIMENTAL"]
    assert sum(1 for c in loader.REGISTRY.values() if getattr(c, "kind", "") == "EXPERIMENTAL") == 1
    assert len(set(loader.REGISTRY)) == len(loader.REGISTRY) == 3
    for m in loader.available(spec):
        validate(m, "research.strategy/1")
        assert m["research_only"] is True and m["execution_level"] == "NONE"


def test_baseline_is_the_frozen_live_rules_and_takes_no_parameters(spec):
    from ayesha.research.simulation.baseline import strategy_manifest

    assert loader.manifest(A, spec) == strategy_manifest(spec)
    with pytest.raises(loader.StrategyError):
        loader.manifest(A, spec, {"rr": 3.0})


def test_parameters_are_bounded_and_change_the_hash(spec):
    base = loader.manifest(B, spec)
    assert base == loader.manifest(B, spec)  # deterministic
    moved = loader.manifest(B, spec, {"range_bars": 5})
    assert moved["strategy_hash"] != base["strategy_hash"] and moved["parameters"]["range_bars"] == 5
    for bad in ({"range_bars": 50}, {"no_such_parameter": 1}, {"rr": True}, {"rr": "2"}):
        with pytest.raises(loader.StrategyError):
            loader.manifest(B, spec, bad)
    with pytest.raises(loader.StrategyError):
        loader.manifest("made-up-strategy", spec)


def test_loader_hands_out_a_copy_of_the_spec(spec, monkeypatch):
    seen = []
    cls = loader.REGISTRY[B]
    init = cls.__init__
    monkeypatch.setattr(cls, "__init__", lambda self, sym, sp, p=None: (seen.append(sp), init(self, sym, sp, p))[1])
    sp = copy.deepcopy(spec)
    loader.load(B, "EURUSD", sp)
    assert seen and seen[0] == sp and seen[0] is not sp


def test_research_signal_ids_cannot_collide_with_live_ids(bars, spec):
    s = research_signal(B, "1.0.0", "EURUSD", "BUY", 5, bars[5].time, 1.1, 1.09, 1.12, 0.0001, 0.001, 9, [], [],
                        0.0001)
    assert s.signal_id.startswith("rs") and s.grade == "RESEARCH"
    leg = run_backtest("EURUSD", bars[:3000], spec)["trades"]
    assert all(not t.signal.signal_id.startswith("rs") for t in leg)


def test_target_gives_the_requested_net_reward_to_risk():
    t = target_for("BUY", 1.1000, 1.0980, 0.0001, 0.00005, 2.0)
    loss = 0.0020 + 0.0001 + 0.00005
    assert (t - 1.1000 - 0.0001) / loss == pytest.approx(2.0)
    assert target_for("SELL", 1.1, 1.102, 0.0001, 0.00005, 2.0) < 1.1


# --- common runner -------------------------------------------------------------------------------

@pytest.mark.parametrize("seed", [3, 21])
def test_baseline_through_the_runner_equals_the_legacy_replay(spec, seed):
    cs = synth.fx_week(8000, seed=seed)
    sp = copy.deepcopy(spec)
    sp["mtf"]["confirm_timeframe"] = None
    leg = run_backtest("EURUSD", cs, sp, account_type="Standard", usd_rates=runner.APPROX_USD_RATES)["trades"]
    st, _ = loader.load(A, "EURUSD", spec)
    lab = runner.run("EURUSD", cs, spec, st)["trades"]
    assert leg, "need some legacy signals"
    assert [_row(lt.trade) for lt in lab] == [_row(t) for t in leg]


@pytest.mark.parametrize("sid", loader.LAB_ORDER)
def test_future_bars_cannot_change_earlier_decisions(spec, bars, sid):
    k = 6000
    changed = bars[:k] + [Candle(b.time, b.open * 1.01, b.high * 1.01, b.low * 1.01, b.close * 1.01, b.volume,
                                 b.spread) for b in bars[k:]]
    out = []
    for cs in (bars, changed):
        st, _ = loader.load(sid, "EURUSD", spec)
        out.append(runner.run("EURUSD", cs, spec, st)["trades"])
    cut = bars[k].time
    early = [[(lt.trade.signal.signal_id, lt.trade.signal.entry, lt.trade.signal.stop) for lt in trades
              if lt.trade.signal.bar_close_utc <= cut] for trades in out]
    assert early[0], "need decisions before the mutation point"
    assert early[0] == early[1]
    ended = [[_row(lt.trade) for lt in trades if lt.ended_at is not None and lt.ended_at <= cut] for trades in out]
    assert ended[0] == ended[1]


@pytest.mark.parametrize("sid", (B, C))
def test_lab_strategies_produce_orders_through_the_same_gates(spec, bars, sid):
    st, _ = loader.load(sid, "EURUSD", spec)
    r = runner.run("EURUSD", bars, spec, st)
    assert r["engine"] == runner.ENGINE and r["trades"]
    for lt in r["trades"]:
        t = lt.trade
        assert t.signal.grade == "RESEARCH" and t.signal.signal_id.startswith("rs")
        assert t.status in runner.TERMINAL or t.status == "UNRESOLVED_END_OF_DATA"
        if t.status == "CLOSED":
            assert t.fill_index > t.signal.created_index  # an order can first fill on the next bar
            assert t.exit_index >= t.fill_index and lt.ended_at >= lt.created_at


def _lab_trade(direction="BUY", entry=1.1, stop=1.098, target=1.106, index=10, t0=synth.T0, symbol="EURUSD",
               ended=None):
    s = research_signal(B, "1.0.0", symbol, direction, index, t0, entry, stop, target, 0.0001, 0.002, index + 8,
                        ["LONDON"], [], 0.0001)
    lt = runner.LabTrade(Trade(s, planned_loss=abs(entry - stop) + 0.0001 + 0.00005), symbol, t0, ended)
    return lt


def test_intrabar_ambiguity_is_flagged():
    lt = _lab_trade()
    lt.trade.status, lt.trade.exit_reason = "CLOSED", "SL"
    runner._flags(lt, "OPEN", Candle(synth.T0, 1.1, 1.107, 1.097, 1.099, 1, 0.0001))
    assert lt.flags == ["AMBIGUOUS_STOP_AND_TARGET_SAME_BAR"]
    lt2 = _lab_trade()
    lt2.trade.status = "OPEN"
    runner._flags(lt2, "PENDING_MARKET", Candle(synth.T0, 1.1, 1.107, 1.099, 1.101, 1, 0.0001))
    assert lt2.flags == ["FILL_BAR_REACHED_TARGET"]
    lt3 = _lab_trade()
    lt3.trade.status, lt3.trade.exit_reason = "CLOSED", "SL"
    runner._flags(lt3, "OPEN", Candle(synth.T0, 1.1, 1.101, 1.097, 1.098, 1, 0.0001))
    assert lt3.flags == []


# --- costs -----------------------------------------------------------------------------------------

def test_cost_models_have_ids_and_hashes_and_change_one_thing(bars):
    ids = [c.model_id for c in (BASE, *SENSITIVITY)]
    assert len(set(ids)) == len(ids) and len({c.hash for c in (BASE, *SENSITIVITY)}) == len(ids)
    assert BASE.apply(bars) is bars
    wide = SENSITIVITY[1].apply(bars[:10])
    assert [w.spread for w in wide] == pytest.approx([b.spread * 1.5 for b in bars[:10]])
    assert [w.close for w in wide] == [b.close for b in bars[:10]]


def test_slippage_and_delay_variants(spec, bars):
    def go(cost):
        st, _ = loader.load(B, "EURUSD", spec)
        return {lt.trade.signal.signal_id: lt for lt in runner.run("EURUSD", bars, spec, st, cost)["trades"]}

    base, slip, late = go(BASE), go(SENSITIVITY[2]), go(SENSITIVITY[3])
    same = set(base) & set(slip)
    assert same
    for sid in same:
        assert slip[sid].trade.planned_loss - base[sid].trade.planned_loss == pytest.approx(0.00005)
    both = set(base) & set(late)
    assert both
    for sid in both:
        assert late[sid].created_at - base[sid].created_at == timedelta(minutes=15)


# --- account simulation ------------------------------------------------------------------------------

def test_account_simulation_uses_the_live_gates(spec, bars):
    st, _ = loader.load(B, "EURUSD", spec)
    lts = runner.run("EURUSD", bars, spec, st)["trades"]
    small, big = portfolio.simulate(lts, spec, 20.0), portfolio.simulate(lts, spec, 5000.0)
    assert small["taken"] <= big["taken"]
    assert portfolio.simulate(lts, spec, 5000.0) == big  # deterministic
    assert big["risk_per_trade_percent"] <= 1.0
    assert "HYPOTHETICAL" in big["basis"]
    empty = portfolio.simulate([], spec, 100.0)
    assert empty["equity_end_usd"] == 100.0 and empty["taken"] == 0


def test_one_position_per_currency(spec):
    t0 = synth.T0 + timedelta(hours=8)
    a = _lab_trade(symbol="EURUSD", t0=t0, ended=t0 + timedelta(hours=4))
    b = _lab_trade(symbol="GBPUSD", entry=1.27, stop=1.268, target=1.276, t0=t0 + timedelta(minutes=15),
                   ended=t0 + timedelta(hours=4))
    for lt in (a, b):
        lt.trade.status, lt.trade.r, lt.trade.exit_reason = "CLOSED", 1.0, "TP"
    r = portfolio.simulate([a, b], spec, 5000.0)
    assert r["taken"] == 1 and any(k.startswith("CORRELATED_EXPOSURE") for k in r["skipped"])


# --- metrics and the split plan -------------------------------------------------------------------------

def test_split_plan_is_defined_on_the_data_not_on_trades(bars):
    start, end = M.time_range([bars])
    p1 = M.split_plan(start, end, 4)
    assert p1 == M.split_plan(start, end, 4) and p1["split_plan_id"].startswith("sp_")
    assert p1["folds"][0][0] == p1["range"][0] and p1["folds"][-1][1] == p1["range"][1]
    hold = start + (end - start) * 0.8
    p2 = M.split_plan(start, end, 4, holdout_from=hold)
    assert p2["split_plan_id"] != p1["split_plan_id"] and p2["folds"][-1][1] == p2["holdout_from"]
    for bad in ({"folds": 1}, {"split_at": end}, {"holdout_from": start}):
        with pytest.raises(ValueError):
            M.split_plan(start, end, **{"folds": 4, **bad})


def test_holdout_stays_sealed_until_revealed(spec, bars):
    st, _ = loader.load(B, "EURUSD", spec)
    lts = runner.run("EURUSD", bars, spec, st)["trades"]
    start, end = M.time_range([bars])
    plan = M.split_plan(start, end, 3, holdout_from=start + (end - start) * 0.7)
    sealed = M.periods(lts, plan)
    assert sealed["holdout"]["state"] == "SEALED" and sealed["holdout"]["orders"] > 0
    assert "expectancy_r" not in sealed["holdout"]
    assert sealed["all"]["signals"] == len(lts) - sealed["holdout"]["orders"]
    shown = M.periods(lts, plan, reveal_holdout=True)
    assert shown["holdout"]["state"] == "REVEALED" and "expectancy_r" in shown["holdout"]


def test_metrics_keep_the_denominator_and_flag_small_samples(spec, bars):
    st, _ = loader.load(C, "EURUSD", spec)
    lts = runner.run("EURUSD", bars, spec, st)["trades"]
    s = M.summary(lts, len(bars))
    assert s["signals"] == len(lts) and sum(s["by_status"].values()) == len(lts)
    assert s["small_sample"] is (s["closed_trades"] < M.MIN_SAMPLE)
    assert M.compact(M.summary(lts[:3]))["sample"] == "INSUFFICIENT_SAMPLE"
    wb = M.without_best(lts)
    assert wb["removed_best_trades"] >= 1


def test_mean_difference_verdicts():
    assert M.mean_diff([1.0], [0.0])["verdict"] == "INSUFFICIENT_SAMPLE"
    a, b = [1.0, -1.0] * 60, [1.0, -1.0] * 60
    assert M.mean_diff(a, b)["verdict"] == "NOT_DISTINGUISHABLE"
    assert M.mean_diff([2.0, 1.9] * 60, [-1.0, -0.9] * 60)["verdict"] == "HIGHER_IN_THIS_SAMPLE"
    assert M.mean_diff([2.0, 1.9] * 10, [-1.0, -0.9] * 10)["verdict"] == "INSUFFICIENT_SAMPLE"
