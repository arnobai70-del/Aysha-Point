"""News Intelligence & Adaptive Capital acceptance tests (spec v1.0 section 6: N01-N12, C01-C10, I02).

Every test name starts with its acceptance id so docs/VERIFICATION.md can point at it.
All data here is synthetic and deterministic; none of it is evidence of trading performance.
"""

import copy
import json
import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from ayesha import broker
from ayesha import capital as capmod
from ayesha.delivery import push
from ayesha.models import AccountState, Candle
from ayesha.news import classify
from ayesha.news.analysis import pre_release_view, reaction, scenario_card
from ayesha.news.calendar import NewsCalendar, NewsEvent
from ayesha.news.ff_feed import FFCalendarSource, parse_ff
from ayesha.news.guard import NewsGuard
from ayesha.news.ledger import reconcile
from ayesha.risk.engine import RiskConfig, TradeProposal, evaluate
from ayesha.rules.mtf import Event
from ayesha.rules.strategy import Signal
from ayesha.storage.db import Registry
from tests.helpers import synthetic
from tests.test_scanner import FakeFeed, Scanner

E = datetime(2026, 10, 15, 12, 30, tzinfo=timezone.utc)  # a Thursday
M5 = timedelta(minutes=5)
COV = (datetime(2026, 10, 11, 4, tzinfo=timezone.utc), datetime(2026, 10, 18, 4, tzinfo=timezone.utc))
PIP = 0.0001
CODE = "ABCD-EFGH-JKMN-PQRS"


def ev(title="Retail Sales m/m", ccy="USD", impact="HIGH", t=E, **kw):
    return NewsEvent(t, ccy, impact, title, provider="TEST", **kw)


def cal(*events, fetched=E - timedelta(hours=2), cov=COV):
    return NewsCalendar(list(events), *cov, provider="TEST", fetched_at=fetched)


def series(start=E - timedelta(hours=3), n=60, price=1.08, rng=0.0004, spread=0.00008, spikes=None,
           spreads=None, missing=()):
    """Deterministic M5 bars: calm by default; spikes / spreads map bar index -> multiplier / spread."""
    out, p = [], price
    for i in range(n):
        if i in missing:
            continue
        r = rng * (spikes or {}).get(i, 1)
        o = p
        c = p + (r / 4 if i % 2 == 0 else -r / 4)
        out.append(Candle(start + i * M5, o, max(o, c) + r / 2, min(o, c) - r / 2, c, 100, (spreads or {}).get(i, spread)))
        p = c
    return out


def idx(t, start=E - timedelta(hours=3)):
    return int((t - start) / M5)


def fetcher(bars):
    return lambda a, b: [c for c in bars if a <= c.time < b]


@pytest.fixture(scope="module")
def guard(spec):
    return NewsGuard(spec)


# --- N01 event mapping, provenance, timezone ----------------------------------------------------

def test_n01_event_maps_to_both_currencies_and_global_usd(guard):
    cpi = ev("CPI m/m")
    assert {p for p in ("EURUSD", "USDJPY", "EURJPY", "GBPUSD", "AUDUSD", "USDCAD") if guard.relevant(cpi, p)} == \
        {"EURUSD", "USDJPY", "EURJPY", "GBPUSD", "AUDUSD", "USDCAD"}  # USD top data blocks every enabled pair
    retail = ev("Retail Sales m/m")  # ordinary USD high impact: only USD pairs
    assert guard.relevant(retail, "USDJPY") and not guard.relevant(retail, "EURJPY")
    zew = ev("German ZEW Economic Sentiment", "EUR")
    assert guard.relevant(zew, "EURUSD") and guard.relevant(zew, "EURJPY") and not guard.relevant(zew, "USDJPY")
    boj = ev("BOJ Policy Rate", "JPY")
    assert classify.tier(boj.title, boj.impact) == "CENTRAL_BANK"
    assert guard.relevant(boj, "USDJPY") and guard.relevant(boj, "EURJPY") and not guard.relevant(boj, "EURUSD")
    a = guard.assess("EURUSD", E - timedelta(minutes=10), cal(cpi))
    assert a.provider == "TEST" and a.verified_at == E - timedelta(hours=2) and a.event.event_id == cpi.event_id


def test_n01_forex_factory_times_are_converted_dst_safe():
    items = [{"title": "CPI m/m", "country": "USD", "date": "2026-10-15T08:30:00-04:00", "impact": "High",
              "forecast": "0.3%", "previous": "0.2%"},
             {"title": "CPI m/m", "country": "USD", "date": "2026-11-12T08:30:00-05:00", "impact": "High"},
             {"title": "no zone", "country": "USD", "date": "2026-10-15T08:30:00", "impact": "High"}]
    evs = parse_ff(items, E)
    assert [e.time.hour for e in evs] == [12, 13]  # EDT -> 12:30 UTC, EST -> 13:30 UTC; naive time skipped
    assert evs[0].forecast == "0.3%" and evs[0].fetched_at == E and evs[0].provider.startswith("FOREXFACTORY")
    assert parse_ff([{"title": "x", "country": "USD", "date": "2026-10-15T08:30:00Z", "impact": "weird"}])[0].impact == "HIGH"


# --- N02 windows, tiers, overlaps -------------------------------------------------------------

@pytest.mark.parametrize("title,before,after", [("Retail Sales m/m", 30, 30), ("CPI m/m", 45, 30),
                                                 ("Non-Farm Employment Change", 45, 30),
                                                 ("Federal Funds Rate", 45, 60), ("FOMC Press Conference", 45, 60)])
def test_n02_windows_by_tier(guard, title, before, after):
    c = cal(ev(title))
    assert guard.assess("EURUSD", E - timedelta(minutes=before + 1), c).phase == "UPCOMING"
    assert guard.assess("EURUSD", E - timedelta(minutes=before - 1), c).phase == "PRE_EVENT_LOCKOUT"
    assert guard.assess("EURUSD", E + timedelta(minutes=2), c).phase == "EVENT_LIVE"
    assert guard.assess("EURUSD", E + timedelta(minutes=after - 1), c).phase == "POST_EVENT_COOLDOWN"
    after_w = guard.assess("EURUSD", E + timedelta(minutes=after + 1), c)  # no market data => still blocked
    assert after_w.phase == "REACTION_WATCH" and "POST_NEWS_NOT_CONFIRMED" in after_w.reasons
    for t in (before - 1, 0):
        a = guard.assess("EURUSD", E - timedelta(minutes=t), c)
        assert a.status == "BLOCKED" and not a.allows_entry


