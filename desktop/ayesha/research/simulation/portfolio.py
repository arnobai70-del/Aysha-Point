"""Account simulation for the Strategy Lab (plan §6.3 portfolio bullet; ticket AI-009).

Takes the replayed orders of one strategy across one or more symbols and walks through them in time as one
hypothetical account would, with the live risk engine making every decision (`ayesha.risk.engine.evaluate`):
risk per trade from the spec (hard cap 1 %), lot floored to the 0.01 step, minimum lot, daily loss limit and two
losses a day, open-risk cap and one position per currency (correlated exposure), on an equity that changes with
every closed trade. Nothing is rounded up to make a trade possible; a small account simply gets NO_TRADE.

Decisions are made when the order is placed (the signal bar's close) with what is known then: positions and
pending orders still alive at that time, and the realised result of trades already closed. An accepted order keeps
its risk reserved until it is closed or has expired. Money values use ASSUMED Exness contract values (no broker
terminal) and approximate cross rates; equities are HYPOTHETICAL scenarios, never the owner's account.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from ayesha.feed.static_specs import assumed_fx_spec
from ayesha.models import AccountState
from ayesha.research.simulation.runner import APPROX_USD_RATES, LabTrade, risk_config
from ayesha.risk.engine import TradeProposal, evaluate
from ayesha.sessions import SessionEngine

END = datetime.max.replace(tzinfo=timezone.utc)
EQUITIES = (20.0, 25.0, 30.0, 100.0, 500.0, 1000.0, 5000.0)


def simulate(lab_trades: list[LabTrade], spec: dict[str, Any], equity: float, account_type: str = "Standard",
             commission_usd_per_lot: float = 0.0, usd_rates: dict[str, float] | None = None) -> dict[str, Any]:
    usd_rates = usd_rates if usd_rates is not None else APPROX_USD_RATES
    cfg = risk_config(spec)
    day_of = SessionEngine.trading_day
    orders = sorted((lt for lt in lab_trades if lt.trade.status not in ("BLOCKED",)),
                    key=lambda lt: (lt.created_at, lt.symbol, lt.trade.signal.signal_id))
    eq = peak = equity
    max_dd = max_dd_pct = 0.0
    live: list[dict[str, Any]] = []        # accepted, not yet ended
    realised: list[tuple] = []              # (ended_at, usd)
    day_loss: dict[Any, float] = {}
    day_losses: dict[Any, int] = {}
    skipped: dict[str, int] = {}
    taken = wins = 0
    worst_day = 0.0
    day_pnl: dict[Any, float] = {}
    curve: list[float] = []

    def settle(until) -> None:
        nonlocal eq, peak, max_dd, max_dd_pct, wins, worst_day
        for o in sorted([o for o in live if o["ended_at"] is not None and o["ended_at"] <= until],
                        key=lambda o: (o["ended_at"], o["id"])):
            live.remove(o)
            t = o["lt"].trade
            if t.status != "CLOSED":
                continue  # expired / missed / unconfirmed: nothing happened, the reserved risk is released
            usd = t.r * o["r_usd"] - o["commission"]
            eq += usd
            d = day_of(o["ended_at"])
            day_pnl[d] = day_pnl.get(d, 0.0) + usd
            worst_day = min(worst_day, day_pnl[d])
            if usd < 0:
                day_loss[d] = day_loss.get(d, 0.0) - usd
                day_losses[d] = day_losses.get(d, 0) + 1
            else:
                wins += 1
            realised.append((o["ended_at"], usd))
            peak = max(peak, eq)
            max_dd = max(max_dd, peak - eq)
            max_dd_pct = max(max_dd_pct, (peak - eq) / peak * 100 if peak > 0 else 0.0)
            curve.append(round(eq, 2))

    for lt in orders:
        t, s = lt.trade, lt.trade.signal
        settle(lt.created_at)
        if t.status.startswith("UNRESOLVED"):
            skipped["UNRESOLVED_END_OF_DATA"] = skipped.get("UNRESOLVED_END_OF_DATA", 0) + 1
            continue
        d = day_of(lt.created_at)
        acct = AccountState(equity_usd=eq, realized_loss_today_usd=day_loss.get(d, 0.0),
                            losses_today=day_losses.get(d, 0), open_risk_usd=sum(o["risk"] for o in live),
                            open_positions=[(o["lt"].symbol, o["lt"].trade.signal.direction) for o in live])
        inst = assumed_fx_spec(lt.symbol, s.entry, account_type, usd_rates)
        if commission_usd_per_lot:
            inst = replace(inst, commission_per_lot_round_trip=commission_usd_per_lot)
        prop = TradeProposal(lt.symbol, s.direction, s.entry, s.stop, s.targets, s.spread, s.atr, 0.0, True, "CLEAR")
        dec = evaluate(prop, inst, acct, cfg, live=False)
        if not dec.ok:
            reason = dec.blockers[0]
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        taken += 1
        # 1R in money = the replayed planned loss at this lot; the commission is charged on top of R
        live.append({"id": s.signal_id, "lt": lt, "ended_at": lt.ended_at, "risk": dec.max_loss_usd,
                     "r_usd": dec.lot * t.planned_loss * inst.tick_value / inst.tick_size,
                     "commission": dec.lot * inst.commission_per_lot_round_trip})
    settle(END)
    closed = len(realised)
    return {
        "equity_start_usd": equity, "equity_end_usd": round(eq, 2),
        "return_percent": round((eq - equity) / equity * 100, 2),
        "orders_considered": len(orders), "taken": taken, "closed": closed, "wins": wins,
        "skipped": dict(sorted(skipped.items())),
        "max_drawdown_usd": round(max_dd, 2), "max_drawdown_percent": round(max_dd_pct, 2),
        "worst_day_usd": round(worst_day, 2), "account_type": account_type,
        "risk_per_trade_percent": cfg.risk_per_trade_percent, "commission_usd_per_lot": commission_usd_per_lot,
        "equity_curve": curve[-400:],
        "basis": "HYPOTHETICAL equity, ASSUMED Exness contract values, approximate cross rates, news not modelled",
    }


def scenarios(lab_trades: list[LabTrade], spec: dict[str, Any], account_type: str = "Standard",
              equities=EQUITIES) -> list[dict[str, Any]]:
    out = []
    for e in equities:
        r = simulate(lab_trades, spec, e, account_type)
        r.pop("equity_curve")
        out.append(r)
    return out
