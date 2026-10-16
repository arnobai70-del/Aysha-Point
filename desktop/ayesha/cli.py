"""Command line entry point. Every command is read-only / advisory; none can place orders."""

from __future__ import annotations

import argparse
import json
import os
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

        return OandaFeed(equity_usd=getattr(a, "equity", None) or None, account_type=a.account_type,
                         environment=a.oanda_env)
    from ayesha.feed.mt5_feed import MT5ReadOnlyFeed

    return MT5ReadOnlyFeed(server_utc_offset_hours=spec["feed"]["server_utc_offset_hours"])


# Exit codes the Windows start script understands: CONFIG and AUTH stop the restart loop.
EXIT_CONFIG, EXIT_AUTH, EXIT_NETWORK = 2, 3, 4


def _connect(a, spec):
    """(exit code, feed, account). Never prints the token."""
    from ayesha.credentials import redact

    try:
        feed = _make_feed(a, spec)
    except Exception as e:
        print("CONFIG ERROR: " + redact(str(e)))
        return EXIT_CONFIG, None, None
    try:
        return 0, feed, feed.connect()
    except Exception as e:
        if type(e).__name__ == "AuthRejected":
            print("TOKEN REJECTED: " + redact(str(e)))
            return EXIT_AUTH, None, None
        print(f"FEED UNREACHABLE ({type(e).__name__}): " + redact(str(e))[:200] + " - will retry")
        return EXIT_NETWORK, None, None


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

    from ayesha.backtest.replay import NEWS_MODES

    spec = load_spec(a.spec)
    d = Path(a.data_dir)
    pairs = [x.strip().upper() for x in (a.pairs or ",".join(spec["pairs"]["enabled"])).split(",") if x.strip()]
    modes = [m.strip() for m in a.modes.split(",") if m.strip()]
    news_modes = [m.strip() for m in (getattr(a, "news_modes", None) or ",".join(NEWS_MODES)).split(",") if m.strip()]
    if any(m not in NEWS_MODES for m in news_modes):
        print(f"unknown news mode in {news_modes} (use {', '.join(NEWS_MODES)})")
        return 2
    cal, cal_sha = None, None
    if a.news:
        import hashlib

        n = spec["news"]
        cal = NewsCalendar.from_csv(a.news, before_min=n["block_minutes_before"], after_min=n["block_minutes_after"],
                                    impacts=tuple(n["impacts_blocked"]))
        cal_sha = hashlib.sha256(Path(a.news).read_bytes()).hexdigest()
    strictest = next((m for m in ("upgraded", "legacy", "none") if m in news_modes), "none")
    results, comparisons, missing = {}, {}, []
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
            key = f"{pair}|{mode}"
            if cal is None:
                results[key] = run_backtest(pair, candles, sp, account_type=a.account_type, usd_rates=APPROX_USD_RATES)
            else:
                f5 = d / f"{pair}_M5.csv"  # closed M5 bars for the upgraded guard's post-news stability check
                m5 = load_candles(f5, point) if mode == "m15" and f5.exists() else None
                comparisons[key] = {nm: run_backtest(pair, candles, sp, calendar=cal, news_mode=nm, m5_candles=m5,
                                                     account_type=a.account_type, usd_rates=APPROX_USD_RATES)
                                    for nm in news_modes}
                results[key] = comparisons[key][strictest]
            print(f"{pair} {mode}: {len(candles)} bars, {len(results[key]['trades'])} signals")
    if not results:
        print("No data files found. Export first, e.g.: ayesha export --feed oanda --symbol EURUSD --tf M15 "
              f"--days 1095 --out {d / 'EURUSD_M15.csv'}")
        return 1
    split = datetime.fromisoformat(a.split).replace(tzinfo=timezone.utc) if a.split else None
    rep = build_report(results, spec, split_at=split, folds=a.folds, data_label=a.label, usd_rates=APPROX_USD_RATES,
                       comparisons=comparisons or None)
    rep["missing_files"] = missing
    if cal is not None:
        rep["news"]["calendar_file"] = Path(a.news).name
        rep["news"]["calendar_sha256"] = cal_sha
    md = to_markdown(rep)
    if a.out:
        Path(a.out).write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    if a.md:
        Path(a.md).write_text(md, encoding="utf-8")
    print(md)
    return 0


