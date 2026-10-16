"""Plan T06: with the research plane present (and whatever its flags say), the legacy advisory path behaves exactly as
release 0.8.0 did on controlled inputs: same signal ids, statuses, lifecycle, signed phone messages, replay trades,
CLI options, and byte-identical protected files. The fixture was generated from the 0.8.0 code before any research
code was added (tests/research/golden.py)."""

import json

import pytest

from tests.research import golden

EXPECTED = json.loads(golden.FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def current(tmp_path_factory):
    return golden.fingerprint(tmp_path_factory.mktemp("golden"))


def _diff(want: dict, got: dict) -> list[str]:
    keys = sorted(set(want) | set(got))
    return [f"{k}: expected {want.get(k)!r}, got {got.get(k)!r}" for k in keys if want.get(k) != got.get(k)]


def test_t06_strategy_identity_unchanged(current):
    assert current["strategy"] == EXPECTED["strategy"] == {"version": "0.4.0", "hash": "9bb5e8ed5937"}


@pytest.mark.parametrize("scenario", sorted(EXPECTED["scanner"]))
def test_t06_scanner_signals_lifecycle_and_signed_messages_match_0_8_0(current, scenario):
    want, got = EXPECTED["scanner"][scenario], current["scanner"][scenario]
    assert got == want, "\n".join(_diff(want, got) + _diff(want["sha256"], got["sha256"]))


@pytest.mark.parametrize("scenario", sorted(EXPECTED["replay"]))
def test_t06_replay_trades_match_0_8_0(current, scenario):
    want, got = EXPECTED["replay"][scenario], current["replay"][scenario]
    assert got == want, "\n".join(_diff(want, got) + _diff(want["sha256"], got["sha256"]))


def test_t06_legacy_cli_options_unchanged(current):
    assert current["cli"] == EXPECTED["cli"], "\n".join(_diff(EXPECTED["cli"], current["cli"]))


def test_t06_protected_legacy_files_are_byte_identical(current):
    changed = _diff(EXPECTED["protected_files"], current["protected_files"])
    assert not changed, ("protected legacy files changed (an approved legacy change needs a new fixture and a "
                         "docs/DECISIONS.md entry):\n" + "\n".join(changed))


def test_t06_fixture_is_rich_enough_to_mean_something():
    """Guard against a vacuous fingerprint: the scenarios must exercise READY, news, NO_TRADE and closed trades."""
    sc = EXPECTED["scanner"]
    assert sc["equity_100000_no_news"]["signals"] >= 10
    assert sc["equity_100000_no_news"]["status_counts"].get("OBSERVED_SL", 0) > 0  # READY -> touched -> observed
    assert set(sc["equity_20_no_news"]["status_counts"]) == {"NO_TRADE"}
    assert sc["equity_100000_news_schedule"]["messages"].get("NEWS", 0) > 0
    rp = EXPECTED["replay"]
    assert rp["m15_news_none"]["closed"] > 0
    assert "INVALIDATED" in rp["m15_from_m5_news_upgraded"]["by_status"]
