"""Read-only local research dashboard (plan AI-007, T08): http://127.0.0.1:<port>/ on this PC only.

Security rules, all enforced here and self-tested by `ayesha research dashboard --check`:
* Bound to 127.0.0.1 only (never 0.0.0.0, never a public port). No VPS, no tunnel, nothing reachable from outside.
* A new random key every start. The printed link carries it once; the dashboard then sets an HttpOnly,
  SameSite=Strict cookie and redirects to a URL without the key. Requests without the key get 401.
* The Host header must be 127.0.0.1:<port> or localhost:<port> (DNS-rebinding protection).
* GET and HEAD only: there is no form, no POST, no action that changes anything, so there is nothing to forge.
* Strict Content-Security-Policy (no scripts at all), no framing, no referrer, no caching.
* Every value is HTML-escaped and redacted (tokens, pairing codes, Bearer headers, Windows user names).
* Data is read with SQLite mode=ro and through the artifact hash checks. The live registry view shows states,
  times and counts only: no lot sizes, no money amounts, no equity.
"""

from __future__ import annotations

import hmac
import html
import http.client
import http.server
import json
import secrets
import threading
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, Callable

from ayesha.research.redact import redact

BIND = "127.0.0.1"
COOKIE = "ayesha_research"
CSP = ("default-src 'none'; style-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
       "frame-ancestors 'none'")
HEADERS = {"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
           "Referrer-Policy": "no-referrer", "Cache-Control": "no-store", "Cross-Origin-Resource-Policy": "same-origin"}
CSS = """
body{font-family:Segoe UI,Nirmala UI,system-ui,sans-serif;margin:0;background:#f6f7f9;color:#1d232b}
header{background:#1d2b3a;color:#fff;padding:10px 18px}header a{color:#cfe3ff;margin-right:14px;text-decoration:none}
.banner{background:#fff4d6;border-bottom:1px solid #e6cf8a;padding:8px 18px;font-size:14px}
main{padding:16px 18px;max-width:1200px}table{border-collapse:collapse;background:#fff;margin:8px 0 18px;font-size:13px}
th,td{border:1px solid #d8dde3;padding:4px 8px;text-align:left;vertical-align:top}th{background:#eef1f5}
.ok{color:#16702e;font-weight:600}.warn{color:#9a6200;font-weight:600}.fail{color:#b3261e;font-weight:600}
.muted{color:#5b6672}code{font-size:12px}h1{font-size:20px}h2{font-size:16px;margin-top:22px}
.card{background:#fff;border:1px solid #d8dde3;padding:10px 14px;margin:8px 0}
@media (prefers-color-scheme: dark){body{background:#12171d;color:#dde3ea}header{background:#0b1016}
.banner{background:#3a3016;border-color:#6b5a26}table,.card{background:#1a2129}th{background:#232c36}
th,td,.card{border-color:#34404c}a{color:#8cb8ff}.ok{color:#5fd07c}.warn{color:#f0b54a}.fail{color:#ff7b72}
.muted{color:#9aa7b4}svg rect{fill:#1a2129;stroke:#34404c}svg polyline{stroke:#8cb8ff}}
"""


def e(v: Any) -> str:
    return html.escape(redact("" if v is None else str(v)), quote=True)


def _state_class(s: str) -> str:
    return {"OK": "ok", "PASS": "ok", "COMPLETED": "ok", "MATCHED": "ok", "WARN": "warn", "DEGRADED": "warn",
            "INFO": "muted", "FAIL": "fail", "REJECTED": "fail", "FAILED": "fail", "CRASHED": "fail",
            "TIMEOUT": "fail", "FAILED_INCOMPLETE": "fail", "RESOURCE_LIMIT": "fail"}.get(s, "")


