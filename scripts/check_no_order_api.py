#!/usr/bin/env python3
"""Fail if any source file can place, modify or close broker orders (master spec W, Y).

Scans .py/.pine/.kt/.kts/.java/.js/.ts files. Allowed exceptions: this script and the
test that proves the MT5 proxy blocks these calls.
"""

import re
import sys
from pathlib import Path

FORBIDDEN = re.compile(
    r"\b(order_send|order_check|order_modify|position_close|positions_close|TRADE_ACTION_\w+|"
    r"OrderSend|OrderModify|OrderClose|PositionClose|strategy\.entry|strategy\.order|strategy\.close)\b"
    # OANDA v20 write endpoints (the data feed may only call /candles)
    r"|/v3/accounts/[^\s\"']*/(orders|trades|positions)"
)
EXTS = {".py", ".pine", ".kt", ".kts", ".java", ".js", ".ts"}
ALLOW = {"scripts/check_no_order_api.py", "desktop/tests/test_safety_config_news.py"}  # tests contain forbidden names on purpose
SKIP_DIRS = {".git", "node_modules", "build", ".venv", "venv", "__pycache__", ".gradle"}


def main(root: str) -> int:
    base = Path(root).resolve()
    bad = []
    for p in base.rglob("*"):
        if not p.is_file() or p.suffix not in EXTS or SKIP_DIRS & set(p.relative_to(base).parts):
            continue
        rel = p.relative_to(base).as_posix()
        if rel in ALLOW:
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if FORBIDDEN.search(line):
                bad.append(f"{rel}:{n}: {line.strip()}")
    if bad:
        print("Order/trade API usage found (advisory-only project):")
        print("\n".join(bad))
        return 1
    print("OK: no order-execution API found")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
