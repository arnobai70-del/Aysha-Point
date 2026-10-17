# Research data policy (research plane, releases 0.9.0 to 1.1.0)

Applies to everything under `ayesha research …` and `%AYESHA_HOME%\research\` (default
`%USERPROFILE%\AyeshaFX\research\`). Research is **off by default** and research-only: it never produces READY, never
sends anything to the phone and never places orders. The live scanner does not read any research file.

## 1. Allowed sources

| Source | How | Licence note written into the manifest |
|---|---|---|
| OANDA v20 **practice** | `ayesha research ingest --provider oanda --pairs EURUSD --days 730`. Uses the legacy read-only adapter `ayesha.feed.oanda_feed.OandaFeed` (GET candles, `price=BA`, complete bars only) with the token `install.bat` saved on this PC. The live environment is refused | "OANDA v20 practice API data downloaded with the owner's own token for personal, non-commercial research on this PC; not for redistribution (see OANDA's API terms)" |
| Owner CSV files | `ayesha research ingest --from-csv-dir FOLDER`. Files named `<PAIR>_M15.csv` / `<PAIR>_M5.csv` in the legacy format written by `ayesha export` and `backtest-local.bat` | "Owner-supplied file; its licence is whatever its source allows (not verified by AYESHA)". The owner is responsible for having the right to use it |
| Owner historical news calendar (1.1.0) | `ayesha research news-ingest --csv FILE --provider NAME --license "..."`. The legacy calendar CSV format that `ayesha report --news` takes (`time_utc,currency,impact,title`, optional `forecast`, `actual`, `actual_published_utc`, `observed_utc` and the other legacy columns) | The owner's own licence statement, written into the snapshot manifest as given. No provider or no licence statement: the file is not imported. AYESHA does not verify the licence; the owner is responsible for having the right to use it |

Not allowed: scraping web pages or TradingView, unlicensed feeds, getting around rate limits, CAPTCHAs or anti-bot
measures, and any Exness login. OANDA requests are paced (at least 0.2 s apart), transient errors are retried with
exponential backoff, and HTTP 401/403 stops at once with a message that contains no secret.

**News history:** no historical calendar is bundled or downloaded. From 1.1.0 the owner can freeze one they are
allowed to use as a news snapshot (`research.news-snapshot/1`, id `ns_` + the first 16 hex characters of the raw
file's SHA-256): the raw bytes are kept as received and an integrity report decides **PASS**, **DEGRADED** (rows
without `observed_utc`, so the schedule is the file's final view and not what was known at the time
(`SCHEDULE_NOT_POINT_IN_TIME`), or actuals without a publication time, which are then never shown; usable,
labelled on every result) or **REJECTED** (missing required columns, does not parse or has no events, unknown currency or impact;
never used). Replays read a snapshot only
through the legacy point-in-time view: a row appears after its `observed_utc`, an actual only after its
`actual_published_utc`. News direction (actual vs forecast) is never backtested (`NEWS DIRECTION NOT BACKTESTED`).
Without a snapshot every result carries `NEWS_NOT_MODELLED`, a warning that the live news gate would block some
setups, and the news comparison is `BLOCKED_BY_DATA`. No licensed historical calendar has been supplied yet.

**Capital and credentials:** research never reads `capital.json`, `broker-confirmed.json` or the pairing code, and
cannot import the capital, signing, delivery or credential modules (the isolation check in CI forbids it). The only
credential involved is the OANDA token, which the legacy feed adapter reads at download time and sends only to OANDA.
Equity figures in research reports ($20 to $5,000) are hypothetical scenarios, never the owner's Exness equity, and
the OANDA practice balance is never used as capital.

## 2. What is stored and where

```
%AYESHA_HOME%\research\
  config.yaml      research settings (research only)
  research.db      research registry (separate SQLite file, own migrations, hash-linked audit trail)
  raw\             exactly what was received (CSV bytes; OANDA response bodies with request path and receipt time)
  normalized\      research.market_bar/1 rows (JSON Lines), one file per symbol and timeframe
  quality\         research.quality_report/1, one per partition
  manifests\       one write-once research.dataset_manifest/1 per dataset
  runs\ candidates\ exports\   run results, research candidates, exported reports (also comparisons, news
                   snapshot manifests *.news.json and feed audits *.feed-audit.json; raw news CSVs are in raw\)
  backups\         rotating verified registry backups (pre-restore copies in backups\pre-restore\)
  logs\            redacted worker logs
  jobs\            worker job and result files
