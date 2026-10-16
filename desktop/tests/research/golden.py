"""Golden fingerprint of the legacy (0.8.0) advisory path, for the research-plane compatibility tests (plan T06).

The fingerprint was written from the 0.8.0 code (commit 7e7da2e) before any research code existed. A later release
that keeps the legacy path unchanged must reproduce it exactly: the same signal ids, statuses, lifecycle events,
signed phone messages (wire format 4), news notices, heartbeats and replay trades on the same inputs.

Inputs are generated with integer arithmetic only (no floating-point maths in the generator), so the candles are
identical on Linux and Windows and on every Python version. All prices are SYNTHETIC; nothing here is market evidence.

Regenerate (only for an owner-approved change of the legacy path, documented in docs/DECISIONS.md):
    cd desktop && python -m tests.research.golden --write
"""

from __future__ import annotations

import argparse
import bisect
import copy
import hashlib
import json
import random
import tempfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ayesha import capital as capmod
from ayesha.config import load_spec
from ayesha.delivery.push import NtfyNotifier
from ayesha.feed.static_specs import assumed_fx_spec
from ayesha.models import Candle, Quote
from ayesha.news.calendar import NewsCalendar, NewsEvent

FIXTURE = Path(__file__).with_name("fixtures") / "legacy-golden-0.8.0.json"
ROOT = Path(__file__).resolve().parents[3]
UTC = timezone.utc
T0 = datetime(2025, 3, 3, 0, 0, tzinfo=UTC)  # a Monday
GOLDEN_CODE = "ABCD-EFGH-JKMN-PQRS"  # test pairing code, never a real one
M15 = timedelta(minutes=15)

# Files the research plane must not change (LF-normalised SHA-256). A research-only release keeps them identical.
PROTECTED = [
    "contracts/strategy-spec.yaml", "contracts/signal.schema.json", "contracts/broker/exness-standard.yaml",
    "contracts/fixtures/pc-news-lockout.txt", "contracts/fixtures/pc-push-ready.txt",
    "tradingview/AyeshaSmartMoney.pine",
    "desktop/ayesha/scanner.py", "desktop/ayesha/capital.py", "desktop/ayesha/broker.py",
    "desktop/ayesha/credentials.py", "desktop/ayesha/doctor.py", "desktop/ayesha/models.py",
    "desktop/ayesha/config.py", "desktop/ayesha/paths.py", "desktop/ayesha/sessions.py", "desktop/ayesha/signing.py",
    "desktop/ayesha/risk/engine.py", "desktop/ayesha/storage/db.py",
    "desktop/ayesha/delivery/notify.py", "desktop/ayesha/delivery/push.py",
    "desktop/ayesha/rules/mtf.py", "desktop/ayesha/rules/primitives.py", "desktop/ayesha/rules/strategy.py",
    "desktop/ayesha/news/analysis.py", "desktop/ayesha/news/calendar.py", "desktop/ayesha/news/classify.py",
    "desktop/ayesha/news/ff_feed.py", "desktop/ayesha/news/guard.py", "desktop/ayesha/news/ledger.py",
    "desktop/ayesha/backtest/asof.py", "desktop/ayesha/backtest/inputs.py", "desktop/ayesha/backtest/replay.py",
    "desktop/ayesha/backtest/report.py",
    "desktop/ayesha/feed/csv_feed.py", "desktop/ayesha/feed/mt5_feed.py", "desktop/ayesha/feed/oanda_feed.py",
    "desktop/ayesha/feed/static_specs.py",
    "desktop/windows/install.bat", "desktop/windows/start-ayesha.bat", "desktop/windows/backtest-local.bat",
    "desktop/windows/run-scanner.bat", "desktop/windows/make-signing-key.bat",
]
PROTECTED_TREES = ["android/app/src"]


# --- inputs -----------------------------------------------------------------------------------

