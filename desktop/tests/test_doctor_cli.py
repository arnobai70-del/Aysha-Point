"""`ayesha doctor` (with fakes, no network) and `ayesha report` on SYNTHETIC CSVs."""

from datetime import datetime, timedelta, timezone

from ayesha import cli
from ayesha.doctor import run_doctor
from ayesha.feed.csv_feed import save_candles
from ayesha.models import Quote
from ayesha.news.calendar import NewsCalendar
from tests.helpers import synthetic

NOW = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)


class _Feed:
    def __init__(self, **kw):
        self.kw = kw

    def quote(self, sym):
        return Quote(sym, NOW - timedelta(seconds=3), 1.08, 1.08008)


class _Notifier:
    sent = []

    def __init__(self, code):
        self.code = code

    def heartbeat(self, *a):
        _Notifier.sent.append(a)
        return True, "HTTP 200"


def _names(rows, ok):
    return {n for o, n, _ in rows if o is ok}


def test_doctor_reports_every_missing_piece(tmp_path):
    rows = run_doctor(env={}, home=tmp_path, make_calendar=lambda p: None, publish=True, clock=lambda: NOW)
    bad = _names(rows, False)
    assert {"OANDA token", "Exness contract", "Pairing code", "News calendar"} <= bad
    assert "OANDA prices" not in _names(rows, True)


def test_doctor_all_green_with_fakes(tmp_path):
    from ayesha.broker import save_confirmed, load_assumed
    from ayesha.delivery.push import new_pairing_code

    save_confirmed("Standard", {k: float(v) for k, v in load_assumed("Standard").items()
                                if k in __import__("ayesha.broker", fromlist=["FIELDS"]).FIELDS},
                   tmp_path / "broker-confirmed.json")
    (tmp_path / "pairing-code.txt").write_text(new_pairing_code(), encoding="utf-8")
    cal = NewsCalendar([], NOW - timedelta(days=1), NOW + timedelta(days=3))
    rows = run_doctor(env={"AYESHA_OANDA_TOKEN": "x" * 20}, home=tmp_path, make_feed=_Feed,
                      make_calendar=lambda p: cal, make_notifier=_Notifier, clock=lambda: NOW)
    assert all(ok for ok, _, _ in rows), rows
    assert _Notifier.sent and _Notifier.sent[-1][1] == "TEST"
    assert not any("x" * 20 in d for _, _, d in rows), "token value must never be printed"


def test_report_cli_on_synthetic_csv(tmp_path, capsys):
    d = tmp_path / "data"
    d.mkdir()
    save_candles(d / "EURUSD_M15.csv", synthetic(5000), 0.00001)
    save_candles(d / "EURUSD_M5.csv", synthetic(12000, minutes=5, vol=0.00035), 0.00001)
    out, md = tmp_path / "r.json", tmp_path / "r.md"
    rc = cli.main(["report", "--data-dir", str(d), "--pairs", "EURUSD,GBPUSD", "--folds", "3",
                   "--split", "2025-04-01", "--label", "SYNTHETIC test data", "--out", str(out), "--md", str(md)])
    assert rc == 0
    import json
    rep = json.loads(out.read_text())
    assert set(rep["runs"]) == {"EURUSD|m15", "EURUSD|m5confirm"}
    assert any("GBPUSD_M15.csv" in m for m in rep["missing_files"])
    txt = md.read_text()
    assert "SYNTHETIC test data" in txt and "NOT modelled" in txt


def test_report_cli_without_data_explains_export(tmp_path, capsys):
    rc = cli.main(["report", "--data-dir", str(tmp_path)])
    assert rc == 1 and "ayesha export --feed oanda" in capsys.readouterr().out


def test_windows_scripts_call_valid_commands():
    """Every `-m ayesha.cli ...` line in the Windows scripts must parse with the current CLI."""
    import re
    import shlex
    from pathlib import Path

    win = Path(__file__).resolve().parents[1] / "windows"
    parser = cli.build_parser()
    seen = 0
    for bat in win.glob("*.bat"):
        for line in bat.read_text(encoding="utf-8").splitlines():
            m = re.search(r"-m ayesha\.cli (.+)$", line)
            if not m:
                continue
            args = shlex.split(m.group(1).replace("%EQ%", "25"))
            parser.parse_args(args)
            seen += 1
    assert seen >= 4
    txt = (win / "install.bat").read_text(encoding="utf-8")
    assert "AsSecureString" in txt and "setx AYESHA_OANDA_TOKEN" in txt  # token typed hidden, kept out of the repo
