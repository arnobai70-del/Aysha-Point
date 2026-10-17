"""T05 / T10 / T12 (partial): research is isolated from the live path, OFF by default, and turning it off returns the
exact 0.8.0 behaviour without losing research data. Also the command line end to end, and version consistency."""

import json
import re
import sqlite3
from pathlib import Path

import pytest

from ayesha.cli import main as ayesha
from tests.research import golden, synth

ROOT = Path(__file__).resolve().parents[3]
EXPECTED = json.loads(golden.FIXTURE.read_text(encoding="utf-8"))


def test_static_isolation_rules_hold():
    from ayesha.research.isolation import check

    assert check(ROOT / "desktop" / "ayesha", ROOT / "desktop" / "windows") == []


def test_isolation_check_catches_violations(tmp_path):
    from ayesha.research.isolation import check

    pkg = tmp_path / "ayesha"
    (pkg / "research").mkdir(parents=True)
    (pkg / "scanner.py").write_text("from ayesha.research import cli\n", encoding="utf-8")
    (pkg / "research" / "x.py").write_text(
        "import ayesha.delivery.push\nfrom ayesha.storage.db import Registry\nimport subprocess\n"
        "state = 'READY'\neval('1')\nimport os\nos.system('x')\n", encoding="utf-8")
    win = tmp_path / "windows"
    win.mkdir()
    (win / "start-ayesha.bat").write_text("python -m ayesha.cli research run\n", encoding="utf-8")
    problems = "\n".join(check(pkg, win))
    for needle in ("legacy code imports ayesha.research", "research imports ayesha.delivery.push",
                   "research imports ayesha.storage.db", "subprocess is only allowed", "'READY'", "eval()",
                   "os.system()", "a live script mentions research"):
        assert needle in problems, needle


def test_t05_research_cannot_write_the_live_registry(home):
    from ayesha.research.readonly import open_ro
    from ayesha.storage.db import Registry

    home.mkdir(parents=True)
    Registry(home / "ayesha.db").db.close()
    con = open_ro(home / "ayesha.db")
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        con.execute("INSERT INTO engine_health (at_utc, state) VALUES ('x', 'READY')")
    con.close()


def test_research_is_off_by_default_and_creates_nothing(home, capsys):
    assert ayesha(["research", "status"]) == 0
    out = capsys.readouterr().out
    assert "OFF (legacy_only)" in out and "No research data yet" in out
    assert ayesha(["research", "run", "baseline-sweep-mss-fvg", "--dataset", "ds_x", "--symbol", "EURUSD"]) == 2
    assert "Research is OFF" in capsys.readouterr().out
    assert ayesha(["research", "ingest", "--from-csv-dir", str(home)]) == 2
    assert not (home / "research").exists()
    assert ayesha(["research", "doctor"]) == 0  # the doctor works with research off and creates nothing
    assert not (home / "research" / "research.db").exists()