def cmd_set_token(a) -> int:
    from ayesha.credentials import delete_token, read_hidden, save_token

    if a.remove:
        delete_token()
        print("OANDA token removed from this Windows user.")
        return 0
    tok = read_hidden("Paste the OANDA practice token (input hidden) and press Enter: ").strip()
    if not tok:
        print("Nothing entered; nothing changed.")
        return 1
    try:
        save_token(tok)
    except (ValueError, RuntimeError) as e:
        print(f"NOT SAVED: {e}")
        return EXIT_CONFIG
    print(f"Token saved for this Windows user ({len(tok)} characters). It is not shown or stored anywhere else.")
    return 0


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def _parse_positions(raw: str):
    from ayesha.capital import validate_position

    out = []
    for part in [x.strip() for x in raw.split(",") if x.strip()]:
        bits = part.split()
        if len(bits) not in (2, 3):
            raise ValueError(f"write each trade as PAIR SIDE [risk USD], e.g. EURUSD BUY 0.50 (got {part!r})")
        out.append(validate_position(*bits))
    return out


def _capital_prompt(book, account_type: str) -> int:
    """Ask for the current Exness equity and open trades. Enter keeps the equity (a confirmation)."""
    from ayesha.capital import CURRENCY, CapitalError, validate_amount

    try:
        cur = book.latest()
    except CapitalError as e:
        print(f"{e}. Starting a new capital history.")
        book.path.rename(book.path.with_suffix(".corrupt.json"))
        cur = None
    unit = CURRENCY[account_type]
    if cur is not None and cur.account_type != account_type:
        cur = None
    while True:
        hint = f" (Enter = unchanged {cur.equity:g} {unit})" if cur else ""
        raw = _ask(f"Equity shown in Exness now, in {unit}{hint}: ")
        try:
            eq = cur.equity if (cur and not raw) else validate_amount(raw)
            break
        except Exception:
            print("Please type a positive number with at most 2 decimals, e.g. 25 or 25.40.")
    reason, amount = ("CONFIRM" if cur and eq == cur.equity else "UPDATE"), 0.0
    if cur and eq != cur.equity:
        k = _ask("Was the change a deposit or withdrawal? D = deposit, W = withdrawal, Enter = trading result: ").upper()
        if k in ("D", "W"):
            reason, amount = ("DEPOSIT", eq - cur.equity) if k == "D" else ("WITHDRAWAL", cur.equity - eq)
            amount = abs(round(amount, 2)) or 0.01
    while True:
        raw = _ask('Open trades in Exness right now? Enter = none, or e.g. "EURUSD BUY 0.50, GBPUSD SELL": ')
        try:
            positions = _parse_positions(raw)
            break
        except (ValueError, CapitalError) as e:
            print(f"Not understood: {e}")
    fm = None
    while positions and fm is None:
        try:
            fm = validate_amount(_ask(f"Free margin shown in Exness, in {unit}: "), "free margin")
        except Exception:
            print("Please type the free margin as a number.")
    try:
        snap = book.record(eq, account_type, reason, amount, positions, fm)
    except CapitalError as e:
        print(f"Not saved: {e}")
        return EXIT_CONFIG
    print(f"Capital confirmed: {snap.equity:g} {unit} (v{snap.version}, {snap.reason.lower()}, owner-entered, "
          f"{len(snap.open_positions)} open trade(s)). Valid for READY sizing for "
          f"{'4' if reason in ('DEPOSIT', 'WITHDRAWAL') else '24'} h; update it with `ayesha capital`.")
    return 0


