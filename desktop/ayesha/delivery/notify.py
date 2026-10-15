"""Alert delivery. Payloads never contain account login, balance or equity."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any, Protocol


class Notifier(Protocol):
    channel: str

    def send(self, rec: dict[str, Any]) -> tuple[bool, str]: ...


GRADE_LABEL = {"A_PLUS": "A+", "WATCH": "WATCH", "IGNORE": "IGNORE"}


def format_alert(rec: dict[str, Any]) -> str:
    icon = "🟢" if rec["direction"] == "BUY" else "🔴"
    tp = ", ".join(f"{x:.5f}" for x in rec["take_profits"])
    bp = rec.get("broker_prices") or {}
    lines = [
        f"[AYESHA FX] {icon} {GRADE_LABEL.get(rec['grade'], rec['grade'])} SETUP — {rec['pair']}",
        f"{rec['direction']} | {'/'.join(rec.get('session', []))} | {rec['timeframe']}",
        f"Chart levels: entry {rec['entry']:.5f} | SL {rec['stop_loss']:.5f} | TP {tp}",
        f"MT5 prices: limit {bp.get('limit', 0):.5f} | SL {bp.get('sl', 0):.5f} | TP {bp.get('tp', 0):.5f}",
        f"Lot {rec['safe_lot']} | max loss ${rec['risk_usd']:.2f} | net RR {rec['net_rr']:.2f}",
        f"Score {rec['score_points']}/100 (rule points, not a probability)",
        f"Expires {rec['expires_at_utc']} UTC | id {rec['signal_id'][:8]}",
        "Manual decision only. Re-check price and spread before placing.",
    ]
    return "\n".join(lines)


class ConsoleNotifier:
    channel = "console"

    def send(self, rec: dict[str, Any]) -> tuple[bool, str]:
        print("\n" + format_alert(rec) + "\n", flush=True)
        return True, "printed"


class TelegramNotifier:
    """Opt-in. Token and chat id come from the environment, never from the repository."""

    channel = "telegram"

    def __init__(self, token: str | None = None, chat_id: str | None = None, timeout: float = 10) -> None:
        self.token = token or os.environ.get("AYESHA_TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("AYESHA_TELEGRAM_CHAT_ID", "")
        if not self.token or not self.chat_id:
            raise RuntimeError("Set AYESHA_TELEGRAM_BOT_TOKEN and AYESHA_TELEGRAM_CHAT_ID to enable Telegram alerts")
        self.timeout = timeout

    def send(self, rec: dict[str, Any]) -> tuple[bool, str]:
        return self.send_text(format_alert(rec))

    def send_text(self, text: str) -> tuple[bool, str]:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": self.chat_id, "text": text}).encode()
        try:
            with urllib.request.urlopen(url, data=data, timeout=self.timeout) as r:
                body = json.loads(r.read().decode())
            return bool(body.get("ok")), "sent" if body.get("ok") else str(body)[:200]
        except Exception as e:  # network errors are logged, never raised into the scan loop
            return False, type(e).__name__