def test_n02_overlapping_events_use_the_strictest_and_last_window(guard):
    c = cal(ev("CPI m/m"), ev("Retail Sales m/m", t=E + timedelta(minutes=45)))
    a = guard.assess("EURUSD", E + timedelta(minutes=20), c)  # CPI cooldown and Retail Sales lockout overlap
    assert a.phase == "PRE_EVENT_LOCKOUT" and a.event.title == "Retail Sales m/m"
    a2 = guard.assess("EURUSD", E + timedelta(minutes=50), c)
    assert a2.phase == "POST_EVENT_COOLDOWN" and a2.window[1] == E + timedelta(minutes=75)


def test_n02_tier_config_can_never_undercut_the_legacy_window(spec):
    s = copy.deepcopy(spec)
    s["news"]["tiers"]["HIGH"] = {"before": 5, "after": 5}
    s["news"]["tiers"]["TOP_DATA"] = {"before": 5, "after": 5}
    g = NewsGuard(s)
    assert g.window_minutes(ev("CPI m/m"))[1:] == (30, 30)
    assert g.assess("EURUSD", E - timedelta(minutes=29), cal(ev())).phase == "PRE_EVENT_LOCKOUT"


def test_n02_title_can_only_make_an_event_stricter():
    assert classify.tier("FOMC Statement", "MEDIUM") == "CENTRAL_BANK"
    assert classify.tier("Building Permits", "HIGH") == "HIGH"
    assert classify.tier("Something", "???") == "HIGH"


# --- N03 reschedule, cancellation, correction ------------------------------------------------------

def test_n03_moved_dropped_and_corrected_events_never_silently_clear(guard):
    cpi = ev("CPI m/m")
    led, evs = reconcile({}, [cpi], E - timedelta(hours=5), COV)
    assert [e.state for e in evs] == ["SCHEDULED"]
    moved = replace(cpi, time=E + timedelta(minutes=90))
    led, evs = reconcile(led, [moved], E - timedelta(hours=1), COV)
    states = {e.time: e.state for e in evs}
    assert states == {E: "CANCELLED_OR_MOVED", E + timedelta(minutes=90): "RESCHEDULED"}
    led, evs = reconcile(led, [moved], E - timedelta(minutes=30), COV)  # same data again: still flagged
    assert sorted(e.state for e in evs) == ["CANCELLED_OR_MOVED", "RESCHEDULED"]
    c = cal(*evs, fetched=E - timedelta(minutes=30))
    a = guard.assess("EURUSD", E - timedelta(minutes=10), c)  # old time still protected
    assert a.phase == "PRE_EVENT_LOCKOUT" and "EVENT_CANCELLED_OR_MOVED" in a.reasons
    assert not a.allows_entry
    a2 = guard.assess("EURUSD", E + timedelta(minutes=60), c)  # new time lockout
    assert a2.phase == "PRE_EVENT_LOCKOUT" and "EVENT_RESCHEDULED" in a2.reasons
    # dropped from the source entirely: ghost keeps blocking around the last known time
    led2, evs2 = reconcile(led, [], E - timedelta(minutes=20), COV)
    assert any(e.state == "CANCELLED_OR_MOVED" and e.time == E + timedelta(minutes=90) for e in evs2)
    # impact lowered by the source: the higher impact is kept
    led3, evs3 = reconcile({}, [cpi], E - timedelta(hours=3), COV)
    _, evs3 = reconcile(led3, [replace(cpi, impact="LOW")], E - timedelta(hours=2), COV)
    assert evs3[0].impact == "HIGH" and "impact lowered" in evs3[0].history[-1]
    # corrected figure after release: a fresh post-event window from the correction time
    rel = replace(cpi, actual="0.4%", actual_published_at=E)
    l4, _ = reconcile({}, [rel], E + timedelta(minutes=5), COV)
    _, evs4 = reconcile(l4, [replace(rel, actual="0.5%")], E + timedelta(minutes=70), COV)
    fix = [e for e in evs4 if e.state == "CORRECTED"]
    assert fix and fix[0].time == E + timedelta(minutes=70)
    a4 = guard.assess("EURUSD", E + timedelta(minutes=80), cal(*evs4, fetched=E + timedelta(minutes=70)))
    assert not a4.allows_entry and "EVENT_CORRECTED" in a4.reasons


# --- N04 missing / stale / corrupt / clock ------------------------------------------------------------

def test_n04_untrusted_calendar_is_news_unverified(guard, tmp_path):
    now = E - timedelta(hours=3)
    assert guard.assess("EURUSD", now, None).reasons == ["NEWS_SOURCE_MISSING"]
    for c, why in [(cal(ev(), fetched=now - timedelta(hours=25)), "NEWS_SOURCE_STALE"),
                   (cal(ev(), fetched=now + timedelta(minutes=30)), "NEWS_CLOCK_DRIFT"),
                   (cal(ev(), fetched=None), "NEWS_SOURCE_PROVENANCE_UNKNOWN"),
                   (cal(ev(), cov=(now + timedelta(hours=1), COV[1])), "NEWS_COVERAGE_GAP"),
                   (cal(ev(), cov=(COV[0], now + timedelta(minutes=30))), "NEWS_COVERAGE_GAP"),
                   (cal(ev(forecast="abc")), "NEWS_DATA_MALFORMED"),
                   (cal(ev(ccy="XYZ")), "NEWS_CURRENCY_MISSING"),
                   (cal(ev(state="CONFLICT")), "NEWS_CONFLICT")]:
        a = guard.assess("EURUSD", now + timedelta(hours=2, minutes=50) if why in (
            "NEWS_DATA_MALFORMED", "NEWS_CURRENCY_MISSING", "NEWS_CONFLICT") else now, c)
        assert a.phase == "NEWS_UNVERIFIED" and why in a.reasons and a.status == "UNKNOWN", why
    # corrupt cache file and no network: no calendar at all (=> NEWS_UNVERIFIED), never "no news"
    (tmp_path / "ff.json").write_text("{not json", encoding="utf-8")
    src = FFCalendarSource(tmp_path / "ff.json", fetch=lambda u: (_ for _ in ()).throw(OSError("offline")),
                           clock=lambda: now)
    assert src.calendar() is None


def test_n04_quote_from_the_future_is_clock_drift(spec, tmp_path):
    sc, sig, bar, _ = _ready_rig(spec, tmp_path)
    sc.feed.skew = timedelta(minutes=2)
    rec = sc._event(Event("SETUP", sig), bar)
    assert rec["status"] == "NO_TRADE" and "DATA_CLOCK_DRIFT" in rec["blockers"]


