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
    rows = run_doctor(env={}, home=tmp_path, make_calendar=lambda p: None, publish=True, clock=lambda: NOW, store=False)
    bad = _names(rows, False)
    assert {"OANDA token", "Exness contract", "Capital", "Pairing code", "News calendar"} <= bad
    assert any("CAPITAL_UNVERIFIED" in d for _, n, d in rows if n == "Capital")
    assert "OANDA prices" not in _names(rows, True)


def test_doctor_shows_capital_warnings_as_codes_without_amounts(tmp_path):
    from ayesha.capital import CapitalBook

    t = [NOW - timedelta(days=3)]
    book = CapitalBook(tmp_path / "capital.json", clock=lambda: t[0])
    book.record(250, positions=[])
    t[0] = NOW - timedelta(hours=1)
    book.record(231.5, positions=[])  # 7.4 % below the week's high
    rows = run_doctor(env={}, home=tmp_path, make_calendar=lambda p: None, publish=False, clock=lambda: NOW, store=False)
    cap = next(d for o, n, d in rows if n == "Capital")
    assert "warning: WEEKLY_DRAWDOWN_WARNING" in cap and "--history" in cap
    assert "231" not in cap and "250" not in cap and "7.4" not in cap, "doctor never prints amounts"


def test_doctor_all_green_with_fakes(tmp_path):
    from ayesha.broker import save_confirmed, load_assumed
    from ayesha.delivery.push import new_pairing_code

    from ayesha.broker import FIELDS, save_leverage
    from ayesha.capital import CapitalBook
    from ayesha.config import load_spec

    bfile = tmp_path / "broker-confirmed.json"
    vals = {k: float(v) for k, v in load_assumed("Standard").items() if k in FIELDS}
    save_confirmed("Standard", vals, bfile)
    save_leverage("Standard", 2000, bfile)
    (tmp_path / "pairing-code.txt").write_text(new_pairing_code(), encoding="utf-8")
    CapitalBook(tmp_path / "capital.json", clock=lambda: NOW - timedelta(hours=2)).record(25, positions=[])
    partial = run_doctor(env={}, home=tmp_path, make_calendar=lambda p: None, publish=False, clock=lambda: NOW,
                         store=False)
    contract = next(d for o, n, d in partial if n == "Exness contract" and not o)
    assert "GBPUSD" in contract and "BROKER_SPEC_UNVERIFIED" in contract  # EURUSD alone confirms nothing else
    for sym in load_spec()["pairs"]["enabled"]:
        save_confirmed("Standard", vals, bfile, symbol=sym)
    cal = NewsCalendar([], NOW - timedelta(days=1), NOW + timedelta(days=3))
    rows = run_doctor(env={"AYESHA_OANDA_TOKEN": "x" * 20}, home=tmp_path, make_feed=_Feed,
                      make_calendar=lambda p: cal, make_notifier=_Notifier, clock=lambda: NOW, store=False)
    assert all(ok for ok, _, _ in rows), rows
    assert _Notifier.sent and _Notifier.sent[-1][1] == "TEST"
    assert not any("25" in d for n, _, d in [(n, o, d) for o, n, d in rows] if n == "Capital"), \
        "doctor does not print the equity amount"
    stale = run_doctor(env={}, home=tmp_path, make_calendar=lambda p: None, publish=False,
                       clock=lambda: NOW + timedelta(hours=30), store=False)
    assert any(n == "Capital" and not o and "CAPITAL_STALE" in d for o, n, d in stale)
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
    txt = md.read_text(encoding="utf-8")
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
            args = shlex.split(m.group(1).replace("%EQ%", "25").replace("%*", "").replace("%~dp0", "x/"))
            parser.parse_args(args)
            seen += 1
    assert seen >= 3  # setup, scan, backtest-run
    txt = (win / "install.bat").read_text(encoding="utf-8")
    # the token is never put on a command line (no `setx <token>`); setup reads it hidden and uses the registry API
    for bat in win.glob("*.bat"):
        assert "setx" not in bat.read_text(encoding="utf-8").lower(), bat.name


# --- credentials, setup, backtest input validation ------------------------------------------

class MemStore:
    def __init__(self, v=None):
        self.v = {} if v is None else v

    def read(self, n):
        return self.v.get(n)

    def write(self, n, val):
        self.v[n] = val

    def delete(self, n):
        self.v.pop(n, None)


TOK = "TESTTOKEN-not-real-0123456789-abcdefghijklmnop"


def test_token_store_and_lookup(monkeypatch):
    from ayesha import credentials as c

    monkeypatch.delenv(c.TOKEN_ENV, raising=False)
    st = MemStore()
    assert c.get_token({}, store=st) == ""
    c.save_token("  " + TOK + "\n", store=st)
    assert st.v[c.TOKEN_ENV] == TOK
    assert c.get_token({}, store=st) == TOK  # falls back to the saved user environment
    assert c.get_token({c.TOKEN_ENV: "x" * 25}, store=st) == "x" * 25  # process env wins
    for bad in ("short", "has space in it 123456789", "semi;colon0123456789abcdef", "a&b" * 10):
        try:
            c.save_token(bad, store=st)
            raise AssertionError(bad)
        except ValueError:
            pass
    c.delete_token(store=st)
    assert c.TOKEN_ENV not in st.v
    monkeypatch.delenv(c.TOKEN_ENV, raising=False)


