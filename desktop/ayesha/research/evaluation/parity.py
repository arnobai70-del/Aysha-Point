"""Baseline parity (plan AI-005): does a frozen snapshot replay exactly like the legacy `ayesha report` path?

The legacy path reads `<PAIR>_<TF>.csv` with `ayesha.feed.csv_feed.load_candles`; when backtest-run exported those
files, `save_candles` stored the spread in whole points. This check builds that legacy input from the snapshot (a
`save_candles` -> `load_candles` round trip in a temporary folder) or reads the owner's original CSV, runs the
unchanged legacy replay on both inputs with the same spec, and compares bars and every signal's outcome. The result
is MATCHED (identical inputs and outcomes), MATCHED_WITH_EXPLAINED_DIFFERENCES (identical outcomes; the inputs differ
only by sub-point spread rounding) or DIFFERENT, with every difference counted and explained. Nothing is adjusted
to make them agree.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from ayesha.research.datasets.normalize import point_for
from ayesha.research.provenance import digest, iso
from ayesha.research.simulation.baseline import APPROX_USD_RATES, MODES, RunRefused, spec_for, load_candles
from ayesha.research.workspace import Workspace

EXPLAIN = {
    "SPREAD_ROUNDED_TO_WHOLE_POINTS": "The legacy CSV keeps the spread in whole points; the snapshot keeps the "
                                      "provider's ask - bid (less than half a point apart). Fills and stop exits use "
                                      "the spread, so an outcome could move by a fraction of a point.",
    "SPREAD_DIFFERENT": "Spreads differ by half a point or more: the two inputs are not the same data.",
    "PRICE_OR_TIME_DIFFERENT": "Bar times or prices differ: the two inputs are not the same data.",
    "BAR_COUNT_DIFFERENT": "One input has more bars (for example a CSV that kept duplicates or rejected rows).",
}
EXPLAINED_ONLY = {"SPREAD_ROUNDED_TO_WHOLE_POINTS"}


def _trade_row(t) -> list[Any]:
    return [t.signal.signal_id, t.status, t.fill_index, t.exit_index, t.exit_reason, t.r, list(t.blockers),
            t.signal.grade, t.signal.score]


def compare_candles(a: list, b: list, point: float) -> dict[str, Any]:
    price = rounded = spread = 0
    examples: list[str] = []
    for x, y in zip(a, b):
        if (x.time, x.open, x.high, x.low, x.close, x.volume) != (y.time, y.open, y.high, y.low, y.close, y.volume):
            price += 1
            if len(examples) < 5:
                examples.append(f"{iso(x.time)}: price/time differs")
        elif x.spread != y.spread:
            if abs(x.spread - y.spread) < point / 2:
                rounded += 1
            else:
                spread += 1
            if len(examples) < 5:
                examples.append(f"{iso(x.time)}: spread {x.spread / point:.6f} vs {y.spread / point:.6f} points")
    codes = []
    if len(a) != len(b):
        codes.append("BAR_COUNT_DIFFERENT")
    if price:
        codes.append("PRICE_OR_TIME_DIFFERENT")
    if spread:
        codes.append("SPREAD_DIFFERENT")
    if rounded:
        codes.append("SPREAD_ROUNDED_TO_WHOLE_POINTS")
    return {"equal": not codes, "bars": [len(a), len(b)], "price_or_time_differences": price,
            "spread_only_differences": rounded + spread, "spread_rounding_differences": rounded, "codes": codes,
            "examples": examples}


def compare_trades(a: list, b: list) -> dict[str, Any]:
    ra, rb = [_trade_row(t) for t in a], [_trade_row(t) for t in b]
    ids_a, ids_b = {r[0]: r for r in ra}, {r[0]: r for r in rb}
    only_a, only_b = sorted(set(ids_a) - set(ids_b)), sorted(set(ids_b) - set(ids_a))
    changed = [i for i in sorted(set(ids_a) & set(ids_b)) if ids_a[i] != ids_b[i]]
    return {"equal": ra == rb, "signals": [len(ra), len(rb)], "sha256": [digest(ra), digest(rb)],
            "only_in_snapshot": only_a[:10], "only_in_legacy": only_b[:10],
            "changed": [{"signal_id": i, "snapshot": ids_a[i][1:], "legacy": ids_b[i][1:]} for i in changed[:10]],
            "changed_count": len(changed)}


def parity(ws: Workspace, spec: dict[str, Any], dataset_id: str, symbol: str, mode: str = "m15",
           legacy_csv: str | Path | None = None, account_type: str = "Standard") -> dict[str, Any]:
    from ayesha.backtest.replay import run_backtest, summarize
    from ayesha.feed import csv_feed

    if mode not in MODES:
        raise RunRefused(f"mode must be one of {sorted(MODES)}")
    tf = MODES[mode][0]
    snap = load_candles(ws, dataset_id, symbol, tf)
    point = point_for(symbol)
    if legacy_csv is not None:
        legacy = csv_feed.load_candles(legacy_csv, point)
        source = "OWNER_CSV"
    else:
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / f"{symbol}_{tf}.csv"
            csv_feed.save_candles(f, snap, point)
            legacy = csv_feed.load_candles(f, point)
        source = "LEGACY_CSV_ROUND_TRIP"
    sp = spec_for(spec, mode)
    res_s = run_backtest(symbol, snap, sp, account_type=account_type, usd_rates=APPROX_USD_RATES)
    res_l = run_backtest(symbol, legacy, sp, account_type=account_type, usd_rates=APPROX_USD_RATES)
    cd = compare_candles(snap, legacy, point)
    td = compare_trades(res_s["trades"], res_l["trades"])
    ss, sl = summarize(res_s["trades"]), summarize(res_l["trades"])
    same_outcomes = td["equal"] and ss == sl
    if cd["equal"] and same_outcomes:
        status = "MATCHED"
    elif same_outcomes and set(cd["codes"]) <= EXPLAINED_ONLY:
        status = "MATCHED_WITH_EXPLAINED_DIFFERENCES"
    else:
        status = "DIFFERENT"
    out = {
        "status": status, "dataset_id": dataset_id, "symbol": symbol, "mode": mode, "legacy_input": source,
        "legacy_engine": "ayesha.backtest.replay.run_backtest (unchanged 0.8.0 code)",
        "candles": cd, "signals": td,
        "summary": {"snapshot": {k: ss[k] for k in ("signals", "closed_trades", "total_r", "by_status")},
                    "legacy": {k: sl[k] for k in ("signals", "closed_trades", "total_r", "by_status")}},
        "explanations": {c: EXPLAIN[c] for c in cd["codes"]},
        "note": "Parity compares inputs and the replay; it says nothing about whether the strategy has an edge.",
    }
    ws.db.audit("research", "PARITY_CHECKED", f"{dataset_id}:{symbol}:{mode}",
                {"status": status, "legacy_input": source, "codes": cd["codes"]})
    return out
