import bisect
import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from ayesha.feed.static_specs import assumed_fx_spec
from ayesha.models import Quote
from ayesha.news.calendar import NewsCalendar
from ayesha.scanner import Scanner
from ayesha.storage.db import Registry
from tests.helpers import synthetic

TF = timedelta(minutes=15)


class FakeFeed:
    def __init__(self, candles, equity, clock):
        self.c = candles
        self.times = [x.time for x in candles]
        self.equity = equity
        self.clock = clock

    def account(self):
        return {"equity": self.equity, "balance": self.equity, "margin_free": self.equity}

    def instrument(self, symbol):
        return replace(assumed_fx_spec(symbol, 1.08), source=f"MT5:{symbol}m")

    def _last(self):
        i = bisect.bisect_right(self.times, self.clock() - TF) - 1
        return self.c[i]

    def quote(self, symbol):
        last = self._last()
        return Quote(symbol, self.clock(), last.close, last.close + last.spread)

    def candles(self, symbol, tf, start, end):
        lo = bisect.bisect_left(self.times, start)
        hi = bisect.bisect_left(self.times, end)
        return self.c[lo:hi]  # may include the still-forming bar; scanner must drop it


class Recorder:
    channel = "test"

    def __init__(self):
        self.sent = []

    def send(self, rec):
        self.sent.append(rec["signal_id"])
        return True, "ok"


@pytest.fixture
def scan_spec(spec):
    s = copy.deepcopy(spec)
    s["pairs"]["enabled"] = ["EURUSD"]
    s["feed"]["warmup_days"] = 3
    s["delivery"]["notify_grades"] = ["A_PLUS", "WATCH"]
    return s


def _calendar(candles):
    return NewsCalendar([], candles[0].time - timedelta(days=1), candles[-1].time + timedelta(days=2))


def _drive(sc, candles, start_idx):
    for c in candles[start_idx:]:
        sc.clock_t[0] = c.time + TF + timedelta(seconds=5)
        sc.poll()


def _make(scan_spec, candles, reg, equity, notifier, warm_idx=400):
    t = [candles[warm_idx].time + timedelta(seconds=5)]
    feed = FakeFeed(candles, equity, lambda: t[0])
    sc = Scanner(feed, scan_spec, reg, [notifier], _calendar(candles), clock=lambda: t[0])
    sc.clock_t = t
    sc.warmup()
    return sc


def test_scanner_end_to_end_no_duplicates(scan_spec, tmp_path):
    candles = synthetic(6000)
    reg = Registry(tmp_path / "a.db")
    rec = Recorder()
    sc = _make(scan_spec, candles, reg, 100_000, rec)
    _drive(sc, candles, 401)
    rows = reg.db.execute("SELECT status, COUNT(*) n FROM signals GROUP BY status").fetchall()
    counts = {r["status"]: r["n"] for r in rows}
    assert sum(counts.values()) > 0, "expected candidates on synthetic data"
    assert rec.sent, "expected at least one READY alert at large equity"
    assert len(rec.sent) == len(set(rec.sent))
    notified = reg.db.execute("SELECT COUNT(*) FROM signal_events WHERE to_status='NOTIFIED'").fetchone()[0]
    assert notified == len(rec.sent)
    # every READY alert carried exact broker prices and a lot that fits the budget
    for sid in rec.sent:
        r = reg.get(sid)
        assert r["safe_lot"] > 0 and r["risk_usd"] <= 100_000 * 0.005 + 1e-6
        assert r["broker_prices"] and r["score_is_probability"] is False
    # lifecycle ran: nothing that is past expiry is still READY/NOTIFIED/WATCH
    end = sc.clock_t[0]
    for r in reg.active(("READY", "NOTIFIED", "WATCH")):
        assert datetime.fromisoformat(r["expires_at_utc"]) > end - TF

    # restart with the same database: warmup must not re-alert anything
    rec2 = Recorder()
    t = [end]
    sc2 = Scanner(FakeFeed(candles, 100_000, lambda: t[0]), scan_spec, reg, [rec2], _calendar(candles),
                  clock=lambda: t[0])
    sc2.warmup()
    sc2.poll()
    assert rec2.sent == []