def _print_capital_history(book, policy: dict, days: int, db: str | None) -> int:
    """Risk history: capital snapshots, the cash-flow-adjusted 7-day change and the owner's own journal.
    Everything stays on this PC; nothing here is a forecast."""
    from ayesha.capital import CapitalError, cash_flow_usd, trading_change, warnings

    try:
        hist = book.history()
    except CapitalError as e:
        print(f"CONFIG ERROR: {e}")
        return EXIT_CONFIG
    if not hist:
        print("No capital snapshot yet: run `ayesha capital`.")
        return EXIT_CONFIG
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    shown = [s for s in hist if s.entered_at >= since] or hist[-1:]
    print(f"Capital history, last {days} days (owner-entered from the Exness app; never sent anywhere):")
    print("  v    entered (UTC)     reason      equity          cash flow   open trades  positions confirmed")
    for s in shown:
        cf = cash_flow_usd(s)
        pc = f"{s.positions_confirmed_at:%Y-%m-%d %H:%M}" if s.positions_confirmed_at else "not confirmed"
        print(f"  {s.version:<4} {s.entered_at:%Y-%m-%d %H:%M}  {s.reason:<11} {s.equity:>10.2f} {s.currency}  "
              f"{(f'{cf:+.2f} USD' if cf else '-'):>11}  {len(s.open_positions):>11}  {pc}")
    ch = trading_change(hist, now, 7.0)
    if ch:
        pct = "n/a" if ch["trading_change_percent"] is None else f"{ch['trading_change_percent']:+.2f}%"
        print(f"\nLast 7 days, deposits/withdrawals excluded: {ch['start_equity_usd']:.2f} -> {ch['latest_equity_usd']:.2f} USD "
              f"(cash flow {ch['net_cash_flow_usd']:+.2f}), trading change {ch['trading_change_usd']:+.2f} USD ({pct}), "
              f"{ch['drawdown_percent'] or 0:.2f}% below the week's high")
    if db and Path(db).exists():
        from ayesha.storage.db import Registry

        rows = Registry(db).closed_since(since)
        pnl = [r["pnl_usd"] for r in rows if r["pnl_usd"] is not None]
        print(f"Your journal (`ayesha mark`), last {days} days: {len(rows)} closed, {sum(1 for x in pnl if x < 0)} losses, "
              f"realized {sum(pnl):+.2f} USD. Journal results are your own marks, never backtest numbers.")
    for w in warnings(hist, now, policy):
        print(f"WARNING {w}")
    print("Hard limits stay on whatever this shows: 2 losses or 2% loss per day, 1% open risk, 1% per trade at most.")
    return 0


def cmd_capital(a) -> int:
    """Update or show the owner's Exness capital snapshot (the only capital AYESHA sizes from)."""
    from ayesha.capital import CapitalBook, CapitalError, check, warnings

    book = CapitalBook(Path(a.file) if a.file else None)
    policy = load_spec(a.spec).get("capital", {})
    if a.history:
        return _print_capital_history(book, policy, a.days, a.db or str(_default_db()))
    if a.show:
        try:
            hist = book.history()
        except CapitalError as e:
            print(f"CONFIG ERROR: {e}")
            return EXIT_CONFIG
        snap = hist[-1] if hist else None
        c = check(snap, datetime.now(timezone.utc), policy, a.account_type)
        if snap is None:
            print("No capital snapshot yet: run `ayesha capital`.")
            return EXIT_CONFIG
        print(f"v{snap.version} {snap.equity:g} {snap.currency} entered {snap.entered_at:%Y-%m-%d %H:%M} UTC "
              f"({snap.reason}); open trades {len(snap.open_positions)}; status {c.label}")
        for w in warnings(hist, datetime.now(timezone.utc), policy):
            print(f"WARNING {w}")
        return 0 if c.ok else 1
    if a.session_start:
        interactive = sys.stdin.isatty() and not os.environ.get("AYESHA_NONINTERACTIVE")
        if not interactive:
            return 0
        print("\n=== Capital check for this session (Exness app -> Accounts) ===")
        try:
            for w in warnings(book.history(), datetime.now(timezone.utc), policy):
                print(f"WARNING {w}")
        except CapitalError:
            pass  # the prompt below explains and starts a new history
        return _capital_prompt(book, a.account_type)
    if a.equity is None:
        return _capital_prompt(book, a.account_type)
    reason = "DEPOSIT" if a.deposit else "WITHDRAWAL" if a.withdrawal else ("CONFIRM" if a.confirm else "UPDATE")
    try:
        positions = [] if a.no_positions or not a.positions else _parse_positions(a.positions)
        snap = book.record(a.equity, a.account_type, reason, a.deposit or a.withdrawal or 0, positions,
                           a.free_margin, positions_confirmed=bool(a.no_positions or a.positions))
    except (CapitalError, ValueError) as e:
        print(f"CONFIG ERROR: {e}")
        return EXIT_CONFIG
    print(f"Capital v{snap.version}: {snap.equity:g} {snap.currency} ({snap.reason}) at {snap.entered_at:%Y-%m-%d %H:%M} UTC")
    if snap.positions_confirmed_at != snap.entered_at:
        print("Open trades not confirmed (use --no-positions or --positions): READY stays blocked "
              "(POSITION_STATE_UNVERIFIED) until you confirm them.")
    return 0


