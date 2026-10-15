"""MT5-free path: OANDA data feed, owner-confirmed Exness spec, Forex Factory calendar, signed phone push."""

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from ayesha import broker
from ayesha.delivery import push
from ayesha.feed.oanda_feed import OandaFeed, oanda_instrument, parse_time
from ayesha.models import AccountState
from ayesha.news.ff_feed import FFCalendarSource, parse_ff
from ayesha.risk.engine import RiskConfig, TradeProposal, evaluate
from ayesha.scanner import Scanner
from ayesha.storage.db import Registry
from tests.helpers import synthetic
from tests.test_scanner import TF, FakeFeed, _calendar

# Shared with android/app/src/test/.../CoreTest.kt: the same code + body must give the same signature.
PARITY_CODE = "ABCD-EFGH-JKMN-PQRS"
PARITY_BODY = "AYESHA HB T=1760000000000 STATE=OK PAIRS=5 V=abc123def456"
PARITY_SIG = "be7e74e951d5dad03d7fce53f5d2d4d3"


def _candle(t, o, h, l, c, spread=0.0001, complete=True):
    f = lambda x: f"{x:.5f}"
    return {"complete": complete, "volume": 10, "time": t.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
            "bid": {"o": f(o), "h": f(h), "l": f(l), "c": f(c)},
            "ask": {"o": f(o + spread), "h": f(h + spread), "l": f(l + spread), "c": f(c + spread)}}


class FakeOanda:
    def __init__(self, now):
        self.now = now
        self.calls = []

    def __call__(self, url, headers):
        assert headers["Authorization"] == "Bearer tkn"
        self.calls.append(url)
        assert "/orders" not in url and "/trades" not in url and "/positions" not in url
        if "granularity=S5" in url:
            px = 150.0 if "USD_JPY" in url else 1.08
            return {"candles": [_candle(self.now - timedelta(seconds=7), px, px, px, px, 0.00012 if px < 10 else 0.012)]}
        t0 = self.now - timedelta(minutes=60)
        cs = [_candle(t0 + timedelta(minutes=15 * i), 1.08, 1.0805, 1.0795, 1.0801) for i in range(4)]
        cs.append(_candle(self.now - timedelta(minutes=5), 1.08, 1.08, 1.08, 1.08, complete=False))
        return {"candles": cs}


NOW = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)


def test_oanda_feed_reads_bid_ask_and_skips_forming_bar(tmp_path):
    fake = FakeOanda(NOW)
    f = OandaFeed(25, token="tkn", http_get=fake, clock=lambda: NOW, confirm_path=tmp_path / "c.json", min_interval_s=0)
    bars = f.candles("EURUSD", "M15", NOW - timedelta(hours=1), NOW)
    assert len(bars) == 4 and all(b.time.tzinfo for b in bars)
    assert bars[0].spread == pytest.approx(0.0001)
    q = f.quote("EURUSD")
    assert q.spread == pytest.approx(0.00012) and q.age_seconds(NOW) >= 0
    assert f.account()["equity"] == 25 and f.account()["source"] == "OWNER_TYPED"
    assert oanda_instrument("eurusd") == "EUR_USD"
    assert parse_time("2026-10-14T00:15:00.123456789Z") == datetime(2026, 10, 14, 0, 15, 0, 123456, tzinfo=timezone.utc)
    # cross: JPY quote valued through USDJPY from the same feed
    spec = f.instrument("EURJPY")
    assert spec.source == "ASSUMED_EXNESS_STANDARD"
    assert spec.pip_value_per_lot == pytest.approx(100_000 * 0.01 / 150.0, rel=1e-3)
    assert f.spread_floor("EURUSD") == pytest.approx(0.0001)
    with pytest.raises(RuntimeError):
        OandaFeed(25, token="")
    with pytest.raises(ValueError):
        OandaFeed(0, token="tkn")


