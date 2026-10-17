# Model and strategy governance (research plane)

Who may decide what. Applies to every research strategy, regime label and (later) machine-learning model. Source:
plan §0, §2.4, §6.2, §8 and §16 in [HYBRID_AI_MASTER_PLAN.md](HYBRID_AI_MASTER_PLAN.md).

**Release 1.1.0 contains no machine-learning model and no LLM.** The research strategies are the frozen legacy
baseline `baseline-sweep-mss-fvg` (A), the control `control-london-orb` (B) and the one experimental strategy
`experimental-h1h4-trend` (C), all replayed on frozen data. None of them is validated; there is no trading edge yet.
1.1.0 adds one deterministic regime detector (`regime-h4-er-slope-vol` 1.0.0, rules, not a learned model) whose
labels are context only, and historical news from licensed frozen snapshots; news direction is never backtested.

## 1. Authority

1. **READY comes only from the legacy scanner** (`desktop/ayesha/scanner.py`) after the hard risk, news, capital and
   READY guards. That path is unchanged and protected by the golden fixture (T06).
2. No research strategy, regime label, ML prediction or language model can be a READY source, open a risk/news/capital
   gate, override `NO_TRADE`, change a lot or a risk percentage, or send anything to the phone.
3. Nothing in AYESHA places, modifies or closes orders. Research cannot import the phone delivery, signing, capital
   or credential code either (isolation check in CI).
4. Research output is labelled `RESEARCH`, `executable: false`, and is shown as **RESEARCH ONLY / HYPOTHETICAL**. It
   never uses the word READY.

## 2. Locks enforced in code (0.9.0, extended in 1.0.0 and 1.1.0)

| Lock | Where | Effect if someone edits it |
|---|---|---|
| `role: RESEARCH_ONLY`, `promotion_enabled: false`, `live_scanner_hooks_enabled: false`, `ml_enabled: false`, `allow_outbound_model_inference: false`, `report_redact_secrets: true`, `dashboard_bind: 127.0.0.1`, `legacy_only_fallback: true` | `const` in `contracts/research/research-config.schema.json` | The config is invalid and research refuses to run; `ayesha research disable` still works and resets the file (`test_safety_locks_cannot_be_loosened`, `test_disable_always_works_even_with_a_broken_settings_file`) |
| A research decision is never READY | CHECK constraint on `research_decisions.proposed_state` (`HYPOTHETICAL_CLOSED`, `BLOCKED`, `NOT_FILLED`, `INVALIDATED`, `UNRESOLVED`) | Insert fails (`test_a_research_decision_can_never_be_ready`) |
| A candidate is never executable | `research.candidate/1`: `source_type: RESEARCH`, `executable: false`, `proposed_state` without READY, no `safe_to_alert_for_entry` field | Validation fails (`test_research_candidate_can_never_be_ready_or_executable`) |
| Strategies are research-only | `research.strategy/1`: `research_only: true`, `execution_level: NONE`; `strategy_definitions.status` can only be `RESEARCH_ONLY` | Validation or insert fails (`test_strategy_manifest_must_be_research_only`) |
| No silent strategy change | A strategy id and version are bound to one hash and parameter hash | A changed hash needs a new version (`test_strategy_hash_collision_needs_a_new_version`) |
| No READY in research code | The isolation check flags the value `"READY"` in any module under `ayesha/research/` | CI fails (`test_isolation_check_catches_violations`) |
| Exactly the registered strategies, exactly one experimental | `strategies/loader.py` registry: duplicate ids or a second `EXPERIMENTAL` stop every load; parameters outside their registered bounds, unknown parameters and any parameter for the baseline are refused | `StrategyError`, the run is refused (`test_registry_has_baseline_control_and_exactly_one_experimental`, `test_parameters_are_bounded_and_change_the_hash`) |
| Research signals look nothing like live ones | ids `rs` + hash of strategy, version, pair, time, direction, entry; grade `RESEARCH`; no score | `test_research_signal_ids_cannot_collide_with_live_ids` |
| A comparison never promotes | `research.comparison/1`: `executable: false`, ranking only `NO_RANKING` or `IN_SAMPLE_ORDER_ONLY`; refused unless dataset, symbols, split, holdout state, costs and account are identical | `test_comparison_refuses_different_inputs` |
| The holdout is looked at on purpose | Results after `--holdout` are only computed with `--reveal-holdout`, a separate run recorded as `HOLDOUT_REVEALED` in the audit trail | `test_revealing_the_holdout_is_a_new_audited_run` |
| A regime label is never a gate (1.1.0) | The runner records the label known at decision time on the order (`LabTrade.regime`) and nowhere reads it to block, allow or size; labels come from closed H4 bars only and are never rewritten; the detector has a version and a code hash in every result | `test_regime_labels_are_causal`, `test_lab_orders_carry_the_regime_known_at_decision` |
| News only from a licensed, frozen source (1.1.0) | `research news-ingest` refuses a file without a provider or licence statement; REJECTED snapshots cannot be loaded; an unknown snapshot id is `BLOCKED_BY_DATA`; replays see the calendar only through the point-in-time `AsOfCalendar` | `test_news_snapshot_needs_a_licence_and_is_content_addressed`, `test_news_snapshot_integrity_decisions` |
| Comparisons on the same news and regime inputs (1.1.0) | `research.comparison/1` also requires the same `news_snapshot_id`, `news_mode` and `regime_detector` | `test_lab_with_a_snapshot_compares_news_modes` |