def test_cli_end_to_end_then_t10_rollback(home, tmp_path, capsys):
    synth.csv_dir(tmp_path / "csv", m15=3000, m5=6000, seed=4)
    assert ayesha(["research", "enable"]) == 0
    assert ayesha(["research", "ingest", "--from-csv-dir", str(tmp_path / "csv"), "--label", "synthetic"]) == 0
    assert "quality PASS" in capsys.readouterr().out
    assert ayesha(["research", "datasets", "--json"]) == 0
    ds = json.loads(capsys.readouterr().out)[0]["dataset_id"]
    assert ayesha(["research", "inspect", ds]) == 0
    assert "coverage 100.0%" in capsys.readouterr().out
    assert ayesha(["research", "run", "baseline-sweep-mss-fvg", "--dataset", ds, "--symbol", "EURUSD",
                   "--mode", "m5confirm", "--split", "2025-03-20"]) == 0
    capsys.readouterr()
    assert ayesha(["research", "runs", "--json"]) == 0
    run = json.loads(capsys.readouterr().out)[0]["run_id"]
    assert ayesha(["research", "run", "baseline-sweep-mss-fvg", "--dataset", ds, "--symbol", "EURUSD",
                   "--mode", "m5confirm", "--split", "2025-03-20", "--verify"]) == 0
    assert "VERIFIED" in capsys.readouterr().out
    md = tmp_path / "r.md"
    assert ayesha(["research", "report", run, "--md", str(md)]) == 0
    assert "RESEARCH ONLY" in md.read_text(encoding="utf-8")
    capsys.readouterr()
    assert ayesha(["research", "parity", "--dataset", ds, "--symbol", "EURUSD"]) == 0
    assert "Parity MATCHED" in capsys.readouterr().out
    capsys.readouterr()
    assert ayesha(["research", "backup"]) == 0
    backup = re.search(r"Backup: (\S+)", capsys.readouterr().out).group(1)
    assert ayesha(["research", "restore", backup, "--yes"]) == 0
    assert ayesha(["research", "doctor", "--deep"]) == 0
    assert ayesha(["research", "selftest", "ok"]) == 0
    assert ayesha(["research", "dashboard", "--check"]) == 0
    capsys.readouterr()

    # T10: turn research off -> legacy_only; the legacy path is exactly 0.8.0 and research data is kept
    assert ayesha(["research", "disable"]) == 0
    assert golden.protected_files() == EXPECTED["protected_files"]
    assert golden._cli_structure() == EXPECTED["cli"]
    capsys.readouterr()
    assert ayesha(["research", "datasets", "--json"]) == 0
    assert [d["dataset_id"] for d in json.loads(capsys.readouterr().out)] == [ds]
    files = sorted(p for p in (home / "research").rglob("*") if p.is_file() and "logs" not in p.parts)
    assert ayesha(["research", "run", "baseline-sweep-mss-fvg", "--dataset", ds, "--symbol", "EURUSD"]) == 2
    assert sorted(p for p in (home / "research").rglob("*") if p.is_file() and "logs" not in p.parts) == files
    assert ayesha(["research", "enable"]) == 0  # and it comes back with everything
    capsys.readouterr()
    assert ayesha(["research", "runs", "--json"]) == 0
    assert run in capsys.readouterr().out


def test_disable_always_works_even_with_a_broken_settings_file(home, capsys):
    p = home / "research" / "config.yaml"
    p.parent.mkdir(parents=True)
    p.write_text("research: {promotion_enabled: true}\n", encoding="utf-8")
    assert ayesha(["research", "status"]) == 0
    assert "config invalid" in capsys.readouterr().out
    assert ayesha(["research", "disable"]) == 0
    assert list(p.parent.glob("config.invalid-*.yaml"))
    from ayesha.research.config import load

    assert load(p).enabled is False


def test_research_files_never_hold_the_token_or_pairing_code(ws, home):
    """T05: after a full OANDA-style flow nothing under research/ contains the token or a pairing code."""
    import gzip
    from datetime import timedelta

    from ayesha.config import load_spec
    from ayesha.research.datasets.ingest import ingest_oanda
    from ayesha.research.simulation.baseline import run_baseline

    token = "0123456789abcdef" * 2 + "-" + "fedcba9876543210" * 2
    series = {"M15": synth.fx_week(2500, seed=8)}
    end = series["M15"][-1].time + timedelta(minutes=20)
    r = ingest_oanda(ws, load_spec(), ["EURUSD"], days=30, timeframes=("M15",), token=token,
                     http_get=synth.FakeOanda(series), clock=lambda: end, sleep=lambda s: None, min_interval_s=0)
    run_baseline(ws, load_spec(), r["dataset_id"], "EURUSD", allow_degraded=True)
    ws.db.backup(ws.backups)
    for f in (home / "research").rglob("*"):
        if f.is_file():
            data = f.read_bytes()
            data = gzip.decompress(data) if f.suffix == ".gz" else data
            assert token.encode() not in data and b"Authorization" not in data, f


def test_t12_base_dependencies_unchanged_and_versions_consistent():
    import ayesha
    from ayesha.research import RESEARCH_VERSION

    py = (ROOT / "desktop" / "pyproject.toml").read_text(encoding="utf-8")
    deps = re.search(r"^dependencies = \[(.*?)\]", py, re.M | re.S).group(1)
    assert re.findall(r'"([^"]+)"', deps) == ["pyyaml>=6.0", "tzdata>=2024.1"]  # research adds no dependency
    version = re.search(r'^version = "([^"]+)"', py, re.M).group(1)
    man = json.loads((ROOT / "contracts" / "version.json").read_text(encoding="utf-8"))
    assert ayesha.__version__ == version == man["components"]["desktop"] == man["release"] == RESEARCH_VERSION
    assert man["components"]["research_contracts"] == "3"
    assert (man["components"]["strategy"], man["components"]["signal_schema"],
            man["components"]["phone_wire_format"], man["components"]["android_app"]) == ("0.4.0", "1.1", "4", "0.5.0")
