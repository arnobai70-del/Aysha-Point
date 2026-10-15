"""Fail if a tracked file looks like it contains a credential (OANDA token, private key, keystore,
GitHub/AWS/Telegram tokens). Run in CI on every push."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PATTERNS = {
    "OANDA token": re.compile(r"\b[0-9a-f]{32}-[0-9a-f]{32}\b"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(ghp|gho|ghs|ghu)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{40,}"),
    "AWS key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Telegram bot token": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
}
BAD_EXT = {".jks", ".keystore", ".p12", ".pfx", ".pem", ".key"}


def tracked(root: Path) -> list[Path]:
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True).stdout
        return [root / p for p in out.decode().split("\0") if p]
    except Exception:
        return [p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts]


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else ".").resolve()
    errs = []
    for p in tracked(root):
        if p.suffix.lower() in BAD_EXT:
            errs.append(f"{p.relative_to(root)}: key/keystore file must never be committed")
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, rx in PATTERNS.items():
            if rx.search(text):
                errs.append(f"{p.relative_to(root)}: looks like a {name}")
    for e in errs:
        print("ERROR:", e)
    if errs:
        return 1
    print("OK: no credentials found in tracked files")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
