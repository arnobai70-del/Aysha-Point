"""PC -> phone push for the AYESHA app, through the ntfy.sh relay (opt-in, disclosed).

Why a relay: the owner runs no VPS and the phone cannot reach the PC directly. ntfy.sh is an
open-source publish/subscribe service with a public free server; the PC POSTs to a topic and the
AYESHA app keeps a connection to the same topic.

What the relay sees: the alert text (pair, levels, status, news phase). Never account login,
balance, equity or tokens: capital travels only as a keyed digest (CAPH=) that the phone can
compare with its own equity setting, plus the snapshot version and time. Anyone who learns the topic name can read those alerts, so the topic is derived
from a random pairing code. Messages are signed (HMAC-SHA256 with the pairing code), so the app
rejects anything not produced by this PC, and the signal id + expiry stop replays.

Wire format 4 (one alert):
    AYESHA BUY OANDA:EURUSD TF=15 E=... SL=... TP=... RR=... LOT=0.00 EXP=0 SRC=PDL TGT=ASIA_H BAR=<ms>
        ST=READY FROM=PC ID=<signal_id> EXPU=<ms> BLK=<codes> MTF=<...> WF=4 NP=<news phase>
        NE=<event id|NONE> NT=<event ms|0> NI=<impact|NONE> NV=<calendar fetch ms|0>
        CAPV=<snapshot version|0> CAPT=<snapshot ms|0> CAPH=<digest|NA> RISKP=<risk %> SPEC=<OWNER|ASSUMED|MT5> V=<hash>
    Why: ...
    SIG=<hex>
News watch (information only, never a trade signal):
    AYESHA NEWS ID=<event id> CCY=USD IMP=HIGH TIER=TOP_DATA T=<ms> PH=UPCOMING|PRE_EVENT_LOCKOUT|RELEASED|WINDOW_END
        ST=<event state> WS=<ms> WE=<ms> SRC=<provider> VER=<ms> PAIRS=EURUSD,USDJPY SENT=<ms> V=<hash>
    Title: ... / Forecast: ... / Scenario: ... / Reaction: ... / Protection: ...
    SIG=<hex>
Heartbeat:
    AYESHA HB T=<ms> STATE=OK|DATA_STALE|FEED_OFFLINE|STOPPED PAIRS=<n> V=<hash> CAP=OK|STALE|MISSING|...
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


WIRE_FORMAT = 4


def _ms(iso: str | None) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000) if iso else 0


def _tok(v: Any, default: str = "NA") -> str:
    t = str(v if v not in (None, "") else default)
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in t)[:40]


def _fmt(x: float, pair: str) -> str:
    return f"{x:.3f}" if pair.endswith("JPY") else f"{x:.5f}"


# PC record status -> phone status (ST=). The phone only knows READY / WATCH / NO_TRADE from the PC.
WIRE_STATUS = {"READY": "READY", "NOTIFIED": "READY", "WATCH": "WATCH", "WATCH_M5": "WATCH",
               "NO_TRADE": "NO_TRADE", "CONFIRM_FAILED": "NO_TRADE", "INVALIDATED": "NO_TRADE"}
MTF_KEYS = (("H4", "H4"), ("H1", "H1"), ("H1_LAST", "H1L"), ("H1_ZONE", "Z"), ("M15", "M15"), ("M5", "M5"))


def format_mtf(mtf: dict[str, str] | None) -> str:
    """Compact multi-timeframe explanation, e.g. H4:UP,H1:UP,H1L:BOS_UP,Z:DISCOUNT,M15:PDL_SWEEP>CHOCH>FVG,M5:OFF"""
    if not mtf:
        return "NA"
    parts = []
    for k, short in MTF_KEYS:
        v = str(mtf.get(k, "")).replace(" ", "_").replace(",", "_").replace(":", "_")
        if v:
            parts.append(f"{short}:{v}")
    return ",".join(parts) or "NA"


def _spec_kind(source: str | None) -> str:
    s = source or ""
    return "MT5" if s.startswith("MT5") else "OWNER" if s.startswith("OWNER_CONFIRMED:") else "ASSUMED"


def format_push(rec: dict[str, Any], tf_minutes: int = 15, code: str | None = None) -> str:
    """Canonical PC signal record -> AYESHA line format the phone parser reads.
    `code` (pairing code) keys the capital digest; without it CAPH=NA."""
    pair = rec["pair"]
    tp = rec["take_profits"][-1]
    blk = ",".join(rec.get("blockers") or []) or "NONE"
    st = WIRE_STATUS.get(rec["status"], "NO_TRADE")
    ev = rec.get("news_event") or {}
    eq = rec.get("capital_equity_usd")
    if code and eq:
        from ayesha.capital import digest

        caph = digest(code, eq)
    else:
        caph = "NA"
    head = (f"AYESHA {rec['direction']} OANDA:{pair} TF={tf_minutes} E={_fmt(rec['entry'], pair)} "
            f"SL={_fmt(rec['stop_loss'], pair)} TP={_fmt(tp, pair)} RR={(rec.get('net_rr') or 0):.2f} "
            f"LOT={(rec.get('safe_lot') or 0):.2f} EXP=0 SRC={rec.get('liquidity_source') or 'NA'} "
            f"TGT={rec.get('target_name') or 'NA'} BAR={_ms(rec['event_time_utc'])} ST={st} FROM=PC "
            f"ID={rec['signal_id']} EXPU={_ms(rec['expires_at_utc'])} BLK={blk} MTF={format_mtf(rec.get('mtf'))} "
            f"WF={WIRE_FORMAT} NP={_tok(rec.get('news_phase'), 'NEWS_UNVERIFIED')} NE={_tok(ev.get('event_id'), 'NONE')} "
            f"NT={_ms(ev.get('time_utc'))} NI={_tok(ev.get('impact'), 'NONE')} NV={_ms(rec.get('news_verified_at_utc'))} "
            f"CAPV={rec.get('capital_snapshot_version') or 0} CAPT={_ms(rec.get('capital_verified_at_utc'))} "
            f"CAPH={caph} RISKP={rec.get('risk_percent', 0)} SPEC={_spec_kind(rec.get('contract_spec_source'))} "
            f"V={rec['strategy_hash']}")
    why = (f"Why: {rec.get('setup', 'SWEEP_MSS_FVG')} score {rec.get('score_points')}/100 (rule points, not a probability); "
           f"news {rec.get('news_phase') or rec.get('news_verification')}; spread {rec.get('spread_pips')} pips (data feed)"
           + ("; waiting for M5 confirmation, not an entry yet" if rec["status"] == "WATCH_M5" else "")
           + ("; M5-confirmed: market entry near E, only for a few minutes"
              if rec.get("entry_type") == "MARKET_AFTER_M5_CONFIRMATION" and st == "READY" else "")
           + ("; INVALIDATED before entry: do not take it" if rec["status"] == "INVALIDATED" else ""))
    lines = [head, why]
    sc = rec.get("news_scenario")
    if sc and sc.get("summary"):
        lines.append("News: " + f"{sc.get('title')} ({sc.get('currency')}, {sc.get('impact')}). " + sc["summary"])
    return "\n".join(lines)


def format_news(n: dict[str, Any], strategy_hash: str) -> str:
    """News Watch message: information and protection status only, never BUY/SELL."""
    head = (f"AYESHA NEWS ID={_tok(n['event_id'])} CCY={_tok(n['currency'])} IMP={_tok(n['impact'])} "
            f"TIER={_tok(n['tier'])} T={_ms(n['time_utc'])} PH={n['phase']} ST={_tok(n.get('state'), 'SCHEDULED')} "
            f"WS={_ms(n['window_start_utc'])} WE={_ms(n['window_end_utc'])} SRC={_tok(n.get('provider'))} "
            f"VER={_ms(n.get('verified_at_utc'))} PAIRS={','.join(n['pairs'])} SENT={_ms(n['sent_at_utc'])} "
            f"V={strategy_hash}")
    lines = [head, "Title: " + " ".join(str(n["title"]).split())[:120],
             f"Forecast: {n.get('forecast') or 'NA'} | Previous: {n.get('previous') or 'NA'}"]
    sc = n.get("scenario")
    if sc:
        lines.append("Scenario: " + sc.get("summary", "Direction unknown; protection active."))
    r = n.get("reaction")
    if r:
        lines.append(f"Reaction: {r.get('state', 'UNAVAILABLE')}; surprise {r.get('surprise') or 'NA'}; "
                     f"{r.get('symbol', '')} move {r.get('observed_pair_move') or 'NA'} ({r.get('observed_atr') or 'NA'} ATR); "
                     f"settled {'yes' if r.get('market_settled') else 'no'}")
    lines.append("Protection: new trades blocked on " + ", ".join(n["pairs"]) +
                 " during the window and until spread and volatility settle. Review any open trade, stop-loss "
                 "and possible gap/slippage. Not a trade signal.")
    return "\n".join(lines)


def format_heartbeat(t_ms: int, state: str, pairs: int, strategy_hash: str, capital: str = "") -> str:
    return f"AYESHA HB T={t_ms} STATE={state} PAIRS={pairs} V={strategy_hash}" + (f" CAP={_tok(capital)}" if capital else "")


class NtfyNotifier:
    """Opt-in push to the AYESHA phone app. Sends READY, and also NO_TRADE/WATCH as archive-only
    records so the phone can show why a setup was not alerted."""

    channel = "ntfy"
    archive_non_ready = True

    def __init__(self, code: str, server: str = NTFY, timeout: float = 10, post=None, strategy_hash: str = "") -> None:
        self.code = normalize_code(code)
        self.url = f"{server.rstrip('/')}/{topic_for(self.code)}"
        self.timeout = timeout
        self._post = post or self._http_post
        self.strategy_hash = strategy_hash

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
        return self.publish(format_push(rec, code=self.code), "high" if rec["status"] == "READY" else "low")

    def news(self, notice: dict[str, Any], strategy_hash: str = "") -> tuple[bool, str]:
        return self.publish(format_news(notice, strategy_hash or self.strategy_hash), "default")

    def heartbeat(self, t_ms: int, state: str, pairs: int, strategy_hash: str, capital: str = "") -> tuple[bool, str]:
        self.strategy_hash = strategy_hash
        return self.publish(format_heartbeat(t_ms, state, pairs, strategy_hash, capital), "min")


def default_code_path() -> Path:
    from ayesha.paths import home

    return home() / "pairing-code.txt"


def load_or_create_code(path: Path | None = None) -> str:
    p = path or default_code_path()
    if p.exists():
        return normalize_code(p.read_text(encoding="utf-8").strip())
    code = new_pairing_code()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(code, encoding="utf-8")
    return normalize_code(code)
