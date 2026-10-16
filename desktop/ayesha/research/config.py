"""Research configuration: `%AYESHA_HOME%/research/config.yaml`, merged over safe defaults and validated strictly.

Research is OFF by default (`enabled: false` = legacy_only). The safety locks (no promotion, no live-scanner hooks,
no ML, no outside model calls, redaction on, loopback-only dashboard) are `const` in the schema, so a typo or an
edited file can only make research refuse to run, never loosen anything. The live scanner never reads this file.
"""

from __future__ import annotations

import copy
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ayesha.paths import home
from ayesha.research.contracts import ContractError, check

DEFAULTS: dict[str, Any] = {
    "schema_version": "research.config/1",
    "research": {
        "enabled": False,
        "role": "RESEARCH_ONLY",
        "promotion_enabled": False,
        "live_scanner_hooks_enabled": False,
        "ml_enabled": False,
        "workers": 1,
        "cpu_limit_percent": 40,
        "memory_limit_mb": 2048,
        "job_timeout_seconds": 3600,
        "data_source": "OANDA_V20_PRACTICE",
        "account_scenario": "DEMO_ONLY",
        "allow_outbound_model_inference": False,
        "report_redact_secrets": True,
        "historical_news_policy": "REQUIRE_POINT_IN_TIME",
        "dashboard_bind": "127.0.0.1",
        "legacy_only_fallback": True,
        "backup_keep": 7,
        "quality": {"max_gap_bars": 8, "min_coverage_percent": 98.0, "stale_run_bars": 6},
    },
}


class ResearchConfigError(RuntimeError):
    """The research config is invalid: research stays off (the live scanner is unaffected)."""


class ResearchDisabled(RuntimeError):
    """Research is turned off (legacy_only)."""


def research_home() -> Path:
    return home() / "research"


def config_path() -> Path:
    return research_home() / "config.yaml"


@dataclass(frozen=True)
class ResearchConfig:
    raw: dict[str, Any]
    path: Path
    file_exists: bool

    @property
    def r(self) -> dict[str, Any]:
        return self.raw["research"]

    @property
    def enabled(self) -> bool:
        return bool(self.r["enabled"])

    @property
    def quality(self) -> dict[str, Any]:
        return dict(self.r["quality"])


def _merge(base: dict[str, Any], over: dict[str, Any], path: str = "") -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if k not in base:
            raise ResearchConfigError(f"unknown setting {path}{k!r} in {config_path()}")
        out[k] = _merge(base[k], v, f"{path}{k}.") if isinstance(base[k], dict) and isinstance(v, dict) else v
    return out


def load(path: Path | None = None) -> ResearchConfig:
    p = path or config_path()
    over: dict[str, Any] = {}
    exists = p.exists()
    if exists:
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
            raise ResearchConfigError(f"cannot read {p}: {type(e).__name__}") from None
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ResearchConfigError(f"{p} must contain a mapping")
        over = data
    merged = _merge(DEFAULTS, over)
    try:
        check(merged, "research.config/1")
    except ContractError as e:
        raise ResearchConfigError(f"{p}: {e}") from None
    return ResearchConfig(merged, p, exists)


def require_enabled(cfg: ResearchConfig) -> None:
    if not cfg.enabled:
        raise ResearchDisabled("Research is off (legacy_only). Turn it on with: ayesha research enable")


def save_enabled(enabled: bool, path: Path | None = None) -> ResearchConfig:
    """Write `enabled` and keep every other setting the owner has; atomic replace, never a half-written file."""
    p = path or config_path()
    cur = load(p)
    data = copy.deepcopy(cur.raw)
    data["research"]["enabled"] = bool(enabled)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = ("# AYESHA research settings (research-only; the live scanner never reads this file).\n"
            "# enabled: false = legacy_only. Safety locks cannot be loosened: an invalid value turns research off.\n"
            + yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return load(p)
