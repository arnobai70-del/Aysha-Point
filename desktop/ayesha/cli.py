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


def _make_feed(a, spec):  # pragma: no cover - needs MT5 terminal or an OANDA token + network
    """MT5 (Windows terminal) or OANDA v20 (any PC, no MT5). Both are read-only."""
    if a.feed == "oanda":
        from ayesha.feed.oanda_feed import OandaFeed

        return OandaFeed(equity_usd=a.equity or 0, account_type=a.account_type, environment=a.oanda_env)
    from ayesha.feed.mt5_feed import MT5ReadOnlyFeed

    return MT5ReadOnlyFeed(server_utc_offset_hours=spec["feed"]["server_utc_offset_hours"])


def cmd_export(a) -> int:  # pragma: no cover - needs a data feed
    spec = load_spec(a.spec)
    if a.feed == "oanda" and not a.equity:
        a.equity = 1.0  # export only reads prices; equity is not used
    feed = _make_feed(a, spec)
    feed.connect()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=a.days)
    bars = feed.candles(a.symbol, a.tf, start, end)
    point = 0.001 if a.symbol.upper().endswith("JPY") else 0.00001
    # drop the still-forming last bar
    minutes = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}[a.tf]
    bars = [b for b in bars if b.time + timedelta(minutes=minutes) <= end]
    save_candles(a.out, bars, point)
    src = getattr(feed, "source_name", "MT5")
    print(f"Saved {len(bars)} closed {a.tf} BID bars for {a.symbol} from {src} to {a.out} (spread column = ask-bid)")
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


def cmd_report(a) -> int:
    """Validation report over several pairs and MTF modes from exported CSVs (<data-dir>/<PAIR>_<TF>.csv)."""
    import copy

    from ayesha.backtest.replay import run_backtest
    from ayesha.backtest.report import build_report, to_markdown
    from ayesha.news.calendar import NewsCalendar

    spec = load_spec(a.spec)
    d = Path(a.data_dir)
    pairs = [x.strip().upper() for x in (a.pairs or ",".join(spec["pairs"]["enabled"])).split(",") if x.strip()]
    modes = [m.strip() for m in a.modes.split(",") if m.strip()]
    cal = None
    if a.news:
        n = spec["news"]
        cal = NewsCalendar.from_csv(a.news, before_min=n["block_minutes_before"], after_min=n["block_minutes_after"],
                                    impacts=tuple(n["impacts_blocked"]))
    results, missing = {}, []
    for pair in pairs:
        point = 0.001 if pip_size_for(pair) == 0.01 else 0.00001
        for mode in modes:
            sp = copy.deepcopy(spec)
            if mode == "m15":
                sp["mtf"]["confirm_timeframe"] = None
                f = d / f"{pair}_M15.csv"
            elif mode == "m5confirm":
                sp["mtf"]["confirm_timeframe"] = "M5"
                f = d / f"{pair}_M5.csv"
            else:
                print(f"unknown mode {mode} (use m15, m5confirm)")
                return 2
            if not f.exists():
                missing.append(str(f))
                continue
            candles = load_candles(f, point)
            sp["strategy_hash"] = spec["strategy_hash"]
            results[f"{pair}|{mode}"] = run_backtest(pair, candles, sp, calendar=cal, account_type=a.account_type,
                                                     usd_rates=APPROX_USD_RATES)
            print(f"{pair} {mode}: {len(candles)} bars, {len(results[f'{pair}|{mode}']['trades'])} signals")
    if not results:
        print("No data files found. Export first, e.g.: ayesha export --feed oanda --symbol EURUSD --tf M15 "
              f"--days 1095 --out {d / 'EURUSD_M15.csv'}")
        return 1
    split = datetime.fromisoformat(a.split).replace(tzinfo=timezone.utc) if a.split else None
    rep = build_report(results, spec, split_at=split, folds=a.folds, data_label=a.label, usd_rates=APPROX_USD_RATES)
    rep["missing_files"] = missing
    if cal is None:
        rep["notes"].append("No news calendar given: news lockout NOT modelled; live strict mode blocks more setups.")
    md = to_markdown(rep)
    if a.out:
        Path(a.out).write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    if a.md:
        Path(a.md).write_text(md, encoding="utf-8")
    print(md)
    return 0


