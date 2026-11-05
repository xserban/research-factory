# Agent-Authored Miners: Lifecycle, Calibration and Evidence Admission Implementation Plan (slice M, sub-plan M-D)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Implemented 2026-11-05 (branch `md`, built unattended).** Rulings added in the build are decision 91 (Proposed); minors are in `docs/backlog-iterate.md` (lines "M-D"). Two deviations from the text below: a calibration unit is never a production unit (not only "until scored"), and the acceptance world has twelve works (five calibrated, seven mined), not thirty.

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** Task 2 bumps `PROJECTION_VERSION` by one from the value it finds. Task 7's acceptance uses the pilot-shaped synthetic fixture of `tests/miner_helpers.py`, not pilot data; it stays in v1.

> **Dependencies.** Plans M-A, M-B and M-C merged (consumes `register_miner`, `registered_miner`, `require_listed`, `mine_next`, `mine_record`, `MineBatchContent.calibration_id`, `population`, `compile_miner`, `kind_checks`, `MinerUse`, `require_gate`, `effective_policy`, `audit_core.*`, `passes.memberships`, `quality.stats.draw_uniform`). Plan M-E consumes the lifecycle state and calibration reports.

**Goal:** Let an agent propose a miner and run it, under IDEA-37's rules: registered before its first task, exploratory until a human-labelled calibration sample passes declared thresholds above platform floors, proposer never evaluator, failed and retired miners kept and reported; and let a protocol admit a calibrated miner as evidence by amendment.

**Architecture:** Lifecycle state is computed from events (`miner.registered`, `miner.calibration_drawn`, `miner.calibration_labelled`, calibration-pass rows, `miner.retired`); nothing stores a state. Calibration reuses the mine path: calibration tasks are ordinary `mine_a` tasks restricted to the drawn units and tagged with the calibration id; gold records are verified exactly as agent records. Scoring is a pure function over gold and calibration rows.

**Tech Stack:** as M-A; no new dependencies.

**Spec:** `docs/specs/slice-M-modules.md` rulings 15–17; gate `miner.calibration_label`, `mine.resolve`; events `miner.calibration_drawn`, `miner.calibration_labelled`, `miner.retired`; check findings `miner-*`; acceptance 11, 12. R-51, R-52; R-141, R-142.

## Rulings made in this plan

