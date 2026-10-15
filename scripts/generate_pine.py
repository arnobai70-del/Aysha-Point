#!/usr/bin/env python3
"""Generate tradingview/AyeshaSmartMoney.pine from the template and contracts/strategy-spec.yaml.

Usage: python scripts/generate_pine.py [--check]
--check exits 1 if the committed .pine file is out of date (used in CI/tests).
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

from ayesha.config import load_spec  # noqa: E402

TEMPLATE = ROOT / "tradingview" / "AyeshaSmartMoney.template.pine"
OUT = ROOT / "tradingview" / "AyeshaSmartMoney.pine"
TV_TF = {"M5": "5", "M15": "15", "H1": "60", "H4": "240", "D1": "D"}


def context(spec: dict) -> dict:
    ctx = dict(spec)
    sess = {}
    for k, v in spec["sessions"].items():
        if isinstance(v, dict) and "start" in v and "end" in v:
            h1, m1 = map(int, v["start"].split(":"))
            h2, m2 = map(int, v["end"].split(":"))
            sess[k] = {**v, "start_min": h1 * 60 + m1, "end_min": h2 * 60 + m2}
        else:
            sess[k] = v
    ctx["sessions"] = sess
    ctx["entry"] = {**spec["entry"], "bias_tv": TV_TF[spec["entry"]["bias_timeframe"]]}
    return ctx


def lookup(ctx: dict, path: str):
    cur = ctx
    for part in path.split("."):
        cur = cur[part]
    return cur


def render() -> str:
    spec = load_spec()
    ctx = context(spec)
    text = TEMPLATE.read_text(encoding="utf-8")
    out = re.sub(r"\{\{([\w.]+)\}\}", lambda m: str(lookup(ctx, m.group(1))), text)
    out = out.replace("// GENERATED from tradingview/AyeshaSmartMoney.template.pine by scripts/generate_pine.py.",
                      f"// GENERATED from AyeshaSmartMoney.template.pine by scripts/generate_pine.py "
                      f"(strategy {spec['strategy_version']} #{spec['strategy_hash']}).")
    if "{{" in out:
        raise SystemExit("unresolved placeholder in Pine template")
    return out


def main() -> int:
    out = render()
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != out:
            print("tradingview/AyeshaSmartMoney.pine is out of date: run python scripts/generate_pine.py")
            return 1
        print("OK: Pine file matches strategy spec")
        return 0
    OUT.write_text(out, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
