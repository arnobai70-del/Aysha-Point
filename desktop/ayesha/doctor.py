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
               clock: Callable[[], datetime] | None = None) -> list[Row]:
    from ayesha.broker import load_confirmed
    from ayesha.config import load_spec
    from ayesha.delivery.push import normalize_code, topic_for

    env = os.environ if env is None else env
    home = home or Path.home() / "AyeshaFX"
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

    token = env.get("AYESHA_OANDA_TOKEN", "")
    rows.append((bool(token), "OANDA token", "set (value hidden)" if token else
                 "missing: run install.bat again or `setx AYESHA_OANDA_TOKEN <token>` and reopen the window"))
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
            rows.append((False, "OANDA prices", f"{type(e).__name__}: {str(e)[:120]}"))

    conf = load_confirmed(account_type, home / "broker-confirmed.json")
    rows.append((conf is not None, "Exness contract", "owner-confirmed" if conf else
                 "NOT confirmed: run `ayesha confirm-broker` (READY stays blocked: CONTRACT_SPEC_UNVERIFIED)"))

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