## 3. Strategy registration (v1.0.0 onwards)

Every strategy carries a `research.strategy/1` manifest: id, explanation, timeframes, symbols, parameters with their
bounds, dependencies, lookback, statefulness, version and hash, `kind` (`BASELINE`, `CONTROL`, `EXPERIMENTAL`), news
and cost sources, `research_only: true`, `execution_level: NONE`. The hash covers the version, the parameters and the
strategy's source file, so editing the code without a new version is visible. Rules:

- Only built-in modules from the repository are loaded; arbitrary Python files are not plugins (a plugin is not a
  security sandbox).
- One experiment cannot change another's parameters or write to `contracts/strategy-spec.yaml`. The live strategy
  (0.4.0, hash `9bb5e8ed5937`) changes only through a separate owner-approved release with its own tests.
- All strategies in a comparison use the same frozen dataset, split and cost model; small samples are labelled
  (`SMALL_SAMPLE` below 100 closed trades) and never ranked as winners.
- A strategy that looks best in hindsight does not become live. See section 5.
- Changing a rule or a default of B or C means a new version and a new hash; old runs keep their old id. Adding a
  second experimental strategy (plan Experimental D) is a new milestone, not an edit.

### Regime detector (v1.1.0 onwards)

- The thresholds of `regime-h4-er-slope-vol` were pre-registered before any real data was seen (DECISIONS.md,
  2026-10-17). Changing a threshold, a window or a rule means a new detector version; it is never tuned to make a
  strategy look better in a regime.
- A regime cell with fewer than 30 closed trades is `INSUFFICIENT_SAMPLE`. No strategy is ranked, chosen or switched
  on by regime, and a strategy that looks good in one regime in hindsight does not become live (section 5).

## 4. Machine learning (v1.2.0, optional, only with enough validated real data)

Not built. When it is, these rules apply (plan §8):

- **Lifecycle:** `DRAFT` → `TRAINED` → `BACKTESTED` → `OOS_REVIEWED` → `PAPER_OBSERVATION` → `REVIEW_ELIGIBLE`.
  Any failed drift, data or safety check moves a model to `SUSPENDED`, and research falls back to rule-only output.
  `REVIEW_ELIGIBLE` is the furthest state: it is not live permission (`research.model_card/1`, reserved).
- **Training:** target and features frozen before the holdout is looked at; time-ordered splits with purge and
  embargo, never shuffled K-fold; features computed as of each decision; macro actuals only after publication; a final
  holdout that is never tuned on; comparison with rule-only baselines under the same costs; the dataset hash, code
  commit, dependency versions, seed and artifact hash recorded in a model card.
- **Small samples:** few signals means no ML release (`INSUFFICIENT_EVIDENCE`). A good-looking metric from a few dozen
  trades is not an edge.
- **No self-learning live model.** Nothing retrains or activates itself. A retrained model is a new version and goes
  through the lifecycle again.
- **Drift** (feed freshness, spread, missing bars, regime mix, feature and label distributions, calibration) disables
  the experimental output. It never raises a lot or a risk percentage.
- **Isolation:** training and prediction run in the research worker, with no access to credentials, Exness capital
  files or live signal writes. No outside model service is called (`allow_outbound_model_inference: false`).
- **Language models**, if ever used, may only summarise structured evidence that already exists; they cannot create
  levels, probabilities or gates.

## 5. Promotion to live advice

Not possible in 0.9.0, 1.0.0 or 1.1.0 (`promotion_enabled` is locked off). Any future link from research to the live
advisory path needs all of:

1. a separate written change specification approved by the owner;
2. the evidence listed in [RESEARCH_ACCEPTANCE.md](RESEARCH_ACCEPTANCE.md) section 5 (real multi-year data,
   untouched out-of-sample, after-cost results, owner-confirmed Exness values, at least 30 trading days of forward
   observation);
3. an explicit strategy id, version and hash, and the owner's recorded approval;
4. integration **behind** the existing hard risk, news, capital and READY guards, which stay the authority;
5. new tests, a compatible protocol version and a tested rollback.

## 6. Owner approvals and audit

Approvals only ever change research states. Every change in the research registry is written to `research_events`, a
hash-linked audit trail; editing or deleting a row is detected (`test_audit_chain_detects_edits_and_deletions`,
`ayesha research doctor`). Nothing is promoted, enabled or retrained automatically.