# --- N05 / N06 market stability after the window ---------------------------------------------------

def test_n05_medium_event_with_shock_or_extreme_spread_blocks(guard):
    c = cal(ev("Existing Home Sales", impact="MEDIUM"))
    assert guard.assess("EURUSD", E + timedelta(minutes=5), c).phase == "POST_EVENT_COOLDOWN"  # +-10 min
    i = idx(E)
    shock = series(spikes={i + 4: 5, i + 5: 5})  # 12:50 and 12:55, after the 10 minute window
    a = guard.assess("EURUSD", E + timedelta(minutes=31), c, m5=fetcher(shock), pip=PIP)
    assert a.phase == "REACTION_WATCH" and "VOLATILITY_UNSTABLE" in a.reasons
    wide = series(spreads={i + 4: 0.0004, i + 5: 0.0004})
    a2 = guard.assess("EURUSD", E + timedelta(minutes=31), c, m5=fetcher(wide), pip=PIP)
    assert "SPREAD_ABNORMAL" in a2.reasons and not a2.allows_entry
    calm = series()
    assert guard.assess("EURUSD", E + timedelta(minutes=31), c, m5=fetcher(calm), pip=PIP).phase == "CLEAR"
    # a LOW event is informational unless the market shows a shock around it
    low = cal(ev("Wholesale Inventories m/m", impact="LOW"))
    assert guard.assess("EURUSD", E + timedelta(minutes=12), low, m5=fetcher(calm), pip=PIP).phase == "CLEAR"
    spike = series(spikes={i: 6})
    lw = guard.assess("EURUSD", E + timedelta(minutes=12), low, m5=fetcher(spike), pip=PIP)
    assert lw.phase == "REACTION_WATCH" and "VOLATILITY_UNSTABLE" in lw.reasons


def test_n06_after_the_timer_the_market_must_settle(guard):
    c = cal(ev())  # HIGH 30/30: window ends 13:00
    i = idx(E)
    t = E + timedelta(minutes=40, seconds=30)  # 13:10:30: bars 13:00 and 13:05 closed after the window
    assert guard.assess("EURUSD", t, c, m5=fetcher(series()), pip=PIP).phase == "CLEAR"
    cases = {
        "SPREAD_ABNORMAL": series(spreads={i + 7: 0.0003}),
        "VOLATILITY_UNSTABLE": series(spikes={i + 7: 4}),
        "NEWS_DATA_GAP": series(missing=(i + 3,)),
        "NEWS_BASELINE_MISSING": series(start=E - timedelta(minutes=20), n=40),
    }
    for why, bars in cases.items():
        a = guard.assess("EURUSD", t, c, m5=fetcher(bars), pip=PIP)
        assert a.phase == "REACTION_WATCH" and why in a.reasons and not a.allows_entry, (why, a.reasons)
    # timer just ended: no closed M5 bar after the window yet
    a = guard.assess("EURUSD", E + timedelta(minutes=32), c, m5=fetcher(series()), pip=PIP)
    assert a.phase == "REACTION_WATCH" and "POST_NEWS_NOT_CONFIRMED" in a.reasons
    # the M5 feed stopped (last closed bar is old)
    a = guard.assess("EURUSD", t + timedelta(minutes=15), c, m5=fetcher(series(n=idx(E) + 8)), pip=PIP)
    assert "POST_NEWS_NOT_CONFIRMED" in a.reasons
    # a live quote with a wide spread also blocks
    a = guard.assess("EURUSD", t, c, m5=fetcher(series()), pip=PIP, quote_spread=0.0005)
    assert "SPREAD_ABNORMAL" in a.reasons
    # whipsaw (big moves both ways after the release) blocks for the whole reaction watch
    whip = series(spikes={i: 8, i + 1: 8})
    whip[i] = replace(whip[i], high=whip[i].open + 0.004, low=whip[i].open - 0.004)
    a = guard.assess("EURUSD", t, c, m5=fetcher(whip), pip=PIP)
    assert "VOLATILITY_UNSTABLE" in a.reasons
    # a shock bar late in the cooldown extends it: two calm bars after the window are not enough
    late = series(spikes={i + 5: 4})  # 12:55, closes 13:00
    a = guard.assess("EURUSD", t, c, m5=fetcher(late), pip=PIP)
    assert a.phase == "REACTION_WATCH" and "VOLATILITY_UNSTABLE" in a.reasons
    assert guard.assess("EURUSD", E + timedelta(minutes=61), c, m5=fetcher(late), pip=PIP).phase == "CLEAR"
    # unclosed bars are never used: a forming bar after `now` is ignored
    calm = series(n=70)
    assert guard.assess("EURUSD", t, c, m5=fetcher(calm), pip=PIP).phase == "CLEAR"


# --- N07 / N08 / N09 analysis is conditional and lookahead-free -------------------------------------

def test_n07_actual_is_invisible_before_publication():
    e = ev("CPI m/m", forecast="0.3%", previous="0.2%", actual="0.6%", actual_published_at=E, revised_previous="0.1%")
    v = pre_release_view(e)
    assert v.actual is None and v.revised_previous is None and v.actual_published_at is None
    card = scenario_card(e, "EURUSD")
    assert "0.6" not in json.dumps(card) and "actual" not in card and card["is_prediction"] is False
    before = reaction(e, "EURUSD", E - timedelta(minutes=1), series(), 0.0005)
    assert before["actual_verified"] is False and before["surprise"] is None
    after = reaction(e, "EURUSD", E + timedelta(minutes=20), series(), 0.0005)
    assert after["actual_verified"] and after["surprise"] == "ABOVE" and after["expected_pair_effect"] == "DOWN"
    no_time = reaction(replace(e, actual_published_at=None), "EURUSD", E + timedelta(hours=1), series(), 0.0005)
    assert no_time["actual_verified"] is False and "BLOCKED BY DATA" in no_time["actual_note"]


def test_n08_missing_or_conflicting_numbers_give_unknown_not_a_probability():
    for e in (ev("CPI m/m"), ev("CPI m/m", forecast="n/a?"), ev("Trade Balance", forecast="-60.1B")):
        card = scenario_card(e, "EURUSD")
        assert card["direction"] == "UNKNOWN" and card["scenarios"] == [] and card["probability"] is None
        assert "protection active" in card["summary"]
    r = reaction(ev("CPI m/m", actual="0.3%", actual_published_at=E), "EURUSD", E + timedelta(hours=1), series(), 0.0005)
    assert r["surprise"] is None and r["state"] in ("OBSERVED_ONLY", "UNAVAILABLE", "UNCLEAR")
    assert classify.parse_number("215K") == 215_000 and classify.parse_number("<0.1%") == 0.1
    with pytest.raises(classify.Malformed):
        classify.parse_number("abc")