def cmd_setup(a) -> int:
    """Interactive one-time setup used by install.bat. Safe to run again: Enter keeps each value."""
    import shutil

    from ayesha.broker import load_confirmed
    from ayesha.credentials import get_token, read_hidden, save_token
    from ayesha.delivery.push import load_or_create_code
    from ayesha.paths import home

    h = home()
    h.mkdir(parents=True, exist_ok=True)
    print(f"\n=== 1/5 OANDA practice token (price data only; stored in your Windows user settings) ===")
    have = bool(get_token())
    for attempt in range(3):
        tok = read_hidden("Token (hidden; Enter = keep current): " if have else "Token (hidden): ").strip()
        if not tok:
            print("Kept the current token." if have else "No token yet: the scanner cannot read prices until you add one.")
            break
        try:
            save_token(tok)
            print(f"Token saved ({len(tok)} characters).")
            break
        except (ValueError, RuntimeError) as e:
            print(f"Not saved: {e}")

    print("\n=== 2/5 Your Exness capital (Exness app -> Accounts) ===")
    from ayesha.capital import CapitalBook

    _capital_prompt(CapitalBook(), a.account_type)

    print("\n=== 3/5 Exness contract per pair (Exness app: pair -> Specification) ===")
    from ayesha.broker import confirmed_symbols, load_leverage

    spec = load_spec(a.spec)
    pairs = [x.upper() for x in spec["pairs"]["enabled"]]
    done = confirmed_symbols(a.account_type)
    if set(pairs) - set(done) or load_leverage(a.account_type) is None or \
            _ask(f"Already confirmed for {len(done)} pairs. Type Y to enter the values again: ").upper() == "Y":
        a.symbols = ",".join(pairs)
        cmd_confirm_broker(a)

    print("\n=== 4/5 Phone pairing ===")
    code = load_or_create_code()
    print("Pairing code: " + "-".join(code[i:i + 4] for i in range(0, 16, 4)))
    print("Type it in the AYESHA app: Settings -> PC link -> Pairing code, tick PC link, Save.")

    print("\n=== 5/5 Health check ===")
    from ayesha.doctor import run_doctor

    rows = run_doctor(account_type=a.account_type, publish=not a.no_publish)
    for ok, name, detail in rows:
        print(f"{'OK  ' if ok else 'FAIL'}  {name}: {detail}")

    if a.startup_script and sys.platform == "win32":
        if _ask("\nStart the scanner automatically when you log on to Windows? (Y/N): ").upper() == "Y":
            startup = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            shutil.copyfile(a.startup_script, startup / "AYESHA FX scanner.bat")
            print("Added to Startup. Delete 'AYESHA FX scanner.bat' from the Startup folder to undo.")
    bad = sum(1 for r in rows if not r[0])
    print("\nSetup finished." + (f" {bad} check(s) still FAIL; READY alerts stay blocked until they pass." if bad else ""))
    return 0