1. **Proposer identity is the registering session [confirm].** The proposer of a miner is `(actor.kind, actor.session)` of its first `miner.registered`. A human-registered miner has a human proposer; R-51 then bars that human's session only from the agent calibration pass, which no human runs anyway.
2. **Calibration units are drawn from the selector population minus units already mined by a production pass [confirm].** Otherwise a production run could have seen (and a resolution could have fixed) the very units being calibrated. Draw: `draw_uniform` over the population keys, recorded seed and population digest; size `max(regime.calibration_size, floor(mode))`, floors 5 (pilot) and 10 (systematic), none in exploratory, capped at the population.
3. **Gold records are recorded as rows, through the same verifier [confirm].** `miner_calibrate_label` takes the same row shape as `mine_record`; a gold row that fails verification is refused (the human must quote correctly too). A unit with no record is labelled `empty` explicitly.
4. **Scores [confirm].** Record recall = matched gold rows ÷ gold rows (match by `pack_row_key`); field agreement = equal normalised values ÷ compared fields over matched rows (plan D's `_same` rule via `field_disagreements`); verification rate = verified rows ÷ submitted rows of the calibration pass. `calibrated` iff recall ≥ max(`recall_min`, floor) and field agreement ≥ max(`field_agreement_min`, floor); floors 0.8/0.9 (pilot), 0.9/0.95 (systematic), none (exploratory). Precision (extra agent rows ÷ agent rows) is reported, never gated, as specificity in R-31.
5. **One calibration per miner version per protocol lineage, retry by new version [confirm].** A failed miner is not recalibrated; the proposer registers a new version (decision 37 item 14 pattern: the screener does not retry). Amending the miner's `MinerUse` does not reset calibration; a new version does.

## Global Constraints

- All M-A to M-C constraints hold. New event types: `miner.calibration_drawn`, `miner.calibration_labelled`, `miner.retired` (schema 1). `PROJECTION_VERSION` bumps once (Task 2).
- Calibration rows never enter `final_rows`, agreement or audit of the production run (they are filtered by `calibration_id` on the task).
- Agents never see gold rows, scores or thresholds; refusals and `mine_status` give counts only (decision 43 pattern).

## Review Focus

1. The proposer's session cannot claim a calibration task, label, resolve, or relay the calibration report (Task 4, `test_proposer_is_not_evaluator`).
2. Calibration rows are invisible to the production run and vice versa (Task 4, `test_calibration_rows_separate`).
3. Scores are computed, never typed; a single mutation of a gold value moves the score (Task 5).
4. `evidence: true` is refused for an uncalibrated miner and allowed after passing (Task 6).

## File Structure

- Modify `model/miners.py`, `index/miners.py`, `events/catalog.py`, `index/default.py`, `services/mining.py`, `services/protocol_rules.py`, `services/protocol.py` (readiness context), `services/modules/mining.py`, `services/methods.py`, `services/evidence_report.py` (builder reads declaration only), `mcp/server.py`, `cli/main.py`, `cli/render.py`.
- Create `src/factory/services/miners.py` (lifecycle, calibration), `src/factory/mining/score.py` (pure scoring).
- Tests: `tests/test_miner_lifecycle.py`, `tests/test_miner_calibration_draw.py`, `tests/test_miner_gold.py`, `tests/test_miner_calibration_pass.py`, `tests/test_miner_score.py`, `tests/test_miner_evidence.py`, `tests/test_acceptance_miners.py` (marked `slow`).

---

### Task 1: Lifecycle state and retirement

*Tier: critical (R-52).*

**Files:** Create `services/miners.py`; Modify `model/miners.py`, `events/catalog.py`; Test `tests/test_miner_lifecycle.py`.

**Interfaces:**
- Produces: `MinerRetired(name, version, reason: str (1..300))`; `MinerState(StrEnum)`: `REGISTERED`, `CALIBRATING`, `CALIBRATED`, `FAILED`, `RETIRED`; `@dataclass(frozen=True) MinerProposer(kind: ActorKind, session: str)`; `miner_state(project, name, version) -> MinerState`; `proposer(project, name, version) -> MinerProposer`; `retire_miner(project, actor, name, version, reason) -> None` (refused for built-in miners; a retired miner's `mine_next` is refused on field `miner`; its rows stay).

- [ ] **Step 1: Tests.** `test_state_registered_after_registration`; `test_retire_from_any_state`; `test_retired_miner_refuses_tasks_keeps_rows`; `test_built_in_cannot_retire`; `test_proposer_is_first_registration`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement (state computed from events; `CALIBRATING`/`CALIBRATED`/`FAILED` stubs return `REGISTERED` until Tasks 2 and 5). **Step 4:** mypy; ruff. **Step 5:** Commit `feat(miners): lifecycle state and retirement`.

### Task 2: Calibration draw

*Tier: critical (sampling; recorded randomness).*

**Files:** Modify `model/miners.py`, `index/miners.py`, `index/default.py`, `services/miners.py`; Test `tests/test_miner_calibration_draw.py`.

**Interfaces:**
- Consumes: `population`, `audit_core.validate_seed`, `AuditPopulation`, `draw_uniform`.
- Produces: `MinerCalibrationDrawn(calibration_id: str (mcl_<ULID>), name, version, digest, units: tuple[CalibrationUnit, ...], random_seed, population, population_digest, protocol_id)`, `CalibrationUnit(work_id, conversion_id)`; tables `miner_calibrations`, `miner_calibration_units`; `draw_miner_calibration(project, actor, name, version, *, random_seed=None) -> MinerCalibrationDrawn` (human only; ruling 2; refused when a calibration of this version exists, when the miner is retired, or when the population is empty); `PROJECTION_VERSION` bump.

- [ ] **Step 1: Tests.** `test_size_respects_floor_by_mode`; `test_units_exclude_production_mined_units`; `test_seed_reproduces_draw`; `test_second_draw_refused`; `test_agent_cannot_draw`; `test_rebuild_determinism`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** mypy; ruff. **Step 5:** Commit `feat(miners): calibration sample draw`.

### Task 3: Gold labels

*Tier: critical (answer key; human gate).*

**Files:** Modify `model/miners.py`, `index/miners.py`, `services/miners.py`, `cli/main.py`, `mcp/server.py`; Test `tests/test_miner_gold.py`.

**Interfaces:**
- Consumes: `require_gate(project, actor, "miner.calibration_label", channel=…)`, `compile_miner`, `kind_checks`, plan-D `verify_row_in`.
- Produces: `MinerCalibrationLabelled(calibration_id, work_id, rows: tuple[StoredRow, ...], empty: bool, channel: Channel)` (verified fields as `extraction.recorded` stores them; validator: `empty` iff `rows == ()`); `label_miner_calibration(project, actor, calibration_id, work_id, rows, *, empty=False, channel) -> str`; a later label for the same unit supersedes (latest wins, earlier kept); CLI `factory miner calibrate label <calibration_id> <work_id> rows.json|--empty`; MCP relay `miner_calibration_label` (human actor, refused to pass sessions and to the proposer's session).

- [ ] **Step 1: Tests.** `test_gold_row_verified_like_agent_row` (a misquoted gold value refused with the verifier's reason); `test_agent_cannot_label`; `test_proposer_session_cannot_relay`; `test_pass_session_cannot_relay`; `test_unit_outside_sample_refused`; `test_relabel_supersedes`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** mypy; ruff. **Step 5:** Commit `feat(miners): human gold labels for calibration`.

### Task 4: Calibration pass on the mine path

*Tier: critical (independence, R-51).*

**Files:** Modify `services/mining.py`, `services/miners.py`, `services/extraction.py` (task filter by `calibration_id`); Test `tests/test_miner_calibration_pass.py`.

**Interfaces:**
- Produces: `mine_next(..., calibration: bool = False)`; with `calibration=True` the pass serves only the drawn units of the miner's open calibration, tasks carry `MineBatchContent.calibration_id`, the label is always `A`; refused (field `session`) to the proposer's session, to any session that relayed a gold label, and to any session that joined a production pass of this miner; production `mine_next` skips calibration units until the calibration is scored; plan-D reads (`live_rows`, `final_rows`, agreement, audit, staleness) take `calibration: bool = False` and filter on it.

- [ ] **Step 1: Tests.** `test_proposer_is_not_evaluator` (claim, record, resolve, relay; each refused, nothing written); `test_calibration_rows_separate` (production `final_rows` unchanged by calibration rows; calibration reads unchanged by production rows); `test_calibration_serves_only_drawn_units`; `test_production_skips_calibration_units_until_scored`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Mine-path and plan-D suites unedited; mypy; ruff. **Step 5:** Commit `feat(miners): calibration pass with proposer exclusion`.

### Task 5: Scoring and state

*Tier: critical (computed rates, R-05).*

**Files:** Create `mining/score.py`; Modify `services/miners.py`, `services/modules/mining.py` (checks); Test `tests/test_miner_score.py`.

**Interfaces:**
- Consumes: plan-D `field_disagreements`, `pack_row_key`.
- Produces (pure): `@dataclass(frozen=True) CalibrationScore(gold_rows, agent_rows, matched, recall: float | None, field_agreement: float | None, precision: float | None, verification_rate: float | None)`; `score(gold: Mapping[str, Sequence[StoredRow]], agent: Mapping[str, Sequence[StoredRow]], pack: Pack) -> CalibrationScore` (ruling 4). Produces (service): `MinerCalibrationReport(calibration_id, units, labelled, closed, score: CalibrationScore | None, thresholds: tuple[float, float], passed: bool | None)`; `miner_calibration_report(project, name, version) -> MinerCalibrationReport | None` (score only when every unit is labelled and closed); `miner_state` now returns `CALIBRATING`, `CALIBRATED` or `FAILED`; checks `miner-calibration-failed` (warning ×3), `miner-uncalibrated-evidence` (error ×3).

- [ ] **Step 1: Tests.** `test_perfect_agent_scores_one`; `test_missing_row_lowers_recall`; `test_value_mismatch_lowers_agreement`; `test_extra_row_lowers_precision_only`; `test_floor_overrides_lower_declared_threshold`; `test_score_withheld_until_complete`; `test_state_failed_below_threshold`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** mypy; ruff; coverage. **Step 5:** Commit `feat(miners): calibration scores and miner state`.

### Task 6: Evidence admission, `mine.resolve` policy, builder versions, methods

*Tier: critical (evidence status).*

**Files:** Modify `services/protocol_rules.py`, `services/protocol.py`, `services/mining.py`, `services/modules/mining.py`, `services/modules/evidence.py`, `services/methods.py`; Test `tests/test_miner_evidence.py`.

**Interfaces:**
- Produces: protocol readiness context gains `calibrated: frozenset[tuple[str, int]]`; `MinerUse.evidence = True` is an error unless `(name, version)` is calibrated in this project (spec ruling 20: an imported calibration does not count); `resolve_extraction` on a miner scope accepts an agent under `agent_audit`/`agent` effective policy of `mine.resolve` (M-B), never the proposer's session, never a session of either pass; `BuilderReads(miners: tuple[tuple[str, int], ...])` declared on builder modules (`evidence` reads `()` registered miners); check `miner-version-unread` (warning ×3) for rows of a registered miner version no builder declares; methods section listing each registered miner with state, proposer kind, calibration score (CLI only; withheld from the agent view), evidence flag, and failed or retired miners (R-52).

- [ ] **Step 1: Tests.** `test_evidence_true_refused_until_calibrated`; `test_evidence_true_allowed_after_pass_by_amendment` (amendment touches `other_changes` only; no screening decision stale); `test_agent_resolution_under_exploratory_preset_is_audited_agent`; `test_proposer_cannot_resolve`; `test_methods_lists_failed_and_retired`; `test_agent_methods_withhold_scores`; `test_version_unread_finding`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Full suite; mypy; ruff. **Step 5:** Commit `feat(miners): evidence admission after calibration; methods`.

### Task 7: Acceptance: an agent-authored miner end to end (slow)

*Tier: standard (implementer sonnet, review opus: acceptance).*

**Files:** Create `tests/test_acceptance_miners.py` (marked `slow`).

- [ ] **Step 1: Test** `test_vision_result_miner_end_to_end`: pilot project from `tests/miner_helpers.py` with 30 included works and hand-written conversions; agent session P registers `m-vision-result@1` (`task` enum, `resolution` number, `evidence` quote); human amends the protocol to list it; human draws calibration (5 units) and labels gold; agent session C (not P) runs the calibration pass; score passes; human amends `evidence: true`; sessions A and B run production passes; human resolves; human audits; `check` shows no `miner-*` error; methods shows the miner, its score and proposer kind. A second variant registers `m-vision-result@2` with a deliberately wrong unit family, fails calibration, is retired, and appears in methods as failed and retired.
- [ ] **Step 2:** Run `uv run pytest -m slow tests/test_acceptance_miners.py`; FAIL until Tasks 1–6 are in. **Step 3:** Fix what the acceptance finds (each fix with its own unit test). **Step 4:** Full suite incl. `slow`; mypy; ruff. **Step 5:** Commit `test(miners): agent-authored miner acceptance`.

## Self-review notes

- **Spec coverage.** Ruling 15 (M-C Task 6, here Task 6 for evidence), 16 (Tasks 1–5), 17 (Task 6); acceptance 11 (M-C), 12 (Tasks 4–7).
- **Types used later.** `MinerState`, `miner_state`, `proposer`, `MinerCalibrationReport`, `miner_calibration_report`, `CalibrationScore`, `BuilderReads`.
- **Tiers.** Tasks 1–6 critical; Task 7 standard with Opus review.

## Later (not v1)

None: every task of this plan is in v1.
