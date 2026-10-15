"""Exness contract specs without MT5 (master spec section K; News spec B2, C04).

Two sources, never mixed silently:
- ASSUMED_EXNESS_<ACCOUNT>: values from contracts/broker/exness-standard.yaml. The risk engine
  treats these as unverified in live mode, so no signal can become READY on them.
- OWNER_CONFIRMED:EXNESS_<ACCOUNT>: the owner typed the numbers from the Exness app with
  `ayesha confirm-broker`, **per symbol**; stored locally (not in the repo) with the date.
  Confirming EURUSD does not confirm GBPUSD: every pair needs its own confirmation.

File layout (%AYESHA_HOME%\\broker-confirmed.json):
    {"Standard": {"leverage": 2000 | "UNLIMITED", "leverage_confirmed_at_utc": ...,
                  "symbols": {"EURUSD": {contract_size, volume_min, volume_step, volume_max,
                                         stops_level_points, typical_spread_pips, confirmed_at_utc}}}}
A file from release 0.7.x (one record per account type, typed from EURUSD) counts for EURUSD only.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ayesha.models import InstrumentSpec, pip_size_for

BROKER_FILE = Path(__file__).resolve().parents[2] / "contracts" / "broker" / "exness-standard.yaml"
FIELDS = ("contract_size", "volume_min", "volume_step", "volume_max")
OPTIONAL = ("stops_level_points", "typical_spread_pips", "commission_per_lot_round_trip")
LEGACY_SYMBOL = "EURUSD"


def default_confirm_path() -> Path:
    from ayesha.paths import home

    return home() / "broker-confirmed.json"


def load_assumed(account_type: str, path: Path = BROKER_FILE) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if account_type not in data["accounts"]:
        raise KeyError(f"Unsupported account type {account_type!r}; supported: {sorted(data['accounts'])}")
    return dict(data["accounts"][account_type])


def _read(path: Path | None) -> dict[str, Any]:
    p = path or default_confirm_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _account(data: dict[str, Any], account_type: str) -> dict[str, Any]:
    rec = dict(data.get(account_type) or {})
    if "symbols" not in rec and all(k in rec for k in FIELDS):  # 0.7.x layout: typed from EURUSD only
        rec = {"symbols": {LEGACY_SYMBOL: {k: rec[k] for k in rec}}}
    rec.setdefault("symbols", {})
    return rec


def _valid(rec: dict[str, Any] | None) -> bool:
    return bool(rec) and all(isinstance(rec.get(k), (int, float)) and math.isfinite(rec[k]) and rec[k] > 0
                             for k in FIELDS)


def load_confirmed(account_type: str, path: Path | None = None, symbol: str = LEGACY_SYMBOL) -> dict[str, Any] | None:
    rec = _account(_read(path), account_type)["symbols"].get(symbol.upper())
    return rec if _valid(rec) else None


def confirmed_symbols(account_type: str, path: Path | None = None) -> list[str]:
    return sorted(s for s, r in _account(_read(path), account_type)["symbols"].items() if _valid(r))


def load_leverage(account_type: str, path: Path | None = None) -> float | str | None:
    lev = _account(_read(path), account_type).get("leverage")
    if lev == "UNLIMITED" or (isinstance(lev, (int, float)) and math.isfinite(lev) and lev >= 1):
        return lev
    return None


def _write(path: Path | None, data: dict[str, Any]) -> Path:
    p = path or default_confirm_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def save_confirmed(account_type: str, values: dict[str, float], path: Path | None = None,
                   symbol: str = LEGACY_SYMBOL) -> Path:
    for k in FIELDS:
        v = values.get(k)
        if not isinstance(v, (int, float)) or not (math.isfinite(v) and v > 0):
            raise ValueError(f"{k} must be a positive number")
    for k in OPTIONAL:
        v = values.get(k)
        if v is not None and (not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0):
            raise ValueError(f"{k} must be 0 or more")
    sym = symbol.upper()
    if len(sym) != 6 or not sym.isalpha():
        raise ValueError(f"bad symbol {symbol!r}")
    data = _read(path)
    acc = _account(data, account_type)
    acc["symbols"][sym] = {**{k: float(values[k]) for k in FIELDS},
                           **{k: float(values[k]) for k in OPTIONAL if values.get(k) is not None},
                           "confirmed_at_utc": datetime.now(timezone.utc).isoformat()}
    data[account_type] = acc
    return _write(path, data)


def save_leverage(account_type: str, leverage: float | str, path: Path | None = None) -> Path:
    if leverage != "UNLIMITED" and not (isinstance(leverage, (int, float)) and math.isfinite(leverage) and leverage >= 1):
        raise ValueError("leverage must be a number like 2000 (for 1:2000) or UNLIMITED")
    data = _read(path)
    acc = _account(data, account_type)
    acc["leverage"] = leverage
    acc["leverage_confirmed_at_utc"] = datetime.now(timezone.utc).isoformat()
    data[account_type] = acc
    return _write(path, data)


def margin_leverage(lev: float | str | None, news_cap: float = 200.0) -> float | None:
    """Leverage used for the margin check: never above `news_cap` (Exness limits leverage around news)."""
    if lev is None:
        return None
    return news_cap if lev == "UNLIMITED" else min(float(lev), news_cap)


def broker_spec(symbol: str, usd_per_quote: float, account_type: str = "Standard",
                confirm_path: Path | None = None, mid: float | None = None,
                news_leverage_cap: float = 200.0) -> InstrumentSpec:
    """Instrument spec for an FX pair. `usd_per_quote` = USD value of 1 unit of the quote currency;
    `mid` (price) is needed for the margin estimate."""
    if not (usd_per_quote > 0):
        raise ValueError(f"No USD conversion for {symbol}")
    symbol = symbol.upper()
    base = load_assumed(account_type)
    conf = load_confirmed(account_type, confirm_path, symbol)
    vals = {**base, **(conf or {})}
    pip = pip_size_for(symbol)
    digits = 3 if pip == 0.01 else 5
    tick = 10 ** (-digits)
    lev = margin_leverage(load_leverage(account_type, confirm_path), news_leverage_cap)
    margin = None
    if conf and lev and mid and mid > 0:
        margin = float(vals["contract_size"]) * mid * usd_per_quote / lev  # USD for 1.0 lot (base value / leverage)
    return InstrumentSpec(
        symbol=symbol,
        digits=digits,
        tick_size=tick,
        tick_value=float(vals["contract_size"]) * tick * usd_per_quote,
        contract_size=float(vals["contract_size"]),
        volume_min=float(vals["volume_min"]),
        volume_step=float(vals["volume_step"]),
        volume_max=float(vals["volume_max"]),
        pip_size=pip,
        base_currency=symbol[:3],
        quote_currency=symbol[3:6],
        commission_per_lot_round_trip=float(vals.get("commission_per_lot_round_trip", 0)),
        stops_level_points=int(vals.get("stops_level_points", 0)),
        margin_per_lot=margin,
        source=(f"OWNER_CONFIRMED:EXNESS_{account_type.upper()}:{symbol}" if conf else f"ASSUMED_EXNESS_{account_type.upper()}"),
    )


def typical_spread_pips(symbol: str, account_type: str, confirm_path: Path | None = None) -> float:
    conf = load_confirmed(account_type, confirm_path, symbol) or {}
    if "typical_spread_pips" in conf:
        return float(conf["typical_spread_pips"])
    return float(load_assumed(account_type).get("typical_spread_pips", 0))


def is_verified_source(source: str) -> bool:
    """Specs read from the broker terminal, or typed by the owner from the broker app."""
    return source.startswith("MT5") or source.startswith("OWNER_CONFIRMED:")