def cmd_backtest_run(a) -> int:  # export part needs network; validation is tested
    """Validated, token-safe multi-year run: OANDA export (M15 + M5) -> validation report.
    Used by desktop\\windows\\backtest-local.bat and the GitHub `backtest` workflow."""
    from argparse import Namespace

    from ayesha.backtest.inputs import InvalidInput, validate
    from ayesha.paths import home

    spec = load_spec(a.spec)
    try:
        prm = validate(a.pairs or ",".join(spec["pairs"]["enabled"]), str(a.days), a.split or "", str(a.folds),
                       spec["pairs"]["enabled"])
    except InvalidInput as e:
        print(f"INVALID INPUT: {e}")
        return EXIT_CONFIG
    if a.news and not (Path(a.news).is_file() and Path(a.news).suffix.lower() == ".csv"):
        print("INVALID INPUT: news: give an existing .csv calendar file")
        return EXIT_CONFIG
    print(f"pairs={','.join(prm.pairs)} days={prm.days} split={prm.split} folds={prm.folds}"
          + (f" news={Path(a.news).name}" if a.news else " news=NOT MODELLED"))
    if a.validate_only:
        return 0
    end = datetime.now(timezone.utc)
    out = Path(a.out_dir) if a.out_dir else home() / "backtest" / end.strftime("%Y%m%d-%H%M%S")
    data = out / "data"
    data.mkdir(parents=True, exist_ok=True)
    a.feed, a.equity = "oanda", 1.0  # equity is not used for exports
    rc, feed, _ = _connect(a, spec)
    if rc:
        return rc
    start = end - timedelta(days=prm.days)
    for pair in prm.pairs:
        point = 0.001 if pip_size_for(pair) == 0.01 else 0.00001
        for tf, minutes in (("M15", 15), ("M5", 5)):
            bars = [b for b in feed.candles(pair, tf, start, end) if b.time + timedelta(minutes=minutes) <= end]
            save_candles(data / f"{pair}_{tf}.csv", bars, point)
            print(f"{pair} {tf}: {len(bars)} closed bars")
    label = f"OANDA v20 {a.oanda_env} BID bars, {prm.days} days to {end:%Y-%m-%d} (exported {end:%Y-%m-%d %H:%M} UTC)"
    ns = Namespace(spec=a.spec, data_dir=str(data), pairs=",".join(prm.pairs), modes="m15,m5confirm", news=a.news,
                   split=prm.split.isoformat(), folds=prm.folds, label=label, account_type=a.account_type,
                   out=str(out / "backtest-report.json"), md=str(out / "backtest-report.md"))
    rc = cmd_report(ns)
    print(f"\nReport: {out / 'backtest-report.md'}")
    return rc


def cmd_make_signing_key(a) -> int:
    from ayesha.paths import home

    try:
        from ayesha.signing import make_key
    except ImportError:
        print("Install the signing extra first: pip install -e .[signing]")
        return EXIT_CONFIG
    try:
        r = make_key(Path(a.out_dir) if a.out_dir else home() / "signing", alias=a.alias)
    except FileExistsError as e:
        print(f"NOT CREATED: {e}")
        return 1
    except ImportError:
        print("Install the signing extra first: pip install -e .[signing]")
        return EXIT_CONFIG
    print(f"Keystore: {r['keystore']}")
    print(f"GitHub secret values (passwords are only in this file): {r['secrets_file']}")
    print(f"Certificate SHA-256: {r['sha256']}")
    return 0


def cmd_doctor(a) -> int:  # pragma: no cover - network; logic tested via run_doctor
    from ayesha.doctor import run_doctor

    rows = run_doctor(account_type=a.account_type, oanda_env=a.oanda_env, publish=not a.no_publish)
    for ok, name, detail in rows:
        print(f"{'OK  ' if ok else 'FAIL'}  {name}: {detail}")
    bad = [r for r in rows if not r[0]]
    print("\nAll checks passed." if not bad else f"\n{len(bad)} check(s) failed. READY alerts stay blocked until fixed.")
    return 0 if not bad else 1


def _default_db() -> Path:
    from ayesha.paths import home

    return home() / "ayesha.db"


