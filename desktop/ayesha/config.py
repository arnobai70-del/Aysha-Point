"""Load the canonical strategy contract and compute its fingerprint."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

DEFAULT_SPEC = Path(__file__).resolve().parents[2] / "contracts" / "strategy-spec.yaml"


def load_spec(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else DEFAULT_SPEC
    with p.open("r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    spec["strategy_hash"] = strategy_hash(spec)
    return spec


def strategy_hash(spec: dict[str, Any]) -> str:
    """Short, stable fingerprint of the rule contract (key order independent)."""
    clean = {k: v for k, v in spec.items() if k != "strategy_hash"}
    canonical = json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