```

- Every artifact is named by the SHA-256 of its content and stored gzip-compressed with no time or name in the gzip
  header, so the same content always gives the same bytes. Every read re-checks the hash; a mismatch raises
  `IntegrityError` and the file is never used.
- Writes go to a temporary file in the same folder, are flushed and fsync'd, then renamed. A crash leaves the old
  state or the complete new file, never half a file.
- A manifest is written once and never changed. New provider data gives a **new dataset**; an existing dataset is
  never overwritten. Importing identical raw data again is recognised (`DATASET_ALREADY_PRESENT`) and not stored twice.
- `dataset_id` = `ds_` + the first 16 hex characters of the hash over the normalised partitions. Because the observed
  time is part of each normalised row (section 3), the same CSV imported at a different time is a different dataset.

## 3. Field honesty

- **BID OHLC** is what both sources provide. **ASK:** OANDA gives the ASK close only, so the spread is
  `ask close − bid close` (`ASK_CLOSE_MINUS_BID_CLOSE`); ASK high and low are unknown and are never invented. CSV
  imports have no ASK at all; their spread is the export's whole-point value at bar close (`CSV_WHOLE_POINTS`).
- **Observed time** (when the bar became known) is kept apart from the bar time. OANDA: the time the provider
  response arrived (`PROVIDER_RESPONSE_TIME`). CSV: the import time (`IMPORT_TIME`), because the original delivery
  time is unknown. A bar that was not closed when it was observed is rejected (`INCOMPLETE_BAR`).
- Nothing is forward-filled, repaired, interpolated or synthesised. A broken row is counted in the quality report with
  its line number; the raw artifact keeps everything as received.
- Prices are the data provider's, not Exness's (`PRICES_NOT_EXNESS`). Exness quotes and spreads differ; feed parity
  with Exness is `UNVERIFIED` until measured on matching real observations. From 1.1.0 `ayesha research feed-audit
  --a DS1 --b DS2 --symbol EURUSD` measures two datasets of the same pair bar by bar (overlap, missing bars each
  side, OHLC and spread differences in pips) with fixed thresholds: `MATCHED` (at least 500 common bars, close
  difference p95 ≤ 1.0 pip and max ≤ 5.0 pips, at most 2 % missing), `DIFFERENT` or `INSUFFICIENT_OVERLAP`. Neither
  feed is the broker's truth; Exness parity stays `UNVERIFIED` unless one side is an Exness export of the same pair
  and the audit says `MATCHED`. No Exness export has been audited yet.

## 4. Quality gate

Expected bars follow the FX week (Sunday 17:00 to Friday 17:00 New York time, IANA zones so DST is handled), skip the
daily rollover minutes and treat 25 December and 1 January as closed.

| Severity | Codes | Decision |
|---|---|---|
| HIGH | `MISSING_COLUMN`, `NO_ROWS`, `PARSE_ERROR`, `NON_FINITE_PRICE`, `NON_POSITIVE_PRICE`, `OHLC_INCONSISTENT`, `NEGATIVE_SPREAD`, `NON_FINITE_SPREAD`, `NEGATIVE_VOLUME`, `BID_ABOVE_ASK`, `DUPLICATE_CONFLICT`, `MISALIGNED_TIMESTAMP`, `FUTURE_BAR`, `INCOMPLETE_BAR` | **REJECTED**: kept for inspection only; every run refuses it |
| MEDIUM | `DUPLICATE_IDENTICAL`, `OUT_OF_ORDER_SORTED`, `GAP_OVER_POLICY`, `COVERAGE_BELOW_POLICY`, `STALE_RUN` | **DEGRADED**: a run needs `--allow-degraded` and its result is labelled `DEGRADED_INPUT_DATA` |
| INFO | `SPREAD_UNKNOWN`, `ZERO_SPREAD`, `ASK_UNKNOWN`, `BAR_OUTSIDE_MARKET_HOURS` | recorded, decision unchanged |

A dataset takes the worst state of its partitions. Policy values live in `config.yaml` under `research.quality`:
`max_gap_bars: 8`, `min_coverage_percent: 98.0`, `stale_run_bars: 6`. They are research defaults set before any real
data was seen; they are never tuned to make a result look better. Each quality report lists the original time range,
time zone handling, coverage percent, missing bars by session, issue counts with examples, and the raw and normalised
hashes.

## 5. Privacy and secrets

- The OANDA token stays in the Windows user environment where `install.bat` put it. It is never in a research file,
  job file, log, manifest, report or the registry: the raw artifact keeps response bodies and request paths, never
  headers. Tested by `test_oanda_ingest_keeps_ask_close_and_never_writes_the_token` and
  `test_research_files_never_hold_the_token_or_pairing_code`.
- Worker logs, job records, dashboard pages and exports pass through `ayesha.research.redact`: Bearer headers,
  OANDA-token shapes, pairing codes, `key=value` secrets and Windows/Unix user names are replaced
  (`test_worker_logs_and_records_are_redacted`, `test_values_are_escaped_and_redacted`).
- The dashboard's live-scanner view shows states, times and counts only; lot sizes and money amounts are replaced by
  `[amount hidden]` (`test_live_registry_view_is_read_only_and_hides_money`).
- **Nothing private goes to GitHub.** Owner datasets, `research.db`, reports and logs stay on the PC. The repository
  only holds synthetic test data generated by code (`desktop/tests/research/synth.py`) and the synthetic golden
  fixture. Before posting an exported report anywhere public, read it: it is redacted, but it is the owner's research.

## 6. Retention, backup and deletion

- Nothing is deleted automatically except older research backups: `ayesha research backup` (or
  `backup-research.bat`) keeps the newest `backup_keep` (default 7) files named `research-*.db` in `backups\` and
  never touches anything else. Legacy files (`ayesha.db`, `capital.json`, journal, pairing) are never deleted or
  rotated by research.
- A backup uses the SQLite online backup API, passes `PRAGMA integrity_check`, is one self-contained file and has a
  `.sha256` file next to it. `ayesha research restore FILE` checks the hash and integrity, refuses a file that is not a
  research registry, saves the current registry to `backups\pre-restore\` first, and asks you to type `RESTORE`.
- To remove research completely: `ayesha research disable`, then delete the `research` folder by hand. The live
  scanner is not affected (it never reads that folder).