def test_n09_usd_headline_gives_conditional_pair_scenarios_only(guard):
    e = ev("CPI m/m", forecast="0.3%", previous="0.2%")
    eu, uj, ej = (scenario_card(e, s) for s in ("EURUSD", "USDJPY", "EURJPY"))
    assert eu["scenarios"][0] == {"case": "ABOVE_FORECAST", "currency_effect": "STRONGER", "pair_effect": "DOWN"}
    assert uj["scenarios"][0]["pair_effect"] == "UP" and uj["scenarios"][2]["pair_effect"] == "DOWN"
    assert ej["scenarios"][0]["pair_effect"] == "UNKNOWN"  # USD not in the pair
    unemp = scenario_card(ev("Unemployment Rate", forecast="4.1%"), "EURUSD")
    assert unemp["scenarios"][0]["currency_effect"] == "WEAKER"
    for c in (eu, uj, ej):
        txt = json.dumps(c)
        assert "BUY" not in txt and "SELL" not in txt and c["is_prediction"] is False and "Not a prediction" in c["summary"]
    # whatever the scenario says, the guard blocks around the release
    assert not guard.assess("EURUSD", E - timedelta(minutes=5), cal(e)).allows_entry


# --- scanner rig for N10 / N11 / C / I02 -----------------------------------------------------------

class RigFeed(FakeFeed):
    """M15 bars for the strategy, M5 bars for news stability, owner-confirmed spec with margin."""

    def __init__(self, candles, m5, equity, clock):
        super().__init__(candles, equity, clock)
        self.m5 = m5
        self.skew = timedelta(0)
        self.spread = 0.00008

    def instrument(self, symbol):
        from ayesha.feed.static_specs import assumed_fx_spec
        return replace(assumed_fx_spec(symbol, 1.08), source=f"OWNER_CONFIRMED:EXNESS_STANDARD:{symbol}",
                       margin_per_lot=540.0)

    def quote(self, symbol):
        from ayesha.models import Quote
        p = self.m5[-1].close
        return Quote(symbol, self.clock() + self.skew, p, p + self.spread)

    def candles(self, symbol, tf, start, end):
        if tf == "M5":
            return [c for c in self.m5 if start <= c.time < end]
        return super().candles(symbol, tf, start, end)


class Bus:
    channel = "ntfy"
    archive_non_ready = True

    def __init__(self):
        self.n = push.NtfyNotifier(CODE, post=self._post)
        self.msgs = []

    def _post(self, url, data, headers):
        self.msgs.append(push.verify(CODE, data.decode()))
        return 200

    def send(self, rec):
        return self.n.send(rec)

    def news(self, notice, h=""):
        return self.n.news(notice, h)

    def heartbeat(self, *a, **kw):
        return self.n.heartbeat(*a, **kw)


