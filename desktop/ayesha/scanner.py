"""Live PC scanner (master spec sections M, Q, X). Advisory only.

Loop: for each enabled pair, read newly CLOSED base bars (M15, or M5 when M5 confirmation is
on), run the multi-timeframe engine, apply the risk engine with live account/quote/news state,
persist every candidate (READY / WATCH / WATCH_M5 / NO_TRADE / CONFIRM_FAILED), alert once per
READY signal, and track lifecycle (EXPIRED / MISSED / ENTRY_TOUCHED / OBSERVED_TP / OBSERVED_SL).
Observations are market observations, not broker fills.

READY is additionally guarded by `_ready_guard`, independent of configuration: it needs a
news phase that allows entry (CLEAR, or UPCOMING with the signal expiring before the lockout), a
verified per-symbol broker spec, a fresh capital snapshot and position confirmation, a fresh
quote, fresh data, a lot > 0 and no blockers. Anything else is NO_TRADE with a
READY_GUARD:<reason> blocker. A READY that has not been entered yet is re-checked on every poll
and at delivery time: a new relevant event, a news phase change or an abnormal spread turns it
into INVALIDATED (the phone is told), never a silent carry-over.

Capital comes from the owner's capital snapshot (`ayesha.capital`), re-read on every evaluation,
never from the data feed. News comes from `ayesha.news.guard.NewsGuard`; scenario and reaction
summaries are attached for explanation only.
"""

from __future__ import annotations

import time as _time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from ayesha import capital as capmod
from ayesha.broker import is_verified_source
from ayesha.models import AccountState, Candle, InstrumentSpec, Quote
from ayesha.news import classify
from ayesha.news.analysis import scenario_card
from ayesha.news.calendar import NewsCalendar
from ayesha.news.guard import NewsAssessment, NewsGuard
from ayesha.risk.engine import RiskConfig, RiskDecision, TradeProposal, broker_order_prices, evaluate
from ayesha.rules.mtf import Event, MtfEngine, check_scalp
from ayesha.rules.strategy import TF_MINUTES, Signal
from ayesha.sessions import SessionEngine
from ayesha.storage.db import Registry

ACTIVE = ("READY", "NOTIFIED", "WATCH", "ENTRY_TOUCHED", "WATCH_M5")
CONFIRMED_EXPIRY_BARS = 3  # a confirmed (market) entry is only valid for a few base bars
CLOCK_SKEW_S = 5.0  # a quote time this far in the future means a wrong clock


def _phase_code(phase: str) -> str:
    return phase if phase.startswith("NEWS_") else "NEWS_" + phase


