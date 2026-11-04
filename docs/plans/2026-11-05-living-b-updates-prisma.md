# Screening Updates, Snapshots and the PRISMA Update Flow Implementation Plan (slice 4b, sub-plan living-B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: draft — rulings recommended; awaiting the researcher's review before any build.**

> **Dependencies.** Plan living-A merged (cycles, `CycleHook`, `cycles`, `watch_status`). Slice 4a (candidate inbox, discovery record, `inbox.prioritised`) merged **or not**: Task 1 has two branches, chosen at build time; both produce the same Interfaces. Living-C may run in parallel with this plan; living-D consumes `snapshot`, `SnapshotBlob` and `prisma_update`.

**Goal:** Works found by a watch reach the declared screening passes with dual-coding, calibration and audit preserved across updates; a living review records snapshots that delimit its updates, and reports a computed PRISMA flow per update besides the cumulative flow.

**Architecture:** A `CycleHook` (`extend_sample_hook`) records pass B's sample extension after each cycle through the existing `_extend_sample`. The audit gains a top-up draw restricted to decisions agreed since the last draw. Snapshots are system events whose blob (`SnapshotBlob`, schema 1) holds the computed cumulative PRISMA flow and a slot for conclusion facts that living-D fills. `services/prisma_update.py` computes the update flow from event order relative to snapshot cut-offs. Watch-related `check` findings are added to `services/check.py` through one new hit collector.

**Tech Stack:** as living-A; no new dependency.

**Spec:** `docs/specs/slice-4b-living-corpus.md` rulings 6, 8, 9, 10, 17, 19, 21, 22; acceptance 7, 8, 14.

## Rulings made in this plan

1. **First identification of a work for update counting.** A canonical work belongs to the update in which its earliest `search.records_parsed` event (over all of its records, including absorbed ones) lies, by event id, after the previous snapshot's `cutoff_event` and at or before the current cut-off. Duplicates removed in an update are records of that update whose canonical work belongs to an earlier update or to the same update with a different record id. [confirm]
2. **Update boxes.** `UpdateFlow`: `previous_included` (from the previous snapshot blob, `included_in_review` if set else `included`), `identified_databases`, `identified_other` (both by source/method, update records only), `duplicates_removed`, `screened`, `excluded` (by criterion), `pending`, `included`, `full_text` (as `FullTextBoxes`, update works only), `total_included` (current `included_in_review` or `included`). Identities: as `PrismaFlow`, over update works. `total_included` need not equal `previous_included + included` (a notice exclusion or an amendment may change earlier works); the difference is reported as `changed_previous` with the work ids. [confirm]
3. **Snapshot triggers.** `factory living snapshot` (human), and the cycle hook `snapshot_hook` when `watch_plan.snapshot_every` cycles have finished since the last snapshot (system). A snapshot is refused while a watch cycle is open. [confirm]
4. **Audit top-up population.** Decisions agreed (both passes, or resolved) with an agreement or resolution event after the last `audit.sampled` of the stage; size = `max(0, audit_size(N_total) − already_sampled)`, drawn with the decision-37 3:1 weighting over the new population only, seed recorded. `audit.sampled` gains `top_up_of: str | None = None` (the previous audit id); absent on every existing event. [confirm]
5. **Model drift.** "Calibrated models of a pass" = the `actor.model` values of `calibration.*` decisions recorded by sessions of that pass under the current protocol lineage since the last criterion-changing amendment. [confirm]

## Global Constraints

- As living-A. No screening outcome is written by this plan. No agent can record a priority hint (human act).
- Every number in `UpdateFlow`, `SnapshotBlob` and the findings is computed; tests recompute them from events.
- The agent view of `prisma_update` follows decision 43 (refused to pass sessions; held-out recall never included).
- `uv run pytest -m "not network and not slow"`, `mypy --strict`, ruff pass; coverage ≥ 90 %.

## Review Focus