def cmd_doctor(a) -> int:  # pragma: no cover - network; logic tested via run_doctor
    from ayesha.doctor import run_doctor

    rows = run_doctor(account_type=a.account_type, oanda_env=a.oanda_env, publish=not a.no_publish)
    for ok, name, detail in rows:
        print(f"{'OK  ' if ok else 'FAIL'}  {name}: {detail}")
    bad = [r for r in rows if not r[0]]
    print("\nAll checks passed." if not bad else f"\n{len(bad)} check(s) failed. READY alerts stay blocked until fixed.")
    return 0 if not bad else 1


def _db_path(a) -> str:
    p = Path(a.db or Path.home() / "AyeshaFX" / "ayesha.db")
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def cmd_scan(a) -> int:  # pragma: no cover - needs a live data feed
    from ayesha.delivery.notify import ConsoleNotifier, TelegramNotifier
    from ayesha.news.calendar import NewsCalendar
    from ayesha.scanner import Scanner
    from ayesha.storage.db import Registry

    spec = load_spec(a.spec)
    if a.feed == "oanda" and not (a.equity and a.equity > 0):
        print("--equity (your Exness equity in USD) is required with --feed oanda")
        return 2
    feed = _make_feed(a, spec)
    acct = feed.connect()
    print(f"Connected read-only: {acct['server']} {acct['trade_mode']} {acct['currency']} | strategy "
          f"{spec['strategy_version']} ({spec['strategy_hash']})")
    notifiers = [ConsoleNotifier()]
    if a.telegram:
        notifiers.append(TelegramNotifier())
    if a.push:
        from ayesha.delivery.push import NtfyNotifier, load_or_create_code

        notifiers.append(NtfyNotifier(load_or_create_code()))
        print("Phone push: ON (ntfy.sh relay, signed). Pairing code: `ayesha pair`.")
    n = spec["news"]
    news_kw = dict(before_min=n["block_minutes_before"], after_min=n["block_minutes_after"],
                   impacts=tuple(n["impacts_blocked"]))
    cal = None
    if a.news:
        cal = NewsCalendar.from_csv(a.news, **news_kw)
    elif a.news_ff:
        from ayesha.news.ff_feed import FFCalendarSource

        src = FFCalendarSource(Path(_db_path(a)).parent / "ff_calendar.json")
        cal = src.calendar(**news_kw)
        if cal is None:
            print(f"WARNING: Forex Factory calendar unavailable ({src.last_error}). Signals => NEWS_UNVERIFIED.")
    elif spec["risk"]["strict_news"]:
        print("WARNING: no --news / --news-ff calendar. Strict mode => every candidate is NO_TRADE: NEWS_UNVERIFIED.")
    if a.feed == "oanda":
        from ayesha.broker import load_confirmed

        if load_confirmed(a.account_type) is None:
            print("WARNING: Exness contract not confirmed (`ayesha confirm-broker`). Signals => CONTRACT_SPEC_UNVERIFIED.")
    sc = Scanner(feed, spec, Registry(_db_path(a)), notifiers, cal)
    try:
        sc.run(max_loops=1 if a.once else None)
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        feed.close()
    return 0


def cmd_pair(a) -> int:
    from ayesha.delivery.push import default_code_path, load_or_create_code, topic_for

    p = default_code_path()
    if a.new and p.exists():
        p.unlink()
    code = load_or_create_code()
    pretty = "-".join(code[i:i + 4] for i in range(0, 16, 4))
    print(f"Pairing code: {pretty}")
    print("Type it in the AYESHA app: Settings -> PC link -> Pairing code. Keep it private.")
    print(f"(relay topic: {topic_for(code)}; stored in {p})")
    return 0


def cmd_push_test(a) -> int:  # pragma: no cover - network
    from ayesha.delivery.push import NtfyNotifier, load_or_create_code

    n = NtfyNotifier(load_or_create_code())
    ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    ok, detail = n.heartbeat(ms, "TEST", 0, load_spec(a.spec)["strategy_hash"])
    print("OK: test heartbeat sent; the app should show 'PC link: test received'" if ok else f"FAILED: {detail}")
    return 0 if ok else 1


