"""PC -> phone push for the AYESHA app, through the ntfy.sh relay (opt-in, disclosed).

Why a relay: the owner runs no VPS and the phone cannot reach the PC directly. ntfy.sh is an
open-source publish/subscribe service with a public free server; the PC POSTs to a topic and the
AYESHA app keeps a connection to the same topic.

What the relay sees: the alert text (pair, levels, status). Never account login, balance,
equity or tokens. Anyone who learns the topic name can read those alerts, so the topic is derived
from a random pairing code. Messages are signed (HMAC-SHA256 with the pairing code), so the app
rejects anything not produced by this PC, and the signal id + expiry stop replays.

Wire format (one alert):
    AYESHA BUY OANDA:EURUSD TF=15 E=... SL=... TP=... RR=... LOT=0.00 EXP=8 SRC=PDL TGT=ASIA_H BAR=<ms>
        QUSD=1 ST=READY FROM=PC ID=<signal_id> EXPU=<ms> BLK=<codes> V=<hash>
    Why: ...
    SIG=<hex>
Heartbeat:
    AYESHA HB T=<ms> STATE=OK|DATA_STALE|FEED_OFFLINE|STOPPED PAIRS=<n> V=<hash>
    SIG=<hex>
The signature covers every byte before "\\nSIG=".
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

NTFY = "https://ntfy.sh"
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L: easy to type on a phone


def new_pairing_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(16))
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


def normalize_code(code: str) -> str:
    c = "".join(ch for ch in code.upper() if ch.isalnum())
    if len(c) != 16 or any(ch not in ALPHABET for ch in c):
        raise ValueError("Pairing code must be 16 characters like ABCD-EFGH-JKMN-PQRS")
    return c


def topic_for(code: str) -> str:
    return "ayesha-" + hashlib.sha256(("topic:" + normalize_code(code)).encode()).hexdigest()[:24]


def sign(code: str, body: str) -> str:
    return hmac.new(normalize_code(code).encode(), body.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def signed(code: str, body: str) -> str:
    return f"{body}\nSIG={sign(code, body)}"


def verify(code: str, message: str) -> str | None:
    """Return the body if the signature is valid, else None."""
    body, sep, sig = message.rpartition("\nSIG=")
    if not sep or not hmac.compare_digest(sign(code, body), sig.strip()):
        return None
    return body


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def _fmt(x: float, pair: str) -> str:
    return f"{x:.3f}" if pair.endswith("JPY") else f"{x:.5f}"


def format_push(rec: dict[str, Any], tf_minutes: int = 15) -> str:
    """Canonical PC signal record -> AYESHA line format the phone parser reads."""
    pair = rec["pair"]
    tp = rec["take_profits"][-1]
    blk = ",".join(rec.get("blockers") or []) or "NONE"
    head = (f"AYESHA {rec['direction']} OANDA:{pair} TF={tf_minutes} E={_fmt(rec['entry'], pair)} "
            f"SL={_fmt(rec['stop_loss'], pair)} TP={_fmt(tp, pair)} RR={(rec.get('net_rr') or 0):.2f} "
            f"LOT={(rec.get('safe_lot') or 0):.2f} EXP=0 SRC={rec.get('liquidity_source') or 'NA'} "
            f"TGT={rec.get('target_name') or 'NA'} BAR={_ms(rec['event_time_utc'])} ST={rec['status']} FROM=PC "
            f"ID={rec['signal_id']} EXPU={_ms(rec['expires_at_utc'])} BLK={blk} V={rec['strategy_hash']}")
    why = (f"Why: {rec.get('setup', 'SWEEP_MSS_FVG')} score {rec.get('score_points')}/100 (rule points, not a probability); "
           f"news {rec.get('news_verification')}; spread {rec.get('spread_pips')} pips (data feed)")
    return head + "\n" + why


def format_heartbeat(t_ms: int, state: str, pairs: int, strategy_hash: str) -> str:
    return f"AYESHA HB T={t_ms} STATE={state} PAIRS={pairs} V={strategy_hash}"


class NtfyNotifier:
    """Opt-in push to the AYESHA phone app. Sends READY, and also NO_TRADE/WATCH as archive-only
    records so the phone can show why a setup was not alerted."""

    channel = "ntfy"
    archive_non_ready = True

    def __init__(self, code: str, server: str = NTFY, timeout: float = 10, post=None) -> None:
        self.code = normalize_code(code)
        self.url = f"{server.rstrip('/')}/{topic_for(self.code)}"
        self.timeout = timeout
        self._post = post or self._http_post

    def _http_post(self, url: str, data: bytes, headers: dict[str, str]) -> int:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return r.status

    def publish(self, body: str, priority: str = "default") -> tuple[bool, str]:
        try:
            st = self._post(self.url, signed(self.code, body).encode("utf-8"),
                            {"Priority": priority, "Title": "AYESHA", "Content-Type": "text/plain; charset=utf-8"})
            return 200 <= st < 300, f"HTTP {st}"
        except Exception as e:  # never raise into the scan loop
            return False, type(e).__name__

    def send(self, rec: dict[str, Any]) -> tuple[bool, str]:
        return self.publish(format_push(rec), "high" if rec["status"] == "READY" else "low")

    def heartbeat(self, t_ms: int, state: str, pairs: int, strategy_hash: str) -> tuple[bool, str]:
        return self.publish(format_heartbeat(t_ms, state, pairs, strategy_hash), "min")


def default_code_path() -> Path:
    return Path.home() / "AyeshaFX" / "pairing-code.txt"


def load_or_create_code(path: Path | None = None) -> str:
    p = path or default_code_path()
    if p.exists():
        return normalize_code(p.read_text(encoding="utf-8").strip())
    code = new_pairing_code()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(code, encoding="utf-8")
    return normalize_code(code)
