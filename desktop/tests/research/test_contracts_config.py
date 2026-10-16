"""AI-002: research contracts and the research configuration. Research is OFF by default and its safety locks cannot
be loosened by editing the file: an invalid value only turns research off."""

import json

import pytest
import yaml

from ayesha.research import contracts
from ayesha.research.config import DEFAULTS, ResearchConfigError, load, save_enabled


@pytest.mark.parametrize("name", sorted(contracts.SCHEMAS))
def test_every_schema_loads_and_uses_only_supported_keywords(name):
    schema = contracts.load_schema(name)
    assert schema["title"]
    assert contracts.unsupported_keywords(schema) == []


def test_defaults_are_valid_and_research_is_off_by_default(home):
    cfg = load(home / "research" / "config.yaml")
    assert cfg.file_exists is False
    assert cfg.enabled is False
    assert contracts.validate(DEFAULTS, "research.config/1") == []
    r = cfg.r
    assert (r["promotion_enabled"], r["live_scanner_hooks_enabled"], r["ml_enabled"],
            r["allow_outbound_model_inference"]) == (False, False, False, False)
    assert r["dashboard_bind"] == "127.0.0.1" and r["report_redact_secrets"] is True and r["workers"] == 1


@pytest.mark.parametrize("override", [
    {"promotion_enabled": True}, {"live_scanner_hooks_enabled": True}, {"ml_enabled": True},
    {"allow_outbound_model_inference": True}, {"report_redact_secrets": False}, {"dashboard_bind": "0.0.0.0"},
    {"workers": 4}, {"role": "LIVE"}, {"account_scenario": "REAL_MONEY"}, {"data_source": "SCRAPED_FEED"},
    {"historical_news_policy": "ANY"}, {"cpu_limit_percent": 100}, {"memory_limit_mb": 64},
    {"legacy_only_fallback": False}, {"enabled": "yes"}, {"surprise_setting": 1}, {"quality": {"max_gap_bars": -1}},
])
def test_safety_locks_cannot_be_loosened(home, override):
    p = home / "research" / "config.yaml"
    p.parent.mkdir(parents=True)
    p.write_text(yaml.safe_dump({"research": override}), encoding="utf-8")
    with pytest.raises(ResearchConfigError):
        load(p)


def test_unreadable_or_odd_config_is_an_error_not_a_default(home):
    p = home / "research" / "config.yaml"
    p.parent.mkdir(parents=True)
    for text in ("research: [1, 2", "- just\n- a list\n", "research: {enabled: true}\nextra: 1\n"):
        p.write_text(text, encoding="utf-8")
        with pytest.raises(ResearchConfigError):
            load(p)


def test_save_enabled_round_trip_keeps_owner_settings(home):
    p = home / "research" / "config.yaml"
    p.parent.mkdir(parents=True)
    p.write_text(yaml.safe_dump({"research": {"cpu_limit_percent": 25, "backup_keep": 3}}), encoding="utf-8")
    on = save_enabled(True, p)
    assert on.enabled and on.r["cpu_limit_percent"] == 25 and on.r["backup_keep"] == 3
    off = save_enabled(False, p)
    assert not off.enabled and off.r["cpu_limit_percent"] == 25
    assert "research-only" in p.read_text(encoding="utf-8")


def _candidate(**kw):
    c = {"schema_version": "research.candidate/1", "research_candidate_id": "rc_0123456789abcdef",
         "source_type": "RESEARCH", "executable": False, "run_id": "run_0123456789abcdef",
         "strategy_id": "baseline-sweep-mss-fvg", "strategy_version": "0.4.0", "strategy_hash": "9bb5e8ed5937",
         "dataset_id": "ds_0123456789abcdef", "asof_utc": "2025-03-03T10:15:00Z", "pair": "EURUSD",
         "direction": "BUY", "levels": {"entry": 1.08, "stop": 1.079, "targets": [1.082]},
         "proposed_state": "HYPOTHETICAL_CLOSED", "replay_status": "CLOSED", "outcome_r": 1.2,
         "rejection_codes": [], "explanation": "x"}
    c.update(kw)
    return c


def test_research_candidate_can_never_be_ready_or_executable():
    assert contracts.validate(_candidate(), "research.candidate/1") == []
    for bad in (_candidate(proposed_state="READY"), _candidate(executable=True), _candidate(source_type="LIVE"),
                _candidate(lot=0.01), _candidate(asof_utc="2025-03-03 10:15:00")):
        assert contracts.validate(bad, "research.candidate/1"), bad


def test_validator_is_strict_about_types():
    assert contracts.validate(_candidate(executable=0), "research.candidate/1")  # 0 is not false
    assert contracts.validate(_candidate(outcome_r=float("nan")), "research.candidate/1")
    with pytest.raises(contracts.ContractError):
        contracts.check(_candidate(pair="eurusd"), "research.candidate/1")


def test_strategy_manifest_must_be_research_only():
    from ayesha.config import load_spec
    from ayesha.research.simulation.baseline import strategy_manifest

    m = strategy_manifest(load_spec())
    assert m["research_only"] is True and m["execution_level"] == "NONE" and m["kind"] == "BASELINE"
    for k, v in (("research_only", False), ("execution_level", "MANUAL_ALERT")):
        assert contracts.validate({**m, k: v}, "research.strategy/1")


def test_schemas_are_valid_json_with_ids_under_contracts_research():
    for f in sorted(contracts.SCHEMA_DIR.glob("*.schema.json")):
        s = json.loads(f.read_text(encoding="utf-8"))
        assert s["$id"].endswith("/contracts/research/" + f.name)
