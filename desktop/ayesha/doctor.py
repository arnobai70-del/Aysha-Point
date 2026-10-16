"""`ayesha doctor`: one-screen health check for a nontechnical owner.

Each check returns (ok, name, detail). Nothing here places orders or changes settings; the
relay check publishes one signed TEST heartbeat that the phone shows as "test received".
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

Row = tuple[bool, str, str]


def run_doctor(*, account_type: str = "Standard", oanda_env: str = "practice", publish: bool = True,
               env: dict[str, str] | None = None, home: Path | None = None,
               make_feed: Callable[..., Any] | None = None, make_calendar: Callable[[Path], Any] | None = None,
               make_notifier: Callable[[str], Any] | None = None,
               clock: Callable[[], datetime] | None = None, store=True) -> list[Row]:
    from ayesha.broker import confirmed_symbols, load_leverage
    from ayesha.config import load_spec
    from ayesha.delivery.push import normalize_code, topic_for

    env = os.environ if env is None else env
    if home is None:
        from ayesha.paths import home as _home

        home = _home()
    clock = clock or (lambda: datetime.now(timezone.utc))
    rows: list[Row] = []

    ok_py = sys.version_info >= (3, 10)
    rows.append((ok_py, "Python", f"{sys.version.split()[0]} ({'ok' if ok_py else 'need 3.10 or newer'})"))

    try:
        spec = load_spec()
        rows.append((True, "Strategy contract", f"{spec['strategy_version']} #{spec['strategy_hash']}"))
    except Exception as e:
        rows.append((False, "Strategy contract", f"cannot load: {type(e).__name__}"))
        return rows

    from ayesha.credentials import get_token, valid_token

    token = get_token(env, store=store)
    if not token:
        rows.append((False, "OANDA token", "missing: run install.bat again (or `ayesha set-token`)"))
    elif not valid_token(token):
        rows.append((False, "OANDA token", "set but malformed (spaces or wrong characters?): run `ayesha set-token` again"))
    else:
        rows.append((True, "OANDA token", f"set ({len(token)} characters, value hidden)"))
    if token:
        try:
            if make_feed is None:
                from ayesha.feed.oanda_feed import OandaFeed

                def make_feed(**kw):
                    return OandaFeed(**kw)
            feed = make_feed(equity_usd=1.0, account_type=account_type, token=token, environment=oanda_env)
            q = feed.quote("EURUSD")
            age = (clock() - q.time).total_seconds()
            rows.append((True, "OANDA prices", f"EURUSD bid {q.bid} ask {q.ask}, quote age {age:.0f}s"
                         + (" (market closed or weekend?)" if age > 120 else "")))
        except Exception as e:
            from ayesha.credentials import redact

            rows.append((False, "OANDA prices", redact(f"{type(e).__name__}: {str(e)[:160]}", token)))

    bfile = home / "broker-confirmed.json"
    pairs = [x.upper() for x in spec["pairs"]["enabled"]]
    done = set(confirmed_symbols(account_type, bfile))
    missing = [x for x in pairs if x not in done]
    lev = load_leverage(account_type, bfile)
    if not missing and lev is not None:
        rows.append((True, "Exness contract", f"owner-confirmed for {len(pairs)} pairs, leverage "
                     f"{'unlimited' if lev == 'UNLIMITED' else f'1:{lev:g}'}"))
    else:
        what = (f"not confirmed for {', '.join(missing)}" if missing else "") + \
            ("; " if missing and lev is None else "") + ("leverage not confirmed" if lev is None else "")
        rows.append((False, "Exness contract", f"{what}: run `ayesha confirm-broker` "
                     "(those pairs stay blocked: BROKER_SPEC_UNVERIFIED)"))

    from ayesha.capital import CapitalBook, CapitalError, check, warnings

    try:
        book = CapitalBook(home / "capital.json")
        hist = book.history()
        snap = hist[-1] if hist else None
        c = check(snap, clock(), spec.get("capital", {}), account_type)
        if snap is None:
            rows.append((False, "Capital", "no Exness equity entered: run `ayesha capital` (READY blocked: "
                         "CAPITAL_UNVERIFIED)"))
        else:
            warn = [w.split(":")[0] for w in warnings(hist, clock(), spec.get("capital", {}))]  # codes only, no amounts
            rows.append((c.ok, "Capital", f"v{snap.version} owner-entered {c.age_hours:.1f} h ago, "
                         + ("OK" if c.ok else f"{', '.join(c.blockers)}: run `ayesha capital`")
                         + (f"; warning: {', '.join(warn)} (see `ayesha capital --history`)" if warn else "")))
    except CapitalError as e:
        rows.append((False, "Capital", f"{e}"))

    code_file = home / "pairing-code.txt"
    code = None
    if code_file.exists():
        try:
            code = normalize_code(code_file.read_text(encoding="utf-8").strip())
        except Exception:
            code = None
    rows.append((code is not None, "Pairing code", f"present, relay topic {topic_for(code)}" if code else
                 "missing or invalid: run `ayesha pair`"))

    try:
        if make_calendar is None:
            from ayesha.news.ff_feed import FFCalendarSource

            def make_calendar(p):
                return FFCalendarSource(p).calendar(before_min=30, after_min=30, impacts=("HIGH",))
        cal = make_calendar(home / "ff_calendar.json")
        if cal is None:
            rows.append((False, "News calendar", "unavailable: every signal => NEWS_UNVERIFIED (NO_TRADE)"))
        else:
            rows.append((True, "News calendar", f"covers {cal.coverage[0]:%Y-%m-%d %H:%M} to "
                                                f"{cal.coverage[1]:%Y-%m-%d %H:%M} UTC"))
    except Exception as e:
        rows.append((False, "News calendar", f"{type(e).__name__}"))

    if publish and code:
        if make_notifier is None:
            from ayesha.delivery.push import NtfyNotifier

            make_notifier = NtfyNotifier
        n = make_notifier(code)
        ok, detail = n.heartbeat(int(clock().timestamp() * 1000), "TEST", 0, spec["strategy_hash"])
        rows.append((ok, "Phone relay (ntfy.sh)", "test heartbeat sent; phone should show 'test received'" if ok
                     else f"publish failed: {detail}"))
    return rows
