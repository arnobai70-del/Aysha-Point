"""Strategy registration and loading (plan §6.2, ticket AI-008).

Only the built-in strategies listed in `REGISTRY` can be loaded: the id is looked up, never imported by name, so a
string from a config file or a job file cannot pull in other code. Every load builds and validates the manifest
(`research.strategy/1`): research_only true, execution level NONE, parameters inside their pre-registered bounds.
Collisions are found at load time (an id twice in the registry, or the same id and version registered earlier
with a different hash, which means the rules changed without a new version). Each instance gets its own copy of
its parameters, so one experiment cannot change another's, and the live spec is only ever read through a copy.
"""

from __future__ import annotations

import copy
from typing import Any

from ayesha.research.contracts import check
from ayesha.research.provenance import digest
from ayesha.research.strategies import baseline, control, experimental

REGISTRY = {
    baseline.BaselineSweep.strategy_id: baseline.BaselineSweep,
    control.LondonOrb.strategy_id: control.LondonOrb,
    experimental.H1H4Trend.strategy_id: experimental.H1H4Trend,
}
SOURCES = {control.LondonOrb.strategy_id: control.source_sha,
           experimental.H1H4Trend.strategy_id: experimental.source_sha}
LAB_ORDER = (baseline.BaselineSweep.strategy_id, control.LondonOrb.strategy_id, experimental.H1H4Trend.strategy_id)
NEWS_SOURCE = "NOT_MODELLED: no point-in-time historical calendar (v1.1.0 item, BLOCKED_BY_DATA)"
COST_SOURCE = "research-runner cost model (legacy replay fills, live risk-engine gates)"


class StrategyError(ValueError):
    """Unknown strategy, bad parameters or a registration collision."""


def _check_registry() -> None:
    ids = [cls.strategy_id for cls in REGISTRY.values()]
    if len(ids) != len(set(ids)) or any(k != v.strategy_id for k, v in REGISTRY.items()):
        raise StrategyError("strategy registry has a duplicate or mismatched id")
    if sum(1 for cls in REGISTRY.values() if cls.kind == "EXPERIMENTAL") != 1:
        raise StrategyError("v1.0.0 allows exactly one experimental strategy")


def params_for(strategy_id: str, overrides: dict[str, float] | None = None) -> dict[str, float]:
    cls = REGISTRY[strategy_id]
    if strategy_id == baseline.BaselineSweep.strategy_id:
        if overrides:
            raise StrategyError("the baseline is frozen: parameters cannot be changed")
        return {}
    p = {k: v.value for k, v in cls.params_def.items()}
    for k, v in (overrides or {}).items():
        if k not in cls.params_def:
            raise StrategyError(f"{strategy_id} has no parameter {k!r}")
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not cls.params_def[k].ok(float(v)):
            d = cls.params_def[k]
            raise StrategyError(f"{strategy_id}.{k}={v!r} is outside its registered bounds [{d.low}, {d.high}]")
        p[k] = float(v)
    return p


def manifest(strategy_id: str, spec: dict[str, Any], overrides: dict[str, float] | None = None) -> dict[str, Any]:
    _check_registry()
    if strategy_id not in REGISTRY:
        raise StrategyError(f"unknown research strategy {strategy_id!r}; available: {', '.join(REGISTRY)}")
    cls = REGISTRY[strategy_id]
    if strategy_id == baseline.BaselineSweep.strategy_id:
        params_for(strategy_id, overrides)
        return baseline.BaselineSweep.manifest_for(spec)
    p = params_for(strategy_id, overrides)
    h = digest({"id": strategy_id, "version": cls.version, "parameters": p, "code": SOURCES[strategy_id]()})[:12]
    return check({
        "schema_version": "research.strategy/1",
        "strategy_id": strategy_id, "version": cls.version, "strategy_hash": h,
        "explanation": cls.explanation, "timeframes": list(cls.timeframes),
        "symbols": sorted(set(spec["pairs"]["enabled"]) | set(spec["pairs"].get("disabled", []))
                          - {"XAUUSD", "USOIL", "BTCUSD"}),
        "parameters": p,
        "parameter_bounds": {k: {"default": v.value, "low": v.low, "high": v.high, "step": v.step}
                             for k, v in cls.params_def.items()},
        "dependencies": ["ayesha.rules.primitives.ATR", "ayesha.rules.strategy.Aggregator", "ayesha.sessions"],
        "lookback_bars": int(cls.lookback_bars), "stateful": True,
        "research_only": True, "execution_level": "NONE",
        "news_source": NEWS_SOURCE, "cost_source": COST_SOURCE, "kind": cls.kind,
    }, "research.strategy/1")


def load(strategy_id: str, symbol: str, spec: dict[str, Any], overrides: dict[str, float] | None = None):
    """A fresh strategy instance for one symbol. The spec handed over is a deep copy."""
    man = manifest(strategy_id, spec, overrides)
    cls = REGISTRY[strategy_id]
    inst = cls(symbol, copy.deepcopy(spec), None if strategy_id == baseline.BaselineSweep.strategy_id
               else params_for(strategy_id, overrides))
    inst.strategy_hash = man["strategy_hash"]
    return inst, man


def available(spec: dict[str, Any]) -> list[dict[str, Any]]:
    return [manifest(sid, spec) for sid in LAB_ORDER]
