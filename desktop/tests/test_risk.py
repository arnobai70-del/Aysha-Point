from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ayesha.feed.static_specs import assumed_fx_spec
from ayesha.models import AccountState
from ayesha.risk.engine import RiskConfig, TradeProposal, broker_order_prices, evaluate, floor_to_step

CFG = RiskConfig()
EU = assumed_fx_spec("EURUSD", 1.08)
EU_MT5 = replace(EU, source="MT5:EURUSDm")


def prop(**kw):
    base = dict(symbol="EURUSD", direction="BUY", entry=1.0800, stop=1.0780, targets=(1.0860,),
                spread=0.00008, atr=0.0015, quote_age_seconds=1, market_open=True, news_status="CLEAR")
    base.update(kw)
    return TradeProposal(**base)


def test_spec_small_account_example_is_no_trade():
    # master spec section K: $25 equity, 0.5% risk, 8 pip stop on EURUSD => below 0.01 min lot
    d = evaluate(prop(stop=1.0792, targets=(1.0830,)), EU_MT5, AccountState(25), CFG)
    assert not d.ok
    assert "MIN_LOT_EXCEEDS_RISK" in d.blockers
    assert d.lot == 0.0 and d.max_loss_usd == 0.0
    assert d.min_lot_loss_percent > 3  # what 0.01 lot would really risk


def test_cent_account_makes_small_equity_tradeable():
    cent = replace(assumed_fx_spec("EURUSD", 1.08, "StandardCent"), source="MT5:EURUSDc")
    d = evaluate(prop(), cent, AccountState(25), CFG)
    assert d.ok, d.blockers
    assert d.max_loss_usd <= d.risk_budget_usd


def test_lot_floors_never_rounds_up():
    d = evaluate(prop(), EU_MT5, AccountState(1000), CFG)
    assert d.ok, d.blockers
    # budget $5; loss/lot = (20 + 0.8 + 0.3 pips) * $10 = $211 => raw 0.0237 => 0.02
    assert d.loss_per_lot_usd == pytest.approx(211.0, rel=1e-6)
    assert d.lot == 0.02
    assert d.max_loss_usd <= d.risk_budget_usd


@settings(max_examples=300, deadline=None)
@given(equity=st.floats(10, 100_000), stop_pips=st.floats(3, 80), spread_pips=st.floats(0, 1.5))
def test_property_loss_never_exceeds_budget(equity, stop_pips, spread_pips):
    p = prop(stop=1.08 - stop_pips * 0.0001, spread=spread_pips * 0.0001, targets=(1.08 + 3 * stop_pips * 0.0001,),
             atr=0.0)
    d = evaluate(p, EU_MT5, AccountState(equity), CFG)
    assert d.max_loss_usd <= d.risk_budget_usd + 1e-9
    steps = round(d.lot / EU.volume_step, 6)
    assert steps == int(steps)
    if d.lot:
        assert d.lot >= EU.volume_min


@pytest.mark.parametrize("v,step,expected", [(0.0299999, 0.01, 0.02), (0.03, 0.01, 0.03), (1.237, 0.1, 1.2),
                                             (0.009, 0.01, 0.0)])
def test_floor_to_step(v, step, expected):
    assert floor_to_step(v, step) == expected


def test_jpy_pip_value():
    uj = assumed_fx_spec("USDJPY", 150.0)
    assert uj.pip_value_per_lot == pytest.approx(100_000 * 0.01 / 150.0)  # ~$6.67 per pip per lot


def test_cross_needs_usd_rate():
    with pytest.raises(ValueError):
        assumed_fx_spec("EURJPY", 162.0)
    ej = assumed_fx_spec("EURJPY", 162.0, usd_rates={"JPY": 1 / 150})
    assert ej.pip_value_per_lot == pytest.approx(100_000 * 0.01 / 150)


