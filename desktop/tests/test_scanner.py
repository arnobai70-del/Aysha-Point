import bisect
import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from ayesha import capital as capmod
from ayesha.feed.static_specs import assumed_fx_spec
from ayesha.models import Quote
from ayesha.news.calendar import NewsCalendar
from ayesha.scanner import Scanner as _Scanner
from ayesha.storage.db import Registry
from tests.helpers import synthetic

TF = timedelta(minutes=15)


def Scanner(feed, spec, reg, notifiers, cal=None, clock=None, capital="fresh"):  # noqa: N802
    """Test wrapper: the owner confirmed capital and positions just now, and the calendar file is fresh."""
    if capital == "fresh":
        capital = capmod.fresh(feed.equity, clock)
    src = cal
    if isinstance(cal, NewsCalendar):
        def src():
            return NewsCalendar(cal.events, *cal.coverage, provider="TEST", fetched_at=clock())
    return _Scanner(feed, spec, reg, notifiers, src, clock=clock, capital=capital)


class FakeFeed:
    def __init__(self, candles, equity, clock):
        self.c = candles
        self.times = [x.time for x in candles]
        self.equity = equity
        self.clock = clock

    def account(self):
        return {"equity": self.equity, "balance": self.equity, "margin_free": self.equity}

    def instrument(self, symbol):
        return replace(assumed_fx_spec(symbol, 1.08), source=f"MT5:{symbol}m", margin_per_lot=540.0)

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


# --- v0.7.0: hard READY guard, delivery retry, M5 confirmation upgrade ------------------------

def test_ready_guard_holds_even_with_strict_news_off(scan_spec, tmp_path):
    """Config can be loosened by mistake; READY must still be impossible without a CLEAR news check."""
    import json
    s = copy.deepcopy(scan_spec)
    s["risk"]["strict_news"] = False
    candles = synthetic(4000)
    reg = Registry(tmp_path / "g.db")
    rec = Recorder()
    t = [candles[400].time + timedelta(seconds=5)]
    sc = Scanner(FakeFeed(candles, 100_000, lambda: t[0]), s, reg, [rec], None, clock=lambda: t[0])
    sc.clock_t = t
    sc.warmup()
    _drive(sc, candles, 401)
    payloads = [json.loads(r["payload"]) for r in reg.db.execute("SELECT payload FROM signals")]
    assert payloads and rec.sent == []
    assert all(p["status"] != "READY" for p in payloads)
    # no calendar: the news guard blocks before the READY guard is even reached, strict_news or not
    assert all("NEWS_UNVERIFIED" in p["blockers"] and "NEWS_SOURCE_MISSING" in p["blockers"] for p in payloads)


class AssumedSpecFeed(FakeFeed):
    def instrument(self, symbol):
        return replace(assumed_fx_spec(symbol, 1.08), margin_per_lot=540.0)  # ASSUMED_* source: not verified


def test_ready_guard_blocks_unverified_contract(scan_spec, tmp_path):
    import json
    candles = synthetic(4000)
    reg = Registry(tmp_path / "h.db")
    rec = Recorder()
    t = [candles[400].time + timedelta(seconds=5)]
    sc = Scanner(AssumedSpecFeed(candles, 100_000, lambda: t[0]), scan_spec, reg, [rec], _calendar(candles),
                 clock=lambda: t[0])
    sc.clock_t = t
    sc.warmup()
    _drive(sc, candles, 401)
    payloads = [json.loads(r["payload"]) for r in reg.db.execute("SELECT payload FROM signals")]
    assert payloads and rec.sent == []
    assert all(p["status"] != "READY" for p in payloads)


class Flaky(Recorder):
    """Fails the first `fail` sends (network down), then works."""
    channel = "ntfy"
    archive_non_ready = False

    def __init__(self, fail):
        super().__init__()
        self.fail = fail
        self.attempts = 0

    def send(self, rec):
        self.attempts += 1
        if self.attempts <= self.fail:
            return False, "URLError"
        return super().send(rec)


