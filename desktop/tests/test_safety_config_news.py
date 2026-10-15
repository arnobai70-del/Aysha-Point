import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from ayesha.config import load_spec, strategy_hash
from ayesha.feed.csv_feed import load_candles, resample, save_candles
from ayesha.feed.mt5_feed import MT5ReadOnlyFeed
from ayesha.news.calendar import NewsCalendar, NewsEvent
from tests.helpers import bars, synthetic

ROOT = Path(__file__).resolve().parents[2]


def test_repo_has_no_order_api():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_no_order_api.py"), str(ROOT)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


class FakeMT5:
    TIMEFRAME_M15 = 15
    ORDER_TYPE_BUY = 0

    def __init__(self):
        self.calls = []

    def initialize(self):
        return True

    def account_info(self):
        return SimpleNamespace(login=12345678, server="Exness-MT5Trial", currency="USD", balance=20.0, equity=20.0,
                               margin_free=20.0, leverage=200, trade_mode=0)

    def symbol_info(self, name):
        if name != "EURUSDm":
            return None
        return SimpleNamespace(digits=5, trade_tick_size=0.00001, trade_tick_value=1.0, trade_contract_size=100000,
                               volume_min=0.01, volume_step=0.01, volume_max=200, currency_base="EUR",
                               currency_profit="USD", trade_stops_level=0)

    def symbols_get(self, pattern):
        return [SimpleNamespace(name="EURUSDm")]

    def symbol_select(self, name, enable):
        return True

    def symbol_info_tick(self, name):
        return SimpleNamespace(time=int(datetime.now(timezone.utc).timestamp()), bid=1.08, ask=1.08008)

    def order_calc_margin(self, *a):
        return 540.0

    def order_send(self, *a):  # must never be reachable
        raise AssertionError("order_send called")

    def last_error(self):
        return (0, "ok")

    def shutdown(self):
        pass


def test_mt5_adapter_is_read_only_and_resolves_suffix():
    f = MT5ReadOnlyFeed(FakeMT5())
    acct = f.connect()
    assert acct["login_masked"] == "***678" and acct["trade_mode"] == "DEMO"
    inst = f.instrument("EURUSD")
    assert inst.source == "MT5:EURUSDm" and inst.pip_value_per_lot == pytest.approx(10.0)
    assert inst.margin_per_lot == 540.0
    with pytest.raises(PermissionError):
        f.mt5.order_send({})
    with pytest.raises(PermissionError):
        f.mt5.positions_get()


def test_strategy_hash_stable_and_sensitive():
    s = load_spec()
    assert s["strategy_hash"] == strategy_hash(s)
    s2 = load_spec()
    s2["risk"]["min_net_rr"] = 2.5
    assert strategy_hash(s2) != s["strategy_hash"]


def test_csv_roundtrip_and_resample(tmp_path):
    cs = synthetic(40)
    p = tmp_path / "c.csv"
    save_candles(p, cs, 0.00001)
    back = load_candles(p, 0.00001)
    assert [c.close for c in back] == [c.close for c in cs]
    assert back[0].spread == pytest.approx(cs[0].spread)
    h1 = resample(cs, 60)
    assert len(h1) == 10 and h1[0].high == max(c.high for c in cs[:4])


def test_candle_validation():
    with pytest.raises(ValueError):
        bars([(1.0, 0.9, 0.8, 1.0)])


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_news_calendar():
    cal = NewsCalendar([NewsEvent(utc(2025, 3, 7, 13, 30), "USD", "HIGH", "NFP")], utc(2025, 3, 3), utc(2025, 3, 8))
    assert cal.status("EURUSD", utc(2025, 3, 7, 13, 10))[0] == "BLOCKED"
    assert cal.status("EURUSD", utc(2025, 3, 7, 14, 1))[0] == "CLEAR"
    assert cal.status("EURGBP", utc(2025, 3, 7, 13, 30))[0] == "CLEAR"
    assert cal.status("EURUSD", utc(2025, 3, 10, 9, 0))[0] == "UNKNOWN"  # outside coverage


def test_news_csv(tmp_path):
    p = tmp_path / "n.csv"
    p.write_text("time_utc,currency,impact,title\n2025-03-07T13:30:00Z,USD,HIGH,NFP\n", encoding="utf-8")
    cal = NewsCalendar.from_csv(p)
    assert cal.status("USDJPY", utc(2025, 3, 7, 13, 45))[0] == "BLOCKED"


def test_pine_generated_from_current_spec():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_pine.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    pine = (ROOT / "tradingview" / "AyeshaSmartMoney.pine").read_text(encoding="utf-8")
    assert pine.startswith("//@version=6")
    assert "alert(msg, alert.freq_once_per_bar_close)" in pine and "It never places orders" in pine
    assert load_spec()["strategy_hash"] in pine


def test_pine_alert_payload_matches_phone_parser():
    # Keys the Android AlertParser relies on (android/.../core/AyeshaAlert.kt). BAR drives expiry and dedup.
    pine = (ROOT / "tradingview" / "AyeshaSmartMoney.pine").read_text(encoding="utf-8")
    head = next(line for line in pine.splitlines() if 'head = "AYESHA "' in line)
    for key in ("TF=", "E=", "SL=", "TP=", "RR=", "LOT=", "EXP=", "SRC=", "TGT=", "BAR=", "QUSD=", "ST=CHART_CANDIDATE", "V="):
        assert f" {key}" in head, key
    assert 'str.tostring(time_close, "#")' in head


def test_version_manifest_matches_components():
    import json
    import re

    man = json.loads((ROOT / "contracts" / "version.json").read_text(encoding="utf-8"))
    py = re.search(r'^version = "([^"]+)"', (ROOT / "desktop" / "pyproject.toml").read_text(), re.M).group(1)
    gradle = re.search(r'versionName = "([^"]+)"', (ROOT / "android" / "app" / "build.gradle.kts").read_text()).group(1)
    assert man["components"]["desktop"] == py
    assert man["components"]["android_app"] == gradle
    assert man["components"]["strategy"] == load_spec()["strategy_version"]
    top = re.search(r"^## (\S+)", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), re.M).group(1)
    assert top == man["release"]