@pytest.mark.parametrize("kw,blocker", [
    (dict(spread=0.0002), "SPREAD_TOO_WIDE"),
    (dict(quote_age_seconds=120), "DATA_STALE"),
    (dict(market_open=False), "MARKET_CLOSED"),
    (dict(news_status="UNKNOWN"), "NEWS_UNVERIFIED"),
    (dict(news_status="BLOCKED"), "NEWS_LOCKOUT"),
    (dict(stop=1.0797, targets=(1.0830,)), "STOP_TOO_TIGHT_FOR_VOLATILITY"),
    (dict(targets=(1.0820,)), "NET_RR_BELOW_MIN"),
])
def test_hard_gates(kw, blocker):
    d = evaluate(prop(**kw), EU_MT5, AccountState(10_000), CFG)
    assert not d.ok
    assert blocker in d.blockers


def test_invalid_levels():
    assert "INVALID_LEVELS" in evaluate(prop(stop=1.0810), EU_MT5, AccountState(10_000), CFG).blockers
    assert "INVALID_LEVELS" in evaluate(prop(direction="SELL"), EU_MT5, AccountState(10_000), CFG).blockers


def test_unverified_spec_blocks_live_but_not_research():
    assert "CONTRACT_SPEC_UNVERIFIED" in evaluate(prop(), EU, AccountState(10_000), CFG).blockers
    assert evaluate(prop(), EU, AccountState(10_000), CFG, live=False).ok


def test_missing_contract_spec():
    bad = replace(EU_MT5, tick_value=0.0)
    assert "CONTRACT_SPEC_MISSING" in evaluate(prop(), bad, AccountState(10_000), CFG).blockers


def test_daily_pause_after_two_losses():
    d = evaluate(prop(), EU_MT5, AccountState(10_000, losses_today=2), CFG)
    assert "DAILY_RISK_PAUSE" in d.blockers


def test_daily_loss_cap():
    d = evaluate(prop(), EU_MT5, AccountState(10_000, realized_loss_today_usd=180), CFG)
    assert "DAILY_RISK_PAUSE" in d.blockers  # 180 + 50 > 200 (2%)


def test_open_risk_cap():
    d = evaluate(prop(), EU_MT5, AccountState(10_000, open_risk_usd=80), CFG)
    assert "OPEN_RISK_CAP" in d.blockers


def test_correlated_usd_exposure():
    acct = AccountState(10_000, open_positions=[("GBPUSD", "BUY")])  # already short USD
    d = evaluate(prop(), EU_MT5, acct, CFG)  # BUY EURUSD is also short USD
    assert "CORRELATED_EXPOSURE_USD" in d.blockers
    ok = evaluate(prop(), EU_MT5, AccountState(10_000, open_positions=[("USDJPY", "SELL")]), RiskConfig(max_same_currency_positions=2))
    assert "CORRELATED_EXPOSURE_USD" not in ok.blockers


def test_margin_gate():
    inst = replace(EU_MT5, margin_per_lot=1000.0)
    d = evaluate(prop(), inst, AccountState(10_000, free_margin_usd=100.0), CFG)
    assert "INSUFFICIENT_FREE_MARGIN" in d.blockers


def test_config_cap():
    d = evaluate(prop(), EU_MT5, AccountState(10_000), RiskConfig(risk_per_trade_percent=2.0))
    assert "CONFIG_RISK_ABOVE_CAP" in d.blockers


def test_net_rr_counts_spread_once():
    d = evaluate(prop(), EU_MT5, AccountState(10_000), CFG)
    # profit 60 - 0.8 = 59.2 pips; loss 20 + 0.8 + 0.3 = 21.1 pips
    assert d.net_rr[0] == pytest.approx(59.2 / 21.1, abs=1e-3)


def test_broker_order_prices():
    assert broker_order_prices("BUY", 1.08, 1.078, 1.086, 0.0001) == {"limit": 1.0801, "sl": 1.078, "tp": 1.086}
    s = broker_order_prices("SELL", 1.08, 1.082, 1.074, 0.0001)
    assert s["limit"] == 1.08 and s["sl"] == pytest.approx(1.0821) and s["tp"] == pytest.approx(1.0741)
