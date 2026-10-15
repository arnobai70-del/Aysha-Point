#!/usr/bin/env python3
"""Live end-to-end check of the PC -> phone relay path (run in CI, needs internet).

Publishes one signed AYESHA heartbeat to a fresh random ntfy.sh topic exactly the way the PC
scanner does, reads it back exactly the way the Android LinkService does (JSON stream with
`since`, here in poll mode), and verifies the signature and the body byte for byte.
It proves the relay transport and the signing format; it does not prove a phone received it.
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))

from ayesha.delivery import push  # noqa: E402


def main() -> int:
    code = push.new_pairing_code()
    n = push.NtfyNotifier(code)
    t_ms = int(time.time() * 1000)
    body = push.format_heartbeat(t_ms, "TEST", 0, "ci")
    t0 = time.monotonic()
    ok, detail = n.publish(body, "min")
    if not ok:
        print(f"FAIL publish: {detail}")
        return 1
    url = f"{push.NTFY}/{push.topic_for(code)}/json?poll=1&since=all"
    for attempt in range(5):
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "AYESHA-FX-CI"}), timeout=20) as r:
            lines = [json.loads(x) for x in r.read().decode().splitlines() if x.strip()]
        msgs = [m["message"] for m in lines if m.get("event") == "message"]
        if msgs:
            got = push.verify(code, msgs[-1])
            if got != body:
                print(f"FAIL verify: got {got!r}")
                return 1
            if push.verify(push.new_pairing_code(), msgs[-1]) is not None:
                print("FAIL: wrong code verified")
                return 1
            print(f"OK relay round trip in {time.monotonic() - t0:.2f}s; signature verified; topic {push.topic_for(code)}")
            return 0
        time.sleep(2)
    print("FAIL: message not readable from relay")
    return 1


if __name__ == "__main__":
    sys.exit(main())