def market(n: int, seed: int, start: datetime = T0, minutes: int = 15, price_points: int = 108_000,
           digits: int = 5) -> list[Candle]:
    """Integer-point random walk with volatility clustering and occasional impulses; weekends skipped.
    Exact on every platform: only integer random draws, and each price is one division by 10**digits."""
    rng = random.Random(seed)
    scale = 10 ** digits
    out: list[Candle] = []
    t, p, vol = start, price_points, 45
    while len(out) < n:
        if t.weekday() >= 5:
            t += timedelta(minutes=minutes)
            continue
        step = max(1, vol // 10)
        vol = max(15, min(120, vol + rng.randint(-step, step)))
        move = sum(rng.randint(-vol, vol) for _ in range(3))
        if rng.randrange(100) < 3:
            move *= 4  # displacement
        o, c = p, p + move
        h = max(o, c) + rng.randint(0, vol // 2)
        lo = min(o, c) - rng.randint(0, vol // 2)
        sp = rng.choice((6, 7, 8, 8, 9, 10))
        out.append(Candle(t, o / scale, h / scale, lo / scale, c / scale, 100.0, sp / scale))
        p = c
        t += timedelta(minutes=minutes)
    return out


def m15_from_m5(m5: list[Candle]) -> list[Candle]:
    out: list[Candle] = []
    i = 0
    while i + 2 < len(m5):
        a = m5[i]
        if a.time.minute % 15 or m5[i + 2].time - a.time != timedelta(minutes=10):
            i += 1
            continue
        b = m5[i:i + 3]
        out.append(Candle(a.time, a.open, max(x.high for x in b), min(x.low for x in b), b[-1].close,
                          sum(x.volume for x in b), max(x.spread for x in b)))
        i += 3
    return out


def events(start: datetime, days: int) -> list[NewsEvent]:
    """A fixed synthetic schedule: USD CPI and a rate decision plus a medium and a low event each week."""
    out: list[NewsEvent] = []
    for d in range(days):
        day = start + timedelta(days=d)
        if day.weekday() == 1:
            out.append(NewsEvent(day.replace(hour=12, minute=30), "USD", "HIGH", "CPI m/m", provider="GOLDEN"))
        if day.weekday() == 2:
            out.append(NewsEvent(day.replace(hour=18), "USD", "HIGH", "Federal Funds Rate", provider="GOLDEN"))
        if day.weekday() == 3:
            out.append(NewsEvent(day.replace(hour=8, minute=30), "EUR", "MEDIUM", "German Ifo", provider="GOLDEN"))
            out.append(NewsEvent(day.replace(hour=14), "USD", "LOW", "Crude Oil Inventories", provider="GOLDEN"))
    return out


# --- legacy scanner harness (same shape as tests/test_scanner.py, frozen here) -------------------

class _Feed:
    source_name = "GOLDEN_SYNTHETIC"

    def __init__(self, candles: list[Candle], clock) -> None:
        self.c, self.times, self.clock = candles, [x.time for x in candles], clock

    def account(self) -> dict[str, Any]:
        return {"equity": None, "balance": None, "margin_free": None}

    def instrument(self, symbol: str):
        return replace(assumed_fx_spec(symbol, 1.08), source=f"MT5:{symbol}m", margin_per_lot=540.0)

    def quote(self, symbol: str) -> Quote:
        i = bisect.bisect_right(self.times, self.clock() - M15) - 1
        last = self.c[i]
        return Quote(symbol, self.clock(), last.close, last.close + last.spread)

    def candles(self, symbol: str, tf: str, start: datetime, end: datetime) -> list[Candle]:
        return self.c[bisect.bisect_left(self.times, start):bisect.bisect_left(self.times, end)]


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _sha(obj: Any) -> str:
    data = obj if isinstance(obj, bytes) else (obj if isinstance(obj, str) else _canon(obj)).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _scan(spec: dict[str, Any], candles: list[Candle], equity: float, cal_events: list[NewsEvent] | None,
          db_path: Path, warm_idx: int = 400) -> dict[str, Any]:
    from ayesha.scanner import Scanner
    from ayesha.storage.db import Registry

    t = [candles[warm_idx].time + timedelta(seconds=5)]
    clock = lambda: t[0]  # noqa: E731
    sent: list[list[str]] = []
    ntfy = NtfyNotifier(GOLDEN_CODE, post=lambda url, data, headers: (sent.append(
        [headers["Priority"], data.decode("utf-8")]), 200)[1], strategy_hash=spec["strategy_hash"])
    cal = None
    if cal_events is not None:
        ev = list(cal_events)
        start, end = candles[0].time - timedelta(days=1), candles[-1].time + timedelta(days=2)

        def cal():  # a fresh calendar file on every poll, like the live Forex Factory source
            return NewsCalendar(ev, start, end, provider="GOLDEN", fetched_at=clock())
    reg = Registry(db_path)
    sc = Scanner(_Feed(candles, clock), spec, reg, [ntfy], cal, clock=clock, capital=capmod.fresh(equity, clock))
    sc.warmup()
    for c in candles[warm_idx + 1:]:
        t[0] = c.time + M15 + timedelta(seconds=5)
        sc.poll()
    db = reg.db
    signals = [[r["signal_id"], r["status"], r["grade"]] for r in
               db.execute("SELECT signal_id, status, grade FROM signals ORDER BY signal_id")]
    evts = [[r["signal_id"], r["from_status"], r["to_status"], r["note"]] for r in
            db.execute("SELECT signal_id, from_status, to_status, note FROM signal_events ORDER BY id")]
    deliveries = [[r["signal_id"], r["channel"], r["ok"], r["detail"]] for r in
                  db.execute("SELECT signal_id, channel, ok, detail FROM deliveries ORDER BY signal_id, channel")]
    health = [[r["symbol"], r["state"], r["detail"]] for r in
              db.execute("SELECT symbol, state, detail FROM engine_health ORDER BY id")]
    payloads = [json.loads(r["payload"]) for r in db.execute("SELECT payload FROM signals ORDER BY signal_id")]
    reg.db.close()
    counts: dict[str, int] = {}
    for _, st, _ in signals:
        counts[st] = counts.get(st, 0) + 1
    kinds: dict[str, int] = {}
    for _, body in sent:
        k = body.split(" ", 2)[1] if body.startswith("AYESHA ") else "?"
        k = k if k in ("NEWS", "HB") else "SIGNAL"
        kinds[k] = kinds.get(k, 0) + 1
    return {
        "signals": len(signals), "status_counts": dict(sorted(counts.items())), "messages": dict(sorted(kinds.items())),
        "first_signal_ids": [s[0] for s in signals[:3]],
        "sha256": {"signals": _sha(signals), "signal_events": _sha(evts), "deliveries": _sha(deliveries),
                   "engine_health": _sha(health), "payloads": _sha(payloads), "signed_messages": _sha(sent)},
    }


def _replay(spec: dict[str, Any], candles: list[Candle], **kw) -> dict[str, Any]:
    from ayesha.backtest.replay import run_backtest, summarize

    res = run_backtest("EURUSD", candles, spec, **kw)
    rows = [[t.signal.signal_id, t.status, t.fill_index, t.exit_index, t.exit_reason, t.r, list(t.blockers),
             t.news_phase, t.signal.grade, t.signal.score] for t in res["trades"]]
    s = summarize(res["trades"])
    return {"trades": len(rows), "by_status": dict(sorted(s["by_status"].items())), "closed": s["closed_trades"],
            "total_r": s["total_r"], "rejections": len(res["rejections"]),
            "sha256": {"trades": _sha(rows),
                       "rejections": _sha([[r.index, r.symbol, r.direction, r.reason] for r in res["rejections"]])}}


def _cli_structure() -> dict[str, str]:
    """Option set of every legacy subcommand (version independent, unlike argparse help text)."""
    from ayesha.cli import build_parser

    p = build_parser()
    sub = next(a for a in p._actions if a.__class__.__name__ == "_SubParsersAction")
    out = {}
    top = [[a.option_strings, a.dest, repr(a.default)] for a in p._actions if a is not sub]
    out["(top)"] = _sha(top)
    for name, sp in sorted(sub.choices.items()):
        if name == "research":
            continue  # the one additive command (research plane)
        rows = [[a.option_strings, a.dest, repr(a.default), list(a.choices) if a.choices else None, a.required,
                 repr(a.nargs), getattr(a.type, "__name__", repr(a.type)), a.__class__.__name__]
                for a in sp._actions]
        out[name] = _sha(rows)
    return out


def _norm_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def protected_files() -> dict[str, str]:
    out = {rel: _norm_sha(ROOT / rel) for rel in PROTECTED}
    for tree in PROTECTED_TREES:
        for f in sorted((ROOT / tree).rglob("*")):
            if f.is_file():
                out[f.relative_to(ROOT).as_posix()] = _norm_sha(f)
    return out


def fingerprint(tmp: Path) -> dict[str, Any]:
    spec = load_spec()
    scan_spec = copy.deepcopy(spec)
    scan_spec["pairs"]["enabled"] = ["EURUSD"]
    scan_spec["feed"]["warmup_days"] = 3
    scan_spec["delivery"]["notify_grades"] = ["A_PLUS", "WATCH"]
    m15 = market(12000, seed=20251016)
    m5 = market(36000, seed=7016, minutes=5)
    m5_15 = m15_from_m5(m5)
    ev = events(m15[0].time, 190)
    ev5 = events(m5[0].time, 190)
    cal5 = NewsCalendar(ev5, m5[0].time - timedelta(days=1), m5[-1].time + timedelta(days=2), provider="GOLDEN")
    return {
        "generated_from": "release 0.8.0, commit 7e7da2e715544dbbc023570275776258abd8bdd4",
        "note": "SYNTHETIC integer-walk prices; a compatibility fingerprint, never evidence of an edge",
        "strategy": {"version": spec["strategy_version"], "hash": spec["strategy_hash"]},
        "scanner": {
            "equity_100000_no_news": _scan(scan_spec, m15, 100_000, [], tmp / "a.db"),
            "equity_20_no_news": _scan(scan_spec, m15, 20, [], tmp / "b.db"),
            "equity_100000_news_schedule": _scan(scan_spec, m15, 100_000, ev, tmp / "c.db"),
        },
        "replay": {
            "m15_news_none": _replay(spec, m15),
            "m15_from_m5_news_legacy": _replay(spec, m5_15, calendar=cal5, news_mode="legacy"),
            "m15_from_m5_news_upgraded": _replay(spec, m5_15, calendar=cal5, news_mode="upgraded", m5_candles=m5),
            "m15_equity_25_standard": _replay(spec, m15, equity_usd=25.0, account_type="Standard",
                                              usd_rates={"JPY": 0.0067, "CAD": 0.73}),
        },
        "cli": _cli_structure(),
        "protected_files": protected_files(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="write the fixture (owner-approved legacy change only)")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as d:
        fp = fingerprint(Path(d))
    text = json.dumps(fp, indent=1, sort_keys=True) + "\n"
    if a.write:
        FIXTURE.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {FIXTURE}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
