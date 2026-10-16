"""AI-007 / T08: the dashboard is loopback-only, keyed, Host-checked and read-only; every value is escaped and
redacted; exports are sanitised; the live registry view hides money and changes nothing."""

import hashlib
import http.client
import threading
from datetime import datetime, timezone

import pytest

from ayesha.config import load_spec
from ayesha.research.dashboard.server import COOKIE, check_server, start
from ayesha.research.datasets.ingest import ingest_csv_dir
from ayesha.research.simulation.baseline import run_baseline

NOW = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
TOKEN = "0123456789abcdef" * 2 + "-" + "fedcba9876543210" * 2  # fake; built so no token literal is committed
LABEL = f"<script>alert(1)</script> token={TOKEN} ABCD-EFGH-JKMN-PQRS C:\\Users\\Enamul\\AyeshaFX"


@pytest.fixture
def server(ws, csv_folder):
    ds = ingest_csv_dir(ws, csv_folder, load_spec(), label=LABEL, now=NOW)["dataset_id"]
    run = run_baseline(ws, load_spec(), ds, "EURUSD")["run_id"]
    ws.close()
    srv, app, url = start(ws.root, 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield {"port": app.port, "token": app.token, "ds": ds, "run": run, "root": ws.root}
    srv.shutdown()
    srv.server_close()


def get(s, path, cookie=True, host=None, method="GET"):
    c = http.client.HTTPConnection("127.0.0.1", s["port"], timeout=20)
    h = {"Host": host or f"127.0.0.1:{s['port']}"}
    if cookie:
        h["Cookie"] = f"{COOKIE}={s['token']}"
    c.request(method, path, headers=h)
    r = c.getresponse()
    body = r.read()
    c.close()
    return r, body


def test_security_self_check_passes(ws):
    lines = []
    assert check_server(ws.root, out=lines.append) == 0, lines
    assert lines[-1] == "Dashboard security self-test passed."


def test_key_cookie_host_and_methods(server):
    assert get(server, "/", cookie=False)[0].status == 401
    r, _ = get(server, f"/?t={server['token']}", cookie=False)
    assert r.status == 303 and r.getheader("Location") == "/"
    assert "HttpOnly" in r.getheader("Set-Cookie") and "SameSite=Strict" in r.getheader("Set-Cookie")
    assert get(server, "/", host="attacker.example")[0].status == 403
    assert get(server, "/", host=f"192.168.1.5:{server['port']}")[0].status == 403
    for m in ("POST", "PUT", "DELETE", "PATCH"):
        assert get(server, "/", method=m)[0].status == 405
    r, body = get(server, "/")
    assert r.status == 200 and b"RESEARCH ONLY" in body
    assert "script-src" not in r.getheader("Content-Security-Policy")  # default-src 'none': no scripts at all
    assert r.getheader("Cache-Control") == "no-store" and r.getheader("Referrer-Policy") == "no-referrer"


def test_values_are_escaped_and_redacted(server):
    for path in (f"/data/{server['ds']}", "/data", f"/runs/{server['run']}", "/diagnostics"):
        r, body = get(server, path)
        assert r.status == 200, path
        text = body.decode("utf-8")
        assert "<script>" not in text, path
        assert TOKEN not in text and "ABCD-EFGH-JKMN-PQRS" not in text and "Enamul" not in text, path
    text = get(server, f"/data/{server['ds']}")[1].decode("utf-8")
    assert "&lt;script&gt;" in text and "[REDACTED" in text and "[user]" in text


def test_run_page_and_sanitised_exports(server):
    r, body = get(server, f"/runs/{server['run']}")
    assert r.status == 200 and b"Cumulative R" in body and b"Research candidates" in body
    r, body = get(server, f"/runs/{server['run']}/report.md")
    assert r.status == 200 and "attachment" in r.getheader("Content-Disposition")
    md = body.decode("utf-8")
    assert "RESEARCH ONLY" in md and "No validated trading edge exists yet" in md and TOKEN not in md
    r, body = get(server, f"/runs/{server['run']}/report.json")
    assert r.status == 200 and TOKEN.encode() not in body and b'"executable": false' in body


def test_pages_never_change_the_research_registry(server):
    db = server["root"] / "research.db"
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    for path in ("/", "/data", f"/data/{server['ds']}", "/runs", f"/runs/{server['run']}", "/legacy",
                 "/diagnostics", "/settings", f"/runs/{server['run']}/report.md"):
        assert get(server, path)[0].status == 200, path
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before


def test_live_registry_view_is_read_only_and_hides_money(server, home):
    from ayesha.storage.db import Registry

    reg = Registry(home / "ayesha.db")
    reg.insert_signal({"signal_id": "EURUSD-20260105-1015-BUY", "pair": "EURUSD", "direction": "BUY",
                       "setup": "SWEEP_MSS_FVG", "grade": "A_PLUS", "status": "READY", "strategy_version": "0.4.0",
                       "strategy_hash": "9bb5e8ed5937", "event_time_utc": "2026-01-05T10:15:00+00:00",
                       "lot": 0.01, "risk_usd": 0.12})
    reg.health("CAPITAL_STALE", None, "equity $25.40 is older than 24 h; risk 0.12 USD")
    reg.db.close()
    before = hashlib.sha256((home / "ayesha.db").read_bytes()).hexdigest()
    r, body = get(server, "/legacy")
    text = body.decode("utf-8")
    assert r.status == 200 and "EURUSD-20260105-1015-BUY" in text and "CAPITAL_STALE" in text
    assert "25.40" not in text and "0.12" not in text and "[amount hidden]" in text
    assert hashlib.sha256((home / "ayesha.db").read_bytes()).hexdigest() == before


def test_cumulative_r_chart_is_plain_svg():
    from ayesha.research.dashboard.server import r_chart

    svg = r_chart([1.5, -1.0, -1.0, 2.0])
    assert svg.startswith("<svg") and "<script" not in svg and "style=" not in svg and "1.50R" in svg
    assert "No closed" in r_chart([])