def cmd_confirm_broker(a) -> int:  # pragma: no cover - interactive
    from ayesha.broker import FIELDS, load_assumed, save_confirmed

    base = load_assumed(a.account_type)
    print(f"Open the Exness app -> EURUSD -> Specification (account type {a.account_type}).")
    print("Type each value exactly as shown there. Press Enter to cancel.")
    vals = {}
    for k in FIELDS:
        raw = input(f"  {k} (repo assumption {base[k]}): ").strip()
        if not raw:
            print("Cancelled; nothing saved.")
            return 1
        vals[k] = float(raw)
    if any(abs(vals[k] - float(base[k])) > 1e-9 for k in FIELDS):
        print("NOTE: values differ from the repo assumption; your typed values will be used.")
    path = save_confirmed(a.account_type, vals)
    print(f"Saved owner-confirmed spec to {path}")
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
    a = build_parser().parse_args(argv)
    return a.fn(a)


def build_parser() -> argparse.ArgumentParser:
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

    def feed_args(s, need_equity=False):
        s.add_argument("--feed", default="mt5", choices=["mt5", "oanda"],
                       help="mt5 = local MT5 terminal; oanda = OANDA v20 API (no MT5, token in AYESHA_OANDA_TOKEN)")
        s.add_argument("--oanda-env", default="practice", choices=["practice", "live"])
        s.add_argument("--equity", type=float, help="your Exness equity in USD (required with --feed oanda for scan)")
        s.add_argument("--account-type", default="Standard", choices=["Standard", "StandardCent"])

    s = sub.add_parser("export", help="export closed bars to CSV from MT5 or OANDA")
    feed_args(s)
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

    s = sub.add_parser("report", help="validation report: pairs x modes, in/out-of-sample, walk-forward, $ feasibility")
    s.add_argument("--data-dir", required=True, help="folder with <PAIR>_M15.csv and/or <PAIR>_M5.csv")
    s.add_argument("--pairs", help="comma list (default: enabled pairs)")
    s.add_argument("--modes", default="m15,m5confirm", help="m15 = M15 setup only; m5confirm = wait for M5 confirmation")
    s.add_argument("--news", help="historical calendar CSV (time_utc,currency,impact,title)")
    s.add_argument("--split", help="in-sample / out-of-sample split date, e.g. 2025-01-01")
    s.add_argument("--folds", type=int, default=4)
    s.add_argument("--label", default="UNLABELLED data", help="data source description shown in the report")
    s.add_argument("--account-type", default="Standard", choices=["Standard", "StandardCent"])
    s.add_argument("--out", help="write JSON")
    s.add_argument("--md", help="write Markdown")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("doctor", help="check token, OANDA, broker spec, pairing, calendar and phone relay")
    s.add_argument("--account-type", default="Standard", choices=["Standard", "StandardCent"])
    s.add_argument("--oanda-env", default="practice", choices=["practice", "live"])
    s.add_argument("--no-publish", action="store_true", help="skip the relay publish test")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("scan", help="live advisory scanner (MT5 terminal or OANDA data, no orders)")
    feed_args(s)
    s.add_argument("--db")
    s.add_argument("--news", help="calendar CSV")
    s.add_argument("--news-ff", action="store_true", help="use the Forex Factory weekly calendar export (cached)")
    s.add_argument("--push", action="store_true", help="send signals + heartbeat to the AYESHA phone app (ntfy.sh)")
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

    s = sub.add_parser("pair", help="show (or with --new, replace) the phone pairing code")
    s.add_argument("--new", action="store_true")
    s.set_defaults(fn=cmd_pair)

    s = sub.add_parser("push-test", help="send a signed test heartbeat to the phone app")
    s.set_defaults(fn=cmd_push_test)

    s = sub.add_parser("confirm-broker", help="type the Exness contract values from the Exness app (no MT5)")
    s.add_argument("--account-type", default="Standard", choices=["Standard", "StandardCent"])
    s.set_defaults(fn=cmd_confirm_broker)

    return p


if __name__ == "__main__":
    sys.exit(main())
