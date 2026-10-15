"""Exness contract specs without MT5 (master spec section K).

Two sources, never mixed silently:
- ASSUMED_EXNESS_<ACCOUNT>: values from contracts/broker/exness-standard.yaml. The risk engine
  treats these as unverified in live mode, so no signal can become READY on them.
- OWNER_CONFIRMED:EXNESS_<ACCOUNT>: the owner typed the same numbers from the Exness app with
  `ayesha confirm-broker`; stored locally (not in the repo) with the date.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ayesha.models import InstrumentSpec, pip_size_for

BROKER_FILE = Path(__file__).resolve().parents[2] / "contracts" / "broker" / "exness-standard.yaml"
FIELDS = ("contract_size", "volume_min", "volume_step", "volume_max")


def default_confirm_path() -> Path:
    from ayesha.paths import home

    return home() / "broker-confirmed.json"


def load_assumed(account_type: str, path: Path = BROKER_FILE) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if account_type not in data["accounts"]:
        raise KeyError(f"Unsupported account type {account_type!r}; supported: {sorted(data['accounts'])}")
    return dict(data["accounts"][account_type])


def load_confirmed(account_type: str, path: Path | None = None) -> dict[str, Any] | None:
    p = path or default_confirm_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rec = data.get(account_type)
    if not rec or any(not isinstance(rec.get(k), (int, float)) or rec[k] <= 0 for k in FIELDS):
        return None
    return rec


def save_confirmed(account_type: str, values: dict[str, float], path: Path | None = None) -> Path:
    for k in FIELDS:
        v = values.get(k)
        if not isinstance(v, (int, float)) or not v > 0:
            raise ValueError(f"{k} must be a positive number")
    p = path or default_confirm_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    data[account_type] = {**{k: float(values[k]) for k in FIELDS},
                          "confirmed_at_utc": datetime.now(timezone.utc).isoformat()}
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def broker_spec(symbol: str, usd_per_quote: float, account_type: str = "Standard",
                confirm_path: Path | None = None) -> InstrumentSpec:
    """Instrument spec for an FX pair. `usd_per_quote` = USD value of 1 unit of the quote currency."""
    if not (usd_per_quote > 0):
        raise ValueError(f"No USD conversion for {symbol}")
    base = load_assumed(account_type)
    conf = load_confirmed(account_type, confirm_path)
    vals = {**base, **(conf or {})}
    symbol = symbol.upper()
    pip = pip_size_for(symbol)
    digits = 3 if pip == 0.01 else 5
    tick = 10 ** (-digits)
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
        commission_per_lot_round_trip=float(base.get("commission_per_lot_round_trip", 0)),
        stops_level_points=int(base.get("stops_level_points", 0)),
        source=(f"OWNER_CONFIRMED:EXNESS_{account_type.upper()}" if conf else f"ASSUMED_EXNESS_{account_type.upper()}"),
    )


def is_verified_source(source: str) -> bool:
    """Specs read from the broker terminal, or typed by the owner from the broker app."""
    return source.startswith("MT5") or source.startswith("OWNER_CONFIRMED:")
