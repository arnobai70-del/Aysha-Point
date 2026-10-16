"""Baseline A for the Strategy Lab: the frozen live rule set SWEEP_MSS_FVG, wrapped without any change.

The wrapped engine is the legacy `ayesha.rules.mtf.MtfEngine` built from a private copy of the live spec; its
events go to the common runner unchanged. Its identity is the live strategy version and hash, the same manifest as
the v0.9.0 baseline (`ayesha.research.simulation.baseline.strategy_manifest`). Through the common runner it gives
exactly the trades of the legacy replay on the same bars (`evaluation.comparison.benchmark_parity` proves it on
every lab run). A benchmark, not a proven edge.
"""

from __future__ import annotations

import copy
from typing import Any

from ayesha.research.simulation.baseline import STRATEGY_ID, strategy_manifest
from ayesha.research.strategies.protocol import AsOfContext
from ayesha.rules.mtf import Event, MtfEngine


class BaselineSweep:
    strategy_id = STRATEGY_ID
    kind = "BASELINE"

    def __init__(self, symbol: str, spec: dict[str, Any], params: dict[str, Any] | None = None) -> None:
        if params:
            raise ValueError("the baseline is frozen: it takes no research parameters")
        self.spec = copy.deepcopy(spec)  # the engine can never touch the caller's (live) spec
        self.spec["mtf"]["confirm_timeframe"] = None  # the lab compares on M15 base bars
        self.version = spec["strategy_version"]
        self.strategy_hash = spec["strategy_hash"]
        self.engine = MtfEngine(symbol, self.spec)

    @staticmethod
    def manifest_for(spec: dict[str, Any]) -> dict[str, Any]:
        return strategy_manifest(spec)

    def manifest(self) -> dict[str, Any]:
        return strategy_manifest(self.spec)

    @property
    def rejections(self) -> list:
        return self.engine.rejections

    def evaluate(self, ctx: AsOfContext) -> list[Event]:
        return self.engine.on_bar(ctx.bar)