1. Watch works enter pass B's sample by the recorded seed and nothing else changes in pass A or B (Task 2, `test_watch_works_extend_pass_b_sample`).
2. The audit top-up never redraws a sampled work and draws only newly agreed decisions (Task 3, `test_top_up_draws_only_new_agreements`).
3. Update-flow identities hold and its boxes recompute from events (Task 5, `test_update_flow_identities`).
4. The snapshot blob is byte-identical across rebuilds for the same events and clock (Task 4, `test_snapshot_blob_deterministic`).
5. A `systematic` join with an uncalibrated model is refused; in `pilot` it is a warning only (Task 6, `test_model_drift_by_mode`).

## File Structure

- Create `services/inbox_watch.py` (Task 1 fallback branch only: `inbox_entries`, `prioritise`; model `InboxPrioritised` in `model/inbox.py`) or modify slice 4a's inbox service to register route `watch` (4a branch).
- Modify `services/screening.py` (priority ordering in `screen_next` queue; public `extend_sample(project, actor, *, stage) -> tuple[str, ...]` wrapping `_extend_sample` and recording), `services/audit.py`, `model/screening.py` (`AuditSampled.top_up_of`), `index/screening.py`.
- Create `model/living.py` (`SnapshotRecorded`, `SnapshotBlob`, `SNP_ID_RE`), `services/snapshots.py`, `index/living.py`, `services/prisma_update.py`.
- Modify `services/prisma.py` (`search_report` rows carry `cycle_id`), `services/check.py` (collector `_living`), `services/calibration.py` (calibrated models), `services/screening.py` (`_check_join` drift rule).
- Modify `cli/main.py` (`living snapshot`, `living prisma-update`, `report prisma --update SNAPSHOT|last`, `inbox prioritise` in the fallback), `mcp/server.py` (`report_prisma(update: str | None)`).
- Tests: `test_inbox_watch.py`, `test_watch_screening.py`, `test_audit_top_up.py`, `test_snapshots.py`, `test_prisma_update.py`, `test_check_living.py`, `test_model_drift.py`.

---

### Task 1: Watch route in the candidate inbox

*Tier: standard.*

**Files (4a branch):** modify 4a's inbox service to accept route `watch` whose reference is the `wcy_` id of the cycle in which the work's first record was parsed. **Files (fallback branch):** Create `model/inbox.py`, `services/inbox_watch.py`; Modify `events/catalog.py`, `index/living.py`. Test `tests/test_inbox_watch.py`.

**Interfaces (both branches):**
- `class InboxEntry(StrictModel): work_id: str; route: str; route_ref: str; surfaced_at: str (event id); priority: int | None`.
- `def inbox_entries(project: Project, *, route: str | None = None, limit: int = 100, after: str | None = None) -> list[InboxEntry]` — pending works at title/abstract (`final_outcomes`), ordered by priority (desc, `None` last) then `surfaced_at`; paginated.
- `def prioritise(project: Project, actor: Actor, work_id: str, priority: int, rationale: str) -> str` — human only; writes `inbox.prioritised` (event id returned); refused for a non-pending work.
- `screen_next` serves pending works by the same order within a batch draw; the draw stays randomised within equal priority (R-34 randomised order holds within a priority level).

