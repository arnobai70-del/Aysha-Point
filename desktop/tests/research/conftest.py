"""Fixtures for the research tests: a throwaway AYESHA_HOME, research on, synthetic data. No network, no token."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.research import synth


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    h = tmp_path / "AyeshaFX"
    monkeypatch.setenv("AYESHA_HOME", str(h))
    monkeypatch.delenv("AYESHA_OANDA_TOKEN", raising=False)
    return h


@pytest.fixture
def ws(home):
    """Research ON, small worker limits (fast resource tests)."""
    import yaml

    from ayesha.research.config import load
    from ayesha.research.workspace import Workspace

    root = home / "research"
    root.mkdir(parents=True)
    (root / "config.yaml").write_text(yaml.safe_dump({"research": {"enabled": True, "memory_limit_mb": 256,
                                                                   "job_timeout_seconds": 120}}), encoding="utf-8")
    w = Workspace(load(root / "config.yaml"), root)
    yield w
    w.close()


@pytest.fixture
def csv_folder(tmp_path) -> Path:
    return synth.csv_dir(tmp_path / "csv", m15=4000, m5=6000, seed=11)
