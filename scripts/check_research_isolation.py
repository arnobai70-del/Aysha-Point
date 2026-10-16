"""CI: the research plane is isolated from the live advisory path (rules in desktop/ayesha/research/isolation.py).

    python scripts/check_research_isolation.py .
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else ".").resolve()
    sys.path.insert(0, str(root / "desktop"))
    from ayesha.research.isolation import check

    problems = check(root / "desktop" / "ayesha", root / "desktop" / "windows")
    for p in problems:
        print("ERROR:", p)
    if problems:
        return 1
    print("OK: the scanner cannot import research; research cannot reach phone delivery, signing, the token store, "
          "the capital file or the live registry; no eval/exec/pickle/shell; no READY value in research code")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