- [ ] **Step 1: Tests.** `test_watch_work_listed_with_cycle_ref`, `test_included_work_leaves_inbox`, `test_priority_orders_entries`, `test_agent_cannot_prioritise` (agent actor refused, nothing written), `test_priority_does_not_change_outcome`, `test_order_random_within_priority` (two seeds give different orders inside a level).
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_inbox_watch.py tests/test_screening*.py -q`.
- [ ] **Step 5: Commit** `feat(living): watch route in the candidate inbox`.

### Task 2: Sample extension after each cycle

*Tier: critical (screening independence).*

**Files:** Modify `services/screening.py` (public `extend_sample`), create `services/living_hooks.py` (`extend_sample_hook`, `snapshot_hook`; registered in the default hook list used by `cli` and `mcp` callers of `watch_run`); Test `tests/test_watch_screening.py`.

**Interfaces:**
- Consumes: `_extend_sample(project, actor, *, random_seed, stage)`, `pass_b_sample`, `CycleHook`.
- Produces: `def extend_sample(project: Project, actor: Actor, *, stage: ScreeningStage = TA, random_seed: int | None = None) -> tuple[str, ...]` (records the event when one is returned); `def extend_sample_hook(project: Project, cycle_id: str, new_work_ids: tuple[str, ...]) -> tuple[str, ...]` (a living-A `CycleHook`, returns `()`; system actor; `random_seed` derived as `int(sha256(cycle_id)[:8], 16)` so the draw is reproducible and recorded).

- [ ] **Step 1: Tests.** `test_watch_works_extend_pass_b_sample` (fraction 0.3 over 200 new works: the added set equals `in_dual_sample` recomputation with the recorded seed), `test_no_extension_when_pass_b_covers_all`, `test_existing_sessions_receive_watch_works`, `test_calibration_not_required_again_after_cycle`, `test_new_session_joins_existing_pass_under_decision_37`.
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_watch_screening.py tests/test_screening*.py tests/test_calibration.py -q`.
- [ ] **Step 5: Commit** `feat(living): pass B sample extension for watch works`.

### Task 3: Audit top-up per update

*Tier: critical (audit record).*

**Files:** Modify `model/screening.py` (`AuditSampled.top_up_of: str | None = None`), `services/audit.py` (`audit_sample(..., top_up: bool = False)`; `audit_outstanding` reports `top-up-due`), `index/screening.py`; Test `tests/test_audit_top_up.py`.

**Interfaces:**
- `def audit_sample(project, actor, *, random_seed=None, stage=TA, top_up: bool = False) -> AuditSampled` — with `top_up`, refused when no previous audit exists of the stage, when the previous audit has unlabelled items, or when the shortfall is 0; otherwise draws ruling 4's population. Without `top_up`, behaviour unchanged.
- `def audit_shortfall(project: Project, *, stage: ScreeningStage = TA) -> int` (computed, used by `check`).

- [ ] **Step 1: Tests.** `test_top_up_draws_only_new_agreements`, `test_top_up_size_meets_recomputed_rule` (N grows from 2,000 to 3,000 → total sampled = `audit_size(3000)`), `test_top_up_keeps_3_to_1_weighting`, `test_top_up_refused_without_previous_audit`, `test_legacy_audit_events_project_unchanged`, `test_error_rate_over_all_labels` (the reported rate pools both draws, weighted by stratum as today).
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_audit*.py -q`.
- [ ] **Step 5: Commit** `feat(living): audit top-up for living updates`.

### Task 4: Snapshots

*Tier: standard.*

**Files:** Create `model/living.py`, `services/snapshots.py`, `index/living.py` (table `snapshots`); Modify `events/catalog.py`, `services/living_hooks.py` (`snapshot_hook`); Test `tests/test_snapshots.py`.

**Interfaces:**
- `class SnapshotBlob(StrictModel): schema_version: Literal[1] = 1; protocol_id: str; cutoff_event: str; prisma: PrismaFlow; included_ids: tuple[str, ...]; conclusion_facts: JsonValue | None = None; conclusions: JsonValue | None = None` — the two `JsonValue` slots are typed by living-D (`ConclusionFacts`, per-conclusion states) and stay `None` until it lands.
- `class SnapshotRecorded(StrictModel): snapshot_id: str; cutoff_event: str; protocol_id: str; blob: str; projection_version: str; trigger: Literal["human", "cycle"]`.
- `def snapshot(project: Project, actor: Actor, *, trigger: Literal["human", "cycle"], extra: Sequence[SnapshotSection] = ()) -> SnapshotRecorded` — refused while a cycle is open; `SnapshotSection = Callable[[Project], tuple[str, JsonValue]]` fills the slots (living-D registers its section); `cutoff_event` = the last event id in the log at the time of the lock.
- `def snapshots(project: Project) -> list[SnapshotRecorded]`; `def snapshot_blob(project: Project, snapshot_id: str) -> SnapshotBlob`.

- [ ] **Step 1: Tests.** `test_snapshot_records_prisma_and_included`, `test_snapshot_refused_while_cycle_open`, `test_snapshot_blob_deterministic` (rebuild + same `FixedClock` → same blob hash), `test_snapshot_hook_every_n_cycles`, `test_agent_cannot_snapshot` (MCP has no snapshot tool; service refuses agent actors).
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_snapshots.py -q`.
- [ ] **Step 5: Commit** `feat(living): review snapshots`.

