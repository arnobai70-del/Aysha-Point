"""Common bar-by-bar runner of the Strategy Lab (plan §6.3, tickets AI-008/AI-009).

Every research strategy, the frozen baseline included, is replayed by this one loop with the same fills, costs and
gates, so differences between strategies come from their rules and nothing else:

- Fills and exits are the legacy replay's own functions (`ayesha.backtest.replay._pending/_market/_open`), not a
  copy: limit orders fill when the BID touches the level, every fill pays its bar's spread, the slippage buffer is
  part of the planned loss and of stop exits, a bar touching stop and target is a stop, the fill bar cannot take
  profit, a gap through the stop exits at the open, trades are flat before the New York rollover. R includes those
  costs (1R = planned loss).
- Gates are the live risk engine's sizing-independent checks (`ayesha.risk.engine.evaluate`: spread cap, stop vs
  ATR(M15), net reward-to-risk) at a notional large equity, with news NOT modelled (no historical calendar); the
  account-level gates (minimum lot, daily loss, open risk, correlated exposure) run in `portfolio`.
- The loop is the one of `ayesha.backtest.replay.run_backtest` with news off: at bar i the strategy sees bars 0..i
  only; an order it creates can first fill on bar i+1. With the baseline it reproduces the legacy replay trade for
  trade (checked on every lab run by `simulation.lab.benchmark_parity`).

Extra book-keeping that the legacy `Trade` does not have: when each order ended (fill, exit or expiry time) for the
account simulation, and intrabar-ambiguity flags (plan §6.3): a stop exit on a bar that also reached the target, and
a fill bar that reached the target (which the conservative model does not count).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from ayesha.backtest.replay import Trade, _market, _open, _pending
from ayesha.feed.static_specs import assumed_fx_spec
from ayesha.models import AccountState, Candle, pip_size_for
from ayesha.research.simulation.costs import BASE, CostModel
from ayesha.research.strategies.protocol import AsOfContext
from ayesha.risk.engine import RiskConfig, TradeProposal, evaluate
from ayesha.rules.strategy import TF_MINUTES

APPROX_USD_RATES = {"JPY": 1 / 150.0, "GBP": 1.27, "CAD": 1 / 1.37, "CHF": 1 / 0.88}  # same as ayesha.cli
TERMINAL = ("CLOSED", "EXPIRED", "MISSED", "BLOCKED", "UNCONFIRMED", "INVALIDATED")
ENGINE = "research-runner-1"


@dataclass
class LabTrade:
    trade: Trade
    symbol: str
    created_at: datetime                     # close of the bar the order became known (after any delay)
    ended_at: datetime | None = None        # exit bar close, or the bar the order expired / was missed
    flags: list[str] = field(default_factory=list)


def risk_config(spec: dict[str, Any]) -> RiskConfig:
    cfg = RiskConfig.from_spec(spec)
    return RiskConfig(**{**cfg.__dict__, "strict_news": False})  # news is NOT modelled (research only)


def run(symbol: str, candles: list[Candle], spec: dict[str, Any], strategy, cost: CostModel = BASE,
        account_type: str = "Standard", usd_rates: dict[str, float] | None = None) -> dict[str, Any]:
    usd_rates = usd_rates if usd_rates is not None else APPROX_USD_RATES
    candles = cost.apply(candles)
    cfg = risk_config(spec)
    pip = pip_size_for(symbol)
    slip = (cfg.slippage_buffer_pips + cost.extra_slippage_pips) * pip
    tf = timedelta(minutes=TF_MINUTES["M15"])
    ctx = AsOfContext(symbol)
    trades: list[LabTrade] = []
    active: list[LabTrade] = []
    awaiting: dict[str, LabTrade] = {}
    queue: list[tuple[int, list]] = []  # (due bar index, events) for delayed decisions

    def gate(sig, c: Candle) -> list[str]:
        prop = TradeProposal(symbol, sig.direction, sig.entry, sig.stop, sig.targets, sig.spread, sig.atr,
                             0.0, True, "CLEAR")
        inst = assumed_fx_spec(symbol, c.close, account_type, usd_rates)
        return evaluate(prop, inst, AccountState(equity_usd=1e6), cfg, live=False).blockers

    def new(sig, c: Candle, status: str) -> LabTrade:
        lt = LabTrade(Trade(sig, planned_loss=abs(sig.entry - sig.stop) + sig.spread + slip), symbol, c.time + tf)
        b = gate(sig, c)
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
                lt = new(sig, c, "AWAITING_CONFIRMATION" if ev.needs_confirmation else "PENDING")
                if lt.trade.status == "AWAITING_CONFIRMATION":
                    awaiting[sig.signal_id] = lt
                elif lt.trade.status == "PENDING":
                    active.append(lt)
            elif ev.kind == "MARKET":
                lt = new(sig, c, "PENDING_MARKET")
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
                b = gate(sig, c)  # re-check at the refined entry, as the legacy replay does
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
            if before == "PENDING":
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
            "cost_model": cost.as_dict(), "engine": ENGINE}


def _flags(lt: LabTrade, before: str, c: Candle) -> None:
    t = lt.trade
    s = t.signal
    tgt = s.targets[-1]
    reached = c.high >= tgt if s.direction == "BUY" else c.low <= tgt
    if t.status == "CLOSED" and t.exit_reason == "SL" and reached:
        lt.flags.append("AMBIGUOUS_STOP_AND_TARGET_SAME_BAR")
    elif before in ("PENDING", "PENDING_MARKET") and t.status == "OPEN" and reached:
        lt.flags.append("FILL_BAR_REACHED_TARGET")