def test_small_equity_is_no_trade(scan_spec, tmp_path):
    candles = synthetic(4000)
    reg = Registry(tmp_path / "b.db")
    rec = Recorder()
    sc = _make(scan_spec, candles, reg, 20, rec)
    _drive(sc, candles, 401)
    rows = reg.db.execute("SELECT payload FROM signals").fetchall()
    assert rows and rec.sent == []
    import json
    for r in rows:
        p = json.loads(r["payload"])
        assert p["status"] == "NO_TRADE" and p["safe_lot"] is None
        assert "MIN_LOT_EXCEEDS_RISK" in p["blockers"]


def test_no_calendar_strict_mode_blocks(scan_spec, tmp_path):
    candles = synthetic(4000)
    reg = Registry(tmp_path / "c.db")
    rec = Recorder()
    t = [candles[400].time + timedelta(seconds=5)]
    sc = Scanner(FakeFeed(candles, 100_000, lambda: t[0]), scan_spec, reg, [rec], None, clock=lambda: t[0])
    sc.clock_t = t
    sc.warmup()
    _drive(sc, candles, 401)
    import json
    payloads = [json.loads(r["payload"]) for r in reg.db.execute("SELECT payload FROM signals")]
    assert payloads and all("NEWS_UNVERIFIED" in p["blockers"] for p in payloads)
    assert rec.sent == []


def test_stale_feed_is_reported(scan_spec, tmp_path):
    candles = synthetic(600)
    reg = Registry(tmp_path / "d.db")
    sc = _make(scan_spec, candles, reg, 100_000, Recorder(), warm_idx=500)
    sc.clock_t[0] = candles[-1].time + timedelta(hours=2)  # no new bars for 2 hours on a weekday
    sc.poll()
    states = [r["state"] for r in reg.db.execute("SELECT state FROM engine_health")]
    assert "DATA_STALE" in states


def test_journal_losses_trigger_daily_pause(tmp_path):
    reg = Registry(tmp_path / "e.db")
    rec = {"signal_id": "a" * 16, "pair": "EURUSD", "direction": "BUY", "setup": "T", "grade": "WATCH",
           "status": "NOTIFIED", "strategy_version": "x", "strategy_hash": "y", "event_time_utc": "2025-03-03T09:00:00+00:00"}
    assert reg.insert_signal(rec)
    assert not reg.insert_signal(rec)  # idempotent
    reg.journal("PLACED", rec["signal_id"])
    assert reg.open_positions() == [("EURUSD", "BUY")]
    reg.journal("CLOSED", rec["signal_id"], -0.5)
    reg.journal("CLOSED", None, -0.4)
    losses, realized = reg.day_stats(datetime.now(timezone.utc) - timedelta(hours=1))
    assert losses == 2 and realized == pytest.approx(0.9)
    hist = [e["to_status"] for e in reg.events(rec["signal_id"])]
    assert hist == ["NOTIFIED", "USER_MARKED_PLACED", "USER_MARKED_CLOSED"]


def test_alert_text_has_no_account_data():
    from ayesha.delivery.notify import format_alert

    rec = {"direction": "BUY", "grade": "A_PLUS", "pair": "EURUSD", "session": ["LONDON"], "timeframe": "M15",
           "entry": 1.08, "stop_loss": 1.078, "take_profits": [1.086], "broker_prices": {"limit": 1.0801, "sl": 1.078,
           "tp": 1.086}, "safe_lot": 0.02, "risk_usd": 4.2, "net_rr": 2.8, "score_points": 88,
           "expires_at_utc": "2025-03-03T11:00:00+00:00", "signal_id": "abcdef0123456789"}
    txt = format_alert(rec)
    assert "A+ SETUP" in txt and "not a probability" in txt
    assert "equity" not in txt.lower() and "balance" not in txt.lower()
