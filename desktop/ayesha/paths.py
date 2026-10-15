"""Where AYESHA keeps the owner's local files (never inside the repository).

Default: %USERPROFILE%\\AyeshaFX (Windows) or ~/AyeshaFX. `AYESHA_HOME` overrides it (tests, CI).
"""

from __future__ import annotations

import os
from pathlib import Path


def home() -> Path:
    v = os.environ.get("AYESHA_HOME", "").strip()
    return Path(v) if v else Path.home() / "AyeshaFX"
