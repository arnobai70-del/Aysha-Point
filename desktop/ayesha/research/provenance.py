"""Provenance helpers: content hashes, canonical JSON, UTC times, code and environment identity.

Every research artifact is identified by the SHA-256 of its content, so a result can be reproduced and checked:
same inputs, same code, same environment, same hashes. Nothing here reads or prints credentials.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]


def canonical_json(obj: Any) -> bytes:
    """Stable bytes for hashing: sorted keys, no whitespace, UTF-8, floats in Python's shortest round-trip form."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str,
                      allow_nan=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(obj: Any) -> str:
    return sha256_bytes(canonical_json(obj))


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(t: datetime | None) -> str | None:
    """UTC time as 2026-01-05T10:00:00Z (microseconds kept only when present)."""
    if t is None:
        return None
    t = t.astimezone(timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S") + (f".{t.microsecond:06d}" if t.microsecond else "") + "Z"


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def commit_sha(root: Path = REPO_ROOT) -> str:
    """The checked-out commit, read from .git without running git. A ZIP download has no .git: UNKNOWN."""
    git = root / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head if len(head) == 40 else "UNKNOWN"
        ref = head[5:]
        f = git / ref
        if f.exists():
            return f.read_text(encoding="utf-8").strip()
        packed = git / "packed-refs"
        if packed.exists():
            for line in packed.read_text(encoding="utf-8").splitlines():
                if line.endswith(" " + ref):
                    return line.split(" ", 1)[0]
    except OSError:
        pass
    return "UNKNOWN"


def desktop_version() -> str:
    from ayesha import __version__

    return __version__


def environment() -> dict[str, str]:
    """Software identity that can change a result: interpreter, OS family, SQLite, YAML parser."""
    try:
        import yaml

        yv = getattr(yaml, "__version__", "?")
    except ImportError:  # pragma: no cover - pyyaml is a base dependency
        yv = "missing"
    return {"python": platform.python_version(), "implementation": platform.python_implementation(),
            "os": platform.system(), "sqlite": sqlite3.sqlite_version, "pyyaml": yv,
            "float_repr": sys.float_repr_style}


def environment_hash() -> str:
    return digest(environment())
