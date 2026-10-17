"""Common bar-by-bar runner of the Strategy Lab (plan §6.3, tickets AI-008/AI-009).

Every research strategy, the frozen baseline included, is replayed by this one loop with the same fills, costs and
gates, so differences between strategies come from their rules and nothing else:

- Fills and exits are the legacy replay's own functions (`ayesha.backtest.replay._pending/_market/_open`), not a
  copy: limit orders fill when the BID touches the level, every fill pays its bar's spread, the slippage buffer is
  part of the planned loss and of stop exits, a bar touching stop and target is a stop, the fill bar cannot take
  profit, a gap through the stop exits at the open, trades are flat before the New York rollover. R includes those
  costs (1R = planned loss).
- Gates are the live risk engine's sizing-independent checks (`ayesha.risk.engine.evaluate`: spread cap, stop vs
  ATR(M15), net reward-to-risk, news) at a notional large equity; the account-level gates (minimum lot, daily loss,
  open risk, correlated exposure) run in `portfolio`.
- News (v1.1.0) is NOT modelled unless a frozen historical calendar is given (`NewsInput`, from a news snapshot).
  Then it is gated exactly like the legacy replay's `news_mode`: "legacy" (fixed HIGH-impact window) or "upgraded"
  (the live NewsGuard on the point-in-time calendar `ayesha.backtest.asof.AsOfCalendar`, closed M5 bars only, a
  pending order invalidated when news turns against it, a setup expiring before the next lockout). News direction is
  never used.
- The loop is the one of `ayesha.backtest.replay.run_backtest`: at bar i the strategy sees bars 0..i only; an order
  it creates can first fill on bar i+1. With the baseline it reproduces the legacy replay trade for trade, with and
  without news (checked on every lab run by `simulation.lab.benchmark_parity`).

Extra book-keeping that the legacy `Trade` does not have: when each order ended (fill, exit or expiry time) for the
account simulation, and intrabar-ambiguity flags (plan §6.3): a stop exit on a bar that also reached the target, and
a fill bar that reached the target (which the conservative model does not count).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from ayesha.backtest.asof import AsOfCalendar
from ayesha.backtest.replay import Trade, _market, _open, _pending, _phase_code, bar_source
from ayesha.feed.static_specs import assumed_fx_spec
from ayesha.models import AccountState, Candle, pip_size_for
from ayesha.news.calendar import NewsCalendar
from ayesha.news.guard import NewsAssessment, NewsGuard
from ayesha.research.regimes.detector import RegimeDetector
from ayesha.research.simulation.costs import BASE, CostModel
from ayesha.research.strategies.protocol import AsOfContext
from ayesha.risk.engine import RiskConfig, TradeProposal, evaluate
from ayesha.rules.strategy import TF_MINUTES

APPROX_USD_RATES = {"JPY": 1 / 150.0, "GBP": 1.27, "CAD": 1 / 1.37, "CHF": 1 / 0.88}  # same as ayesha.cli
TERMINAL = ("CLOSED", "EXPIRED", "MISSED", "BLOCKED", "UNCONFIRMED", "INVALIDATED")
ENGINE = "research-runner-1"
NEWS_MODES = ("legacy", "upgraded")


@dataclass
class LabTrade:
    trade: Trade
    symbol: str
    created_at: datetime                     # close of the bar the order became known (after any delay)
    ended_at: datetime | None = None        # exit bar close, or the bar the order expired / was missed
    flags: list[str] = field(default_factory=list)
    regime: str = "UNKNOWN"                  # as-of regime label known when the order was decided (v1.1.0)


@dataclass(frozen=True)
class NewsInput:
    """A frozen historical calendar for a replay; only ever read through its point-in-time view."""
    calendar: NewsCalendar
    mode: str = "upgraded"                   # "legacy" | "upgraded" (see ayesha.backtest.replay)
    m5: list[Candle] | None = None           # closed M5 bars for the reaction watch (None: held to its maximum)

    def __post_init__(self) -> None:
        if self.mode not in NEWS_MODES:
            raise ValueError(f"news mode must be one of {NEWS_MODES}")


def risk_config(spec: dict[str, Any], news_modelled: bool = False) -> RiskConfig:
    cfg = RiskConfig.from_spec(spec)
    if news_modelled:
        return cfg
    return RiskConfig(**{**cfg.__dict__, "strict_news": False})  # news is NOT modelled (research only)


def run(symbol: str, candles: list[Candle], spec: dict[str, Any], strategy, cost: CostModel = BASE,
        account_type: str = "Standard", usd_rates: dict[str, float] | None = None,
        news: NewsInput | None = None) -> dict[str, Any]:
    usd_rates = usd_rates if usd_rates is not None else APPROX_USD_RATES
    candles = cost.apply(candles)
    cfg = risk_config(spec, news is not None)
    pip = pip_size_for(symbol)
    slip = (cfg.slippage_buffer_pips + cost.extra_slippage_pips) * pip
    tf = timedelta(minutes=TF_MINUTES["M15"])
    ctx = AsOfContext(symbol)
    det = RegimeDetector()
    trades: list[LabTrade] = []
    active: list[LabTrade] = []
    awaiting: dict[str, LabTrade] = {}
    queue: list[tuple[int, list]] = []  # (due bar index, events) for delayed decisions
    mode = news.mode if news is not None else "none"
    guard = asof = m5 = None
    if news is not None:
        guard, asof = NewsGuard(spec), AsOfCalendar(news.calendar)
        m5 = bar_source(news.m5) if news.m5 else None
    seen: dict[datetime, NewsAssessment] = {}
    decision_times: list[datetime] = []

    def news_at(t: datetime) -> NewsAssessment:
        """The live guard at `t`: the calendar as known then and M5 bars closed by then (legacy replay's own)."""
        if t not in seen:
            decision_times.append(t)
            seen[t] = guard.assess(symbol, t, asof.at(t), m5=m5, pip=pip, live=False)
        return seen[t]

    def gate(sig, c: Candle, tr: Trade, late: int) -> list[str]:
        status, extra = "CLEAR", []
        if guard is not None:
            t = sig.bar_close_utc if not late else c.time + tf  # a delayed decision sees the news of its own bar
            na = news_at(t)
            tr.news_phase = na.phase
            if mode == "legacy":
                status, _ = asof.at(t).status(symbol, t)
            else:
                status = na.status
                if not na.allows_entry:
                    extra = [_phase_code(na.phase)] + [r for r in na.reasons if r != na.phase]
                elif na.next_block_start is not None:
                    tr.expires_at = na.next_block_start  # the order must be gone before the next lockout
                    if na.next_block_start - t < tf:
                        extra = ["NEWS_LOCKOUT_BEFORE_EXPIRY"]
            sb = getattr(sig, "score_breakdown", None)
            if status == "CLEAR" and sb is not None and sb.get("news_integrity", 0) == 0:
                sb["news_integrity"] = 5  # same score note as the legacy replay; scores never gate research
                sig.score += 5
        prop = TradeProposal(symbol, sig.direction, sig.entry, sig.stop, sig.targets, sig.spread, sig.atr,
                             0.0, True, status)
        inst = assumed_fx_spec(symbol, c.close, account_type, usd_rates)
        blockers = evaluate(prop, inst, AccountState(equity_usd=1e6), cfg, live=False).blockers
        return blockers + [b for b in extra if b not in blockers]

    def new(sig, c: Candle, status: str, late: int) -> LabTrade:
        lt = LabTrade(Trade(sig, planned_loss=abs(sig.entry - sig.stop) + sig.spread + slip), symbol, c.time + tf,
                      regime=det.current.label)
        b = gate(sig, c, lt.trade, late)
        if b:
            lt.trade.status, lt.trade.blockers, lt.ended_at = "BLOCKED", b, c.time + tf
        else:
            lt.trade.status = status
        trades.append(lt)
        return lt

    def apply(events: list, c: Candle, i: int, late: int) -> None:
        for ev in events:
            sig = ev.signal
            if late:
                sig = replace(sig, expires_index=sig.expires_index + late)
            if ev.kind == "SETUP":
                lt = new(sig, c, "AWAITING_CONFIRMATION" if ev.needs_confirmation else "PENDING", late)
                if lt.trade.status == "AWAITING_CONFIRMATION":
                    awaiting[sig.signal_id] = lt
                elif lt.trade.status == "PENDING":
                    active.append(lt)
            elif ev.kind == "MARKET":
                lt = new(sig, c, "PENDING_MARKET", late)
                if lt.trade.status == "PENDING_MARKET":
                    active.append(lt)
            elif ev.kind == "CONFIRM_FAILED":
                lt = awaiting.pop(sig.signal_id, None)
                if lt is not None:
                    lt.trade.status, lt.trade.exit_reason, lt.ended_at = "UNCONFIRMED", ev.reason, c.time + tf
            elif ev.kind == "CONFIRMED":
                lt = awaiting.pop(sig.signal_id, None)
                if lt is None:
                    continue
                lt.trade.signal = sig
                lt.trade.planned_loss = abs(sig.entry - sig.stop) + sig.spread + slip
                b = gate(sig, c, lt.trade, late)  # re-check at the refined entry, as the legacy replay does
                if b:
                    lt.trade.status, lt.trade.blockers, lt.ended_at = "BLOCKED", b, c.time + tf
                else:
                    lt.trade.status = "PENDING_MARKET"
                    active.append(lt)
            else:
                raise ValueError(f"unknown research event kind {ev.kind!r}")

    for i, c in enumerate(candles):
        # 1) manage orders created on earlier bars only (legacy fill functions)
        still = []
        for lt in active:
            t = t0 = lt.trade
            before = t.status
            if before == "PENDING" and mode == "upgraded" and not (na := news_at(c.time)).allows_entry:
                # what was known when this bar opened (N10): the pending order is withdrawn
                t.status = "INVALIDATED"
                t.blockers = ["INVALIDATED", _phase_code(na.phase)] + [r for r in na.reasons if r != na.phase]
            elif before == "PENDING" and t.expires_at is not None and c.time + tf > t.expires_at:
                t.status, t.exit_reason = "EXPIRED", "NEWS_LOCKOUT_BEFORE_EXPIRY"
            elif before == "PENDING":
                _pending(t, c, i, slip)
            elif before == "PENDING_MARKET":
                _market(t, c, i, slip)
            elif before == "OPEN":
                _open(t, c, i, slip, tf)
            if t.status == "CLOSED" and t.exit_time is None:
                t.exit_time = c.time + tf
            _flags(lt, before, c)
            if t0.status in TERMINAL:
                lt.ended_at = c.time + tf
            else:
                still.append(lt)
        active = still
        # 2) the strategy sees the closed bar
        ctx.advance(c)
        det.update(ctx)
        events = strategy.evaluate(ctx)
        if cost.delay_bars:
            if events:
                queue.append((i + cost.delay_bars, events))
            due = [q for q in queue if q[0] == i]
            queue = [q for q in queue if q[0] != i]
            for _, evs in due:
                apply(evs, c, i, cost.delay_bars)
        else:
            apply(events, c, i, 0)
    for lt in trades:
        if lt.trade.status in ("PENDING", "OPEN", "PENDING_MARKET", "AWAITING_CONFIRMATION"):
            lt.trade.status, lt.trade.exit_reason = "UNRESOLVED_END_OF_DATA", "END"
    return {"symbol": symbol, "trades": trades, "rejections": list(strategy.rejections), "bars": len(candles),
            "start": candles[0].time if candles else None, "end": candles[-1].time + tf if candles else None,
            "cost_model": cost.as_dict(), "engine": ENGINE, "news_mode": mode,
            "news_integrity": asof.integrity(decision_times) if asof is not None else None,
            "news_stability_bars": "M5 closed bars" if m5 is not None else (
                "none: reaction watch held to its maximum" if guard is not None else None)}


def _flags(lt: LabTrade, before: str, c: Candle) -> None:
    t = lt.trade
    s = t.signal
    tgt = s.targets[-1]
    reached = c.high >= tgt if s.direction == "BUY" else c.low <= tgt
    if t.status == "CLOSED" and t.exit_reason == "SL" and reached:
        lt.flags.append("AMBIGUOUS_STOP_AND_TARGET_SAME_BAR")
    elif before in ("PENDING", "PENDING_MARKET") and t.status == "OPEN" and reached:
        lt.flags.append("FILL_BAR_REACHED_TARGET")
