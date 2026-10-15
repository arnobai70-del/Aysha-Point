"""Live PC scanner (master spec sections M, Q, X). Advisory only.

Loop: for each enabled pair, read newly CLOSED base bars (M15, or M5 when M5 confirmation is
on), run the multi-timeframe engine, apply the risk engine with live account/quote/news state,
persist every candidate (READY / WATCH / WATCH_M5 / NO_TRADE / CONFIRM_FAILED), alert once per
READY signal, and track lifecycle (EXPIRED / MISSED / ENTRY_TOUCHED / OBSERVED_TP / OBSERVED_SL).
Observations are market observations, not broker fills.

READY is additionally guarded by `_ready_guard`, independent of configuration: it needs a
CLEAR news check, a verified contract spec, a fresh quote, fresh data, a lot > 0 and no
blockers. Anything else is NO_TRADE with a READY_GUARD:<reason> blocker.
"""

from __future__ import annotations

import time as _time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from ayesha.broker import is_verified_source
from ayesha.models import AccountState, Candle, InstrumentSpec, Quote
from ayesha.news.calendar import NewsCalendar
from ayesha.risk.engine import RiskConfig, RiskDecision, TradeProposal, broker_order_prices, evaluate
from ayesha.rules.mtf import Event, MtfEngine, check_scalp
from ayesha.rules.strategy import TF_MINUTES, Signal
from ayesha.sessions import SessionEngine
from ayesha.storage.db import Registry

ACTIVE = ("READY", "NOTIFIED", "WATCH", "ENTRY_TOUCHED", "WATCH_M5")
CONFIRMED_EXPIRY_BARS = 3  # a confirmed (market) entry is only valid for a few base bars