def table(head: list[str], rows: list[list[Any]], raw_cols: tuple[int, ...] = ()) -> str:
    h = "<tr>" + "".join(f"<th>{e(x)}</th>" for x in head) + "</tr>" if any(head) else ""  # no header for key/value
    body = []
    for r in rows:
        cells = []
        for i, v in enumerate(r):
            cells.append(f"<td>{v}</td>" if i in raw_cols else f"<td class='{_state_class(str(v))}'>{e(v)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table>{h}{''.join(body)}</table>" if rows else "<p class='muted'>Nothing yet.</p>"


def link(href: str, text: Any) -> str:
    return f"<a href='{html.escape(href, quote=True)}'>{e(text)}</a>"


def r_chart(values: list[float]) -> str:
    """Cumulative R of closed hypothetical trades as inline SVG (no script; presentation attributes only)."""
    if not values:
        return "<p class='muted'>No closed hypothetical trades in this run.</p>"
    cum, s = [0.0], 0.0
    for v in values:
        s += v
        cum.append(s)
    w, h, pad = 640, 180, 10
    lo, hi = min(cum + [0.0]), max(cum + [0.0])
    span = (hi - lo) or 1.0
    xs = [pad + i * (w - 2 * pad) / max(1, len(cum) - 1) for i in range(len(cum))]
    ys = [h - pad - (c - lo) * (h - 2 * pad) / span for c in cum]
    zero = h - pad - (0 - lo) * (h - 2 * pad) / span
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    return (f"<svg width='{w}' height='{h}' viewBox='0 0 {w} {h}' role='img' aria-label='cumulative R'>"
            f"<rect x='0' y='0' width='{w}' height='{h}' fill='#ffffff' stroke='#d8dde3'/>"
            f"<line x1='{pad}' y1='{zero:.1f}' x2='{w - pad}' y2='{zero:.1f}' stroke='#9aa5b1' stroke-dasharray='4 3'/>"
            f"<polyline points='{pts}' fill='none' stroke='#1f5fbf' stroke-width='2'/></svg>"
            f"<p class='muted'>Cumulative R over {len(values)} closed hypothetical trades, ending at {s:.2f}R. "
            "A replay of history, not a forecast.</p>")


class App:
    """Routes for the dashboard. `root` is the research folder; everything is opened read-only per request."""

    def __init__(self, root: Path, token: str) -> None:
        self.root = Path(root)
        self.token = token
        self.port = 0

    # --- plumbing -----------------------------------------------------------------------------
    def page(self, title: str, body: str) -> bytes:
        nav = "".join(link(h, t) for h, t in (("/", "সারাংশ · Overview"), ("/data", "ডেটা · Data"),
                                               ("/runs", "রান · Runs"), ("/legacy", "লাইভ স্ক্যানার · Live scanner"),
                                               ("/diagnostics", "ডায়াগনস্টিক · Diagnostics"),
                                               ("/settings", "সেটিংস · Settings")))
        doc = (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{e(title)} - AYESHA research"
               f"</title><meta name='viewport' content='width=device-width,initial-scale=1'>"
               f"<link rel='stylesheet' href='/app.css'></head><body><header><b>AYESHA research</b> &nbsp; {nav}"
               f"</header><div class='banner'><span lang='bn'>শুধু গবেষণা: জমানো (frozen) পুরনো ডেটায় simulation। "
               f"কখনো READY নয়, ফোনে যায় না, কোনো order নেই। এখনো কোনো যাচাই করা trading edge নেই।</span><br>"
               f"RESEARCH ONLY: historical simulations on frozen data. Never READY, "
               f"never sent to the phone, no orders. No validated trading edge exists yet.</div><main>"
               f"<h1>{e(title)}</h1>{body}</main></body></html>")
        return doc.encode("utf-8")

    def _ws(self):
        from ayesha.research.readonly import ReadOnlyWorkspace

        return ReadOnlyWorkspace(self.root)

    def route(self, path: str) -> tuple[int, str, bytes, dict[str, str]]:
        parts = [urllib.parse.unquote(p) for p in path.split("/") if p]
        if path == "/app.css":
            return 200, "text/css; charset=utf-8", CSS.encode(), {}
        ws = self._ws()
        try:
            if not parts:
                return self._ok("Overview", self.overview(ws))
            if parts == ["data"]:
                return self._ok("Data", self.data(ws))
            if len(parts) == 2 and parts[0] == "data":
                return self._ok(f"Dataset {parts[1]}", self.dataset(ws, parts[1]))
            if parts == ["runs"]:
                return self._ok("Runs", self.runs(ws))
            if len(parts) == 2 and parts[0] == "runs":
                return self._ok(f"Run {parts[1]}", self.run(ws, parts[1]))
            if len(parts) == 3 and parts[0] == "runs" and parts[2] in ("report.md", "report.json"):
                return self.export(ws, parts[1], parts[2])
            if parts == ["legacy"]:
                return self._ok("Live scanner (read-only view)", self.legacy())
            if parts == ["diagnostics"]:
                return self._ok("Diagnostics", self.diagnostics(ws))
            if len(parts) == 3 and parts[:2] == ["diagnostics", "log"]:
                return self._ok(f"Log {parts[2]}", self.log(ws, parts[2]))
            if parts == ["settings"]:
                return self._ok("Settings", self.settings())
            return 404, "text/html; charset=utf-8", self.page("Not found", f"<p>No page {e(path)}</p>"), {}
        finally:
            ws.close()

    def _ok(self, title: str, body: str) -> tuple[int, str, bytes, dict[str, str]]:
        return 200, "text/html; charset=utf-8", self.page(title, body), {}

    # --- pages ------------------------------------------------------------------------------------
    def overview(self, ws) -> str:
        from ayesha import __version__
        from ayesha.config import load_spec
        from ayesha.research import RESEARCH_VERSION
        from ayesha.research.config import ResearchConfigError, load
        from ayesha.research.worker import lock_for

        try:
            cfg = load(self.root / "config.yaml")
            state = "ON (research-only)" if cfg.enabled else "OFF (legacy_only)"
        except ResearchConfigError:
            state = "OFF (settings file invalid)"
        spec = load_spec()
        rows = [["Research", state], ["Versions", f"research {RESEARCH_VERSION}, desktop {__version__}"],
                ["Live strategy", f"{spec['strategy_version']} hash {spec['strategy_hash']} (research never changes it)"],
                ["Worker", "busy" if lock_for(self.root).held_by_other() else "idle"]]
        if ws.db is None:
            return table(["", ""], rows) + "<p>No research data yet. Start with <code>ayesha research enable</code> " \
                                          "and <code>ayesha research ingest</code>.</p>"
        ds = ws.db.datasets()
        runs = ws.db.runs(10)
        rows += [["Datasets", len(ds)], ["Runs (latest 10 shown)", len(runs)]]
        jobs = ws.db.jobs(5)
        return (table(["", ""], rows)
                + "<h2>Latest runs</h2>" + self._runs_table(runs)
                + "<h2>Latest jobs</h2>" + table(["Job", "Kind", "Status", "Started"], [
                    [link(f"/diagnostics/log/{j['job_id']}", j["job_id"]), j["kind"], j["status"], j["started_utc"]]
                    for j in jobs], raw_cols=(0,)))

    def data(self, ws) -> str:
        if ws.db is None:
            return "<p>No research data yet.</p>"
        return table(["Dataset", "Quality", "Provider", "Symbols", "Timeframes", "From", "To", "Label"], [
            [link(f"/data/{d['dataset_id']}", d["dataset_id"]), d["quality_state"], d["provider"], d["symbols"],
             d["timeframes"], d["start_utc"], d["end_utc"], d["label"]] for d in ws.db.datasets()], raw_cols=(0,))

    def dataset(self, ws, dataset_id: str) -> str:
        if ws.db is None or ws.db.dataset(dataset_id) is None:
            return f"<p>Unknown dataset {e(dataset_id)}</p>"
        d = ws.db.dataset(dataset_id)
        m = json.loads(d["manifest_json"])
        src = m["source"]
        out = [table(["", ""], [["Quality", d["quality_state"]], ["Label", src["label"]], ["Provider", src["provider"]],
                                ["Adapter", src["adapter"]], ["Environment", src["environment"]],
                                ["Range", f"{m['range_utc']['start']} .. {m['range_utc']['end']}"],
                                ["Downloaded", m["downloaded_at_utc"]], ["Observed time basis", m["observed_at_basis"]],
                                ["Licence", m["license_notes"]], ["Code", f"{m['code']['commit'][:12]} / "
                                                                          f"{m['code']['desktop_version']}"],
                                ["Normalised hash", m["normalized_sha256"]]])]
        out.append("<h2>Limitations</h2><ul>" + "".join(f"<li>{e(x)}</li>" for x in m["limitations"]) + "</ul>")
        for p in ws.db.partitions(dataset_id):
            try:
                rep = json.loads(ws.store.get("quality", p["quality_sha"], ".json"))
            except Exception as ex:  # noqa: BLE001 - show the integrity problem instead of failing the page
                out.append(f"<p class='fail'>{e(p['symbol'])} {e(p['timeframe'])}: quality report unreadable "
                           f"({e(type(ex).__name__)})</p>")
                continue
            out.append(f"<h2>{e(p['symbol'])} {e(p['timeframe'])}: <span class='{_state_class(rep['decision'])}'>"
                       f"{e(rep['decision'])}</span></h2>")
            out.append(f"<p>{e(rep['rows_out'])}/{e(rep['rows_in'])} rows kept, coverage {e(rep['coverage_percent'])}%"
                       f", missing {e(rep['missing_bars'])} of {e(rep['expected_bars'])} expected bars, longest gap "
                       f"{e(rep['longest_gap_bars'])} bars. Nothing was filled in or repaired.</p>")
            out.append(table(["Severity", "Issue", "Count", "Examples"], [
                [i["severity"], i["code"], i["count"], "; ".join(i["examples"][:3])] for i in rep["issues"]]))
        return "".join(out)

    def _runs_table(self, runs) -> str:
        rows = []
        for r in runs:
            inp = json.loads(r["inputs_json"])
            rows.append([link(f"/runs/{r['run_id']}", r["run_id"]), r["status"], r["strategy_id"], r["version"],
                         link(f"/data/{r['dataset_id']}", r["dataset_id"]), inp.get("symbol"), inp.get("mode"),
                         r["created_utc"]])
        return table(["Run", "Status", "Strategy", "Version", "Dataset", "Symbol", "Mode", "Created"], rows,
                     raw_cols=(0, 4))

    def runs(self, ws) -> str:
        if ws.db is None:
            return "<p>No research data yet.</p>"
        return self._runs_table(ws.db.runs(200))

    def run(self, ws, run_id: str) -> str:
        from ayesha.research.simulation.baseline import load_result

        if ws.db is None or ws.db.run(run_id) is None:
            return f"<p>Unknown run {e(run_id)}</p>"
        row = ws.db.run(run_id)
        if row["status"] != "COMPLETED":
            return table(["", ""], [["Status", row["status"]], ["Error", row["error"]], ["Created", row["created_utc"]]])
        res = load_result(ws, run_id)
        mt = res["metrics"]
        s = mt["summary"]
        out = [f"<p>{link(f'/runs/{run_id}/report.md', 'Download sanitised report (Markdown)')} &nbsp; "
               f"{link(f'/runs/{run_id}/report.json', 'Download sanitised result (JSON)')}</p>"]
        out.append(table(["", ""], [
            ["Strategy", f"{res['strategy_id']} {res['strategy_version']} hash {res['strategy_hash']}"],
            ["Dataset", f"{res['dataset_id']} ({res['dataset_quality']})"], ["Costs", res["cost_model_id"]],
            ["Account scenario", res["account_scenario_id"]], ["News", res["news_snapshot_id"]],
            ["Split", res["split_plan_id"]], ["Result hash", res["result_sha256"]],
            ["Code", f"{res['commit_sha'][:12]} / desktop {res['desktop_version']}"]]))
        out.append("<h2>Limitations</h2><ul>" + "".join(f"<li>{e(x)}</li>" for x in res["limitations"])
                   + "".join(f"<li class='warn'>{e(x)}</li>" for x in res["warnings"]) + "</ul>")
        out.append("<h2>Summary (R after modelled costs)</h2>" + table(
            ["Signals", "Closed", "Wins", "Losses", "Win rate (95% CI)", "Expectancy R", "Profit factor", "Max DD R",
             "Total R"],
            [[s["signals"], s["closed_trades"], s["wins"], s["losses"], "n/a (no closed trades)"
              if s["win_rate"] is None else f"{s['win_rate']} [{s['win_rate_95ci'][0]}, {s['win_rate_95ci'][1]}]",
              s["expectancy_r"], s["profit_factor"], s["max_drawdown_r"], s["total_r"]]]))
        counts = ", ".join(f"{k} {v}" for k, v in sorted(s["by_status"].items())) or "none"
        out.append(f"<p>Status counts: {e(counts)}. Blocked share {e(mt['no_trade_share'])}, not filled "
                   f"share {e(mt['not_filled_share'])}.</p>")
        try:
            from ayesha.research.simulation.baseline import load_candidates

            cands = load_candidates(ws, run_id)
        except Exception:  # noqa: BLE001
            cands = []
        out.append("<h2>Cumulative R</h2>" + r_chart([c["outcome_r"] for c in cands
                                                     if c["proposed_state"] == "HYPOTHETICAL_CLOSED"
                                                     and c["outcome_r"] is not None]))
        io = mt.get("in_vs_out_of_sample")
        if io:
            out.append("<h2>In-sample vs out-of-sample</h2>" + table(
                ["Period", "Closed", "Expectancy R", "Profit factor", "Max DD R"],
                [[k, io[k]["closed_trades"], io[k]["expectancy_r"], io[k]["profit_factor"], io[k]["max_drawdown_r"]]
                 for k in ("in_sample", "out_of_sample")]))
        wf = mt["walk_forward"]["folds"]
        out.append("<h2>Walk-forward folds (frozen rules)</h2>" + table(
            ["From", "To", "Closed", "Expectancy R", "Profit factor"],
            [[f["from"][:10], f["to"][:10], f["closed_trades"], f["expectancy_r"], f["profit_factor"]] for f in wf]))
        for title, key in (("By session", "by_session"), ("By direction", "by_direction"),
                           ("By H4 context", "by_h4_context")):
            out.append(f"<h2>{title}</h2>" + table(["Group", "Signals", "Closed", "Expectancy R", "Total R"], [
                [k, v["signals"], v["closed_trades"], v["expectancy_r"], v["total_r"]] for k, v in mt[key].items()]))
        out.append("<h2>Minimum-lot feasibility (assumed Exness Standard, hypothetical equity)</h2>" + table(
            ["Equity", "Risk %", "Allowed by 0.01 lot", "Verdict"],
            [[f"${c['equity_usd']:,.0f}", c["risk_percent"], f"{c['allowed_by_min_lot']}/{c['closed_trades']}",
              c["verdict"]] for c in mt["capital_exness_standard"]]))
        out.append(f"<h2>Research candidates ({len(cands)}, not executable)</h2>" + table(
            ["As of (UTC)", "Pair", "Direction", "Proposed state", "Replay", "R", "Reasons"],
            [[c["asof_utc"], c["pair"], c["direction"], c["proposed_state"], c["replay_status"], c["outcome_r"],
              ", ".join(c["rejection_codes"])] for c in cands[:300]]))
        return "".join(out)

    def export(self, ws, run_id: str, name: str) -> tuple[int, str, bytes, dict[str, str]]:
        from ayesha.research.evaluation.report import run_json, run_markdown
        from ayesha.research.simulation.baseline import RunRefused

        if ws.db is None or ws.db.run(run_id) is None:
            return 404, "text/html; charset=utf-8", self.page("Not found", f"<p>Unknown run {e(run_id)}</p>"), {}
        try:
            if name == "report.md":
                body, ctype = run_markdown(ws, run_id).encode("utf-8"), "text/markdown; charset=utf-8"
            else:
                body = json.dumps(run_json(ws, run_id), indent=2, ensure_ascii=False).encode("utf-8")
                ctype = "application/json; charset=utf-8"
        except RunRefused as ex:
            return 404, "text/html; charset=utf-8", self.page("Not found", f"<p>{e(ex)}</p>"), {}
        safe = "".join(ch for ch in run_id if ch.isalnum() or ch == "_")
        return 200, ctype, body, {"Content-Disposition": f"attachment; filename=\"{safe}-{name}\""}

    def legacy(self) -> str:
        from ayesha.research.readonly import legacy_summary

        s = legacy_summary()
        if not s["present"]:
            return "<p>The live registry (ayesha.db) does not exist yet: the scanner has not run on this PC.</p>"
        if not s.get("readable"):
            return f"<p class='warn'>The live registry could not be read read-only ({e(s.get('error'))}).</p>"
        out = ["<p class='muted'>Read-only view of the live scanner's registry. States, times and counts only: no "
               "lot sizes, no money amounts, no equity. Research never writes here.</p>"]
        out.append(f"<h2>Signals in the last {e(s['days'])} days by status</h2>" + table(
            ["Status", "Count"], [[k, v] for k, v in s.get("signals_by_status", {}).items()]))
        out.append("<h2>Last signal per pair</h2>" + table(
            ["Pair", "Last signal (UTC)"], [[k, v] for k, v in s.get("last_signal_by_pair", {}).items()]))
        if "deliveries" in s:
            d = s["deliveries"]
            out.append(f"<p>Phone deliveries in the last {e(s['days'])} days: {e(d['ok'])}/{e(d['count'])} OK, "
                       f"last {e(d['last_utc'])}.</p>")
        out.append("<h2>Recent scanner health</h2>" + table(
            ["At (UTC)", "Pair", "State", "Detail"], [[h["at_utc"], h["symbol"], h["state"], h["detail"]]
                                                       for h in s.get("health", [])]))
        out.append("<h2>Recent signals</h2>" + table(
            ["Signal", "Pair", "Direction", "Grade", "Status", "Time (UTC)"],
            [[r["signal_id"], r["symbol"], r["direction"], r["grade"], r["status"], r["event_time_utc"]]
             for r in s.get("recent_signals", [])]))
        return "".join(out)

    def diagnostics(self, ws) -> str:
        from ayesha.research.doctor import run_doctor

        checks = run_doctor(root=self.root)
        out = [table(["State", "Check", "Detail"], [[c.state, c.name, c.detail] for c in checks])]
        if ws.db is not None:
            out.append("<h2>Jobs</h2>" + table(["Job", "Kind", "Status", "Exit", "Started", "Finished", "Limits"], [
                [link(f"/diagnostics/log/{j['job_id']}", j["job_id"]), j["kind"], j["status"], j["exit_code"],
                 j["started_utc"], j["finished_utc"],
                 ", ".join((json.loads(j["result_json"] or "{}").get("limits_applied") or []))]
                for j in ws.db.jobs(30)], raw_cols=(0,)))
            out.append("<h2>Audit trail (latest 30)</h2>" + table(["#", "At", "Actor", "Operation", "Target"], [
                [r["id"], r["at_utc"], r["actor"], r["operation"], r["target"]] for r in ws.db.events(30)]))
        return "".join(out)

    def log(self, ws, job_id: str) -> str:
        if ws.db is None or ws.db.job(job_id) is None:
            return f"<p>Unknown job {e(job_id)}</p>"
        j = ws.db.job(job_id)
        p = self.root / (j["log_relpath"] or "")
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[-20000:] if j["log_relpath"] else ""
        except OSError:
            text = "(log file not found)"
        return f"<p>Status {e(j['status'])}, exit code {e(j['exit_code'])}</p><pre>{e(text)}</pre>"

    def settings(self) -> str:
        from ayesha.research.config import ResearchConfigError, load

        try:
            cfg = load(self.root / "config.yaml")
        except ResearchConfigError as ex:
            return f"<p class='fail'>Settings file invalid, research stays off: {e(ex)}</p>"
        rows = [[k, json.dumps(v)] for k, v in cfg.r.items()]
        return ("<p>Read-only. Change research on/off with <code>ayesha research enable</code> / "
                "<code>ayesha research disable</code>. The safety locks (no promotion, no live-scanner hooks, no "
                "ML, no outside model calls, loopback only) cannot be loosened.</p>" + table(["Setting", "Value"],
                                                                                           rows))


def make_handler(app: App, allowed_hosts: Callable[[], set[str]]):
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "AYESHA-research"
        sys_version = ""

        def log_message(self, fmt: str, *args: Any) -> None:  # never log query strings (the key)
            pass

        def _send(self, code: int, ctype: str, body: bytes, extra: dict[str, str] | None = None,
                  head: bool = False) -> None:
            self.send_response(code)
            for k, v in {**HEADERS, **(extra or {})}.items():
                self.send_header(k, v)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def _deny(self, code: int, msg: str, head: bool = False) -> None:
            self._send(code, "text/plain; charset=utf-8", msg.encode(), head=head)

        def _authorised(self) -> bool:
            jar = {}
            for part in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = part.strip().partition("=")
                jar[k] = v
            return hmac.compare_digest(jar.get(COOKIE, ""), app.token)

        def _serve(self, head: bool) -> None:
            if self.client_address[0] != BIND:
                return self._deny(403, "loopback only", head)
            if (self.headers.get("Host") or "") not in allowed_hosts():
                return self._deny(403, "wrong Host header (only 127.0.0.1 / localhost on this port)", head)
            url = urllib.parse.urlsplit(self.path)
            q = urllib.parse.parse_qs(url.query)
            if "t" in q:
                if hmac.compare_digest(q["t"][0], app.token):
                    self.send_response(303)
                    for k, v in HEADERS.items():
                        self.send_header(k, v)
                    self.send_header("Set-Cookie", f"{COOKIE}={app.token}; HttpOnly; SameSite=Strict; Path=/")
                    self.send_header("Location", url.path or "/")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return None
                return self._deny(401, "wrong key: open the link printed by `ayesha research dashboard`", head)
            if not self._authorised():
                return self._deny(401, "open the link printed by `ayesha research dashboard` (it carries a key)",
                                  head)
            try:
                code, ctype, body, extra = app.route(url.path)
            except Exception as ex:  # noqa: BLE001 - a broken page must not stop the dashboard or leak a trace
                code, ctype, extra = 500, "text/html; charset=utf-8", {}
                body = app.page("Error", f"<p class='fail'>This page failed: {e(type(ex).__name__)}. The research "
                                         "data was not changed.</p>")
            return self._send(code, ctype, body, extra, head)

        def do_GET(self) -> None:  # noqa: N802
            self._serve(False)

        def do_HEAD(self) -> None:  # noqa: N802
            self._serve(True)

        def _no(self) -> None:
            self._deny(405, "read-only dashboard: GET only")

        do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _no  # noqa: N815

    return Handler


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


def start(root: Path | None = None, port: int = 0) -> tuple[Server, App, str]:
    from ayesha.research.config import research_home

    app = App(Path(root) if root else research_home(), secrets.token_urlsafe(32))
    holder: dict[str, set[str]] = {}
    srv = Server((BIND, port), make_handler(app, lambda: holder["hosts"]))
    app.port = srv.server_address[1]
    holder["hosts"] = {f"127.0.0.1:{app.port}", f"localhost:{app.port}"}
    url = f"http://127.0.0.1:{app.port}/?t={app.token}"
    return srv, app, url


def serve(root: Path | None = None, port: int = 0, open_browser: bool = True) -> int:
    srv, app, url = start(root, port)
    print("AYESHA research dashboard (read-only, this PC only). Close this window or press Ctrl+C to stop.")
    print(f"Open: {url}")
    print("The link carries a one-time key for this session; do not share it.")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - a missing browser is not an error; the link is printed
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


def _req(port: int, method: str, path: str, headers: dict[str, str] | None = None) -> http.client.HTTPResponse:
    c = http.client.HTTPConnection(BIND, port, timeout=10)
    c.request(method, path, headers=headers or {})
    r = c.getresponse()
    r.body = r.read()  # type: ignore[attr-defined]
    c.close()
    return r


def check_server(root: Path | None = None, out: Callable[[str], None] = print) -> int:
    """Start on a free port, check every security rule against the live server, stop. 0 = all passed."""
    srv, app, url = start(root, 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    port, host = app.port, {"Host": f"127.0.0.1:{app.port}"}
    results: list[tuple[bool, str]] = []
    try:
        results.append((srv.server_address[0] == BIND, f"bound to {srv.server_address[0]} only"))
        r = _req(port, "GET", "/", host)
        results.append((r.status == 401, f"no key -> {r.status} (want 401)"))
        r = _req(port, "GET", "/?t=wrong", host)
        results.append((r.status == 401, f"wrong key -> {r.status} (want 401)"))
        r = _req(port, "GET", f"/?t={app.token}", host)
        sc = r.getheader("Set-Cookie") or ""
        results.append((r.status == 303 and "HttpOnly" in sc and "SameSite=Strict" in sc
                        and app.token not in (r.getheader("Location") or ""),
                        f"key -> {r.status}, cookie HttpOnly+SameSite=Strict, key removed from the URL"))
        ck = {**host, "Cookie": f"{COOKIE}={app.token}"}
        r = _req(port, "GET", "/", ck)
        csp = r.getheader("Content-Security-Policy") or ""
        results.append((r.status == 200 and b"RESEARCH ONLY" in r.body, f"with cookie -> {r.status}"))
        results.append(("default-src 'none'" in csp and r.getheader("X-Frame-Options") == "DENY",
                        "CSP without scripts, no framing"))
        r = _req(port, "GET", "/", {"Host": f"evil.example:{port}", "Cookie": f"{COOKIE}={app.token}"})
        results.append((r.status == 403, f"foreign Host header -> {r.status} (want 403)"))
        r = _req(port, "POST", "/", ck)
        results.append((r.status == 405, f"POST -> {r.status} (want 405, read-only)"))
        r = _req(port, "GET", "/runs/%3Cscript%3Ealert(1)%3C%2Fscript%3E", ck)
        results.append((b"<script>" not in r.body, "page text is escaped (no script injection)"))
        for path in ("/data", "/runs", "/legacy", "/diagnostics", "/settings", "/app.css"):
            r = _req(port, "GET", path, ck)
            results.append((r.status == 200, f"{path} -> {r.status}"))
    finally:
        srv.shutdown()
        srv.server_close()
    for ok, text in results:
        out(f"{'PASS' if ok else 'FAIL'}  {text}")
    bad = sum(1 for ok, _ in results if not ok)
    out("Dashboard security self-test passed." if not bad else f"{bad} dashboard check(s) failed.")
    return 0 if not bad else 1
