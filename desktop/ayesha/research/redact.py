"""Redaction for everything research writes for people to read: worker logs, exports, dashboard pages.

Defence in depth: research code never handles the token, pairing code or signing passwords on purpose, but an error
message or a pasted path could still carry one, so text is scrubbed before it reaches a log, page or export.
"""

from __future__ import annotations

import re

_PAIR = "[ABCDEFGHJKMNPQRSTUVWXYZ23456789]"  # ayesha.delivery.push.ALPHABET
PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [REDACTED]"),
    (re.compile(r"\b[0-9a-fA-F]{32}-[0-9a-fA-F]{32}\b"), "[REDACTED_TOKEN]"),  # OANDA personal access token shape
    (re.compile(rf"(?<![A-Za-z0-9_]){_PAIR}{{4}}-{_PAIR}{{4}}-{_PAIR}{{4}}-{_PAIR}{{4}}(?![A-Za-z0-9_])"),
     "[REDACTED_PAIRING_CODE]"),
    (re.compile(rf"(?<![A-Za-z0-9_]){_PAIR}{{16}}(?![A-Za-z0-9_])"), "[REDACTED_PAIRING_CODE]"),
    (re.compile(r"(?i)\b(token|password|passwd|secret|pairing[_ -]?code|api[_-]?key|storepass|keypass|"
                r"authorization)(\"?\s*[:=]\s*\"?)([^\s\",;}]+)"), r"\1\2[REDACTED]"),
    (re.compile(r"(?i)\b([A-Z]:\\+Users\\+)[^\\/\s\"']+"), r"\1[user]"),
    (re.compile(r"(/(?:home|Users)/)[^/\s\"']+"), r"\1[user]"),
]


def redact(text: str) -> str:
    for pat, rep in PATTERNS:
        text = pat.sub(rep, text)
    return text


def redact_obj(o):
    """Redact every string inside a JSON-like value (keys and values), keeping its structure valid."""
    if isinstance(o, str):
        return redact(o)
    if isinstance(o, dict):
        return {redact(str(k)): redact_obj(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [redact_obj(v) for v in o]
    return o


class RedactingWriter:
    """Text stream wrapper: every write is redacted before it reaches the underlying stream (worker logs)."""

    def __init__(self, stream) -> None:
        self.stream = stream

    def write(self, s: str) -> int:
        self.stream.write(redact(s))
        return len(s)

    def flush(self) -> None:
        self.stream.flush()

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self) -> str:
        return getattr(self.stream, "encoding", "utf-8")