def _ready_rig(spec, tmp_path, events=(), equity=100_000, now=E - timedelta(hours=3), capital="fresh"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    s = copy.deepcopy(spec)
    s["pairs"]["enabled"] = ["EURUSD"]
    s["feed"]["warmup_days"] = 2
    m15 = synthetic(400, start=now - timedelta(days=5))
    m5 = series(start=now - timedelta(hours=4), n=12 * 10)
    t = [now]
    feed = RigFeed(m15, m5, equity, lambda: t[0])
    bus = Bus()
    c = cal(*events, fetched=now - timedelta(minutes=30))
    sc = Scanner(feed, s, Registry(tmp_path / "r.db"), [bus], c, clock=lambda: t[0], capital=capital)
    sc.inst["EURUSD"] = feed.instrument("EURUSD")
    sc.state["EURUSD"] = "OK"
    sc.strats = {}
    sc.clock_t, sc.bus = t, bus
    bar = m15[-1]
    p = m5[-1].close
    sig = Signal("cafe000000000001", "EURUSD", "BUY", "SWEEP_MSS_FVG", 0, now - timedelta(seconds=5),
                 p - 0.0003, p - 0.0023, (p + 0.0060,), 0.00008, 0.0010, 90, "A_PLUS", 8, ["LONDON"], 1,
                 mtf={"H4": "UP", "H1": "UP", "M15": "PDL_SWEEP>CHOCH>FVG", "M5": "OFF"}, score_breakdown={"x": 90})
    return sc, sig, bar, bus


def test_c00_rig_produces_a_ready_when_everything_is_verified(spec, tmp_path):
    sc, sig, bar, bus = _ready_rig(spec, tmp_path)
    rec = sc._event(Event("SETUP", sig), bar)
    assert rec["status"] == "READY", rec["blockers"]
    assert rec["news_phase"] == "CLEAR" and rec["capital_status"] == "OK" and rec["safe_lot"] > 0


# --- N10 invalidation ---------------------------------------------------------------------------

def test_n10_ready_is_invalidated_when_a_new_event_appears(spec, tmp_path):
    now = E - timedelta(hours=3)
    sc, sig, bar, bus = _ready_rig(spec, tmp_path, now=now)
    rec = sc._event(Event("SETUP", sig), bar)
    assert rec["status"] == "READY"
    # the calendar refresh adds a surprise high-impact USD event 40 minutes from now
    surprise = ev("Fed Chair Powell Speaks", t=now + timedelta(minutes=40))
    sc.calendar_src = lambda: cal(surprise, fetched=now)
    sc.clock_t[0] = now + timedelta(minutes=1)
    sc.poll()
    after = sc.reg.get(sig.signal_id)
    assert after["status"] == "INVALIDATED"
    assert {"NEWS_LOCKOUT_BEFORE_EXPIRY", "NEWS_PRE_EVENT_LOCKOUT"} & set(after["blockers"])
    lines = [m.splitlines()[0] for m in bus.msgs if m.startswith("AYESHA BUY")]
    assert " ST=READY " in lines[0] and " ST=NO_TRADE " in lines[-1] and "INVALIDATED" in lines[-1]


def test_n10_expiry_is_capped_before_the_next_lockout(spec, tmp_path):
    now = E - timedelta(hours=3)
    sc, sig, bar, _ = _ready_rig(spec, tmp_path, events=[ev(t=now + timedelta(minutes=90))], now=now)
    rec = sc._event(Event("SETUP", sig), bar)
    assert rec["status"] == "READY" and rec["news_phase"] in ("CLEAR", "UPCOMING")
    assert datetime.fromisoformat(rec["expires_at_utc"]) == now + timedelta(minutes=60)  # lockout starts at -30
    sc2, sig2, bar2, _ = _ready_rig(spec, tmp_path / "b", events=[ev(t=now + timedelta(minutes=35))], now=now)
    rec2 = sc2._event(Event("SETUP", sig2), bar2)
    assert rec2["status"] == "NO_TRADE" and "NEWS_LOCKOUT_BEFORE_EXPIRY" in rec2["blockers"]


def test_n10_a_failed_push_is_rechecked_before_it_is_retried(spec, tmp_path):
    now = E - timedelta(hours=3)
    sc, sig, bar, bus = _ready_rig(spec, tmp_path, now=now)
    bus.send = lambda rec: (False, "URLError")  # network down: READY not delivered
    rec = sc._event(Event("SETUP", sig), bar)
    assert rec["status"] == "READY" and not bus.msgs
    sc.feed.spread = 0.0004  # 4 pips: abnormal now
    sc.clock_t[0] = now + timedelta(minutes=2)
    sc.retry_deliveries()
    assert sc.reg.get(sig.signal_id)["status"] == "INVALIDATED"
    assert "SPREAD_ABNORMAL" in sc.reg.get(sig.signal_id)["blockers"]


# --- N11 signed, distinct notifications -------------------------------------------------------------

def test_n11_news_watch_ready_and_heartbeat_are_signed_and_distinct(spec, tmp_path):
    now = E - timedelta(minutes=50)
    sc, sig, bar, bus = _ready_rig(spec, tmp_path, events=[ev("CPI m/m", forecast="0.3%", previous="0.2%")], now=now)
    sc.news_notices()
    sc.news_notices()  # once per phase only
    news = [m for m in bus.msgs if m and m.startswith("AYESHA NEWS")]
    assert len(news) == 1 and " PH=UPCOMING " in news[0] and " PAIRS=EURUSD " in news[0]
    assert "BUY" not in news[0] and "SELL" not in news[0] and "Not a trade signal" in news[0]
    assert "Scenario: Above forecast 0.3%" in news[0]
    sc.clock_t[0] = E - timedelta(minutes=40)
    sc.news_notices()
    sc.clock_t[0] = E + timedelta(minutes=1)
    sc.news_notices()
    sc.clock_t[0] = E + timedelta(minutes=31)
    sc.news_notices()  # window over, but no closed M5 bar after it yet: no summary yet
    assert " PH=RELEASED " in [m for m in bus.msgs if m.startswith("AYESHA NEWS")][-1]
    sc.clock_t[0] = E + timedelta(minutes=41)
    sc.news_notices()  # two calm closed bars after the window: the post-news summary goes out once
    sc.news_notices()
    phases = [m.split(" PH=")[1].split()[0] for m in bus.msgs if m and m.startswith("AYESHA NEWS")]
    assert phases == ["UPCOMING", "PRE_EVENT_LOCKOUT", "RELEASED", "WINDOW_END"]
    last = [m for m in bus.msgs if m.startswith("AYESHA NEWS")][-1]
    assert "Reaction:" in last and " SET=Y " in last and " RX=" in last
    assert " SET=NA " in [m for m in bus.msgs if m.startswith("AYESHA NEWS")][0]
    sc.heartbeat(force_state="OK")
    assert bus.msgs[-1].startswith("AYESHA HB") and " CAP=OK" in bus.msgs[-1]
    # every message on the relay verifies with the pairing code
    assert all(m is not None for m in bus.msgs)


# --- N12 offline source recovers; ledger is auditable and secret-free ----------------------------------

def test_n12_offline_news_source_recovers_and_ledger_is_auditable(tmp_path):
    clock = [E - timedelta(hours=10)]
    up = [True]
    items = [{"title": "CPI m/m", "country": "USD", "date": "2026-10-15T08:30:00-04:00", "impact": "High"}]

    def fetch(url):
        if not up[0]:
            raise OSError("offline")
        return json.dumps(items).encode()

    src = FFCalendarSource(tmp_path / "ff.json", fetch=fetch, clock=lambda: clock[0])
    assert src.calendar() is not None
    up[0] = False
    clock[0] += timedelta(hours=5)
    c = src.calendar()
    assert c is not None and c.fetched_at == E - timedelta(hours=10) and "offline" in src.last_error  # cache ok
    clock[0] += timedelta(hours=20)
    assert src.calendar() is None  # cache too old => NEWS_UNVERIFIED
    up[0] = True
    items[0]["date"] = "2026-10-15T10:00:00-04:00"  # moved while we were offline
    c = src.calendar()
    assert c is not None and {e.state for e in c.events} == {"RESCHEDULED", "CANCELLED_OR_MOVED"}
    led = json.loads((tmp_path / "news-ledger.json").read_text())
    rec = next(iter(led.values()))
    assert rec["previous_time"].startswith("2026-10-15T12:30") and any("time" in h for h in rec["history"])
    assert "token" not in json.dumps(led).lower()


# --- C01..C10 adaptive capital --------------------------------------------------------------------------

def _prop(stop_pips=20):
    return TradeProposal("EURUSD", "BUY", 1.0800, 1.0800 - stop_pips * PIP, (1.0800 + 3 * stop_pips * PIP,),
                         0.00008, 0.0015, 1, True, "CLEAR")


def _inst():
    from ayesha.feed.static_specs import assumed_fx_spec
    return replace(assumed_fx_spec("EURUSD", 1.08), source="OWNER_CONFIRMED:EXNESS_STANDARD:EURUSD", margin_per_lot=540.0)


def test_c01_budget_and_lot_follow_verified_equity_without_code_changes(tmp_path):
    book = capmod.CapitalBook(tmp_path / "capital.json", clock=lambda: E)
    lots = {}
    for eq in (25, 100, 500, 1000, 5000):
        snap = book.record(eq, reason="UPDATE")
        d = evaluate(_prop(), _inst(), AccountState(snap.equity_usd, free_margin_usd=snap.equity_usd), RiskConfig())
        assert d.nominal_budget_usd == pytest.approx(eq * 0.005)
        lots[eq] = d.lot
    assert lots[25] == 0 and lots[100] == 0  # 0.01 lot of a 20-pip stop risks ~$2.11
    assert 0 < lots[500] < lots[1000] < lots[5000]
    assert lots[1000] == pytest.approx(0.02) and lots[5000] == pytest.approx(0.11)
    assert [s.version for s in book.history()] == [1, 2, 3, 4, 5]
    # equity falls again: the lot falls with it, same percentage
    snap = book.record(400, reason="UPDATE")
    d = evaluate(_prop(), _inst(), AccountState(snap.equity_usd, free_margin_usd=400), RiskConfig())
    assert d.lot < lots[500] or d.lot == 0.0
    assert d.nominal_budget_usd == pytest.approx(2.0)


def test_c02_bad_stale_or_missing_capital_never_gives_ready(spec, tmp_path):
    book = capmod.CapitalBook(tmp_path / "c.json", clock=lambda: E)
    for bad in (-5, 0, float("nan"), float("inf"), "abc", "12.345"):
        with pytest.raises(capmod.CapitalError):
            book.record(bad)
    pol = spec["capital"]
    assert capmod.check(None, E, pol, "Standard").blockers == ["CAPITAL_UNVERIFIED"]
    s = book.record(500)
    assert capmod.check(s, E + timedelta(hours=11), pol, "Standard").ok
    assert capmod.check(s, E + timedelta(hours=13), pol, "Standard").blockers == ["POSITION_STATE_UNVERIFIED"]
    assert "CAPITAL_STALE" in capmod.check(s, E + timedelta(hours=25), pol, "Standard").blockers
    w = book.record(300, reason="WITHDRAWAL", amount=200)
    assert "CAPITAL_STALE" in capmod.check(w, E + timedelta(hours=5), pol, "Standard").blockers  # 4 h after a change
    assert "CAPITAL_MISMATCH" in capmod.check(w, E, pol, "Standard", compare_equity_usd=320).blockers
    assert "CAPITAL_CLOCK_DRIFT" in capmod.check(w, E - timedelta(hours=1), pol, "Standard").blockers
    # scanner: missing provider, unreadable file and stale snapshot all end as NO_TRADE
    for cap, why in [(None, "CAPITAL_UNVERIFIED"), (capmod.CapitalBook(tmp_path / "bad.json"), "CAPITAL_UNREADABLE"),
                     (capmod.static(replace(s, entered_at=E - timedelta(days=3), positions_confirmed_at=E - timedelta(days=3))),
                      "CAPITAL_STALE")]:
        (tmp_path / "bad.json").write_text("{oops", encoding="utf-8")
        sc, sig, bar, bus = _ready_rig(spec, tmp_path / why, capital=cap)
        rec = sc._event(Event("SETUP", sig), bar)
        assert rec["status"] == "NO_TRADE" and any(b.startswith(why) for b in rec["blockers"]), (why, rec["blockers"])
        assert not any(m.startswith("AYESHA BUY") and " ST=READY " in m for m in bus.msgs)


def test_c03_cent_and_standard_are_distinct_and_oanda_balance_is_never_used(spec, tmp_path):
    book = capmod.CapitalBook(tmp_path / "c.json", clock=lambda: E)
    cent = book.record(2500, account_type="StandardCent")
    assert cent.currency == "USC" and cent.equity_usd == 25.0
    bad = replace(cent, currency="USD")
    assert "CAPITAL_CURRENCY_MISMATCH" in capmod.check(bad, E, spec["capital"], "StandardCent").blockers
    assert "CAPITAL_ACCOUNT_TYPE_MISMATCH" in capmod.check(cent, E, spec["capital"], "Standard").blockers
    # the data feed reports $100,000 but the owner's Exness snapshot says $25: the snapshot sizes the trade
    sc, sig, bar, _ = _ready_rig(spec, tmp_path / "s", equity=100_000,
                                 capital=capmod.fresh(25, lambda: E - timedelta(hours=3)))
    rec = sc._event(Event("SETUP", sig), bar)
    assert rec["status"] == "NO_TRADE" and "MIN_LOT_EXCEEDS_RISK" in rec["blockers"]
    assert rec["capital_equity_usd"] == 25


def test_c04_broker_spec_is_per_symbol(tmp_path):
    p = tmp_path / "b.json"
    broker.save_confirmed("Standard", {"contract_size": 100000, "volume_min": 0.01, "volume_step": 0.01,
                                       "volume_max": 200, "typical_spread_pips": 0.9}, p, symbol="EURUSD")
    broker.save_leverage("Standard", 500, p)
    eu = broker.broker_spec("EURUSD", 1.0, "Standard", p, mid=1.08)
    gu = broker.broker_spec("GBPUSD", 1.0, "Standard", p, mid=1.27)
    assert eu.source.endswith(":EURUSD") and gu.source.startswith("ASSUMED") and gu.margin_per_lot is None
    assert eu.margin_per_lot == pytest.approx(100_000 * 1.08 / 200)  # 1:500 is checked at the 1:200 news cap
    assert broker.typical_spread_pips("EURUSD", "Standard", p) == 0.9
    assert broker.confirmed_symbols("Standard", p) == ["EURUSD"]
    # a 0.7.x file (one record typed from EURUSD) confirms EURUSD only
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"Standard": {"contract_size": 100000, "volume_min": 0.01, "volume_step": 0.01,
                                            "volume_max": 200, "confirmed_at_utc": "2026-10-15T00:00:00+00:00"}}))
    assert broker.load_confirmed("Standard", old, "EURUSD") and broker.load_confirmed("Standard", old, "USDJPY") is None
    d = evaluate(_prop(), gu, AccountState(10_000, free_margin_usd=10_000), RiskConfig())
    assert "BROKER_SPEC_UNVERIFIED" in d.blockers


