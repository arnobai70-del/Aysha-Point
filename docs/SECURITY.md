# Security notes (credentials, workflows, signing, capital, research) — release 0.9.0

The repository is **public**. Nothing secret may ever be committed; CI enforces this with
`scripts/check_no_secrets.py` (OANDA-token shape, private keys, keystores, GitHub/AWS/Telegram tokens).

## OANDA token audit (2026-10-15)
| Place | Before 0.7.1 | Now |
|---|---|---|
| Windows install | `setx AYESHA_OANDA_TOKEN "<token>"`: the token was a **command-line argument** of `setx`, visible to other processes and process-audit logs | `ayesha setup` / `ayesha set-token` read it hidden (getpass) and write `HKCU\Environment` with the registry API; no subprocess, no argument. Test: `test_windows_scripts_call_valid_commands` forbids `setx` in every .bat |
| Reading | process environment only | process environment, then `HKCU\Environment` (`ayesha/credentials.py`) |
| HTTP | `Authorization: Bearer` header to OANDA over HTTPS | unchanged; the URL never contains it (`test_oanda_feed_maps_401_to_auth_rejected_without_leaking_token`) |
| Errors and logs | exception text printed as is | HTTP errors re-raised without the original chain; 401/403 ⇒ `AuthRejected`; doctor and scan pass every message through `redact()`; scripted tests assert the token never appears in output (`test_setup_runs_unattended_and_is_rerunnable`, `test_scan_exit_codes_for_the_start_script`, Windows CI scenarios) |
| Database, reports, artifacts | not stored | not stored; reports contain only price-derived numbers |
| GitHub `backtest` workflow | token was job-level env for **every** step (including `pip install`, which runs third-party code); inputs were interpolated into `run:` (shell injection) | token only in the single export step, as env; inputs passed as quoted env vars and validated (`ayesha backtest-run --validate-only`); `permissions: contents: read`; `persist-credentials: false`; only the two report files are uploaded. `scripts/check_workflows.py` fails CI on any `${{ inputs.* }}`, `${{ github.event.* }}` or `${{ secrets.* }}` inside `run:` |

Remaining risk, stated plainly: any program running as your Windows user can read your user
environment (true for every environment variable). Use an **OANDA practice** token only, and revoke it
on the OANDA site (Manage API Access) if the PC is compromised. AYESHA never calls any order endpoint
(`scripts/check_no_order_api.py`), but the token itself would allow it on the practice account.

Artifacts of a public repository can be downloaded by any signed-in GitHub user. Reports hold no
secrets, but if you want them private use `desktop\windows\backtest-local.bat` (nothing leaves the PC).

## Backtest input validation
`ayesha/backtest/inputs.py`: pairs must be in the strategy's enabled list (exact `[A-Z]{6}`), days
30–3650 (digits only), folds 2–12, split date `YYYY-MM-DD`, a real calendar date inside the data.
Anything else exits with code 2 before any network call. Tested with injection strings
(`test_backtest_inputs_are_strictly_validated`).

## Android signing and data
See [10-owner-testing-guide.md](10-owner-testing-guide.md) (section গ৪). Summary: Android keeps app data on
update only when the new APK has the same signing key. `ayesha make-signing-key` creates a PKCS#12
key locally; its four values go into GitHub secrets; CI proves on every build that a key made this way
signs the APK (`Signing self-test` step) and prints the signer SHA-256 in each release note.

## Capital, broker and news data (0.8.0)
- **Exness:** AYESHA never asks for an Exness login, password, investor password or API key and has no Exness
  connection. Equity, open trades, free margin, leverage and contract values are typed by the owner from the Exness app.
- **Equity stays local.** PC snapshots are in `%AYESHA_HOME%\capital.json` (default `%USERPROFILE%\AyeshaFX`), the
  phone keeps its own value in app storage. Neither file is in the repository, a report or a workflow artifact.
- **Relay:** the public ntfy.sh relay never sees the amount. A READY carries `CAPH`, the first 16 hex characters of
  HMAC-SHA256(pairing code, `capital:v1:<cents>`); without the pairing code a relay reader cannot test guesses. The
  heartbeat carries only a status code (`CAP=OK`, `CAP=STALE`, ...). Tests: `test_c09_capital_updates_reach_the_scanner_and_never_the_relay`,
  Kotlin `capitalDigestMatchesPythonVector`.
- **Doctor and warnings** print codes, never amounts (`test_doctor_shows_capital_warnings_as_codes_without_amounts`);
  `ayesha capital --history` shows amounts only in the owner's own console.
- **News:** the Forex Factory weekly export needs no key. The local event ledger (`news-ledger.json`) holds only public
  calendar data and its provenance (`test_n12_offline_news_source_recovers_and_ledger_is_auditable` checks it holds no
  token). No paid or licensed calendar key is used or stored; a historical calendar CSV for P2 stays on the PC
  (`backtest-local.bat --news ...`); the report records only its file name (no folder path) and SHA-256.
- **Orders:** news, capital and scores can only block. Nothing in the PC or phone code can place, modify or close an
  order (`scripts/check_no_order_api.py`).

## Research plane (0.9.0)
- **Off by default.** Nothing under `%AYESHA_HOME%\research\` exists until `ayesha research enable`. The scanner
  never imports research (CI isolation check), and research cannot import the phone delivery, signing, capital,
  credential or live-registry code, `pickle`/`marshal`/`shelve`, or call `eval`/`exec`/`os.system`/`shell=True`.
  `subprocess` is allowed only in the worker, `urllib.request` only in the OANDA ingest, and HTTP serving only in the
  dashboard (`scripts/check_research_isolation.py`).
- **Token:** research uses the token only through the legacy OANDA adapter at download time. The raw artifact keeps
  response bodies and request paths, never headers; job files never contain it; logs, job records, dashboard pages and
  exports pass through a redactor (Bearer headers, OANDA-token shape, pairing codes, `key=value` secrets, user names).
  Tests: `test_oanda_ingest_keeps_ask_close_and_never_writes_the_token`,
  `test_research_files_never_hold_the_token_or_pairing_code`, `test_worker_logs_and_records_are_redacted`.
- **Live registry:** opened only with SQLite `mode=ro`; the dashboard's live view hides lot sizes and money
  (`test_t05_research_cannot_write_the_live_registry`, `test_live_registry_view_is_read_only_and_hides_money`).
- **Dashboard:** bound to 127.0.0.1 only; a new random key per start, passed once in the link and then kept in an
  HttpOnly, SameSite=Strict cookie; requests without it get 401; a Host header other than 127.0.0.1/localhost gets 403
  (DNS rebinding); only GET and HEAD (others 405), so there is no state-changing request to forge; CSP
  `default-src 'none'` (no scripts at all), no framing, no referrer, no caching; every value HTML-escaped and redacted.
  `ayesha research dashboard --check` runs 15 of these checks against a live instance. Do not share the printed link.
- **Integrity:** artifacts are content-addressed and re-hashed on every read; the registry has a hash-linked audit
  trail; backups are integrity-checked with a `.sha256` file; a restore refuses tampered or foreign files.
- **Supply chain:** no new dependency. `pip-audit` runs in `research-ci` as information; the `research-ci` workflow
  has `permissions: contents: read` and `persist-credentials: false` and uses no secret.
- **Data:** owner datasets, `research.db`, reports and logs stay on the PC; only synthetic test data is in the
  repository. See [RESEARCH_DATA_POLICY.md](RESEARCH_DATA_POLICY.md).