def test_failed_ready_push_is_retried_once_delivered(scan_spec, tmp_path):
    candles = synthetic(6000)
    reg = Registry(tmp_path / "i.db")
    fl = Flaky(fail=2)
    sc = _make(scan_spec, candles, reg, 100_000, fl)
    _drive(sc, candles, 401)
    assert fl.sent, "the READY alert must arrive after the network comes back"
    assert len(fl.sent) == len(set(fl.sent)), "never delivered twice"
    first = fl.sent[0]
    assert reg.was_delivered(first, "ntfy", "READY")
    hist = [e["to_status"] for e in reg.events(first)]
    assert hist.count("NOTIFIED") == 1


class M5Feed(FakeFeed):
    def _last(self):
        i = bisect.bisect_right(self.times, self.clock() - timedelta(minutes=5)) - 1
        return self.c[i]


class Archive(Recorder):
    channel = "ntfy"
    archive_non_ready = True

    def send(self, rec):
        self.sent.append((rec["signal_id"], rec["status"], rec.get("entry_type")))
        return True, "ok"


def test_m5_confirmation_upgrades_watch_to_ready_without_duplicates(scan_spec, tmp_path):
    import json
    s = copy.deepcopy(scan_spec)
    s["mtf"]["confirm_timeframe"] = "M5"
    candles = synthetic(24000, minutes=5, vol=0.00035, seed=5)
    reg = Registry(tmp_path / "m5.db")
    ar = Archive()
    t = [candles[1200].time + timedelta(seconds=5)]
    sc = Scanner(M5Feed(candles, 100_000, lambda: t[0]), s, reg, [ar], _calendar(candles), clock=lambda: t[0])
    assert sc.tf_name == "M5" and sc.setup_tf_name == "M15"
    sc.warmup()
    for c in candles[1201:]:
        t[0] = c.time + timedelta(minutes=5, seconds=5)
        sc.poll()
    rows = [json.loads(r["payload"]) | {"_st": r["status"]} for r in reg.db.execute("SELECT payload, status FROM signals")]
    assert rows
    by_id: dict[str, list] = {}
    for sid, st, et in ar.sent:
        by_id.setdefault(sid, []).append((st, et))
    # a READY push only ever follows a WATCH_M5 push of the same id, and comes at most once
    readies = [sid for sid, st, _ in ar.sent if st == "READY"]
    assert len(readies) == len(set(readies))
    for sid in readies:
        seq = [x[0] for x in by_id[sid]]
        assert seq.index("WATCH_M5") < seq.index("READY")
        assert ("READY", "MARKET_AFTER_M5_CONFIRMATION") in by_id[sid]
        hist = [e["to_status"] for e in reg.events(sid)]
        assert hist[0] == "WATCH_M5" and "READY" in hist
    # nothing became READY at setup time while confirmation is required
    for sid, seq in by_id.items():
        assert seq[0][0] != "READY"
    watch_m5 = [r for r in rows if any(e["to_status"] == "WATCH_M5" for e in reg.events(r["signal_id"]))]
    assert watch_m5, "expected setups waiting for M5 confirmation"
    assert {r["_st"] for r in watch_m5} - {"WATCH_M5"}, "some setups must resolve (confirmed or failed)"