def test_c05_lot_floors_hard_cap_holds_and_stop_is_never_moved(spec, tmp_path):
    big = RiskConfig(risk_per_trade_percent=1.5, max_risk_per_trade_percent=5.0)
    d = evaluate(_prop(), _inst(), AccountState(10_000, free_margin_usd=10_000), big)
    assert "CONFIG_RISK_ABOVE_CAP" in d.blockers and d.lot == 0
    d = evaluate(_prop(), _inst(), AccountState(1234.56, free_margin_usd=1234.56), RiskConfig())
    assert d.lot == math.floor(d.raw_lot * 100) / 100 and d.max_loss_usd <= d.risk_budget_usd + 1e-9
    sc, sig, bar, _ = _ready_rig(spec, tmp_path, capital=capmod.fresh(25, lambda: E - timedelta(hours=3)))
    rec = sc._event(Event("SETUP", sig), bar)
    assert rec["stop_loss"] == sig.stop and rec["entry"] == sig.entry  # never tightened to fit the min lot


def test_c06_positions_margin_exposure_and_daily_limits(spec, tmp_path):
    pol = spec["capital"]
    book = capmod.CapitalBook(tmp_path / "c.json", clock=lambda: E)
    s = book.record(1000, positions_confirmed=True)
    old = replace(s, positions_confirmed_at=E - timedelta(hours=13))
    assert "POSITION_STATE_UNVERIFIED" in capmod.check(old, E, pol, "Standard").blockers
    pos = book.record(1000, positions=[capmod.validate_position("gbpusd", "buy")])
    assert "MARGIN_UNVERIFIED" in capmod.check(pos, E, pol, "Standard").blockers
    pos2 = book.record(1000, positions=[capmod.validate_position("GBPUSD", "BUY")], free_margin=900)
    assert capmod.check(pos2, E, pol, "Standard").ok
    sc, sig, bar, _ = _ready_rig(spec, tmp_path / "s", capital=capmod.static(capmod.with_time(pos2, E - timedelta(hours=3))))
    acct = sc._account_state(sc.capital())
    assert acct.open_risk_usd == pytest.approx(10.0)  # unknown risk counts as the whole 1% open-risk cap
    rec = sc._event(Event("SETUP", sig), bar)
    assert rec["status"] == "NO_TRADE" and "OPEN_RISK_CAP" in rec["blockers"]
    assert "CORRELATED_EXPOSURE_USD" in rec["blockers"]  # GBPUSD long and EURUSD long are both short USD
    d = evaluate(_prop(), _inst(), AccountState(1000, free_margin_usd=1000, losses_today=2), RiskConfig())
    assert "DAILY_RISK_PAUSE" in d.blockers
    d = evaluate(_prop(), _inst(), AccountState(1000, free_margin_usd=1000, realized_loss_today_usd=25), RiskConfig())
    assert "DAILY_RISK_PAUSE" in d.blockers and d.lot == 0


