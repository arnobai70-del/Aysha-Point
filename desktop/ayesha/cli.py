"""Command line entry point. Every command is read-only / advisory; none can place orders."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ayesha.config import load_spec
from ayesha.feed.csv_feed import load_candles, save_candles
from ayesha.feed.static_specs import assumed_fx_spec
from ayesha.models import AccountState, pip_size_for
from ayesha.risk.engine import RiskConfig, TradeProposal, broker_order_prices, evaluate

# Rough prices only for offline what-if tables; real values come from `spec-check` (MT5).
APPROX = {"EURUSD": 1.08, "GBPUSD": 1.27, "USDJPY": 150.0, "AUDUSD": 0.66, "USDCAD": 1.37, "EURJPY": 162.0,
          "NZDUSD": 0.60, "USDCHF": 0.88, "EURGBP": 0.85}
APPROX_USD_RATES = {"JPY": 1 / 150.0, "GBP": 1.27, "CAD": 1 / 1.37, "CHF": 1 / 0.88}


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str, ensure_ascii=False))


def cmd_lot_table(a) -> int:
    spec = load_spec(a.spec)
    cfg = RiskConfig.from_spec(spec)
    pct = a.risk_percent or cfg.risk_per_trade_percent
    budget = a.equity * pct / 100
    print(f"Equity ${a.equity:.2f} | risk {pct}% = ${budget:.3f} per trade | account {a.account_type} "
          f"| specs ASSUMED (verify with spec-check)\n")
    stops = [int(s) for s in a.stops.split(",")]
    print(f"{'pair':8}" + "".join(f"{str(s)+'p SL':>16}" for s in stops))
    for sym in spec["pairs"]["enabled"]:
        inst = assumed_fx_spec(sym, APPROX[sym], a.account_type, APPROX_USD_RATES)
        row = f"{sym:8}"
        for s in stops:
            loss = inst.volume_min * (s * inst.pip_size / inst.tick_size) * inst.tick_value
            row += f"{f'${loss:.2f} ({100 * loss / a.equity:.2f}%)':>16}"
        print(row)
    print("\nEach cell = loss at the broker MINIMUM lot (0.01) if the stop is hit, before spread.")
    print(f"Any cell above {pct}% means that trade is NO_TRADE: MIN_LOT_EXCEEDS_RISK.")
    return 0


def cmd_risk(a) -> int:
    spec = load_spec(a.spec)
    cfg = RiskConfig.from_spec(spec)
    sym = a.symbol.upper()
    pip = pip_size_for(sym)
    inst = assumed_fx_spec(sym, a.entry, a.account_type, APPROX_USD_RATES)
    spread = a.spread_pips * pip
    prop = TradeProposal(sym, a.direction.upper(), a.entry, a.stop, tuple(a.target), spread, a.atr_pips * pip,
                         0.0, True, a.news)
    acct = AccountState(equity_usd=a.equity, losses_today=a.losses_today)
    d = evaluate(prop, inst, acct, cfg, live=False)
    out = asdict(d) | {"status": d.status, "spec_source": inst.source}
    if d.ok:
        out["broker_prices"] = broker_order_prices(prop.direction, a.entry, a.stop, a.target[-1], spread)
    _print(out)
    return 0 if d.ok else 2


def cmd_spec_check(a) -> int:  # pragma: no cover - needs Windows + MT5 terminal
    from ayesha.feed.mt5_feed import MT5ReadOnlyFeed

    spec = load_spec(a.spec)
    feed = MT5ReadOnlyFeed(server_utc_offset_hours=spec["feed"]["server_utc_offset_hours"])
    acct = feed.connect()
    print("Account (read-only):")
    _print(acct)
    try:
        raw = MT5ReadOnlyFeed(feed.mt5._m).quote(spec["pairs"]["enabled"][0])  # raw server time, no offset
        est = round((raw.time - datetime.now(timezone.utc)).total_seconds() / 3600)
        print(f"server_offset_estimate_hours: {est} (configured: {spec['feed']['server_utc_offset_hours']}; "
              "estimate is only meaningful while the market is open)")
    except Exception as e:
        print(f"server offset check skipped: {e}")
    budget = acct["equity"] * spec["risk"]["risk_per_trade_percent"] / 100
    rows = []
    for sym in spec["pairs"]["enabled"]:
        try:
            inst = feed.instrument(sym)
            q = feed.quote(sym)
        except Exception as e:  # report and continue
            rows.append({"symbol": sym, "error": str(e)})
            continue
        r = {"symbol": sym, "broker_symbol": inst.source.split(":", 1)[1], "contract": inst.contract_size,
             "min_lot": inst.volume_min, "step": inst.volume_step, "max_lot": inst.volume_max,
             "pip_value_per_lot": round(inst.pip_value_per_lot, 4), "spread_pips": round(q.spread / inst.pip_size, 2),
             "quote_age_s": round(q.age_seconds(), 1), "margin_per_lot": inst.margin_per_lot,
             "stops_level_points": inst.stops_level_points}
        for s in (10, 15, 20):
            loss = inst.volume_min * s * inst.pip_value_per_lot
            r[f"min_lot_loss_{s}p"] = f"${loss:.3f} ({100 * loss / acct['equity']:.2f}% equity)"
        rows.append(r)
    _print(rows)
    print(f"\nRisk budget per trade: ${budget:.3f}. Rows where min-lot loss > budget cannot be traded safely.")
    feed.close()
    return 0


def cmd_export(a) -> int:  # pragma: no cover - needs Windows + MT5 terminal
    from ayesha.feed.mt5_feed import MT5ReadOnlyFeed

    spec = load_spec(a.spec)
    feed = MT5ReadOnlyFeed(server_utc_offset_hours=spec["feed"]["server_utc_offset_hours"])
    feed.connect()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=a.days)
    bars = feed.candles(a.symbol, a.tf, start, end)
    inst = feed.instrument(a.symbol)
    # drop the still-forming last bar
    minutes = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}[a.tf]
    bars = [b for b in bars if b.time + timedelta(minutes=minutes) <= end]
    save_candles(a.out, bars, inst.point)
    print(f"Saved {len(bars)} closed {a.tf} bars for {a.symbol} to {a.out} (point={inst.point})")
    feed.close()
    return 0


def cmd_backtest(a) -> int:
    from ayesha.backtest.replay import capital_report, run_backtest, split_report, summarize
    from ayesha.news.calendar import NewsCalendar

    spec = load_spec(a.spec)
    sym = a.symbol.upper()
    point = 0.001 if pip_size_for(sym) == 0.01 else 0.00001
    candles = load_candles(a.csv, point)
    cal = None
    if a.news:
        n = spec["news"]
        cal = NewsCalendar.from_csv(a.news, before_min=n["block_minutes_before"], after_min=n["block_minutes_after"],
                                    impacts=tuple(n["impacts_blocked"]))
    res = run_backtest(sym, candles, spec, calendar=cal, equity_usd=a.equity, account_type=a.account_type,
                       usd_rates=APPROX_USD_RATES)
    trades = res["trades"]
    report = {
        "symbol": sym, "strategy_version": spec["strategy_version"], "strategy_hash": spec["strategy_hash"],
        "data": {"bars": res["bars"], "start": res["start"], "end": res["end"], "file": str(a.csv)},
        "news_modelled": res["news_modelled"],
        "all": summarize(trades),
        "a_plus_only": summarize([t for t in trades if t.signal.grade == "A_PLUS"]),
        "rejections": _count(r.reason for r in res["rejections"]),
        "blockers": _count(b for t in trades for b in t.blockers),
        "disclaimer": "Historical simulation. Not a profit forecast. Scores are not probabilities.",
    }
    if a.split:
        report["walk_forward_split"] = split_report(trades, datetime.fromisoformat(a.split).replace(tzinfo=timezone.utc))
    if a.equity is not None:
        report["capital"] = {"equity_usd": a.equity, "account_type": a.account_type} | capital_report(res["capital_checks"])
    if not res["news_modelled"]:
        report["warning"] = "No news calendar given: news lockout NOT modelled; live strict mode would block these."
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        if a.trades_csv:
            _write_trades(a.trades_csv, trades)
    _print(report)
    return 0


def _db_path(a) -> str:
    p = Path(a.db or Path.home() / "AyeshaFX" / "ayesha.db")
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def cmd_scan(a) -> int:  # pragma: no cover - needs Windows + MT5 terminal
    from ayesha.delivery.notify import ConsoleNotifier, TelegramNotifier
    from ayesha.feed.mt5_feed import MT5ReadOnlyFeed
    from ayesha.news.calendar import NewsCalendar
    from ayesha.scanner import Scanner
    from ayesha.storage.db import Registry

    spec = load_spec(a.spec)
    feed = MT5ReadOnlyFeed(server_utc_offset_hours=spec["feed"]["server_utc_offset_hours"])
    acct = feed.connect()
    print(f"Connected read-only: {acct['server']} {acct['trade_mode']} {acct['currency']} | strategy "
          f"{spec['strategy_version']} ({spec['strategy_hash']})")
    notifiers = [ConsoleNotifier()]
    if a.telegram:
        notifiers.append(TelegramNotifier())
    cal = None
    if a.news:
        n = spec["news"]
        cal = NewsCalendar.from_csv(a.news, before_min=n["block_minutes_before"], after_min=n["block_minutes_after"],
                                    impacts=tuple(n["impacts_blocked"]))
    elif spec["risk"]["strict_news"]:
        print("WARNING: no --news calendar. Strict mode => every candidate is NO_TRADE: NEWS_UNVERIFIED.")
    sc = Scanner(feed, spec, Registry(_db_path(a)), notifiers, cal)
    try:
        sc.run(max_loops=1 if a.once else None)
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        feed.close()
    return 0


def cmd_signals(a) -> int:
    from ayesha.storage.db import Registry

    reg = Registry(_db_path(a))
    if a.id:
        rec = reg.get(a.id) or next((reg.get(r["signal_id"]) for r in reg.recent(500)
                                     if r["signal_id"].startswith(a.id)), None)
        if rec is None:
            print("not found")
            return 1
        _print(rec | {"history": [dict(e) for e in reg.events(rec["signal_id"])]})
        return 0
    for r in reg.recent(a.limit):
        print(f"{r['event_time_utc'][:16]}  {r['symbol']:7} {r['direction']:4} {r['grade']:7} {r['status']:18} {r['signal_id']}")
    return 0


def cmd_mark(a) -> int:
    from ayesha.storage.db import Registry

    reg = Registry(_db_path(a))
    action = "PLACED" if a.placed else "CLOSED"
    reg.journal(action, a.id, a.pnl, a.note or "")
    print(f"Journal: {action} {a.id} pnl={a.pnl}")
    return 0


def cmd_telegram_test(a) -> int:
    from ayesha.delivery.notify import TelegramNotifier

    ok, detail = TelegramNotifier().send_text("AYESHA FX test message. Advisory alerts only.")
    print("OK" if ok else f"FAILED: {detail}")
    return 0 if ok else 1


def _count(it) -> dict[str, int]:
    out: dict[str, int] = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _write_trades(path: str, trades) -> None:
    import csv

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["signal_id", "time_utc", "direction", "grade", "score", "entry", "stop", "target", "status",
                    "exit_reason", "r", "blockers"])
        for t in trades:
            s = t.signal
            w.writerow([s.signal_id, s.bar_close_utc.isoformat(), s.direction, s.grade, s.score, s.entry, s.stop,
                        s.targets[-1], t.status, t.exit_reason, t.r, "|".join(t.blockers)])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ayesha", description="AYESHA FX advisory tools (no order execution)")
    p.add_argument("--spec", default=None, help="path to strategy-spec.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("lot-table", help="min-lot loss vs equity for typical stops (offline)")
    s.add_argument("--equity", type=float, required=True)
    s.add_argument("--risk-percent", type=float)
    s.add_argument("--account-type", default="Standard", choices=["Standard", "StandardCent"])
    s.add_argument("--stops", default="8,10,15,20,30")
    s.set_defaults(fn=cmd_lot_table)

    s = sub.add_parser("risk", help="size one trade idea and run every hard gate")
    s.add_argument("--equity", type=float, required=True)
    s.add_argument("--symbol", required=True)
    s.add_argument("--direction", required=True, choices=["BUY", "SELL", "buy", "sell"])
    s.add_argument("--entry", type=float, required=True)
    s.add_argument("--stop", type=float, required=True)
    s.add_argument("--target", type=float, action="append", required=True)
    s.add_argument("--spread-pips", type=float, default=1.0)
    s.add_argument("--atr-pips", type=float, default=0.0)
    s.add_argument("--news", default="UNKNOWN", choices=["CLEAR", "BLOCKED", "UNKNOWN"])
    s.add_argument("--losses-today", type=int, default=0)
    s.add_argument("--account-type", default="Standard", choices=["Standard", "StandardCent"])
    s.set_defaults(fn=cmd_risk)

    s = sub.add_parser("spec-check", help="read real contract specs from the local MT5 terminal (Windows)")
    s.set_defaults(fn=cmd_spec_check)

    s = sub.add_parser("export", help="export closed bars from MT5 to CSV (Windows)")
    s.add_argument("--symbol", required=True)
    s.add_argument("--tf", default="M15", choices=["M1", "M5", "M15", "H1", "H4", "D1"])
    s.add_argument("--days", type=int, default=730)
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("backtest", help="bar-by-bar replay of SWEEP_MSS_FVG on a CSV")
    s.add_argument("--csv", required=True)
    s.add_argument("--symbol", required=True)
    s.add_argument("--news", help="calendar CSV (time_utc,currency,impact,title)")
    s.add_argument("--equity", type=float, help="also report how many signals the min lot allows")
    s.add_argument("--account-type", default="Standard", choices=["Standard", "StandardCent"])
    s.add_argument("--split", help="walk-forward split date, e.g. 2025-07-01")
    s.add_argument("--out", help="write JSON report")
    s.add_argument("--trades-csv", help="write per-signal CSV (with --out)")
    s.set_defaults(fn=cmd_backtest)

    s = sub.add_parser("scan", help="live advisory scanner on the local MT5 terminal (Windows)")
    s.add_argument("--db")
    s.add_argument("--news", help="calendar CSV")
    s.add_argument("--telegram", action="store_true", help="also send READY alerts to Telegram")
    s.add_argument("--once", action="store_true", help="warm up, run one pass, exit")
    s.set_defaults(fn=cmd_scan)

    s = sub.add_parser("signals", help="list recent signals, or show one with --id")
    s.add_argument("--db")
    s.add_argument("--id")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(fn=cmd_signals)

    s = sub.add_parser("mark", help="journal a manual trade: --placed, or --closed --pnl -0.10")
    s.add_argument("--db")
    s.add_argument("--id", required=True)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--placed", action="store_true")
    g.add_argument("--closed", action="store_true")
    s.add_argument("--pnl", type=float, help="realized USD incl. fees (for --closed)")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_mark)

    s = sub.add_parser("telegram-test", help="send a test Telegram message")
    s.set_defaults(fn=cmd_telegram_test)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
