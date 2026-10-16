# Release and rollback (research plane, release 0.9.0)

Release 0.9.0 adds the research plane next to the 0.8.0 advisory path. It changes no legacy behaviour (golden
fixture T06), publishes no new APK and needs no phone update. Rollback therefore means **turning research off**;
going back to older code is only for the unexpected case and needs the owner's approval. Every step below is tested
(T10) unless it says otherwise.

## What 0.9.0 changes and what it does not

| Part | 0.9.0 |
|---|---|
| Scanner, risk, news, capital, rules, storage, feeds, backtest, delivery, signing | unchanged, byte-identical (protected files in the golden fixture) |
| `strategy-spec.yaml` (0.4.0, hash `9bb5e8ed5937`), `signal.schema.json` (1.1), wire format 4, Pine file | unchanged |
| `install.bat`, `start-ayesha.bat`, `backtest-local.bat`, `run-scanner.bat`, `make-signing-key.bat` | unchanged |
| Android app | unchanged; stays [android-v0.5.0-b9](https://github.com/arnobai70-del/Aysha-Point/releases/tag/android-v0.5.0-b9). `build-android` no longer runs for research-only files |
| `cli.py` | one new subcommand, `ayesha research …`, imported only when used |
| New | `desktop/ayesha/research/`, `contracts/research/`, `start-research.bat`, `backup-research.bat`, `research-ci` workflow, docs |
| Versions | release 0.9.0, desktop 0.9.0, research contracts 1 (`contracts/version.json`) |
| Owner data | research files only under `%AYESHA_HOME%\research\`, created only after `ayesha research enable` |

## Level 1: turn research off (no reinstall, nothing lost)

1. Close the research dashboard window (or press Ctrl+C in it). If a research job is running, closing its window ends
   the worker too (Windows job object with kill-on-close); the next research command marks the job and any
   half-finished run as failed. Nothing partial is ever used.
2. In the `desktop` folder: `python -m ayesha.cli research disable`. Research is now `legacy_only`: `ingest`, `run`
   and `parity` are refused; the read-only commands (`status`, `doctor`, `datasets`, `inspect`, `runs`, `report`,
   `dashboard`) and `backup`, `restore`, `selftest` still work. The files under `research\` stay exactly as they were.
3. Start the scanner as always: `desktop\windows\start-ayesha.bat`. It never depended on research.

To come back later: `python -m ayesha.cli research enable`. All datasets and runs are still there.
Tested by `test_cli_end_to_end_then_t10_rollback`, `test_disable_always_works_even_with_a_broken_settings_file`,
`scripts/research_smoke.py` and `scripts/windows_research_tests.ps1`.

## Level 2: the research registry is damaged

Symptoms: `ayesha research doctor` shows FAIL for the registry or the audit trail. The scanner is not affected.

1. Pick the newest backup in `%AYESHA_HOME%\research\backups\` (`research-<time>.db`, each with a `.sha256` file).
   A new backup of a damaged registry is refused, because every backup must pass the integrity check.
2. `python -m ayesha.cli research restore <backup file>` and type `RESTORE`. The file is checked (hash, integrity,
   research schema) before anything changes; the current registry is first saved to `backups\pre-restore\`, so a
   restore can itself be undone.
3. `python -m ayesha.cli research doctor --deep` re-checks the registry, the audit trail and every artifact hash.

Datasets and run results are content-addressed files; a restore never deletes them. Nothing is deleted
automatically except older research backups beyond `backup_keep` (default 7).

## Level 3: go back to the 0.8.0 code (only with the owner's approval)

Not expected to be needed: with research off, 0.9.0 behaves exactly like 0.8.0. If the owner still wants the old code:

- **On the PC** (the code comes as a GitHub ZIP): unzip each version into its own folder and keep the old one, e.g.
  `C:\AYESHA-0.8.0` and `C:\AYESHA-0.9.0`. To go back, start `desktop\windows\start-ayesha.bat` from the old folder;
  the .bat files run the code of the folder they are in. `%AYESHA_HOME%` (capital, broker values, pairing, journal,
  signal registry) is shared and untouched; 0.8.0 simply ignores the `research` folder. Run the old folder's
  `install.bat` again only if you want the old version for command-prompt use too (it keeps your earlier answers).
- **On GitHub** (after a merge): revert with a new pull request (`git revert -m 1 <merge commit>`), reviewed like any
  change. 0.8.0 is commit `7e7da2e`.

## Never part of a rollback

- No force-push, no history rewrite on `main`.
- No deleting or "cleaning" `ayesha.db`, the journal, `capital.json`, `broker-confirmed.json` or the pairing code.
- No new pairing code and no phone reinstall: the phone app is not involved.
- No start of `build-android` by hand for research changes (without the owner's signing secrets it would publish an
  APK with a new debug signer, which forces an uninstall).

## Release evidence for 0.9.0

| Item | Where |
|---|---|
| Baseline before any change | CP-00 audit report; golden fixture commit `33f9342` |
| Tests | `ci` and `research-ci` on Ubuntu and Windows for the PR head; [RESEARCH_ACCEPTANCE.md](RESEARCH_ACCEPTANCE.md) |
| Component versions | `contracts/version.json` |
| Safety scans | order API, secrets, workflows, Pine check, research isolation (all in CI) |
| Merge | only after the owner approves the pull request |