class Feed(Protocol):
    def account(self) -> dict[str, Any]: ...
    def instrument(self, symbol: str) -> InstrumentSpec: ...
    def quote(self, symbol: str) -> Quote: ...
    def candles(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[Candle]: ...


class Scanner:
    def __init__(self, feed: Feed, spec: dict[str, Any], registry: Registry, notifiers: list,
                 calendar: Any = None, clock: Callable[[], datetime] | None = None,
                 capital: Callable[[], capmod.CapitalSnapshot | None] | None = None) -> None:
        """`calendar`: a NewsCalendar, an object with `.calendar()` (e.g. FFCalendarSource, refreshed
        every poll), or None. `capital`: returns the latest owner capital snapshot (CapitalBook)."""
        self.feed, self.spec, self.reg, self.notifiers = feed, spec, registry, notifiers
        self.calendar_src = calendar
        self.calendar: NewsCalendar | None = calendar if isinstance(calendar, NewsCalendar) or calendar is None else None
        self.capital = capital
        self.capital_policy = dict(spec.get("capital") or {}, max_clock_skew_minutes=spec["news"].get("max_clock_skew_minutes", 5))
        self.account_type = spec.get("account", {}).get("account_type", "Standard")
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.cfg = RiskConfig.from_spec(spec)
        self.news = NewsGuard(spec)
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
        self._news_kw = dict(before_min=spec["news"]["block_minutes_before"], after_min=spec["news"]["block_minutes_after"],
                             impacts=tuple(spec["news"]["impacts_blocked"]))
        self.refresh_calendar()

    def refresh_calendar(self) -> NewsCalendar | None:
        """Re-read the calendar source (the FF source refetches at most hourly and keeps its ledger)."""
        src = self.calendar_src
        if src is None or isinstance(src, NewsCalendar):
            return self.calendar
        try:
            cal = src.calendar(**self._news_kw) if hasattr(src, "calendar") else src()
        except Exception as e:
            self.reg.health("NEWS_SOURCE_ERROR", None, f"{type(e).__name__}: {e}")
            cal = None
        if cal is None and self.calendar is not None:
            self.reg.health("NEWS_UNVERIFIED", None, "calendar unavailable: READY blocked until it recovers")
        self.calendar = cal
        return cal

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
        self.refresh_calendar()
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
        self.recheck_active()
        self.retry_deliveries()
        self.news_notices()
        self.heartbeat()
        return n

    def retry_deliveries(self) -> None:
        """A READY alert whose push failed (network down) is re-sent on later polls until it expires.
        Channels that already received it are skipped, so nothing is sent twice. It is re-checked
        first: a READY that is no longer valid is invalidated instead of being delivered late."""
        now = self.clock()
        for rec in self.reg.active(("READY", "NOTIFIED")):
            if rec is None or datetime.fromisoformat(rec["expires_at_utc"]) <= now:
                continue
            if self._invalidate_if_needed(rec, now):
                continue
            self._deliver(rec)

    def recheck_active(self) -> None:
        """N10: a READY not yet entered becomes INVALIDATED when news or the quote turns against it."""
        now = self.clock()
        for rec in self.reg.active(("READY", "NOTIFIED")):
            if rec is not None and datetime.fromisoformat(rec["expires_at_utc"]) > now:
                self._invalidate_if_needed(rec, now)

    def _invalidate_if_needed(self, rec: dict[str, Any], now: datetime) -> bool:
        sym = rec["pair"]
        why: list[str] = []
        q, spread, age = self._quote(sym, now, rec.get("spread_pips", 0) * self._pip(sym))
        na = self._news(sym, now, spread if q else None)
        if not na.allows_entry:
            why += [_phase_code(na.phase)] + na.reasons
        elif na.next_block_start and na.next_block_start < datetime.fromisoformat(rec["expires_at_utc"]):
            why.append("NEWS_LOCKOUT_BEFORE_EXPIRY")
        if q is not None and spread / self._pip(sym) > self.cfg.max_spread_pips:
            why.append("SPREAD_ABNORMAL")
        if not why:
            return False
        out = dict(rec, status="INVALIDATED", safe_to_alert_for_entry=False,
                   blockers=list(dict.fromkeys(list(rec.get("blockers") or []) + ["INVALIDATED"] + why)),
                   news_phase=na.phase, news_reasons=na.reasons, invalidated_at_utc=now.isoformat())
        self.reg.update_signal(out, "invalidated: " + ",".join(why))
        self._deliver(out)
        return True

    def news_notices(self) -> None:
        """Separate News Watch messages (never trade signals): upcoming, lockout, released, window end.
        Each (event, phase) is sent once per channel; a scanner started mid-event sends the current phase."""
        cal = self.calendar
        targets = [n for n in self.notifiers if hasattr(n, "news")]
        if cal is None or not targets:
            return
        now = self.clock()
        for e in cal.events:
            tier, before, after = self.news.window_minutes(e)
            if classify.TIER_RANK[tier] < classify.TIER_RANK["HIGH"]:
                continue
            pairs = [p for p in self.pairs if self.news.relevant(e, p)]
            if not pairs:
                continue
            start, end = e.time - timedelta(minutes=before), e.time + timedelta(minutes=after)
            if start - self.news.notice <= now < start:
                phase = "UPCOMING"
            elif start <= now < e.time:
                phase = "PRE_EVENT_LOCKOUT"
            elif e.time <= now < end:
                phase = "RELEASED"
            elif end <= now < end + timedelta(minutes=30):
                phase = "WINDOW_END"
            else:
                continue
            key = f"news:{e.event_id}"
            todo = [n for n in targets if not self.reg.was_delivered(key, n.channel, phase)]
            if not todo:
                continue
            main = next((p for p in pairs if e.currency in (p[:3], p[3:6])), pairs[0])
            notice = {"event_id": e.event_id, "title": e.title, "currency": e.currency, "impact": e.impact,
                      "tier": tier, "time_utc": e.time.isoformat(), "state": e.state, "phase": phase,
                      "pairs": pairs, "window_start_utc": start.isoformat(), "window_end_utc": end.isoformat(),
                      "provider": cal.provider, "verified_at_utc": cal.fetched_at.isoformat() if cal.fetched_at else None,
                      "forecast": e.forecast, "previous": e.previous, "sent_at_utc": now.isoformat(),
                      "scenario": scenario_card(e, main) if phase in ("UPCOMING", "PRE_EVENT_LOCKOUT") else None,
                      "reaction": None}
            if phase == "WINDOW_END":
                # one post-news summary: as soon as closed M5 bars show the market settled, else 20 min after
                # the window (the guard keeps blocking READY until it settles either way)
                try:
                    notice["reaction"] = self.news.reaction_for(
                        e, main, now, lambda a, b, s=main: self.feed.candles(s, "M5", a, b), self._pip(main))
                except Exception as ex:
                    notice["reaction"] = {"state": "UNAVAILABLE", "error": type(ex).__name__}
                if not notice["reaction"].get("market_settled") and now < end + timedelta(minutes=20):
                    continue
            for n in todo:
                try:
                    ok, detail = n.news(notice, self.spec["strategy_hash"])
                except Exception as ex:
                    ok, detail = False, type(ex).__name__
                self.reg.record_delivery(key, n.channel, ok, detail, phase)

    def capital_label(self) -> str:
        snap, err = self._capital()
        if err:
            return "MISSING"
        c = capmod.check(snap, self.clock(), self.capital_policy, self.account_type)
        return "OK" if c.ok else ("MISSING" if snap is None else c.blockers[0].replace("CAPITAL_", ""))

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
                hb(int(now.timestamp() * 1000), state, len(self.pairs), self.spec["strategy_hash"],
                   capital=self.capital_label())
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
    def _capital(self) -> tuple[capmod.CapitalSnapshot | None, list[str]]:
        if self.capital is None:
            return None, ["CAPITAL_UNVERIFIED"]
        try:
            return self.capital(), []
        except Exception as e:
            return None, [f"CAPITAL_UNREADABLE:{type(e).__name__}"]

    def _account_state(self, snap: capmod.CapitalSnapshot | None = None) -> AccountState:
        """Sizing inputs from the owner's capital snapshot (never from the data feed's balance)."""
        losses, realized = self.reg.day_stats(self.sessions.trading_day(self.clock()))
        marked = [r for r in self.reg.active(("USER_MARKED_PLACED",)) if r]
        open_risk = sum(r.get("risk_usd") or 0 for r in marked)
        positions = list(self.reg.open_positions())
        if snap is None:
            return AccountState(equity_usd=float("nan"), realized_loss_today_usd=realized, losses_today=losses,
                                open_risk_usd=open_risk, open_positions=positions)
        eq = snap.equity_usd
        for p in snap.open_positions:
            positions.append((p.symbol, p.direction))
            # an open trade whose risk is unknown uses up the whole open-risk cap
            open_risk += p.risk_usd if p.risk_usd is not None else eq * self.cfg.max_open_risk_percent / 100.0
        free = snap.free_margin_usd if (snap.open_positions or marked) else eq
        return AccountState(equity_usd=eq, balance_usd=None, free_margin_usd=free, realized_loss_today_usd=realized,
                            losses_today=losses, open_risk_usd=open_risk, open_positions=positions)

    def _pip(self, sym: str) -> float:
        inst = self.inst.get(sym)
        return inst.pip_size if inst else (0.01 if sym.upper().endswith("JPY") else 0.0001)

    def _quote(self, sym: str, now: datetime, fallback_spread: float) -> tuple[Quote | None, float, float]:
        try:
            q = self.feed.quote(sym)
            spread, age = q.spread, (now - q.time).total_seconds()
        except Exception:
            q, spread, age = None, fallback_spread, float("inf")
        floor = getattr(self.feed, "spread_floor", None)
        if floor is not None:
            spread = max(spread, floor(sym))  # data feed is not the broker: never assume a tighter spread
        return q, spread, age

    def _news(self, sym: str, now: datetime, quote_spread: float | None) -> NewsAssessment:
        def m5(start: datetime, end: datetime) -> list[Candle]:
            return self.feed.candles(sym, "M5", start, end)

        try:
            return self.news.assess(sym, now, self.calendar, m5=m5, pip=self._pip(sym), quote_spread=quote_spread)
        except Exception as e:
            return NewsAssessment("NEWS_UNVERIFIED", [f"NEWS_GUARD_ERROR:{type(e).__name__}"])

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
            self.inst[sym] = self.feed.instrument(sym)  # refresh USD conversion for JPY/cross pairs
        except Exception:
            pass
        q, spread, age = self._quote(sym, now, sig.spread)
        na = self._news(sym, now, spread if q else None)
        news = na.status
        if news == "CLEAR" and not sig.score_breakdown.get("news_integrity"):
            sig.score_breakdown["news_integrity"] = 5
            sig.score = sum(sig.score_breakdown.values())
            sc = self.spec["scoring"]
            sig.grade = "A_PLUS" if sig.score >= sc["a_plus"] else "WATCH" if sig.score >= sc["watch"] else "IGNORE"
        snap, cap_err = self._capital()
        cap = capmod.check(snap, now, self.capital_policy, self.account_type) if not cap_err else None
        prop = TradeProposal(sym, sig.direction, sig.entry, sig.stop, sig.targets, spread, sig.atr, max(age, 0.0),
                             self.sessions.market_open(now), news)
        try:
            d = evaluate(prop, self.inst[sym], self._account_state(snap if cap is not None else None), self.cfg, live=True)
        except Exception as e:
            d = RiskDecision(ok=False, blockers=[f"RISK_ENGINE_ERROR:{type(e).__name__}"])
        extra: list[str] = list(cap_err) + (cap.blockers if cap is not None else [])
        if age < -CLOCK_SKEW_S:
            extra.append("DATA_CLOCK_DRIFT")
        if not na.allows_entry:
            extra += [r for r in [_phase_code(na.phase)] + na.reasons if r not in d.blockers]
        expires = self._expiry(sig, confirmed)
        if na.next_block_start is not None and na.next_block_start < expires:
            expires = na.next_block_start  # a READY must be over before the next lockout starts
        if self.calendar is not None and self.calendar.coverage[1] < expires:
            expires = self.calendar.coverage[1]  # beyond the calendar nothing is known
        if expires - now < self.tf:  # less than one base bar left before the lockout
            extra.append("NEWS_LOCKOUT_BEFORE_EXPIRY")
        if extra:
            d = replace(d, ok=False, blockers=list(dict.fromkeys(list(d.blockers) + extra)))
        if d.ok and sig.grade in self.notify_grades:
            status = "WATCH_M5" if awaiting else "READY"
        elif d.ok:
            status = "WATCH"
        else:
            status = "NO_TRADE"
        if status == "READY":
            why = self._ready_guard(sym, d, na, age, cap)
            if why:
                status = "NO_TRADE"
                d = replace(d, ok=False, blockers=list(d.blockers) + [f"READY_GUARD:{why}"])
        return self._record(sig, d, spread, news, status, q, confirmed=confirmed, na=na, cap=cap, expires=expires)

    def _expiry(self, sig: Signal, confirmed: bool) -> datetime:
        expires = sig.bar_close_utc + self.setup_tf * self.spec["entry"]["expiry_bars"]
        if confirmed:
            expires = min(expires, sig.bar_close_utc + self.tf * CONFIRMED_EXPIRY_BARS)
        return expires

    def _ready_guard(self, sym: str, d: RiskDecision, na: NewsAssessment, quote_age: float,
                     cap: capmod.CapitalCheck | None) -> str | None:
        """Last line of defence: READY is impossible unless every input is verified, whatever the config says."""
        if not na.allows_entry or na.status != "CLEAR":
            return "NEWS_NOT_VERIFIED_CLEAR"
        if not is_verified_source(self.inst[sym].source):
            return "BROKER_SPEC_UNVERIFIED"
        if cap is None or not cap.ok:
            return "CAPITAL_UNVERIFIED"
        if not (0 <= quote_age + CLOCK_SKEW_S and quote_age <= self.cfg.max_quote_age_seconds):
            return "QUOTE_NOT_FRESH"
        if self.state.get(sym, "OK") != "OK":
            return f"DATA_{self.state[sym]}"
        if not (d.lot and d.lot > 0):
            return "NO_SAFE_LOT"
        if d.margin_required_usd is None:
            return "MARGIN_UNVERIFIED"
        if d.lot > 0 and d.max_loss_usd > (cap.snapshot.equity_usd * min(self.cfg.risk_per_trade_percent, 1.0) / 100 + 1e-9):
            return "RISK_ABOVE_CAP"
        if d.blockers:
            return "BLOCKERS_PRESENT"
        return None

    def _record(self, sig: Signal, d: RiskDecision, spread: float, news: str, status: str,
                q: Quote | None, confirmed: bool = False, na: NewsAssessment | None = None,
                cap: capmod.CapitalCheck | None = None, expires: datetime | None = None) -> dict[str, Any]:
        inst = self.inst[sig.symbol]
        expires = expires or self._expiry(sig, confirmed)
        ev = na.event if na else None
        snap = cap.snapshot if cap else None
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
            "news_phase": na.phase if na else "NEWS_UNVERIFIED",
            "news_reasons": na.reasons if na else [],
            "news_event": None if ev is None else {
                "event_id": ev.event_id, "title": ev.title, "currency": ev.currency, "impact": ev.impact,
                "tier": na.tier, "time_utc": ev.time.isoformat(), "state": ev.state},
            "news_provider": na.provider if na else "",
            "news_verified_at_utc": na.verified_at.isoformat() if na and na.verified_at else None,
            "news_next_lockout_utc": na.next_block_start.isoformat() if na and na.next_block_start else None,
            "news_scenario": scenario_card(ev, sig.symbol) if ev is not None else None,
            "news_reaction": na.reaction if na else None,
            "capital_status": cap.label if cap else "CAPITAL_UNVERIFIED",
            "capital_snapshot_version": snap.version if snap else None,
            "capital_verified_at_utc": snap.entered_at.isoformat() if snap else None,
            "capital_source": snap.source if snap else None,
            "capital_equity_usd": snap.equity_usd if snap else None,  # PC only: never sent to the relay
            "risk_percent": self.cfg.risk_per_trade_percent,
            "risk_budget_usd": round(d.risk_budget_usd, 4),
            "nominal_budget_usd": round(d.nominal_budget_usd, 4),
            "budget_limited_by": d.budget_limited_by,
            "lot_status": "OK" if d.ok else next((b for b in d.blockers if b in (
                "MIN_LOT_EXCEEDS_RISK", "DAILY_RISK_PAUSE", "OPEN_RISK_CAP", "MARGIN_UNVERIFIED",
                "INSUFFICIENT_FREE_MARGIN", "EQUITY_UNKNOWN")), "BLOCKED"),
            "margin_required_usd": None if d.margin_required_usd is None else round(d.margin_required_usd, 2),
            "chart_parity": "UNVERIFIED",
            "blockers": d.blockers,
            "min_lot_loss_usd": round(d.min_lot_loss_usd, 3),
            "min_lot_loss_percent": round(d.min_lot_loss_percent, 3),
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
        cancel = st == "INVALIDATED"  # every channel that may have shown the READY hears about the cancel
        for n in self.notifiers:
            if not ready and not cancel and not getattr(n, "archive_non_ready", False):
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