def _db_path(a) -> str:
    p = Path(a.db or _default_db())
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def cmd_scan(a) -> int:  # pragma: no cover - needs a live data feed
    from ayesha.delivery.notify import ConsoleNotifier, TelegramNotifier
    from ayesha.news.calendar import NewsCalendar
    from ayesha.scanner import Scanner
    from ayesha.storage.db import Registry

    from ayesha.capital import CapitalBook, CapitalError, check

    spec = load_spec(a.spec)
    book = CapitalBook()
    try:
        snap = book.latest()
    except CapitalError as e:
        print(f"CONFIG ERROR: {e}")
        return EXIT_CONFIG
    if snap is None:
        print("CONFIG ERROR: no capital snapshot. Run install.bat (or `ayesha capital`) and type your Exness equity.")
        return EXIT_CONFIG
    c = check(snap, datetime.now(timezone.utc), spec.get("capital", {}), a.account_type)
    if not c.ok:
        print(f"WARNING: capital {c.label} ({', '.join(c.blockers)}): READY stays blocked until `ayesha capital`.")
    rc, feed, acct = _connect(a, spec)
    if rc:
        return rc
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

        cal = FFCalendarSource(Path(_db_path(a)).parent / "ff_calendar.json")  # refreshed by the scanner every poll
        if cal.calendar(**news_kw) is None:
            print(f"WARNING: Forex Factory calendar unavailable ({cal.last_error}). Signals => NEWS_UNVERIFIED "
                  "until it recovers.")
    elif spec["risk"]["strict_news"]:
        print("WARNING: no --news / --news-ff calendar. Strict mode => every candidate is NO_TRADE: NEWS_UNVERIFIED.")
    if a.feed == "oanda":
        from ayesha.broker import confirmed_symbols

        missing = sorted(set(x.upper() for x in spec["pairs"]["enabled"]) - set(confirmed_symbols(a.account_type)))
        if missing:
            print(f"WARNING: Exness contract not confirmed for {', '.join(missing)} (`ayesha confirm-broker`). "
                  "Those pairs => BROKER_SPEC_UNVERIFIED.")
    spec = dict(spec, account=dict(spec.get("account", {}), account_type=a.account_type))
    sc = Scanner(feed, spec, Registry(_db_path(a)), notifiers, cal, capital=book)
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