class Feed(Protocol):
    def account(self) -> dict[str, Any]: ...
    def instrument(self, symbol: str) -> InstrumentSpec: ...
    def quote(self, symbol: str) -> Quote: ...
    def candles(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[Candle]: ...


class Scanner:
    def __init__(self, feed: Feed, spec: dict[str, Any], registry: Registry, notifiers: list,
                 calendar: NewsCalendar | None = None, clock: Callable[[], datetime] | None = None) -> None:
        self.feed, self.spec, self.reg, self.notifiers, self.calendar = feed, spec, registry, notifiers, calendar
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.cfg = RiskConfig.from_spec(spec)
        self.sessions = SessionEngine(spec)
        check_scalp(spec)
        self.setup_tf_name = spec["entry"]["setup_timeframe"]
        self.setup_tf = timedelta(minutes=TF_MINUTES[self.setup_tf_name])
        self.confirm_tf = (spec.get("mtf") or {}).get("confirm_timeframe") or None
        self.tf_name = self.confirm_tf or self.setup_tf_name  # base bars the engine is fed
        self.tf = timedelta(minutes=TF_MINUTES[self.tf_name])
        self.pairs = [p.upper() for p in spec["pairs"]["enabled"]]
        self.strats: dict[str, MtfEngine] = {}
        self.last_bar: dict[str, datetime] = {}
        self.inst: dict[str, InstrumentSpec] = {}
        self.notify_grades = set(spec.get("delivery", {}).get("notify_grades", ["A_PLUS"]))
        self.state: dict[str, str] = {}  # pair -> OK | DATA_STALE | FEED_OFFLINE
        self.heartbeat_seconds = float(spec.get("delivery", {}).get("heartbeat_seconds", 300))
        self._last_hb: datetime | None = None
        self._last_overall = ""

    # --- setup -----------------------------------------------------------------------------
    def warmup(self) -> None:
        now = self.clock()
        start = now - timedelta(days=self.spec["feed"]["warmup_days"])
        for sym in self.pairs:
            try:
                self.inst[sym] = self.feed.instrument(sym)
                strat = MtfEngine(sym, self.spec)
                bars = self._closed(self.feed.candles(sym, self.tf_name, start, now), now)
                for c in bars:
                    for ev in strat.on_bar(c):
                        if ev.signal.bar_close_utc >= now - self.tf:  # just closed: still actionable
                            self._event(ev, c)
                    self._lifecycle(sym, c)
                self.strats[sym] = strat
                self.last_bar[sym] = bars[-1].time if bars else start
                self.reg.health("WARMED_UP", sym, f"{len(bars)} bars")
                self.state[sym] = "OK"
            except Exception as e:
                self.reg.health("FEED_OFFLINE", sym, f"warmup: {type(e).__name__}: {e}")
                self.state[sym] = "FEED_OFFLINE"

    def _closed(self, bars: list[Candle], now: datetime) -> list[Candle]:
        return [b for b in bars if b.time + self.tf <= now]

    # --- loop ------------------------------------------------------------------------------
    def poll(self) -> int:
        """One pass over all pairs. Returns the number of new closed bars processed."""
        now = self.clock()
        n = 0
        for sym, strat in self.strats.items():
            try:
                bars = self._closed(self.feed.candles(sym, self.tf_name, self.last_bar[sym] + self.tf, now), now)
                bars = [b for b in bars if b.time > self.last_bar[sym]]
                for c in bars:
                    for ev in strat.on_bar(c):
                        self._event(ev, c)
                    self._lifecycle(sym, c)
                    self.last_bar[sym] = c.time
                    n += 1
                stale = self.spec["feed"]["stale_after_bars"]
                if self.sessions.market_open(now) and now - (self.last_bar[sym] + self.tf) > stale * self.tf:
                    self.reg.health("DATA_STALE", sym, f"last closed bar {self.last_bar[sym].isoformat()}")
                    self.state[sym] = "DATA_STALE"
                else:
                    self.state[sym] = "OK"
            except Exception as e:
                self.reg.health("FEED_OFFLINE", sym, f"{type(e).__name__}: {e}")
                self.state[sym] = "FEED_OFFLINE"
        self.retry_deliveries()
        self.heartbeat()
        return n

    def retry_deliveries(self) -> None:
        """A READY alert whose push failed (network down) is re-sent on later polls until it expires.
        Channels that already received it are skipped, so nothing is sent twice."""
        now = self.clock()
        for rec in self.reg.active(("READY", "NOTIFIED")):
            if rec is None or datetime.fromisoformat(rec["expires_at_utc"]) <= now:
                continue
            self._deliver(rec)

    def overall_state(self) -> str:
        vals = [self.state.get(p, "FEED_OFFLINE") for p in self.pairs]
        for s in ("FEED_OFFLINE", "DATA_STALE"):
            if s in vals:
                return s
        return "OK"

    def heartbeat(self, force_state: str | None = None) -> None:
        """Tell heartbeat-capable channels (the phone) that the PC is alive and whether data is fresh.
        Sent every `heartbeat_seconds` and immediately when the overall state changes."""
        now = self.clock()
        state = force_state or self.overall_state()
        due = self._last_hb is None or (now - self._last_hb).total_seconds() >= self.heartbeat_seconds
        if not (due or state != self._last_overall or force_state):
            return
        for n in self.notifiers:
            hb = getattr(n, "heartbeat", None)
            if hb is None:
                continue
            try:
                hb(int(now.timestamp() * 1000), state, len(self.pairs), self.spec["strategy_hash"])
            except Exception:
                pass
        self._last_hb, self._last_overall = now, state

    def run(self, poll_seconds: float | None = None, max_loops: int | None = None) -> None:
        poll_seconds = poll_seconds or self.spec["feed"]["poll_seconds"]
        self.warmup()
        loops = 0
        try:
            while max_loops is None or loops < max_loops:
                self.poll()
                loops += 1
                if max_loops is None or loops < max_loops:
                    _time.sleep(poll_seconds)
        finally:
            if max_loops is None:
                self.heartbeat(force_state="STOPPED")  # phone shows "PC scanner stopped" at once

    # --- signal handling -------------------------------------------------------------------
    def _account_state(self) -> AccountState:
        a = self.feed.account()
        losses, realized = self.reg.day_stats(self.sessions.trading_day(self.clock()))
        open_risk = sum((r or {}).get("risk_usd") or 0 for r in self.reg.active(("USER_MARKED_PLACED",)))
        return AccountState(equity_usd=a["equity"], balance_usd=a.get("balance"), free_margin_usd=a.get("margin_free"),
                            realized_loss_today_usd=realized, losses_today=losses, open_risk_usd=open_risk,
                            open_positions=self.reg.open_positions())

    def _event(self, ev: Event, bar: Candle) -> dict[str, Any] | None:
        sig = ev.signal
        if ev.kind == "SETUP":
            return self._handle(sig, bar, awaiting=ev.needs_confirmation)
        old = self.reg.get(sig.signal_id)
        if ev.kind == "CONFIRMED":
            if old is None:
                return self._handle(sig, bar)  # setup closed before the scanner started: evaluate fresh
            if old["status"] != "WATCH_M5":
                return None  # blocked or already resolved at setup time: a confirmation never un-blocks it
            rec = self._evaluate(sig, confirmed=True)
            self.reg.update_signal(rec, f"M5 confirmation -> {rec['status']}")
            self._deliver(rec)
            return rec
        # CONFIRM_FAILED
        if old is None or old["status"] not in ("WATCH_M5", "WATCH"):
            return None
        rec = dict(old, status="CONFIRM_FAILED", blockers=list(old.get("blockers") or []) + [ev.reason],
                   safe_to_alert_for_entry=False, mtf=dict(sig.mtf))
        self.reg.update_signal(rec, ev.reason)
        self._deliver(rec)
        return rec

    def _handle(self, sig: Signal, bar: Candle, awaiting: bool = False) -> dict[str, Any] | None:
        rec = self._evaluate(sig, awaiting=awaiting)
        if not self.reg.insert_signal(rec):
            return None  # already known: never alert twice
        self._deliver(rec)
        return rec

    def _evaluate(self, sig: Signal, awaiting: bool = False, confirmed: bool = False) -> dict[str, Any]:
        now = self.clock()
        sym = sig.symbol
        try:
            q = self.feed.quote(sym)
            spread, age = q.spread, (now - q.time).total_seconds()
        except Exception:
            q, spread, age = None, sig.spread, float("inf")
        floor = getattr(self.feed, "spread_floor", None)
        if floor is not None:
            spread = max(spread, floor(sym))  # data feed is not the broker: never assume a tighter spread
        try:
            self.inst[sym] = self.feed.instrument(sym)  # refresh USD conversion for JPY/cross pairs
        except Exception:
            pass
        news = "UNKNOWN"
        if self.calendar is not None:
            news, _ = self.calendar.status(sym, now)
        if news == "CLEAR" and not sig.score_breakdown.get("news_integrity"):
            sig.score_breakdown["news_integrity"] = 5
            sig.score = sum(sig.score_breakdown.values())
            sc = self.spec["scoring"]
            sig.grade = "A_PLUS" if sig.score >= sc["a_plus"] else "WATCH" if sig.score >= sc["watch"] else "IGNORE"
        prop = TradeProposal(sym, sig.direction, sig.entry, sig.stop, sig.targets, spread, sig.atr, age,
                             self.sessions.market_open(now), news)
        try:
            d = evaluate(prop, self.inst[sym], self._account_state(), self.cfg, live=True)
        except Exception as e:
            d = RiskDecision(ok=False, blockers=[f"RISK_ENGINE_ERROR:{type(e).__name__}"])
        if d.ok and sig.grade in self.notify_grades:
            status = "WATCH_M5" if awaiting else "READY"
        elif d.ok:
            status = "WATCH"
        else:
            status = "NO_TRADE"
        if status == "READY":
            why = self._ready_guard(sym, d, news, age)
            if why:
                status = "NO_TRADE"
                d = replace(d, ok=False, blockers=list(d.blockers) + [f"READY_GUARD:{why}"])
        return self._record(sig, d, spread, news, status, q, confirmed=confirmed)

    def _ready_guard(self, sym: str, d: RiskDecision, news: str, quote_age: float) -> str | None:
        """Last line of defence: READY is impossible unless every input is verified, whatever the config says."""
        if news != "CLEAR":
            return "NEWS_NOT_VERIFIED_CLEAR"
        if not is_verified_source(self.inst[sym].source):
            return "CONTRACT_SPEC_UNVERIFIED"
        if not (quote_age <= self.cfg.max_quote_age_seconds):
            return "QUOTE_NOT_FRESH"
        if self.state.get(sym, "OK") != "OK":
            return f"DATA_{self.state[sym]}"
        if not (d.lot and d.lot > 0):
            return "NO_SAFE_LOT"
        if d.blockers:
            return "BLOCKERS_PRESENT"
        return None

    def _record(self, sig: Signal, d: RiskDecision, spread: float, news: str, status: str,
                q: Quote | None, confirmed: bool = False) -> dict[str, Any]:
        inst = self.inst[sig.symbol]
        expires = sig.bar_close_utc + self.setup_tf * self.spec["entry"]["expiry_bars"]
        if confirmed:
            expires = min(expires, sig.bar_close_utc + self.tf * CONFIRMED_EXPIRY_BARS)
        return {
            "schema_version": "1.0",
            "signal_id": sig.signal_id,
            "strategy_version": self.spec["strategy_version"],
            "strategy_hash": self.spec["strategy_hash"],
            "pair": sig.symbol,
            "broker_symbol": inst.source.split(":", 1)[-1],
            "direction": sig.direction,
            "setup": sig.setup,
            "timeframe": f"{self.setup_tf_name} (bias {self.spec['entry']['bias_timeframe']}, context "
                         f"{(self.spec.get('mtf') or {}).get('context_timeframe', 'OFF')}"
                         f"{', confirm ' + self.confirm_tf if self.confirm_tf else ''})",
            "mtf": dict(sig.mtf),
            "entry_type": "MARKET_AFTER_M5_CONFIRMATION" if confirmed else "LIMIT_AT_FVG",
            "event_time_utc": sig.bar_close_utc.isoformat(),
            "session": sig.session,
            "status": status,
            "grade": sig.grade,
            "entry": sig.entry,
            "stop_loss": sig.stop,
            "take_profits": list(sig.targets),
            "broker_prices": broker_order_prices(sig.direction, sig.entry, sig.stop, sig.targets[-1], spread) if d.ok else None,
            "safe_lot": d.lot if d.ok else None,
            "risk_usd": round(d.max_loss_usd, 2) if d.ok else None,
            "net_rr": d.net_rr[-1] if d.net_rr else None,
            "spread_pips": round(spread / inst.pip_size, 2),
            "quote_time_utc": q.time.isoformat() if q else None,
            "score_points": sig.score,
            "score_breakdown": sig.score_breakdown,
            "score_is_probability": False,
            "news_verification": news,
            "chart_parity": "UNVERIFIED",
            "blockers": d.blockers,
            "min_lot_loss_usd": round(d.min_lot_loss_usd, 3),
            "rule_trace": sig.trace,
            "liquidity_source": sig.liquidity_source,
            "target_name": sig.target_name,
            "data_source": getattr(self.feed, "source_name", "MT5"),
            "contract_spec_source": inst.source,
            "expires_at_utc": expires.isoformat(),
            "safe_to_alert_for_entry": status == "READY",
        }

    def _deliver(self, rec: dict[str, Any]) -> None:
        """READY goes to every channel. Other statuses go only to channels that keep an archive
        (the phone app shows them as 'not alerted, because ...'), never as an entry alert."""
        ready = rec["status"] in ("READY", "NOTIFIED")
        out = dict(rec, status="READY") if ready else rec
        st = out["status"]
        any_ok = False
        for n in self.notifiers:
            if not ready and not getattr(n, "archive_non_ready", False):
                continue
            if self.reg.was_delivered(rec["signal_id"], n.channel, st):
                continue
            try:
                ok, detail = n.send(out)
            except Exception as e:
                ok, detail = False, type(e).__name__
            self.reg.record_delivery(rec["signal_id"], n.channel, ok, detail, st)
            any_ok = any_ok or ok
        if any_ok and rec["status"] == "READY":
            self.reg.set_status(rec["signal_id"], "NOTIFIED")

    # --- lifecycle -------------------------------------------------------------------------
    def _lifecycle(self, sym: str, c: Candle) -> None:
        for rec in self.reg.active(ACTIVE):
            if rec is None or rec["pair"] != sym:
                continue
            if datetime.fromisoformat(rec["event_time_utc"]) > c.time:
                continue  # bar is not after the signal
            buy = rec["direction"] == "BUY"
            e, s, t = rec["entry"], rec["stop_loss"], rec["take_profits"][-1]
            sid = rec["signal_id"]
            if rec["status"] == "WATCH_M5":  # waiting for M5 confirmation: only expiry applies here
                if c.time + self.tf >= datetime.fromisoformat(rec["expires_at_utc"]):
                    self.reg.set_status(sid, "EXPIRED", "no M5 confirmation before expiry")
                continue
            if rec["status"] == "ENTRY_TOUCHED":
                if (c.low <= s) if buy else (c.high >= s):
                    self.reg.set_status(sid, "OBSERVED_SL", f"bar {c.time.isoformat()}")
                elif (c.high >= t) if buy else (c.low <= t):
                    self.reg.set_status(sid, "OBSERVED_TP", f"bar {c.time.isoformat()}")
                continue
            if (c.low <= e) if buy else (c.high >= e):
                self.reg.set_status(sid, "ENTRY_TOUCHED", f"bar {c.time.isoformat()} (observation, not a fill)")
            elif (c.high >= t) if buy else (c.low <= t):
                self.reg.set_status(sid, "MISSED", "target reached before entry; do not chase")
            elif c.time + self.tf >= datetime.fromisoformat(rec["expires_at_utc"]):
                self.reg.set_status(sid, "EXPIRED")