def test_c06_open_trade_risk_needs_a_dollar_sign_so_a_lot_is_never_read_as_risk():
    from ayesha.cli import _parse_positions

    p = _parse_positions("EURUSD BUY $0.50, gbpusd sell, USDJPY SELL risk=1.2")
    assert [(x.symbol, x.direction, x.risk_usd) for x in p] == [("EURUSD", "BUY", 0.5), ("GBPUSD", "SELL", None),
                                                                ("USDJPY", "SELL", 1.2)]
    with pytest.raises(ValueError, match="lot size"):
        _parse_positions("EURUSD BUY 0.50")  # 0.50 lot would risk far more than $0.50
    for bad in ("EURUSD BUY $-1", "EURUSD BUY $nan", "EURUSD BUY $abc", "EURUSD", "EURUSD HOLD"):
        with pytest.raises((ValueError, capmod.CapitalError)):
            _parse_positions(bad)


def test_c07_min_lot_explanation_at_25_and_same_geometry_feasible_later():
    d25 = evaluate(_prop(), _inst(), AccountState(25, free_margin_usd=25), RiskConfig())
    assert d25.blockers == ["MIN_LOT_EXCEEDS_RISK"]
    assert d25.min_lot_loss_usd == pytest.approx(2.11, abs=0.01) and d25.min_lot_loss_percent == pytest.approx(8.44, abs=0.05)
    assert d25.risk_budget_usd == pytest.approx(0.125)
    d500 = evaluate(_prop(), _inst(), AccountState(500, free_margin_usd=500), RiskConfig())
    assert d500.ok and d500.lot == pytest.approx(0.01) and d500.max_loss_usd <= 2.5


def test_c08_deposits_are_not_trading_pnl(tmp_path):
    book = capmod.CapitalBook(tmp_path / "c.json", clock=lambda: E)
    book.record(25)
    book.record(125, reason="DEPOSIT", amount=100)
    book.record(100, reason="WITHDRAWAL", amount=25)
    assert book.cash_flows_usd() == pytest.approx(75)
    reg = Registry(tmp_path / "r.db")
    losses, realized = reg.day_stats(E - timedelta(days=1))
    assert (losses, realized) == (0, 0)  # capital changes never enter the trade journal
    with pytest.raises(capmod.CapitalError):
        book.record(100, reason="DEPOSIT", amount=0)


def _book_over_days(tmp_path, steps):
    """steps: (days after start, equity, reason, amount). Returns the book and the time of the last step."""
    t = [E - timedelta(days=6)]
    book = capmod.CapitalBook(tmp_path / "c.json", clock=lambda: t[0])
    for days, eq, reason, amount in steps:
        t[0] = E - timedelta(days=6) + timedelta(days=days)
        book.record(eq, reason=reason, amount=amount)
    return book, t[0]


def test_b4_weekly_drawdown_excludes_cash_flows_and_is_only_a_warning(spec, tmp_path):
    book, now = _book_over_days(tmp_path, [(0, 25, "UPDATE", 0), (2, 24, "UPDATE", 0),
                                           (3, 524, "DEPOSIT", 500), (5, 520, "UPDATE", 0)])
    ch = capmod.trading_change(book.history(), now)
    assert ch["net_cash_flow_usd"] == 500 and ch["trading_change_usd"] == -5
    assert ch["drawdown_percent"] == pytest.approx(20.0)  # (25 - 20) / 25, not "+2,000 %" growth
    policy = spec["capital"]
    w = capmod.warnings(book.history(), now, policy)
    assert any(x.startswith("WEEKLY_DRAWDOWN_WARNING") for x in w)
    c = capmod.check(book.latest(), now, policy, "Standard")
    assert c.ok, "a warning never blocks, and never loosens, a hard gate"
    # a withdrawal is not a loss either
    book2, now2 = _book_over_days(tmp_path / "w", [(0, 500, "UPDATE", 0), (4, 200, "WITHDRAWAL", 300)])
    ch2 = capmod.trading_change(book2.history(), now2)
    assert ch2["trading_change_usd"] == 0 and ch2["drawdown_percent"] == 0
    assert not capmod.warnings(book2.history(), now2, policy)
    # the window is 7 days: an older fall no longer warns
    assert not any(x.startswith("WEEKLY") for x in capmod.warnings(book.history(), now + timedelta(days=9), policy))


