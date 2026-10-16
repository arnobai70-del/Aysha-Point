"""News protection state machine (News Intelligence spec A2/A3). Fails closed.

Per pair, every relevant calendar event is placed in a phase:

    UPCOMING -> PRE_EVENT_LOCKOUT -> EVENT_LIVE -> POST_EVENT_COOLDOWN -> REACTION_WATCH -> CLEAR
    any -> NEWS_UNVERIFIED when the source, its coverage, its age, the clock or the event data
           cannot be trusted

The pair's phase is the strictest phase of all its events (overlaps wait for the last window).
Only CLEAR and UPCOMING allow a new READY, and an UPCOMING READY must expire before the next
lockout starts (`next_block_start`). REACTION_WATCH ends only when closed M5 bars show the spread
and range back near the pre-event baseline: a timer alone never clears it inside the watch. The watch
is bounded by `reaction_watch_max_minutes` after the window; past that the event no longer blocks
and the ordinary hard gates (absolute spread cap, quote age, risk) decide. Post-release market
reaction is an explanation field (`reaction`), never permission to enter.

Windows are configured in contracts/strategy-spec.yaml `news.tiers` and can never be shorter than
the legacy HIGH-impact window (`block_minutes_before/after`).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from ayesha.models import Candle
from ayesha.news import classify
from ayesha.news.calendar import NewsCalendar, NewsEvent

PHASE_RANK = {"CLEAR": 0, "UPCOMING": 1, "REACTION_WATCH": 2, "POST_EVENT_COOLDOWN": 3,
              "PRE_EVENT_LOCKOUT": 4, "EVENT_LIVE": 5, "NEWS_UNVERIFIED": 6}
ALLOWS_ENTRY = ("CLEAR", "UPCOMING")
M5 = timedelta(minutes=5)


@dataclass
class NewsAssessment:
    phase: str
    reasons: list[str] = field(default_factory=list)
    event: NewsEvent | None = None  # the event that decided the phase
    tier: str = ""
    window: tuple[datetime, datetime] | None = None
    next_block_start: datetime | None = None  # a READY must expire before this
    provider: str = ""
    verified_at: datetime | None = None  # calendar fetch time
    reaction: dict[str, Any] | None = None
    events: list[tuple[NewsEvent, str]] = field(default_factory=list)  # (event, its phase)

    @property
    def status(self) -> str:
        """Legacy three-value status used by the risk engine: CLEAR | BLOCKED | UNKNOWN."""
        if self.phase in ALLOWS_ENTRY:
            return "CLEAR"
        return "UNKNOWN" if self.phase == "NEWS_UNVERIFIED" else "BLOCKED"

    @property
    def allows_entry(self) -> bool:
        return self.phase in ALLOWS_ENTRY


class NewsGuard:
    def __init__(self, spec: dict[str, Any], max_spread_pips: float | None = None) -> None:
        n = spec["news"]
        self.legacy = (int(n["block_minutes_before"]), int(n["block_minutes_after"]))
        self.tiers = {k: (int(v["before"]), int(v["after"])) for k, v in (n.get("tiers") or {}).items()}
        self.global_ccys = {c.upper() for c in n.get("global_currencies", [])}
        self.notice = timedelta(minutes=int(n.get("upcoming_notice_minutes", 60)))
        self.live = timedelta(minutes=int(n.get("event_live_minutes", 5)))
        self.watch_max = timedelta(minutes=int(n.get("reaction_watch_max_minutes", 120)))
        self.max_age = timedelta(hours=float(n.get("source_max_age_hours", 24)))
        self.skew = timedelta(minutes=float(n.get("max_clock_skew_minutes", 5)))
        st = n.get("stability") or {}
        self.baseline = timedelta(minutes=int(st.get("baseline_minutes", 120)))
        self.min_base = int(st.get("min_baseline_bars", 12))
        self.after_bars = max(2, int(st.get("closed_bars_after", 2)))
        self.spread_ratio = float(st.get("spread_ratio_max", 1.5))
        self.spread_slack = float(st.get("spread_abs_slack_pips", 0.2))
        self.range_ratio = float(st.get("range_ratio_max", 2.0))
        self.shock_ratio = float(st.get("shock_ratio", 3.0))
        self.whipsaw_ratio = float(st.get("whipsaw_ratio", 3.0))
        self.shock_extend = timedelta(minutes=int(st.get("shock_extend_minutes", 30)))
        self.max_spread_pips = max_spread_pips if max_spread_pips is not None else float(spec["risk"]["max_spread_pips"])
        self.max_before = max([self.legacy[0]] + [b for b, _ in self.tiers.values()])

    # --- configuration --------------------------------------------------------------------
    def window_minutes(self, e: NewsEvent) -> tuple[str, int, int]:
        t = classify.tier(e.title, e.impact)
        before, after = self.tiers.get(t, self.legacy if classify.TIER_RANK[t] >= 2 else (0, 0))
        if classify.TIER_RANK[t] >= classify.TIER_RANK["HIGH"]:  # never looser than the legacy window
            before, after = max(before, self.legacy[0]), max(after, self.legacy[1])
        return t, before, after

    def relevant(self, e: NewsEvent, symbol: str) -> bool:
        ccys = {symbol[:3].upper(), symbol[3:6].upper()}
        c = e.currency.upper()
        if c in ccys or c in classify.GLOBAL_CODES:
            return True
        if not classify.currency_known(c):
            return classify.TIER_RANK[classify.tier(e.title, e.impact)] >= 1  # unmappable: assume it matters
        t = classify.tier(e.title, e.impact)
        return c in self.global_ccys and classify.TIER_RANK[t] >= classify.TIER_RANK["TOP_DATA"]

    # --- main entry -----------------------------------------------------------------------
    def assess(self, symbol: str, now: datetime, calendar: NewsCalendar | None,
               m5: Callable[[datetime, datetime], list[Candle]] | None = None,
               pip: float = 0.0001, quote_spread: float | None = None, live: bool = True) -> NewsAssessment:
        if calendar is None:
            return NewsAssessment("NEWS_UNVERIFIED", ["NEWS_SOURCE_MISSING"])
        a = NewsAssessment("CLEAR", provider=calendar.provider, verified_at=calendar.fetched_at)
        if live:
            if calendar.fetched_at is None:
                a.reasons.append("NEWS_SOURCE_PROVENANCE_UNKNOWN")
            elif calendar.fetched_at > now + self.skew:
                a.reasons.append("NEWS_CLOCK_DRIFT")
            elif now - calendar.fetched_at > self.max_age:
                a.reasons.append("NEWS_SOURCE_STALE")
        lead = timedelta(minutes=self.max_before)
        if not (calendar.coverage[0] <= now and now + lead < calendar.coverage[1]):
            a.reasons.append("NEWS_COVERAGE_GAP")  # cannot see whether a lockout starts soon
        if a.reasons:
            a.phase = "NEWS_UNVERIFIED"
            return a

        bars_cache: dict[str, list[Candle]] = {}
        best_rank = 0
        for e in calendar.events:
            if not self.relevant(e, symbol):
                continue
            tier, before, after = self.window_minutes(e)
            start, end = e.time - timedelta(minutes=before), e.time + timedelta(minutes=after)
            if now >= end + self.watch_max or now < start - self.notice and tier != "LOW":
                if start > now and classify.TIER_RANK[tier] >= 1:
                    a.next_block_start = min(filter(None, (a.next_block_start, start)))
                continue
            phase, why = self._phase(e, tier, start, end, now, symbol, m5, pip, quote_spread, bars_cache, a)
            if phase is None:
                continue
            if start > now and classify.TIER_RANK[tier] >= 1:
                a.next_block_start = min(filter(None, (a.next_block_start, start)))
            a.events.append((e, phase))
            if PHASE_RANK[phase] >= PHASE_RANK["REACTION_WATCH"] or phase == "NEWS_UNVERIFIED":
                for r in why:
                    if r not in a.reasons:
                        a.reasons.append(r)
            if PHASE_RANK[phase] > best_rank or (PHASE_RANK[phase] == best_rank and a.event is not None
                                                 and phase != "CLEAR" and end > a.window[1]):
                best_rank = PHASE_RANK[phase]
                a.phase, a.event, a.tier, a.window = phase, e, tier, (start, end)
        if a.phase == "UPCOMING" and "NEWS_UPCOMING" not in a.reasons:
            a.reasons.append("NEWS_UPCOMING")
        return a

    def _phase(self, e, tier, start, end, now, symbol, m5, pip, quote_spread, cache, a):
        why: list[str] = []
        if not classify.currency_known(e.currency):
            why.append("NEWS_CURRENCY_MISSING")
        if e.state == "CONFLICT":
            why.append("NEWS_CONFLICT")
        if classify.TIER_RANK[tier] >= 2 and classify.malformed(e.forecast, e.previous, e.actual):
            why.append("NEWS_DATA_MALFORMED")
        if why and now < end + self.watch_max:
            return "NEWS_UNVERIFIED", why
        if e.state == "RESCHEDULED":
            why.append("EVENT_RESCHEDULED")
        elif e.state == "CANCELLED_OR_MOVED":
            why.append("EVENT_CANCELLED_OR_MOVED")
        elif e.state == "CORRECTED":
            why.append("EVENT_CORRECTED")

        if tier == "LOW":  # informational, unless the market shows a shock around it
            if not (e.time <= now < e.time + self.watch_max) or m5 is None:
                return None, []
            _, reasons, _ = self.stability(e, start, end, now, m5, pip, quote_spread, cache, symbol, shock_only=True)
            # a low-impact event only blocks when the market really shows a shock around it
            return ("REACTION_WATCH", why + reasons) if "VOLATILITY_UNSTABLE" in reasons else (None, [])
        if now < start:
            return "UPCOMING", why
        if now < e.time:
            return "PRE_EVENT_LOCKOUT", why + ["NEWS_LOCKOUT"]
        if now < e.time + self.live:
            return "EVENT_LIVE", why + ["NEWS_RELEASE_PENDING" if e.actual is None else "NEWS_LOCKOUT"]
        if now < end:
            return "POST_EVENT_COOLDOWN", why + ["NEWS_LOCKOUT"]
        if m5 is None:
            return "REACTION_WATCH", why + ["POST_NEWS_NOT_CONFIRMED"]
        ok, reasons, metrics = self.stability(e, start, end, now, m5, pip, quote_spread, cache, symbol)
        if a.reaction is None:
            from ayesha.news.analysis import reaction

            a.reaction = reaction(e, symbol, now, cache.get("bars", []), metrics.get("baseline_range"))
        return ("CLEAR", []) if ok else ("REACTION_WATCH", why + reasons)

    def reaction_for(self, e: NewsEvent, symbol: str, now: datetime,
                     m5: Callable[[datetime, datetime], list[Candle]], pip: float = 0.0001) -> dict[str, Any]:
        """Post-release summary for one event and pair (explanation only), with whether the market settled."""
        from ayesha.news.analysis import reaction

        _, before, after = self.window_minutes(e)
        start, end = e.time - timedelta(minutes=before), e.time + timedelta(minutes=after)
        cache: dict = {}
        ok, reasons, metrics = self.stability(e, start, end, now, m5, pip, None, cache, symbol)
        r = reaction(e, symbol, now, cache.get("bars", []), metrics.get("baseline_range"))
        r.update(symbol=symbol, market_settled=ok, settle_reasons=reasons)
        return r

    # --- A3: market stability after the window ---------------------------------------------
    def stability(self, e: NewsEvent, start: datetime, end: datetime, now: datetime,
                  m5: Callable[[datetime, datetime], list[Candle]], pip: float, quote_spread: float | None,
                  cache: dict, symbol: str, shock_only: bool = False) -> tuple[bool, list[str], dict[str, float]]:
        lo = start - self.baseline
        if "bars" not in cache or cache.get("lo", lo) > lo:
            try:
                cache["bars"] = [b for b in m5(lo, now) if b.time + M5 <= now]  # closed bars only
            except Exception:
                cache["bars"] = []
            cache["lo"] = lo
        bars = sorted(cache["bars"], key=lambda b: b.time)
        base = [b for b in bars if lo <= b.time and b.time + M5 <= start]
        post = [b for b in bars if b.time >= e.time]
        metrics: dict[str, float] = {}
        if len(base) < self.min_base:
            return False, ["NEWS_BASELINE_MISSING"], metrics
        tr = [_true_range(base[i], base[i - 1]) for i in range(1, len(base))]
        base_range = statistics.fmean(tr) if tr else 0.0
        base_spread = statistics.median(b.spread for b in base)
        metrics.update(baseline_range=base_range, baseline_spread=base_spread)
        if not base_range > 0:
            return False, ["NEWS_BASELINE_MISSING"], metrics
        reasons = []
        # gaps: every 5-minute bar from the release to the last closed bar must be present
        if post:
            expect = int((post[-1].time - post[0].time) / M5) + 1
            if len(post) < expect or post[0].time - e.time >= M5:
                reasons.append("NEWS_DATA_GAP")
        last_closed = (bars[-1].time + M5) if bars else None
        if last_closed is None or now - last_closed > 2 * M5:
            reasons.append("POST_NEWS_NOT_CONFIRMED")  # no fresh closed M5 bar
        prev = base[-1]
        ranges = []
        for b in post:
            ranges.append(_true_range(b, prev))
            prev = b
        # an abrupt spike extends the cooldown: nothing clears until `shock_extend_minutes` after the
        # last shock bar closed, however the timer stands
        shocks = [b for b, r in zip(post, ranges) if r > self.shock_ratio * base_range]
        if shocks and now - (shocks[-1].time + M5) < self.shock_extend:
            if shock_only:
                return False, ["VOLATILITY_UNSTABLE"] + reasons, metrics
            reasons.append("VOLATILITY_UNSTABLE")
        if shock_only:
            return True, [], metrics
        after = [b for b in post if b.time >= end]
        if len(after) < self.after_bars:
            reasons.append("POST_NEWS_NOT_CONFIRMED")
        recent = after[-self.after_bars:]
        cap = min(max(base_spread * self.spread_ratio, base_spread + self.spread_slack * pip), self.max_spread_pips * pip)
        spreads = [b.spread for b in recent] + ([quote_spread] if quote_spread is not None else [])
        if any(s > cap + 1e-12 for s in spreads):
            reasons.append("SPREAD_ABNORMAL")
        rr = ranges[-len(recent):] if recent else []
        if any(r > self.range_ratio * base_range for r in rr):
            reasons.append("VOLATILITY_UNSTABLE")
        if post:
            pre_close = base[-1].close
            up = max(b.high for b in post) - pre_close
            dn = pre_close - min(b.low for b in post)
            if min(up, dn) > self.whipsaw_ratio * base_range:
                reasons.append("VOLATILITY_UNSTABLE")
                metrics["whipsaw"] = 1.0
        return not reasons, list(dict.fromkeys(reasons)), metrics


def _true_range(b: Candle, prev: Candle) -> float:
    return max(b.high, prev.close) - min(b.low, prev.close)
