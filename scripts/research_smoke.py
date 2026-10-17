"""CI smoke test of the research command line, end to end, in a throwaway AYESHA_HOME (synthetic data only).

    python scripts/research_smoke.py

Runs `python -m ayesha.cli research ...` as separate processes, the way an owner would, and checks exit codes and
key lines: off by default, enable, ingest, inspect, run, verify, report, parity, the Strategy Lab (strategies, lab,
one lab run with verify, compare, comparison report), backup, restore, doctor, selftests, dashboard security check,
disable (legacy_only) and refusal while off.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"
FAILED: list[str] = []


def run(args: list[str], want: int = 0, expect: tuple[str, ...] = (), env: dict[str, str] | None = None) -> str:
    p = subprocess.run([sys.executable, "-m", "ayesha.cli", "research", *args], cwd=DESKTOP, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    out = p.stdout + p.stderr
    ok = p.returncode == want and all(e in out for e in expect)
    print(f"{'PASS' if ok else 'FAIL'}  research {' '.join(args)}  (exit {p.returncode}, want {want})")
    if not ok:
        print(out)
        FAILED.append(" ".join(args))
    return out


def main() -> int:
    sys.path.insert(0, str(DESKTOP))
    from tests.research import synth

    with tempfile.TemporaryDirectory() as d:
        env = dict(os.environ, AYESHA_HOME=str(Path(d) / "AyeshaFX"), PYTHONIOENCODING="utf-8")
        env.pop("AYESHA_OANDA_TOKEN", None)
        csv = synth.csv_dir(Path(d) / "csv", m15=3000, m5=6000, seed=4)
        run(["status"], 0, ("OFF (legacy_only)", "No research data yet"), env)
        run(["ingest", "--from-csv-dir", str(csv)], 2, ("Research is OFF",), env)
        run(["enable"], 0, ("Research is ON",), env)
        out = run(["ingest", "--from-csv-dir", str(csv), "--label", "CI synthetic"], 0, ("quality PASS",), env)
        ds = re.search(r"Dataset (ds_[0-9a-f]{16})", out).group(1) if "Dataset ds_" in out else "ds_missing"
        run(["inspect", ds], 0, ("coverage 100.0%",), env)
        out = run(["run", "baseline-sweep-mss-fvg", "--dataset", ds, "--symbol", "EURUSD", "--split", "2025-03-20"],
                  0, ("COMPLETED",), env)
        rid = re.search(r"Run (run_[0-9a-f]{16})", out).group(1) if "Run run_" in out else "run_missing"
        run(["run", "baseline-sweep-mss-fvg", "--dataset", ds, "--symbol", "EURUSD", "--split", "2025-03-20",
             "--verify"], 0, ("VERIFIED",), env)
        run(["report", rid], 0, ("RESEARCH ONLY", "Legacy replay report"), env)
        run(["parity", "--dataset", ds, "--symbol", "EURUSD", "--mode", "m5confirm"], 0, ("Parity MATCHED",), env)
        run(["strategies"], 0, ("baseline-sweep-mss-fvg", "control-london-orb", "experimental-h1h4-trend"), env)
        out = run(["lab", "--dataset", ds, "--symbols", "EURUSD", "--quick", "--holdout", "2025-04-01"], 0,
                  ("benchmark parity MATCHED", "ranking NO_RANKING"), env)
        cid = re.search(r"Comparison (cmp_[0-9a-f]{16})", out).group(1) if "Comparison cmp_" in out else "cmp_missing"
        run(["report", cid], 0, ("RESEARCH ONLY", "Side by side"), env)
        cal = Path(d) / "calendar.csv"
        rows = ["time_utc,currency,impact,title,observed_utc"]
        for day in range(3, 32):
            for hh, ccy in ((8, "EUR"), (12, "USD"), (14, "USD")):
                rows.append(f"2025-03-{day:02d}T{hh:02d}:30:00Z,{ccy},HIGH,Synthetic {hh},2025-03-01T00:00:00Z")
        cal.write_text("\n".join(rows) + "\n", encoding="utf-8")
        run(["news-ingest", "--csv", str(cal), "--provider", "SYNTHETIC", "--license", "x"], 2, ("licence",), env)
        out = run(["news-ingest", "--csv", str(cal), "--provider", "SYNTHETIC", "--license",
                   "synthetic calendar written by the smoke test"], 0, ("PASS", "never backtested"), env)
        ns = re.search(r"(ns_[0-9a-f]{16})", out).group(1) if "ns_" in out else "ns_missing"
        run(["news"], 0, (ns,), env)
        run(["regime", "--dataset", ds, "--symbol", "EURUSD"], 0, ("regime-h4-er-slope-vol", "never a gate"), env)
        out = run(["lab", "--dataset", ds, "--symbols", "EURUSD", "--quick", "--news", ns], 0,
                  ("benchmark parity MATCHED",), env)
        ncid = re.search(r"Comparison (cmp_[0-9a-f]{16})", out).group(1) if "Comparison cmp_" in out else "cmp_missing"
        run(["report", ncid], 0, ("Strategy x regime", "News comparison: COMPARED"), env)
        run(["feed-audit", "--a", ds, "--b", ds, "--symbol", "EURUSD"], 2, ("two different datasets",), env)
        run(["feed-audits"], 0, ("No feed audits",), env)
        out = run(["run", "control-london-orb", "--dataset", ds, "--symbol", "EURUSD", "--quick"], 0,
                  ("COMPLETED",), env)
        run(["run", "control-london-orb", "--dataset", ds, "--symbol", "EURUSD", "--quick", "--verify"], 0,
            ("VERIFIED",), env)
        b = re.search(r"Run (run_[0-9a-f]{16})", out).group(1) if "Run run_" in out else "run_missing"
        run(["compare", rid, b], 2, ("not a Strategy Lab run",), env)
        out = run(["backup"], 0, ("integrity ok",), env)
        m = re.search(r"Backup: (\S+)", out)
        run(["restore", m.group(1) if m else "missing", "--yes"], 0, ("Restored",), env)
        run(["doctor", "--deep", "--selftest"], 0, ("All research checks passed",), env)
        run(["selftest", "crash"], 1, ("CRASHED",), env)
        run(["selftest", "ok"], 0, ("selftest ok: OK",), env)
        run(["dashboard", "--check"], 0, ("Dashboard security self-test passed",), env)
        run(["disable"], 0, ("Research is OFF",), env)
        run(["run", "baseline-sweep-mss-fvg", "--dataset", ds, "--symbol", "EURUSD"], 2, ("Research is OFF",), env)
        run(["datasets"], 0, (ds,), env)
    if FAILED:
        print(f"{len(FAILED)} research smoke step(s) failed")
        return 1
    print("Research smoke test passed (synthetic data; says nothing about a trading edge).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