def test_b4_confirmation_expiry_warning_before_it_goes_stale(spec, tmp_path):
    book = capmod.CapitalBook(tmp_path / "c.json", clock=lambda: E)
    book.record(100, positions=[])
    policy = spec["capital"]
    assert not capmod.warnings(book.history(), E + timedelta(hours=9), policy)
    w = capmod.warnings(book.history(), E + timedelta(hours=10.5), policy)
    assert w and w[0].startswith("POSITIONS_CONFIRMATION_EXPIRES_SOON")
    w = capmod.warnings(book.history(), E + timedelta(hours=22.5), policy)
    assert any(x.startswith("CAPITAL_EXPIRES_SOON") for x in w)
    late = E + timedelta(hours=25)
    assert not any("EXPIRES_SOON" in x for x in capmod.warnings(book.history(), late, policy))
    assert "CAPITAL_STALE" in capmod.check(book.latest(), late, policy, "Standard").blockers


def test_b5_capital_history_shows_snapshots_change_journal_and_warnings(spec, tmp_path, capsys, monkeypatch):
    from ayesha import cli

    t = [datetime.now(timezone.utc) - timedelta(days=5)]
    book = capmod.CapitalBook(tmp_path / "capital.json", clock=lambda: t[0])
    book.record(25)
    t[0] += timedelta(days=2)
    book.record(524, reason="DEPOSIT", amount=500)
    t[0] += timedelta(days=2)
    book.record(500)
    reg = Registry(tmp_path / "ayesha.db")
    reg.journal("CLOSED", None, -1.25)
    rc = cli.main(["capital", "--history", "--file", str(tmp_path / "capital.json"), "--db", str(tmp_path / "ayesha.db")])
    out = capsys.readouterr().out
    assert rc == 0 and "DEPOSIT" in out and "+500.00 USD" in out and "INITIAL" in out
    assert "deposits/withdrawals excluded: 25.00 -> 500.00 USD (cash flow +500.00)" in out
    assert "1 closed, 1 losses, realized -1.25 USD" in out and "never backtest numbers" in out
    assert "WARNING WEEKLY_DRAWDOWN_WARNING" in out and "2 losses or 2% loss per day" in out


def test_c09_capital_updates_reach_the_scanner_and_never_the_relay(spec, tmp_path):
    t0 = E - timedelta(hours=3)
    book = capmod.CapitalBook(tmp_path / "capital.json", clock=lambda: t0)
    book.record(25)
    sc, sig, bar, bus = _ready_rig(spec, tmp_path / "s", capital=book)
    assert sc._event(Event("SETUP", sig), bar)["status"] == "NO_TRADE"
    book.record(100_000.00, reason="DEPOSIT", amount=99_975)  # another window: `ayesha capital`
    sig2 = replace(sig, signal_id="cafe000000000002")
    rec = sc._event(Event("SETUP", sig2), bar)
    assert rec["status"] == "READY" and rec["capital_snapshot_version"] == 2
    body = [m for m in bus.msgs if m.startswith("AYESHA BUY") and " ST=READY " in m][0]
    assert "100000" not in body and "99975" not in body and " CAPH=" + capmod.digest(CODE, 100_000) in body
    assert capmod.digest(CODE, 100_000) != capmod.digest(CODE, 100_000.01)
    assert json.loads((tmp_path / "capital.json").read_text())["history"][-1]["reason"] == "DEPOSIT"


def test_c10_news_and_scores_never_bypass_capital_or_daily_rules(spec, tmp_path):
    sc, sig, bar, _ = _ready_rig(spec, tmp_path)
    sc.reg.journal("CLOSED", None, -600)
    sc.reg.journal("CLOSED", None, -700)  # two losses today
    hi = replace(sig, score=100, grade="A_PLUS")
    rec = sc._event(Event("SETUP", hi), bar)
    assert rec["status"] == "NO_TRADE" and "DAILY_RISK_PAUSE" in rec["blockers"] and rec["news_phase"] == "CLEAR"
    d = evaluate(_prop(), _inst(), AccountState(1000, free_margin_usd=1000, realized_loss_today_usd=float("nan")),
                 RiskConfig())
    assert "ACCOUNT_STATE_INVALID" in d.blockers and not d.ok


# --- I02 integration: event -> block -> stabilisation -> risk -> signed phone explanation ------------------

def _assert_matches_schema(rec):
    """The PC record and contracts/signal.schema.json stay aligned (no silent protocol change)."""
    from pathlib import Path

    schema = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "signal.schema.json").read_text(encoding="utf-8"))
    props = schema["properties"]
    assert set(schema["required"]) <= set(rec), set(schema["required"]) - set(rec)
    assert set(rec) <= set(props), f"fields missing from the schema: {sorted(set(rec) - set(props))}"
    assert rec["schema_version"] in props["schema_version"]["enum"]
    for k, v in rec.items():
        if "enum" in props[k] and not isinstance(v, (list, dict)):
            assert v in props[k]["enum"], (k, v)


def test_i02_event_block_stabilise_then_signed_ready(spec, tmp_path):
    cpi = ev("CPI m/m", forecast="0.3%", previous="0.2%")
    start = E - timedelta(minutes=40)
    sc, sig, bar, bus = _ready_rig(spec, tmp_path, events=[cpi], now=start)
    sc.feed.m5 = series(start=E - timedelta(hours=3), n=12 * 5)
    rec = sc._event(Event("SETUP", sig), bar)
    assert rec["status"] == "NO_TRADE" and rec["news_phase"] == "PRE_EVENT_LOCKOUT"
    assert rec["news_event"]["title"] == "CPI m/m" and rec["news_scenario"]["direction"] == "CONDITIONAL"
    assert rec["news_affected_currencies"] == ["USD"] and rec["capital_warnings"] == []
    _assert_matches_schema(rec)
    later = E + timedelta(minutes=45, seconds=10)
    sc.clock_t[0] = later
    sig2 = replace(sig, signal_id="cafe000000000003", bar_close_utc=later - timedelta(seconds=5))
    rec2 = sc._event(Event("SETUP", sig2), bar)
    assert rec2["status"] == "READY", rec2["blockers"]
    assert rec2["news_phase"] == "CLEAR" and rec2["news_reaction"]["is_permission"] is False
    _assert_matches_schema(rec2)
    line = [m for m in bus.msgs if m.startswith("AYESHA BUY") and " ST=READY " in m][0].splitlines()[0]
    assert " WF=4 " in line and " NP=CLEAR " in line and " SPEC=OWNER " in line and " CAPH=" in line
    # no order is ever sent: scripts/check_no_order_api.py (test_repo_has_no_order_api) scans every source file