def test_redact_scrubs_token_and_bearer():
    from ayesha.credentials import redact

    t = redact(f"GET failed Authorization: Bearer {TOK} token={TOK}", TOK)
    assert TOK not in t and "***" in t
    assert "abcdefgh12345" not in redact("bearer abcdefgh12345", "")


def test_hidden_prompt_reads_stdin_when_not_a_terminal():
    import io

    from ayesha.credentials import read_hidden

    class NotTty(io.StringIO):
        def isatty(self):
            return False

    class Tty(io.StringIO):
        def isatty(self):
            return True

    assert read_hidden("p", stdin=NotTty(TOK + "\r\n")) == TOK
    assert read_hidden("p", stdin=Tty(""), getpass_fn=lambda prompt: "hidden") == "hidden"


def test_oanda_feed_maps_401_to_auth_rejected_without_leaking_token():
    import urllib.error

    from ayesha.feed.oanda_feed import AuthRejected, OandaFeed

    def get(url, headers):
        assert TOK not in url  # the token travels only in the header
        raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)

    f = OandaFeed(equity_usd=1, token=TOK, http_get=get, min_interval_s=0)
    try:
        f.quote("EURUSD")
        raise AssertionError("expected AuthRejected")
    except AuthRejected as e:
        assert TOK not in str(e) and "401" in str(e)


def test_scan_exit_codes_for_the_start_script(monkeypatch, capsys, tmp_path):
    import urllib.error

    from ayesha import credentials as c

    from ayesha.capital import CapitalBook

    monkeypatch.setenv("AYESHA_HOME", str(tmp_path))
    monkeypatch.delenv(c.TOKEN_ENV, raising=False)
    monkeypatch.setattr(c, "default_store", lambda: None)
    assert cli.main(["scan", "--feed", "oanda"]) == cli.EXIT_CONFIG  # no capital snapshot yet
    assert "no capital snapshot" in capsys.readouterr().out
    CapitalBook(tmp_path / "capital.json").record(25, positions=[])
    assert cli.main(["scan", "--feed", "oanda"]) == cli.EXIT_CONFIG  # no token
    (tmp_path / "capital.json").write_text("abc", encoding="utf-8")
    assert cli.main(["scan", "--feed", "oanda"]) == cli.EXIT_CONFIG  # corrupt capital file
    (tmp_path / "capital.json").unlink()
    CapitalBook(tmp_path / "capital.json").record(25, positions=[])
    monkeypatch.setenv(c.TOKEN_ENV, TOK)

    def http401(url, headers):
        raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)

    def offline(url, headers):
        raise urllib.error.URLError("network down")

    import ayesha.feed.oanda_feed as of

    monkeypatch.setattr(of, "_default_get", http401)
    assert cli.main(["scan", "--feed", "oanda"]) == cli.EXIT_AUTH
    monkeypatch.setattr(of, "_default_get", offline)
    assert cli.main(["scan", "--feed", "oanda"]) == cli.EXIT_NETWORK
    out = capsys.readouterr().out
    assert TOK not in out and "will retry" in out


def test_setup_runs_unattended_and_is_rerunnable(monkeypatch, tmp_path, capsys):
    import io

    from ayesha import credentials as c
    from ayesha.broker import confirmed_symbols, load_confirmed, load_leverage
    from ayesha.capital import CapitalBook
    from ayesha.config import load_spec

    st = MemStore()
    monkeypatch.setenv("AYESHA_HOME", str(tmp_path))
    monkeypatch.delenv(c.TOKEN_ENV, raising=False)
    monkeypatch.setattr(c, "default_store", lambda: st)
    monkeypatch.setattr("ayesha.doctor.run_doctor", lambda **kw: [(True, "fake", "ok")])

    class In(io.StringIO):
        def isatty(self):
            return False

    # token, equity, open trades (none), leverage, EURUSD 4 contract values + spread, then the other
    # five pairs: "same values, I checked" + spread
    monkeypatch.setattr("sys.stdin", In(f"{TOK}\n25\n\n2000\n100000\n0.01\n0.01\n200\n\n" + "Y\n\n" * 5))
    assert cli.main(["setup", "--no-publish"]) == 0
    assert st.v[c.TOKEN_ENV] == TOK
    assert not (tmp_path / "equity.txt").exists()
    book = CapitalBook(tmp_path / "capital.json")
    first = book.latest()
    assert (first.equity, first.reason, first.open_positions, first.source) == (25, "INITIAL", (), "OWNER_ENTERED")
    bfile = tmp_path / "broker-confirmed.json"
    assert confirmed_symbols("Standard", bfile) == sorted(load_spec()["pairs"]["enabled"])
    assert load_confirmed("Standard", bfile, "GBPUSD")["volume_min"] == 0.01
    assert load_leverage("Standard", bfile) == 2000
    assert (tmp_path / "pairing-code.txt").exists()
    code = (tmp_path / "pairing-code.txt").read_text()
    # second run: Enter keeps the token; a bad equity is refused, then 30 accepted as a deposit;
    # no open trades; contract values already confirmed (Enter = keep)
    monkeypatch.setattr("sys.stdin", In("\nabc\n30\nD\n\n\n"))
    assert cli.main(["setup", "--no-publish"]) == 0
    assert st.v[c.TOKEN_ENV] == TOK
    last = book.latest()
    assert (last.version, last.equity, last.reason, last.amount, last.previous_equity) == (2, 30, "DEPOSIT", 5, 25)
    assert book.cash_flows_usd() == 5  # the deposit is a cash flow, not trading profit
    assert (tmp_path / "pairing-code.txt").read_text() == code
    out = capsys.readouterr().out
    assert TOK not in out and "Please type a positive number" in out and "Capital confirmed: 30" in out
    monkeypatch.delenv(c.TOKEN_ENV, raising=False)