def test_assumed_exness_spec_blocks_live_until_owner_confirms(tmp_path):
    p = tmp_path / "confirmed.json"
    spec = broker.broker_spec("EURUSD", 1.0, "Standard", confirm_path=p)
    prop = TradeProposal("EURUSD", "BUY", 1.0812, 1.0794, (1.0861,), 0.0001, 0.001, 1, True, "CLEAR")
    acct = AccountState(equity_usd=100_000)
    assert "CONTRACT_SPEC_UNVERIFIED" in evaluate(prop, spec, acct, RiskConfig()).blockers
    with pytest.raises(ValueError):
        broker.save_confirmed("Standard", {"contract_size": 100000, "volume_min": 0, "volume_step": 0.01,
                                           "volume_max": 200}, p)
    broker.save_confirmed("Standard", {"contract_size": 100000, "volume_min": 0.01, "volume_step": 0.01,
                                       "volume_max": 200}, p)
    spec2 = broker.broker_spec("EURUSD", 1.0, "Standard", confirm_path=p)
    assert spec2.source == "OWNER_CONFIRMED:EXNESS_STANDARD"
    assert evaluate(prop, spec2, acct, RiskConfig()).ok
    with pytest.raises(KeyError):
        broker.broker_spec("EURUSD", 1.0, "Pro", confirm_path=p)
    with pytest.raises(ValueError):
        broker.broker_spec("EURJPY", float("nan"), "Standard", confirm_path=p)


@pytest.mark.parametrize("equity", [20, 25, 30])
@pytest.mark.parametrize("risk", [0.5, 1.0])
def test_exness_standard_small_accounts_are_no_trade(tmp_path, equity, risk):
    p = tmp_path / "c.json"
    broker.save_confirmed("Standard", {"contract_size": 100000, "volume_min": 0.01, "volume_step": 0.01,
                                       "volume_max": 200}, p)
    spec = broker.broker_spec("EURUSD", 1.0, "Standard", confirm_path=p)
    prop = TradeProposal("EURUSD", "BUY", 1.0812, 1.0794, (1.0900,), 0.0001, 0.001, 1, True, "CLEAR")
    d = evaluate(prop, spec, AccountState(equity_usd=equity), RiskConfig(risk_per_trade_percent=risk))
    assert not d.ok and d.lot == 0 and "MIN_LOT_EXCEEDS_RISK" in d.blockers
    assert d.min_lot_loss_usd == pytest.approx(0.01 * (18 + 1 + 0.3) * 10, rel=1e-6)  # ~$1.93 = 6-10% of equity


FF_ITEMS = [
    {"title": "CPI m/m", "country": "USD", "date": "2026-10-14T08:30:00-04:00", "impact": "High"},
    {"title": "Speech", "country": "EUR", "date": "2026-10-13T05:00:00-04:00", "impact": "Medium"},
    {"title": "Bad", "country": "USD", "date": "not a date", "impact": "High"},
]


def test_forex_factory_calendar_blocks_and_caches(tmp_path):
    fetched = []

    def fetch(url):
        fetched.append(url)
        return json.dumps(FF_ITEMS).encode()

    clock = [NOW]
    src = FFCalendarSource(tmp_path / "ff.json", fetch=fetch, clock=lambda: clock[0])
    cal = src.calendar(before_min=30, after_min=30)
    assert len(parse_ff(FF_ITEMS)) == 2
    assert cal.status("EURUSD", datetime(2026, 10, 14, 12, 40, tzinfo=timezone.utc))[0] == "BLOCKED"
    assert cal.status("EURUSD", datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc))[0] == "CLEAR"
    assert cal.status("EURUSD", datetime(2026, 10, 25, 15, 0, tzinfo=timezone.utc))[0] == "UNKNOWN"  # next week
    src.calendar()
    assert len(fetched) == 1  # cached: no refetch within an hour

    def broken(url):
        raise OSError("offline")

    clock[0] = NOW + timedelta(hours=30)
    src2 = FFCalendarSource(tmp_path / "ff.json", fetch=broken, clock=lambda: clock[0])
    assert src2.calendar() is None and "offline" in src2.last_error  # stale cache => no calendar => NEWS_UNVERIFIED


def test_push_signing_and_parity_vector():
    code = push.normalize_code(PARITY_CODE)
    assert push.sign(code, PARITY_BODY) == PARITY_SIG
    msg = push.signed(code, PARITY_BODY)
    assert push.verify(code, msg) == PARITY_BODY
    assert push.verify(code, msg.replace("STATE=OK", "STATE=XX")) is None
    assert push.verify(push.new_pairing_code(), msg) is None
    assert push.topic_for(PARITY_CODE).startswith("ayesha-") and len(push.topic_for(PARITY_CODE)) == 31
    with pytest.raises(ValueError):
        push.normalize_code("ABCD-0000-1111-IIII")
    c = push.new_pairing_code()
    assert len(push.normalize_code(c)) == 16


class Bus:
    def __init__(self):
        self.msgs = []

    def __call__(self, url, data, headers):
        self.msgs.append(data.decode())
        return 200


