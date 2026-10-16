"""Adaptive capital: the owner's verified Exness equity as a versioned snapshot (News spec module B).

Capital is a variable, never a constant: every candidate is sized from the latest snapshot, so the
same code works at $20, $500 or $5,000, and the dollar budget follows equity both up and down
while the risk *percentage* never changes because equity grew.

There is no Exness API here, so every snapshot is labelled OWNER_ENTERED with its UTC time. A READY
needs a snapshot younger than `capital.max_age_hours` (shorter after a deposit, withdrawal or a
large change) and an open-positions confirmation younger than `capital.positions_max_age_hours`.
OANDA's practice balance is never used. Snapshots live only on the PC (%AYESHA_HOME%\\capital.json);
the phone gets a keyed digest, never the amount.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REASONS = ("INITIAL", "UPDATE", "CONFIRM", "DEPOSIT", "WITHDRAWAL")
CURRENCY = {"Standard": "USD", "StandardCent": "USC"}
MAX_EQUITY_USD = 10_000_000.0


@dataclass(frozen=True)
class OpenPosition:
    symbol: str
    direction: str  # BUY | SELL
    risk_usd: float | None = None  # loss if the stop is hit; None = unknown (counts as the whole open-risk cap)


@dataclass(frozen=True)
class CapitalSnapshot:
    version: int
    equity: float  # in the account currency as shown by Exness (USD, or USC for a Cent account)
    currency: str  # USD | USC
    account_type: str  # Standard | StandardCent
    entered_at: datetime
    reason: str = "UPDATE"
    source: str = "OWNER_ENTERED"
    amount: float = 0.0  # deposit / withdrawal amount (account currency); never counted as trading P&L
    previous_equity: float | None = None
    positions_confirmed_at: datetime | None = None
    open_positions: tuple[OpenPosition, ...] = field(default=())
    free_margin: float | None = None  # account currency; needed only when trades are open

    @property
    def equity_usd(self) -> float:
        return self.equity / 100.0 if self.currency == "USC" else self.equity

    @property
    def free_margin_usd(self) -> float | None:
        if self.free_margin is None:
            return None
        return self.free_margin / 100.0 if self.currency == "USC" else self.free_margin

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["entered_at"] = self.entered_at.isoformat()
        d["positions_confirmed_at"] = self.positions_confirmed_at.isoformat() if self.positions_confirmed_at else None
        d["open_positions"] = [asdict(p) for p in self.open_positions]
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "CapitalSnapshot":
        return cls(version=int(d["version"]), equity=float(d["equity"]), currency=str(d["currency"]),
                   account_type=str(d["account_type"]), entered_at=datetime.fromisoformat(d["entered_at"]),
                   reason=str(d.get("reason", "UPDATE")), source=str(d.get("source", "OWNER_ENTERED")),
                   amount=float(d.get("amount") or 0.0),
                   previous_equity=None if d.get("previous_equity") is None else float(d["previous_equity"]),
                   positions_confirmed_at=(datetime.fromisoformat(d["positions_confirmed_at"])
                                           if d.get("positions_confirmed_at") else None),
                   open_positions=tuple(OpenPosition(p["symbol"], p["direction"], p.get("risk_usd"))
                                        for p in d.get("open_positions") or []),
                   free_margin=None if d.get("free_margin") is None else float(d["free_margin"]))


class CapitalError(ValueError):
    pass


def validate_amount(v: Any, what: str = "equity") -> float:
    try:
        x = float(str(v).strip().replace(",", "")) if not isinstance(v, (int, float)) else float(v)
    except ValueError:
        raise CapitalError(f"{what} must be a number") from None
    if not math.isfinite(x) or x <= 0:
        raise CapitalError(f"{what} must be a positive number")
    if x > MAX_EQUITY_USD * 100:
        raise CapitalError(f"{what} is implausibly large")
    if round(x, 2) != x:
        raise CapitalError(f"{what}: at most 2 decimals")
    return x


def validate_position(symbol: str, direction: str, risk_usd: Any = None) -> OpenPosition:
    s, d = symbol.strip().upper(), direction.strip().upper()
    if len(s) != 6 or not s.isalpha():
        raise CapitalError(f"bad symbol {symbol!r}")
    if d not in ("BUY", "SELL"):
        raise CapitalError("direction must be BUY or SELL")
    r = None
    if risk_usd not in (None, ""):
        r = float(risk_usd)
        if not math.isfinite(r) or r < 0:
            raise CapitalError("risk must be 0 or more")
    return OpenPosition(s, d, r)


@dataclass
class CapitalCheck:
    ok: bool
    blockers: list[str]
    snapshot: CapitalSnapshot | None
    age_hours: float | None = None
    max_age_hours: float | None = None
    positions_ok: bool = False

    @property
    def label(self) -> str:
        if self.snapshot is None:
            return "CAPITAL_UNVERIFIED"
        return "OK" if self.ok else self.blockers[0]


def check(snap: CapitalSnapshot | None, now: datetime, policy: dict[str, Any], account_type: str,
          compare_equity_usd: float | None = None) -> CapitalCheck:
    """Can this snapshot size a READY right now? Every unknown fails closed."""
    if snap is None:
        return CapitalCheck(False, ["CAPITAL_UNVERIFIED"], None)
    b: list[str] = []
    if snap.account_type != account_type:
        b.append("CAPITAL_ACCOUNT_TYPE_MISMATCH")
    if CURRENCY.get(snap.account_type) != snap.currency:
        b.append("CAPITAL_CURRENCY_MISMATCH")
    if not (math.isfinite(snap.equity) and snap.equity > 0):
        b.append("CAPITAL_INVALID")
    if snap.source not in ("OWNER_ENTERED", "MT5_READ_ONLY"):
        b.append("CAPITAL_SOURCE_UNTRUSTED")
    age = (now - snap.entered_at).total_seconds() / 3600
    changed = snap.reason in ("DEPOSIT", "WITHDRAWAL") or (
        snap.previous_equity and abs(snap.equity - snap.previous_equity) / snap.previous_equity * 100
        > float(policy.get("large_change_percent", 25)))
    max_age = float(policy.get("max_age_after_change_hours" if changed else "max_age_hours", 24))
    if age < -float(policy.get("max_clock_skew_minutes", 5)) / 60:
        b.append("CAPITAL_CLOCK_DRIFT")
    elif age > max_age:
        b.append("CAPITAL_STALE")
    pos_ok = snap.positions_confirmed_at is not None and \
        0 <= (now - snap.positions_confirmed_at).total_seconds() / 3600 <= float(policy.get("positions_max_age_hours", 12))
    if not pos_ok:
        b.append("POSITION_STATE_UNVERIFIED")
    elif snap.open_positions and snap.free_margin is None:
        b.append("MARGIN_UNVERIFIED")
    if compare_equity_usd is not None and math.isfinite(compare_equity_usd) and snap.equity_usd > 0 and \
            abs(compare_equity_usd - snap.equity_usd) / snap.equity_usd > 0.02:
        b.append("CAPITAL_MISMATCH")
    return CapitalCheck(not b, b, snap, round(age, 2), max_age, pos_ok)


def cash_flow_usd(s: CapitalSnapshot) -> float:
    """Deposit (+) or withdrawal (-) recorded with this snapshot, in USD. Never trading P&L."""
    k = 0.01 if s.currency == "USC" else 1.0
    return k * (s.amount if s.reason == "DEPOSIT" else -s.amount if s.reason == "WITHDRAWAL" else 0.0)


def trading_change(history: list[CapitalSnapshot], now: datetime, days: float = 7.0) -> dict[str, Any] | None:
    """Equity change over the last `days` from the owner's snapshots with deposits and withdrawals
    taken out (spec B4, C08), for the latest snapshot's account type. Information for warnings only.

    Adjusted equity = equity minus the net cash flow since the window start, so a $500 deposit is
    neither growth nor a cushion; `drawdown_percent` is how far the adjusted equity now sits below its
    highest value in the window."""
    hist = [x for x in history if x.entered_at <= now]
    if not hist:
        return None
    hist = [x for x in hist if x.account_type == hist[-1].account_type]
    since = now - timedelta(days=days)
    start = max([k for k, x in enumerate(hist) if x.entered_at <= since], default=0)
    win = hist[start:]
    flows, adj = 0.0, []
    for k, x in enumerate(win):
        if k:
            flows += cash_flow_usd(x)
        adj.append(x.equity_usd - flows)
    peak = max(adj)
    return {"days": days, "from_utc": win[0].entered_at.isoformat(), "snapshots": len(win),
            "start_equity_usd": round(win[0].equity_usd, 2), "latest_equity_usd": round(win[-1].equity_usd, 2),
            "net_cash_flow_usd": round(flows, 2), "trading_change_usd": round(adj[-1] - adj[0], 2),
            "trading_change_percent": round((adj[-1] - adj[0]) / adj[0] * 100, 2) if adj[0] > 0 else None,
            "drawdown_percent": round((peak - adj[-1]) / peak * 100, 2) if peak > 0 else None}


def warnings(history: list[CapitalSnapshot], now: datetime, policy: dict[str, Any]) -> list[str]:
    """Warnings only (spec B4): they never block a trade or loosen a hard gate; the daily loss,
    two-loss and open-risk gates stay as they are. Each one names what to do."""
    out: list[str] = []
    if not history:
        return out
    snap = history[-1]
    soon = float(policy.get("freshness_warning_hours", 2))
    c = check(snap, now, policy, snap.account_type)
    if c.age_hours is not None and c.max_age_hours is not None and 0 < c.max_age_hours - c.age_hours <= soon:
        out.append(f"CAPITAL_EXPIRES_SOON: confirm your Exness equity within {c.max_age_hours - c.age_hours:.1f} h "
                   "(`ayesha capital`)")
    if snap.positions_confirmed_at is not None:
        left = float(policy.get("positions_max_age_hours", 12)) - (now - snap.positions_confirmed_at).total_seconds() / 3600
        if 0 < left <= soon:
            out.append(f"POSITIONS_CONFIRMATION_EXPIRES_SOON: confirm open trades within {left:.1f} h")
    limit = policy.get("weekly_drawdown_warning_percent")
    ch = trading_change(history, now, 7.0)
    if limit is not None and ch and ch["drawdown_percent"] is not None and ch["drawdown_percent"] >= float(limit):
        out.append(f"WEEKLY_DRAWDOWN_WARNING: equity is {ch['drawdown_percent']:.1f}% below this week's high "
                   "(deposits/withdrawals excluded). Review your journal before the next trade; risk per trade "
                   "does not change and losses are never chased")
    return out


def digest(pairing_code: str, equity_usd: float) -> str:
    """Keyed fingerprint of the equity in cents, so the phone can compare without the amount being sent.
    Same algorithm in android core/Capital.kt (shared test vector)."""
    from ayesha.delivery.push import normalize_code

    cents = int(round(equity_usd * 100))
    return hmac.new(normalize_code(pairing_code).encode(), f"capital:v1:{cents}".encode(), hashlib.sha256).hexdigest()[:16]


def default_path() -> Path:
    from ayesha.paths import home

    return home() / "capital.json"


class CapitalBook:
    """Append-only capital history on the PC. `latest()` is re-read on every evaluation, so
    `ayesha capital` in another window takes effect without restarting the scanner."""

    def __init__(self, path: Path | None = None, clock=None) -> None:
        self.path = Path(path) if path else default_path()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _read(self) -> list[CapitalSnapshot]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return [CapitalSnapshot.from_json(d) for d in data["history"]]
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise CapitalError(f"capital file unreadable ({type(e).__name__}); run `ayesha capital` again") from None

    def history(self) -> list[CapitalSnapshot]:
        return self._read()

    def latest(self) -> CapitalSnapshot | None:
        h = self._read()
        return h[-1] if h else None

    __call__ = latest

    def record(self, equity: Any, account_type: str = "Standard", reason: str = "UPDATE", amount: Any = 0,
               positions: list[OpenPosition] | None = None, free_margin: Any = None,
               positions_confirmed: bool = True) -> CapitalSnapshot:
        if reason not in REASONS:
            raise CapitalError(f"reason must be one of {REASONS}")
        if account_type not in CURRENCY:
            raise CapitalError(f"unsupported account type {account_type!r}")
        eq = validate_amount(equity)
        amt = validate_amount(amount, "amount") if reason in ("DEPOSIT", "WITHDRAWAL") else 0.0
        fm = validate_amount(free_margin, "free margin") if free_margin not in (None, "") else None
        hist = self._read()
        prev = hist[-1] if hist else None
        now = self.clock()
        snap = CapitalSnapshot(
            version=(prev.version + 1) if prev else 1, equity=eq, currency=CURRENCY[account_type],
            account_type=account_type, entered_at=now, reason="INITIAL" if prev is None else reason,
            amount=amt, previous_equity=prev.equity if prev else None,
            positions_confirmed_at=now if positions_confirmed else (prev.positions_confirmed_at if prev else None),
            open_positions=tuple(positions or ()) if positions_confirmed else (prev.open_positions if prev else ()),
            free_margin=fm)
        hist.append(snap)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"format": "ayesha-capital", "version": 1,
                                   "history": [s.to_json() for s in hist[-500:]]}, indent=1), encoding="utf-8")
        tmp.replace(self.path)
        return snap

    def cash_flows_usd(self, since: datetime | None = None) -> float:
        """Net deposits minus withdrawals in USD. Kept apart from trading P&L (spec B4, C08)."""
        return sum(cash_flow_usd(s) for s in self._read() if not (since and s.entered_at < since))


def static(snapshot: CapitalSnapshot):
    """Provider returning a fixed snapshot (tests, research)."""
    return lambda: snapshot


def fresh(equity: float, clock, account_type: str = "Standard", positions=()) -> Any:
    """Provider whose snapshot is always just confirmed (tests and backtests only)."""
    def f():
        now = clock()
        return CapitalSnapshot(1, equity, CURRENCY[account_type], account_type, now, "CONFIRM",
                               positions_confirmed_at=now, open_positions=tuple(positions))
    return f


def with_time(s: CapitalSnapshot, t: datetime) -> CapitalSnapshot:
    return replace(s, entered_at=t, positions_confirmed_at=t)