def cmd_confirm_broker(a) -> int:  # interactive; tested through `setup` with piped answers
    """Per-pair Exness contract values typed from the Exness app, plus the account leverage."""
    from ayesha.broker import FIELDS, load_assumed, load_confirmed, save_confirmed, save_leverage

    base = load_assumed(a.account_type)
    pairs = [x.strip().upper() for x in (getattr(a, "symbols", None) or "").split(",") if x.strip()] or \
        [x.upper() for x in load_spec(a.spec)["pairs"]["enabled"]]
    print(f"Account type {a.account_type}. Type each value exactly as the Exness app shows it. Enter on the first "
          "question cancels.")
    while True:
        raw = _ask("  Account leverage, e.g. 2000 for 1:2000, or U for unlimited: ").strip().upper()
        if not raw:
            print("Cancelled; nothing saved.")
            return 1
        try:
            lev = "UNLIMITED" if raw in ("U", "UNLIMITED") else float(raw.replace("1:", ""))
            save_leverage(a.account_type, lev)
            break
        except ValueError as e:
            print(f"  {e}")
    prev = None
    saved = []
    for sym in pairs:
        vals = None
        if prev is not None:
            k = _ask(f"{sym}: open {sym} -> Specification. Same contract size / min / step / max lot as {prev[0]}? "
                     "Y = yes, I checked / N = type them / S = skip: ").upper()
            if k == "S":
                print(f"  {sym} skipped: it stays unverified (no READY for {sym}).")
                continue
            if k == "Y":
                vals = {f: prev[1][f] for f in FIELDS}
        if vals is None:
            print(f"{sym}: Exness app -> {sym} -> Specification")
            vals = {}
            for f in FIELDS:
                while True:
                    raw = _ask(f"  {f} (repo assumption {base[f]}): ")
                    try:
                        v = float(raw)
                        if v > 0:
                            vals[f] = v
                            break
                    except ValueError:
                        pass
                    print("  Please type a positive number.")
        old = load_confirmed(a.account_type, None, sym) or {}
        dflt = old.get("typical_spread_pips", base.get("typical_spread_pips", 1.0))
        raw = _ask(f"  {sym} typical spread in pips when the market is calm (Enter = {dflt}): ")
        try:
            vals["typical_spread_pips"] = float(raw) if raw else float(dflt)
        except ValueError:
            vals["typical_spread_pips"] = float(dflt)
        save_confirmed(a.account_type, vals, symbol=sym)
        saved.append(sym)
        prev = (sym, vals)
    print(f"Saved owner-confirmed spec for {', '.join(saved) or 'no pair'} "
          f"(leverage {'unlimited' if lev == 'UNLIMITED' else f'1:{lev:g}'}).")
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
        s.add_argument("--equity", type=float, help="research commands only; the scanner sizes from `ayesha capital`")
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
    s.add_argument("--news", help="historical calendar CSV (time_utc,currency,impact,title[,observed_utc,...])")
    s.add_argument("--news-modes", default="none,legacy,upgraded",
                   help="with --news: news modes compared on the same candles (none, legacy 30/30, upgraded)")
    s.add_argument("--split", help="in-sample / out-of-sample split date, e.g. 2025-01-01")
    s.add_argument("--folds", type=int, default=4)
    s.add_argument("--label", default="UNLABELLED data", help="data source description shown in the report")
    s.add_argument("--account-type", default="Standard", choices=["Standard", "StandardCent"])
    s.add_argument("--out", help="write JSON")
    s.add_argument("--md", help="write Markdown")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("set-token", help="save the OANDA token for this Windows user (typed hidden)")
    s.add_argument("--remove", action="store_true", help="delete the saved token")
    s.set_defaults(fn=cmd_set_token)

    s = sub.add_parser("setup", help="one-time interactive setup (used by install.bat)")
    s.add_argument("--account-type", default="Standard", choices=["Standard", "StandardCent"])
    s.add_argument("--startup-script", help="start script to copy into the Windows Startup folder if you agree")
    s.add_argument("--no-publish", action="store_true", help="skip the phone relay test in the health check")
    s.set_defaults(fn=cmd_setup)

    s = sub.add_parser("backtest-run", help="validated multi-year OANDA export + validation report (token-safe)")
    s.add_argument("--pairs", help="comma list from the enabled pairs (default: all enabled)")
    s.add_argument("--days", default="1095", help="30..3650")
    s.add_argument("--split", default="", help="YYYY-MM-DD inside the data; default = middle")
    s.add_argument("--folds", default="4", help="2..12")
    s.add_argument("--out-dir", help="default: <AyeshaFX home>/backtest/<timestamp>")
    s.add_argument("--oanda-env", default="practice", choices=["practice", "live"])
    s.add_argument("--account-type", default="Standard", choices=["Standard", "StandardCent"])
    s.add_argument("--news", help="optional historical calendar CSV you are allowed to use (enables the news comparison)")
    s.add_argument("--validate-only", action="store_true")
    s.set_defaults(fn=cmd_backtest_run)

    s = sub.add_parser("make-signing-key", help="create the stable Android release key (once; keep it offline)")
    s.add_argument("--out-dir")
    s.add_argument("--alias", default="ayesha")
    s.set_defaults(fn=cmd_make_signing_key)

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

    s = sub.add_parser("confirm-broker", help="type the Exness contract values per pair from the Exness app (no MT5)")
    s.add_argument("--account-type", default="Standard", choices=["Standard", "StandardCent"])
    s.add_argument("--symbols", help="comma list (default: every enabled pair)")
    s.set_defaults(fn=cmd_confirm_broker)

    s = sub.add_parser("capital", help="update / confirm your Exness equity and open trades (sizing source)")
    s.add_argument("--account-type", default="Standard", choices=["Standard", "StandardCent"])
    s.add_argument("--equity", help="equity shown in Exness (USD; USC for a Cent account)")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--deposit", type=float, help="this update follows a deposit of this amount")
    g.add_argument("--withdrawal", type=float, help="this update follows a withdrawal of this amount")
    g.add_argument("--confirm", action="store_true", help="equity unchanged, just re-confirming")
    s.add_argument("--positions", help='open trades, e.g. "EURUSD BUY 0.50,GBPUSD SELL"')
    s.add_argument("--no-positions", action="store_true", help="confirm there are no open trades")
    s.add_argument("--free-margin", help="free margin shown in Exness (needed with open trades)")
    s.add_argument("--show", action="store_true", help="print the latest snapshot and whether it is valid")
    s.add_argument("--history", action="store_true",
                   help="risk history: capital snapshots, 7-day change without deposits, your journal, warnings")
    s.add_argument("--days", type=int, default=30, help="with --history: how many days to list (default 30)")
    s.add_argument("--session-start", action="store_true", help="prompt once if a person is at the keyboard")
    s.add_argument("--db", help=argparse.SUPPRESS)
    s.add_argument("--file", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_capital)

    return p


if __name__ == "__main__":
    sys.exit(main())
