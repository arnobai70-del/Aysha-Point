"""Event groups, guard tiers and the (conditional) currency polarity of a data surprise.

Tiers decide how long new entries are blocked around an event. They are proposed research
defaults from the News Intelligence spec, not statistically optimised values, and a title match
can only make an event stricter than its calendar impact tag, never looser.

Polarity says which way the currency would move *all else equal* when the figure comes in above
forecast: +1 (higher = currency stronger, e.g. CPI, payrolls, rate decision), -1 (higher = weaker,
e.g. unemployment rate, jobless claims), 0 = unknown/ambiguous. It is an explanation aid only; the
real reaction often differs (positioning, revisions, other releases, guidance, risk sentiment).
"""

from __future__ import annotations

import math
import re

TIER_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "TOP_DATA": 3, "CENTRAL_BANK": 4}
FX_CODES = {"USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF", "CNY"}
GLOBAL_CODES = {"ALL", "GLOBAL"}

_CENTRAL_BANK = re.compile(
    r"\b(fomc|federal funds rate|fed chair|rate decision|interest rate decision|cash rate|official bank rate|"
    r"main refinancing rate|monetary policy (statement|report|summary)|policy rate|overnight rate|"
    r"boj policy rate|press conference|rate statement|minimum bid rate|deposit facility rate)\b", re.I)
_TOP_DATA = re.compile(r"\b(cpi|consumer price index|non-farm|nonfarm|nfp|core pce|pce price index)\b", re.I)

_POLARITY = [
    (re.compile(r"unemployment rate|jobless claims|claimant count|unemployment claims", re.I), -1),
    (re.compile(r"\b(cpi|ppi|pce|inflation|price index|gdp|non-farm|nonfarm|employment change|payrolls|"
                r"retail sales|pmi|average (hourly )?earnings|wage|rate decision|federal funds rate|cash rate|"
                r"bank rate|refinancing rate|policy rate|overnight rate|industrial production)\b", re.I), +1),
]


def tier(title: str, impact: str) -> str:
    """Strictest of the calendar impact tag and the title's event group."""
    base = impact.upper() if impact.upper() in TIER_RANK else "HIGH"  # unknown tag: treat as HIGH
    by_title = "CENTRAL_BANK" if _CENTRAL_BANK.search(title) else "TOP_DATA" if _TOP_DATA.search(title) else "LOW"
    return max((base, by_title), key=TIER_RANK.__getitem__)


def polarity(title: str) -> int:
    for rx, sign in _POLARITY:
        if rx.search(title):
            return sign
    return 0


def currency_known(ccy: str) -> bool:
    return ccy.upper() in FX_CODES or ccy.upper() in GLOBAL_CODES


_NUM = re.compile(r"^\s*[<>~]?\s*([+-]?\d+(?:\.\d+)?)\s*([%KMBT]?)\s*$", re.I)
_SCALE = {"": 1.0, "%": 1.0, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


class Malformed(ValueError):
    pass


def parse_number(s: str | None) -> float | None:
    """'0.3%' -> 0.3, '215K' -> 215000, '' / None -> None. Raises Malformed for anything else."""
    if s is None or not str(s).strip():
        return None
    m = _NUM.match(str(s).replace(",", ""))
    if not m:
        raise Malformed(f"not a number: {s!r}")
    v = float(m.group(1)) * _SCALE[m.group(2).upper()]
    if not math.isfinite(v):
        raise Malformed(f"not finite: {s!r}")
    return v


def malformed(*vals: str | None) -> bool:
    for v in vals:
        try:
            parse_number(v)
        except Malformed:
            return True
    return False
