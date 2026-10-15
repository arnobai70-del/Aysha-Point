"""Validation of backtest run parameters. Shared by the GitHub workflow and the local Windows script,
so untrusted text (workflow_dispatch inputs, typed answers) never reaches a shell or a file path."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

MIN_DAYS, MAX_DAYS = 30, 3650
MIN_FOLDS, MAX_FOLDS = 2, 12
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PAIR = re.compile(r"^[A-Z]{6}$")


class InvalidInput(ValueError):
    pass


@dataclass(frozen=True)
class BacktestParams:
    pairs: tuple[str, ...]
    days: int
    split: date
    folds: int


def validate(pairs: str, days: str, split: str, folds: str, allowed: list[str],
             today: date | None = None) -> BacktestParams:
    today = today or datetime.now(timezone.utc).date()
    allow = {p.upper() for p in allowed}
    raw = [p.strip().upper() for p in (pairs or "").split(",") if p.strip()]
    if not raw:
        raise InvalidInput("pairs: give at least one pair")
    if len(raw) > len(allow):
        raise InvalidInput("pairs: too many")
    bad = [p for p in raw if not _PAIR.match(p) or p not in allow]
    if bad:
        raise InvalidInput(f"pairs: not allowed {sorted(set(bad))!r}; allowed: {sorted(allow)}")
    out_pairs = tuple(dict.fromkeys(raw))  # de-duplicate, keep order
    if not re.fullmatch(r"\d{1,5}", (days or "").strip()):
        raise InvalidInput("days: whole number required")
    d = int(days)
    if not MIN_DAYS <= d <= MAX_DAYS:
        raise InvalidInput(f"days: must be {MIN_DAYS}..{MAX_DAYS}")
    if not re.fullmatch(r"\d{1,2}", (folds or "").strip()):
        raise InvalidInput("folds: whole number required")
    f = int(folds)
    if not MIN_FOLDS <= f <= MAX_FOLDS:
        raise InvalidInput(f"folds: must be {MIN_FOLDS}..{MAX_FOLDS}")
    start = today - timedelta(days=d)
    s = (split or "").strip()
    if not s:
        sp = start + timedelta(days=d // 2)
    else:
        if not _DATE.match(s):
            raise InvalidInput("split: use YYYY-MM-DD")
        try:
            sp = date.fromisoformat(s)
        except ValueError:
            raise InvalidInput("split: not a real date") from None
        if not start + timedelta(days=MIN_DAYS // 2) <= sp <= today - timedelta(days=MIN_DAYS // 2):
            raise InvalidInput(f"split: must lie inside the data, between {start + timedelta(days=15)} and "
                               f"{today - timedelta(days=15)}")
    return BacktestParams(out_pairs, d, sp, f)
