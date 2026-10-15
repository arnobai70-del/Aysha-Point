"""Read-only OANDA v20 REST data feed: the MT5-free live and historical data path.

Why OANDA: its v20 API is an official, documented API that a free fxTrade Practice (demo)
account can use with a personal access token. It returns BID and ASK candles, so the scanner
gets real spreads and quote ages. No scraping, no browser automation.

Only candle and instrument endpoints are called (GET). The order, trade and position endpoints
are never referenced, and `scripts/check_no_order_api.py` guards the repository.

Prices are OANDA's, not Exness's. Levels are close but not identical to the Exness app; the
scanner adds the owner's typical Exness spread when OANDA's spread is lower.

Token: environment variable AYESHA_OANDA_TOKEN (never in the repository or the database).
"""

from __future__ import annotations

import json
import os
import time as _time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ayesha.broker import broker_spec
from ayesha.models import Candle, InstrumentSpec, Quote

HOSTS = {"practice": "https://api-fxpractice.oanda.com", "live": "https://api-fxtrade.oanda.com"}
GRANULARITY = {"M1": "M1", "M5": "M5", "M15": "M15", "H1": "H1", "H4": "H4", "D1": "D"}
TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
MAX_CANDLES = 5000  # per request, OANDA limit

HttpGet = Callable[[str, dict[str, str]], dict[str, Any]]


def _default_get(url: str, headers: dict[str, str]) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def oanda_instrument(symbol: str) -> str:
    s = symbol.upper()
    if len(s) != 6:
        raise KeyError(f"Not an FX pair: {symbol}")
    return f"{s[:3]}_{s[3:]}"


def parse_time(s: str) -> datetime:
    """OANDA RFC3339 with nanoseconds, e.g. 2026-10-14T00:15:00.000000000Z."""
    s = s.rstrip("Z")
    if "." in s:
        head, frac = s.split(".", 1)
        s = f"{head}.{frac[:6]}"
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _rfc3339(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class MissingToken(RuntimeError):
    pass


class AuthRejected(RuntimeError):
    """OANDA refused the token (HTTP 401/403). Retrying will not help."""


class OandaFeed:
    """Implements the scanner `Feed` protocol without MT5.

    `equity_usd` is the owner's Exness equity typed on the command line: OANDA is only a data
    source here, its own demo balance is never used for sizing.
    """

    def __init__(self, equity_usd: float, account_type: str = "Standard", token: str | None = None,
                 environment: str = "practice", http_get: HttpGet | None = None,
                 clock: Callable[[], datetime] | None = None, confirm_path=None, min_interval_s: float = 0.2) -> None:
        if token is None:
            from ayesha.credentials import get_token

            token = get_token()
        self.token = token
        if not self.token:
            raise MissingToken("No OANDA token: run install.bat (or `ayesha set-token`)")
        if environment not in HOSTS:
            raise ValueError(f"environment must be one of {sorted(HOSTS)}")
        if not (equity_usd > 0):
            raise ValueError("equity_usd must be positive (your Exness equity in USD)")
        self.host = HOSTS[environment]
        self.equity_usd = float(equity_usd)
        self.account_type = account_type
        self._get = http_get or _default_get
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.confirm_path = confirm_path
        self.min_interval_s = min_interval_s
        self._last_call = 0.0
        self.source_name = f"OANDA_V20_{environment.upper()}"

    # --- http ------------------------------------------------------------------------------
    def _call(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        wait = self.min_interval_s - (_time.monotonic() - self._last_call)
        if wait > 0:
            _time.sleep(wait)  # stay far below OANDA's documented rate limits
        self._last_call = _time.monotonic()
        url = f"{self.host}{path}?{urllib.parse.urlencode(params)}"
        try:
            return self._get(url, {"Authorization": f"Bearer {self.token}", "Accept-Datetime-Format": "RFC3339"})
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise AuthRejected(f"OANDA rejected the token (HTTP {e.code}); check it or create a new one") from None
            raise RuntimeError(f"OANDA HTTP {e.code}") from None

    # --- Feed protocol ---------------------------------------------------------------------
    def account(self) -> dict[str, Any]:
        return {"equity": self.equity_usd, "balance": self.equity_usd, "margin_free": None,
                "currency": "USD", "source": "OWNER_TYPED", "server": "OANDA data feed", "trade_mode": "DATA_ONLY"}

    def connect(self) -> dict[str, Any]:
        self.quote("EURUSD")  # proves the token and the network work
        return self.account()

    def close(self) -> None:
        pass

    def candles(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[Candle]:
        """Complete BID candles in [start, end). `spread` = ask close - bid close."""
        gran = GRANULARITY[timeframe]
        step = timedelta(seconds=TF_SECONDS[timeframe] * (MAX_CANDLES - 1))
        now = self.clock()
        end = min(end, now)
        out: list[Candle] = []
        t = start
        while t < end:
            chunk_end = min(t + step, end)
            body = self._call(f"/v3/instruments/{oanda_instrument(symbol)}/candles",
                              {"price": "BA", "granularity": gran, "from": _rfc3339(t), "to": _rfc3339(chunk_end)})
            for c in body.get("candles", []):
                if not c.get("complete"):
                    continue  # never use a bar that is still forming
                bid, ask = c["bid"], c["ask"]
                ct = parse_time(c["time"])
                if out and ct <= out[-1].time:
                    continue
                out.append(Candle(ct, float(bid["o"]), float(bid["h"]), float(bid["l"]), float(bid["c"]),
                                  float(c.get("volume", 0)), max(0.0, float(ask["c"]) - float(bid["c"]))))
            t = chunk_end
        return out

    def quote(self, symbol: str) -> Quote:
        """Latest bid/ask from the newest 5-second candle; its time is the quote time."""
        body = self._call(f"/v3/instruments/{oanda_instrument(symbol)}/candles",
                          {"price": "BA", "granularity": "S5", "count": 1})
        cs = body.get("candles") or []
        if not cs:
            raise RuntimeError(f"No quote for {symbol}")
        c = cs[-1]
        t = min(parse_time(c["time"]) + timedelta(seconds=5), self.clock())
        return Quote(symbol.upper(), t, float(c["bid"]["c"]), float(c["ask"]["c"]))

    def usd_per_quote(self, symbol: str, mid: float) -> float:
        s = symbol.upper()
        quote = s[3:6]
        if quote == "USD":
            return 1.0
        if s[:3] == "USD":
            return 1.0 / mid
        # cross: price the quote currency against USD from the feed itself
        for pair, invert in ((f"USD{quote}", True), (f"{quote}USD", False)):
            try:
                q = self.quote(pair)
            except Exception:
                continue
            m = (q.bid + q.ask) / 2
            return 1.0 / m if invert else m
        raise RuntimeError(f"No USD rate for {quote}")

    def spread_floor(self, symbol: str) -> float:
        """Owner's typical Exness spread (price units). OANDA's spread can be tighter than Exness's."""
        from ayesha.broker import load_assumed
        from ayesha.models import pip_size_for

        return float(load_assumed(self.account_type).get("typical_spread_pips", 0)) * pip_size_for(symbol)

    def instrument(self, symbol: str) -> InstrumentSpec:
        q = self.quote(symbol)
        return broker_spec(symbol, self.usd_per_quote(symbol, (q.bid + q.ask) / 2), self.account_type, self.confirm_path)