def test_scanner_pushes_signed_ready_archive_and_heartbeat(spec, tmp_path):
    s = copy.deepcopy(spec)
    s["pairs"]["enabled"] = ["EURUSD"]
    s["feed"]["warmup_days"] = 3
    s["delivery"]["notify_grades"] = ["A_PLUS", "WATCH"]
    candles = synthetic(3000)
    bus = Bus()
    n = push.NtfyNotifier(PARITY_CODE, post=bus)
    t = [candles[400].time + timedelta(seconds=5)]
    sc = Scanner(FakeFeed(candles, 20, lambda: t[0]), s, Registry(tmp_path / "p.db"), [n], _calendar(candles),
                 clock=lambda: t[0])
    sc.warmup()
    for c in candles[401:]:
        t[0] = c.time + TF + timedelta(seconds=5)
        sc.poll()
    bodies = [push.verify(PARITY_CODE, m) for m in bus.msgs]
    assert all(b is not None for b in bodies)
    hb = [b for b in bodies if b.startswith("AYESHA HB")]
    sig = [b for b in bodies if not b.startswith("AYESHA HB")]
    assert hb and "STATE=OK" in hb[0]
    assert sig, "expected archive records at $20 equity"
    for b in sig:  # $20 Standard: every candidate is NO_TRADE and says why
        line = b.splitlines()[0]
        assert " ST=NO_TRADE FROM=PC " in line and "MIN_LOT_EXCEEDS_RISK" in line and " BAR=" in line and " EXPU=" in line
        assert "equity" not in b.lower() and "balance" not in b.lower()
    # stopping announces STOPPED
    sc.heartbeat(force_state="STOPPED")
    assert "STATE=STOPPED" in push.verify(PARITY_CODE, bus.msgs[-1])


def test_spread_floor_never_lets_feed_spread_be_tighter_than_broker(spec, tmp_path):
    s = copy.deepcopy(spec)
    s["pairs"]["enabled"] = ["EURUSD"]
    s["feed"]["warmup_days"] = 3
    candles = synthetic(1200)
    t = [candles[400].time + timedelta(seconds=5)]
    feed = FakeFeed(candles, 100_000, lambda: t[0])
    feed.spread_floor = lambda sym: 0.0005  # 5 pips: above the 1.5 pip max
    sc = Scanner(feed, s, Registry(tmp_path / "s.db"), [], _calendar(candles), clock=lambda: t[0])
    sc.warmup()
    for c in candles[401:]:
        t[0] = c.time + TF + timedelta(seconds=5)
        sc.poll()
    payloads = [json.loads(r["payload"]) for r in sc.reg.db.execute("SELECT payload FROM signals")]
    assert payloads and all("SPREAD_TOO_WIDE" in p["blockers"] for p in payloads)


FIXTURE = __import__("pathlib").Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "pc-push-ready.txt"
FIXTURE_REC = {
    "pair": "EURUSD", "direction": "BUY", "entry": 1.0812, "stop_loss": 1.0794, "take_profits": [1.0861],
    "net_rr": 2.55, "safe_lot": 0.02, "liquidity_source": "PDL", "target_name": "ASIA_H",
    "event_time_utc": "2026-10-14T09:15:00+00:00", "expires_at_utc": "2026-10-14T11:15:00+00:00",
    "status": "READY", "signal_id": "0123456789abcdef", "blockers": [], "strategy_hash": "FIXTUREHASH",
    "setup": "SWEEP_MSS_FVG", "score_points": 88, "news_verification": "CLEAR", "spread_pips": 0.9,
    "mtf": {"H4": "UP", "H1": "UP", "H1_LAST": "BOS_UP", "H1_ZONE": "DISCOUNT", "M15": "PDL_SWEEP>CHOCH>FVG",
            "M5": "OFF"},
}


def test_pc_push_fixture_is_current():
    """contracts/fixtures/pc-push-ready.txt is read by the Android parser test (cross-language parity)."""
    msg = push.signed(PARITY_CODE, push.format_push(FIXTURE_REC))
    if FIXTURE.read_text(encoding="utf-8") != msg:
        raise AssertionError("fixture out of date; regenerate with: python -c 'from tests.test_no_mt5_path import "
                             "write_fixture; write_fixture()' (from desktop/)")


def write_fixture():
    FIXTURE.write_text(push.signed(PARITY_CODE, push.format_push(FIXTURE_REC)), encoding="utf-8")