### Task 5: PRISMA update flow and cycle rows in PRISMA-S

*Tier: critical (reported counts).*

**Files:** Create `services/prisma_update.py`; Modify `services/prisma.py` (`SearchReportRow.runs` items gain `cycle_id: str | None`), `cli/main.py`, `cli/render.py`, `mcp/server.py`; Test `tests/test_prisma_update.py`.

**Interfaces:**
- `class UpdateFlow(StrictModel)` (ruling 2 fields) with an `_identities_hold` validator mirroring `PrismaFlow`.
- `def prisma_update(project: Project, *, since: str | None = None, until: str | None = None) -> UpdateFlow` — `since`/`until` are snapshot ids; `since=None` means the last snapshot, `until=None` means now (provisional when pending > 0).
- `def update_work_ids(project: Project, since_event: str | None, until_event: str | None) -> tuple[set[str], int]` (canonical works of the update and the update's duplicate record count; indexed query on `search_records` by event id range, no full load).

- [ ] **Step 1: Tests.** `test_update_flow_counts_only_update_records`, `test_update_flow_identities`, `test_duplicate_of_earlier_work_counted_in_update_duplicates`, `test_previous_included_from_snapshot_blob`, `test_changed_previous_lists_works` (a notice-excluded or re-screened earlier work), `test_cumulative_equals_prisma_flow`, `test_search_report_rows_carry_cycle_ids`, `test_mcp_prisma_update_refused_to_pass_session`.
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_prisma*.py -q`.
- [ ] **Step 5: Commit** `feat(living): PRISMA update flow`.

### Task 6: Living findings in `check` and model drift

*Tier: standard.*

**Files:** Modify `services/check.py` (`_living(project) -> list[_Hit]`), `services/calibration.py` (`calibrated_models(project, label, stage) -> set[str]`), `services/screening.py` (`_check_join`); Test `tests/test_check_living.py`, `tests/test_model_drift.py`.

**Interfaces:** findings `watch-plan-missing`, `watch-overdue` (now > next_due + interval), `watch-source-failing` (`consecutive_failures >= max_consecutive_failures`), `watch-cycle-open`, `window-misses` (last full replay `window_missed > 0`; advisory), `update-audit-outstanding` (`audit_shortfall > 0` after a cycle; warning in pilot, error in systematic), `calibration-model-drift`. Severities by mode via the existing `_severity`. Join refusal in `systematic` with issue `("model", "not calibrated for this pass")`.

- [ ] **Step 1: Tests.** One constructed case per finding (`test_finding_<name>`), `test_findings_carry_no_document_text`, `test_model_drift_by_mode`, `test_check_promote_to_pilot_lists_watch_plan_gap`.
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_check*.py tests/test_model_drift.py -q`.
- [ ] **Step 5: Commit** `feat(living): watch findings and calibration model drift`.

## Verification

`uv run pytest -m "not network and not slow" -q && uv run mypy --strict src && uv run ruff check src tests` from `platform/`.

## Self-review notes

- The 4a branch and the fallback branch expose the same `inbox_entries`/`prioritise` signatures; the fallback's `inbox.prioritised` event type is the one 4a is asked to adopt (stated in the slice spec, open question 5).
- `AuditSampled.top_up_of` defaults to `None`, so existing audit events validate and project unchanged.