def test_backtest_inputs_are_strictly_validated():
    from datetime import date

    import pytest

    from ayesha.backtest.inputs import InvalidInput, validate

    allowed = ["EURUSD", "GBPUSD", "USDJPY"]
    today = date(2026, 10, 15)
    p = validate("eurusd, GBPUSD,EURUSD", "1095", "", "4", allowed, today)
    assert p.pairs == ("EURUSD", "GBPUSD") and p.days == 1095 and p.folds == 4
    assert date(2023, 10, 16) < p.split < today
    for pairs, days, split, folds in [
        ("EURUSD;rm -rf /", "1095", "", "4"), ("$(whoami)", "1095", "", "4"), ("XAUUSD", "1095", "", "4"),
        ("", "1095", "", "4"), ("EURUSD", "10", "", "4"), ("EURUSD", "99999", "", "4"),
        ("EURUSD", "1e3", "", "4"), ("EURUSD", "1095; ls", "", "4"), ("EURUSD", "1095", "2026-02-30", "4"),
        ("EURUSD", "1095", "2020-01-01", "4"), ("EURUSD", "1095", "2026-10-14", "4"),
        ("EURUSD", "1095", "2025-01-01`id`", "4"), ("EURUSD", "1095", "", "1"), ("EURUSD", "1095", "", "50"),
    ]:
        with pytest.raises(InvalidInput):
            validate(pairs, days, split, folds, allowed, today)


def test_backtest_run_validate_only(capsys):
    assert cli.main(["backtest-run", "--pairs", "EURUSD", "--days", "730", "--validate-only"]) == 0
    assert cli.main(["backtest-run", "--pairs", "EURUSD && echo pwned", "--validate-only"]) == cli.EXIT_CONFIG
    assert "INVALID INPUT" in capsys.readouterr().out


def test_mtf_design_defaults_are_kept(spec):
    """H4 context, H1 bias, M15 setup on; M5 optional (off); M1 scalp disabled and not validated."""
    assert spec["mtf"]["context_timeframe"] == "H4"
    assert spec["entry"]["bias_timeframe"] == "H1" and spec["entry"]["setup_timeframe"] == "M15"
    assert spec["mtf"]["confirm_timeframe"] is None
    assert spec["mtf"]["scalp_m1"] == {"enabled": False, "validated": False}


def test_workflows_and_repo_hygiene():
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]

    def load(name):
        spec_ = importlib.util.spec_from_file_location(name, root / "scripts" / f"{name}.py")
        m = importlib.util.module_from_spec(spec_)
        spec_.loader.exec_module(m)
        return m

    cw = load("check_workflows")
    assert cw.main(["x", str(root / ".github" / "workflows")]) == 0
    bad = root / "desktop" / "tests" / "_tmp_bad.yml"
    try:
        bad.write_text("on: {workflow_dispatch: {inputs: {p: {default: x}}}}\njobs:\n  j:\n    steps:\n"
                       "      - run: echo ${{ inputs.p }}\n", encoding="utf-8")
        errs = cw.check(bad)
        assert any("permissions" in e for e in errs) and any("run:" in e for e in errs)
    finally:
        bad.unlink()
    assert load("check_no_secrets").main(["x", str(root)]) == 0


def test_make_signing_key_creates_loadable_pkcs12_once(tmp_path, capsys):
    import pytest

    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.serialization import pkcs12

    out = tmp_path / "sig"
    assert cli.main(["make-signing-key", "--out-dir", str(out)]) == 0
    printed = capsys.readouterr().out
    secrets_txt = (out / "github-secrets-DELETE-AFTER-USE.txt").read_text()
    pw = secrets_txt.split("AYESHA_KEYSTORE_PASSWORD\n")[1].split("\n")[0]
    assert len(pw) == 32 and pw not in printed  # the password is only in the local file
    key, cert, _ = pkcs12.load_key_and_certificates((out / "ayesha-release.p12").read_bytes(), pw.encode())
    assert key is not None and cert is not None
    # never overwrite an existing key: that would break updates
    assert cli.main(["make-signing-key", "--out-dir", str(out)]) == 1