def test_confirmed_event_upgrades_record_and_pushes_ready_once(scan_spec, tmp_path):
    """Deterministic path: SETUP (needs M5) -> WATCH_M5 archive push; CONFIRMED -> READY push; repeat -> nothing."""
    from ayesha.rules.mtf import Event
    from ayesha.rules.strategy import Signal

    s = copy.deepcopy(scan_spec)
    s["mtf"]["confirm_timeframe"] = "M5"
    candles = synthetic(2000, minutes=5, vol=0.00035, seed=5)
    reg = Registry(tmp_path / "u.db")
    ar = Archive()
    t = [candles[1500].time + timedelta(minutes=5, seconds=5)]
    sc = Scanner(M5Feed(candles, 100_000, lambda: t[0]), s, reg, [ar], _calendar(candles), clock=lambda: t[0])
    sc.warmup()
    bar = candles[1500]
    p = bar.close
    sig = Signal("feedc0de00000001", "EURUSD", "BUY", "SWEEP_MSS_FVG", 0, bar.time + timedelta(minutes=5),
                 p - 0.0003, p - 0.0023, (p + 0.0060,), 0.00008, 0.0010, 90, "A_PLUS", 8, ["LONDON"], 1,
                 mtf={"H4": "UP", "H1": "UP", "H1_ZONE": "DISCOUNT", "M15": "PDL_SWEEP>CHOCH>FVG", "M5": "PENDING"},
                 score_breakdown={"x": 85})
    rec = sc._event(Event("SETUP", sig, needs_confirmation=True), bar)
    assert rec["status"] == "WATCH_M5" and reg.get(sig.signal_id)["status"] == "WATCH_M5"
    assert ar.sent == [(sig.signal_id, "WATCH_M5", "LIMIT_AT_FVG")]
    conf = replace(sig, entry=p, mtf=dict(sig.mtf, M5="CONFIRMED_UP"))
    out = sc._event(Event("CONFIRMED", conf), bar)
    assert out["status"] == "READY", out["blockers"]
    if out["status"] == "READY":
        assert ar.sent[-1] == (sig.signal_id, "READY", "MARKET_AFTER_M5_CONFIRMATION")
        assert reg.get(sig.signal_id)["status"] == "NOTIFIED"
        exp = datetime.fromisoformat(out["expires_at_utc"])
        assert exp <= conf.bar_close_utc + timedelta(minutes=15)
    else:
        assert any(b.startswith("READY_GUARD") or b for b in out["blockers"])
    n = len(ar.sent)
    assert sc._event(Event("CONFIRMED", conf), bar) is None  # not WATCH_M5 any more
    sc.retry_deliveries()
    assert len(ar.sent) == n, "already delivered READY is never re-sent"
    hist = [e["to_status"] for e in reg.events(sig.signal_id)]
    assert hist[0] == "WATCH_M5"


def test_confirm_failed_is_archived_not_alerted(scan_spec, tmp_path):
    from ayesha.rules.mtf import Event
    from ayesha.rules.strategy import Signal

    s = copy.deepcopy(scan_spec)
    s["mtf"]["confirm_timeframe"] = "M5"
    candles = synthetic(2000, minutes=5, vol=0.00035, seed=5)
    reg = Registry(tmp_path / "f.db")
    ar = Archive()
    t = [candles[1500].time + timedelta(minutes=5, seconds=5)]
    sc = Scanner(M5Feed(candles, 100_000, lambda: t[0]), s, reg, [ar], _calendar(candles), clock=lambda: t[0])
    sc.warmup()
    bar = candles[1500]
    p = bar.close
    sig = Signal("feedc0de00000002", "EURUSD", "SELL", "SWEEP_MSS_FVG", 0, bar.time + timedelta(minutes=5),
                 p + 0.0003, p + 0.0023, (p - 0.0060,), 0.00008, 0.0010, 90, "A_PLUS", 8, ["LONDON"], -1,
                 score_breakdown={"x": 85})
    sc._event(Event("SETUP", sig, needs_confirmation=True), bar)
    out = sc._event(Event("CONFIRM_FAILED", sig, "NO_M5_CONFIRMATION"), bar)
    assert out["status"] == "CONFIRM_FAILED" and "NO_M5_CONFIRMATION" in out["blockers"]
    assert [x[1] for x in ar.sent] == ["WATCH_M5", "CONFIRM_FAILED"]
    from ayesha.delivery.push import format_push
    assert " ST=NO_TRADE " in format_push(out)
