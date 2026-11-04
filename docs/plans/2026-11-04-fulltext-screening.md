# Full-text Screening and Full PRISMA Implementation Plan (slice 2, sub-plan C)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Screen the works promoted at title/abstract against their full text with the slice-1 machinery (two independent passes, calibration, κ, disagreements, audit, verified quotes), citing anchors in a pinned converted document, and derive the full PRISMA 2020 flow.

**Architecture:** Slice 1 keeps one screening state. This plan adds a `stage` dimension (`title-abstract` | `full-text`) to passes, sessions, calibration, resolutions, audits and decisions. Every slice-1 service gains a keyword `stage` defaulting to `title-abstract`, so slice-1 behaviour and tests do not change. Full-text batches carry works with a converted document; the screener reads it through `document_read`, and `screen_record` verifies each quote against the cited anchor of the pinned conversion.

**Tech Stack:** as plans A and B2; no new dependencies.

**Spec:** `docs/specs/slice-2.md` (user flow 1 and 4; Verification, quote check; acceptance 4 and 13). `docs/specs/01-rigour.md` R-13–R-16, R-30–R-39 at the full-text stage. Decisions 37 and 46–49. Built on plan B2 (`document_read`, `resolve_anchor`, `quote_in_element`).

## Rulings made in this plan

1. **Stage namespace.** `ScreeningStage.TITLE_ABSTRACT` and `FULL_TEXT` are the stages of a run; `EITHER` is valid only on criteria. State is partitioned by stage; slice-1 events lack the field and read as `title-abstract`.
2. **Protocol.** `ProtocolSpec.full_text_screening: ScreeningPlan | None = None`, an amendable hashed field. When `None` it is left out of `protocol_version`, so every existing `P@` id is unchanged. Full-text screening is refused until it is declared (R-13). It reuses `ScreeningPlan` (passes, dual sample, κ floor, calibration size, audit fraction and minimum, reviewers).
3. **Population and pinning.** A work enters full-text screening when its title/abstract final outcome is `INCLUDED` and it has a converted live document. The batch pins that document's default conversion (`conversion_id`, B2 ruling 5); quotes are verified against exactly that conversion. A later document version never changes a recorded decision; `check` lists such decisions (warning). A promoted work without a converted document is not screened and is reported in PRISMA as sought, not retrieved.
4. **Calibration, agreement, audit** apply at the full-text stage with the decision-37 rules and thresholds unchanged (sensitivity ≥ 0.9 `pilot`, ≥ 0.95 `systematic`; audit size; ceiling). The full-text calibration set is drawn by the human's command from the eligible works and labelled by the human. *The researcher confirms this ruling at plan review; the alternative (no full-text calibration in `pilot`) would need a new decision.*
5. **Sessions.** A session's pass binding is per stage: independence rules (decision 37 items 1, 2, 6, 15) hold within a stage; a session that screened title/abstract may join a full-text pass. A session in a title/abstract pass still cannot read documents. A session in a full-text pass may read documents only of the works in its own pass queue (B2 gate extended).
6. **Quote rule at full text.** A decision cites `anchor` and `conversion_id`; the quote must occur verbatim, after the declared normalisation, in that anchor's element (B2 `quote_in_element`, never across blocks or cells). Title/abstract decisions carry neither field.
7. **Outcomes.** `final_outcomes(project, stage=FULL_TEXT)` is defined over the eligible works only. A work is *included in the review* when its full-text outcome is `INCLUDED`; PRISMA counts derive from the two stages, never typed.
8. **Out of scope:** extraction, comparability, evidence report (plans D, E); re-screening on a new document version (listed, not automated); full-text screening of works the researcher supplies outside the promoted set.

## Global Constraints

- All plan-A, B1, B2 constraints hold. No model calls. No document text in events other than the verified quote (which is already allowed in decision events).
- Slice-1 behaviour is unchanged: every slice-1 test passes without edits except where a task states a pinned-version change. A slice-1 event log replays to identical screening rows (stage `title-abstract`).
- Business logic in `services/`; `mcp/` and `cli/` parse and format.
- Coverage ≥ 90% for `services/` and `model/`; `mypy --strict` and ruff pass on changed files.

## Review Focus

1. A slice-1 event log (fixture from existing tests) rebuilt after this plan gives identical decisions, passes and PRISMA numbers, and the same `P@` ids (Tasks 1, 2).
2. A promoted work with no converted document never appears in a full-text batch and is counted as not retrieved (Tasks 4, 7).
3. A quote that is correct text but cited at the wrong anchor, spans two table cells or paragraphs, or cites an anchor missing from the pinned conversion is rejected, and valid items in the same batch are written (Task 5).
4. A full-text screener reads only documents of its own queue and never the other pass's verdicts; a title/abstract pass session reads no document (Task 6).
5. An amendment to a full-text-only criterion stales only full-text decisions citing it; a criterion applying at `either` stales both stages' decisions per the existing rules (Tasks 3, 5).

## File Structure

- Modify `model/screening.py`, `model/chase.py`, `model/protocol.py`: stage fields, decision anchor fields, protocol field and hash rule.
- Modify `index/screening.py`, `index/default.py`: stage columns, `PROJECTION_VERSION`.
- Modify `services/calibration.py`, `screening.py`, `agreement.py`, `audit.py`, `protocol_rules.py`, `check.py`, `methods.py`, `trace.py`, `prisma.py`, `fulltext_status.py` (as the tasks state).
- Create `services/fulltext_screening.py` (eligibility and pinned batches).
- Modify `services/document_read.py` (gate), `mcp/server.py`, `cli/main.py`, `cli/render.py`.
- Modify the plugin skill `rf-screen` (full-text mode) under the plugin directory used by `tests/test_skills.py`.
- Tests: `test_stage_model.py`, `test_stage_index.py`, `test_stage_services.py`, `test_fulltext_eligibility.py`, `test_fulltext_screen_record.py`, `test_document_read_gate.py`, `test_prisma_full.py`, `test_mcp_fulltext_screening.py`, `test_cli_fulltext_screening.py`, `test_acceptance_fulltext_screening.py`.

---

### Task 1: Stage in events, decision anchors, protocol field

**Files:** `model/screening.py`, `model/chase.py`, `model/protocol.py`; Test `tests/test_stage_model.py`.

**Interfaces:**
- Produces: `RunStage = Literal[ScreeningStage.TITLE_ABSTRACT, ScreeningStage.FULL_TEXT]` (a validator on each field below rejects `EITHER`); field `stage: ScreeningStage = ScreeningStage.TITLE_ABSTRACT` on `PassOpened`, `PassJoined`, `SampleExtended`, `CalibrationDrawn`, `CalibrationLabelled`, `DisagreementResolved`, `AuditSampled`, `AuditLabelled`; on `DecisionRecorded` the existing `stage` is checked the same way plus new fields `anchor: str | None = None` (`ANCHOR_RE` or cell form) and `conversion_id: str | None = None` (`CONVERSION_ID_RE`), required together exactly when `stage` is `full-text`; on `ScreeningItem` a field `anchor: str | None = None`; `ProtocolSpec.full_text_screening: ScreeningPlan | None = None` added to `AMENDABLE_FIELDS`; `protocol_version` and `section_digest` leave a `None` `full_text_screening` out of the hash.

- [ ] **Step 1: Tests.** `test_old_events_default_to_title_abstract` (validate a payload dict without `stage` for each event type); `test_either_is_not_a_run_stage`; `test_full_text_decision_needs_anchor_and_conversion` and `test_title_abstract_decision_forbids_them`; `test_protocol_version_unchanged_when_full_text_plan_absent` (pin a literal `P@…` computed from the current repo's fixture protocol before the change); `test_protocol_version_changes_when_plan_present`; `test_full_text_plan_validates_like_screening_plan` (passes, dual_sample range); `test_amendment_reports_full_text_screening_in_other_changes`.
- [ ] **Step 2:** Run; expect FAIL. **Step 3:** Implement. **Step 4:** Tests, `mypy --strict`, ruff pass; the whole existing suite still passes. **Step 5:** Commit `feat(screening): stage on events, full-text decision anchors, protocol plan`.

### Task 2: Projection of stage

**Files:** `index/screening.py`, `index/default.py`; Test `tests/test_stage_index.py`.

**Interfaces:**
- Produces: `stage` columns (default `'title-abstract'`) on `passes` (primary key becomes `(stage, pass_label)`), `pass_sessions` (key `(stage, session)`, columns kept), `calibration_items`, `calibration_labels`, `resolutions`, `audits`, `label_sessions` where they exist per stage; `decisions` gains `anchor` and `conversion_id`. Handlers take the stage from the payload. `PROJECTION_VERSION` bumped; update its single pin in `test_fulltext_index.py`.

- [ ] **Step 1: Tests.** `test_slice1_log_rebuilds_identically` (replay the screening events of an existing slice-1 fixture project; assert every row of the stage-bearing tables equals the pre-change rows plus `stage='title-abstract'`); `test_two_stages_do_not_collide` (same pass label, work and session in both stages give separate rows); `test_decision_anchor_projected`; `test_rebuild_state_hash_stable`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement; the primary-key change needs the projection rebuilt, which the version bump triggers. **Step 4:** Pass (index tests only). **Step 5:** Commit `feat(screening): project stage`.

### Task 3: Stage-aware slice-1 services

**Files:** `services/calibration.py`, `services/screening.py`, `services/agreement.py`, `services/audit.py`, `services/protocol_rules.py`, `services/check.py`, `services/methods.py`, `services/trace.py`; Test `tests/test_stage_services.py`.

**Interfaces:**
- Produces: keyword `stage: ScreeningStage = ScreeningStage.TITLE_ABSTRACT` on every public function that reads or writes pass, session, calibration, decision, agreement, resolution or audit state, including `open_pass`, `join_pass`, `screen_next`, `live_decisions`, `pass_b_sample`, `calibration_items`, `calibration_labels`, `calibration_status`, `draw_calibration`, `label_calibration`, `screen_agreement`, `resolve_disagreement`, `agreed_works`, `final_outcomes`, `exclusion_criteria`, `single_pass_works`, `pass_progress`, `audit` sampling and labelling, `is_pass_session`. Every SQL text query that touches a stage-bearing table filters on `stage`. `_criteria(protocol, label, stage)` serves criteria whose `applies_at` is the stage or `EITHER`. `TASK_KIND` becomes a function `task_kind(stage, label)`: `screen_a`/`screen_b` at title/abstract (unchanged), `screen_ft_a`/`screen_ft_b` at full text. `stale_decisions` already matches stages; its test is extended.
- Consumes: Task 2 columns.

- [ ] **Step 1: Tests.** The whole slice-1 suite is the regression gate (no edits). New: `test_stage_defaults_leave_slice1_unchanged` (call each function with and without `stage=TITLE_ABSTRACT`; equal results); `test_full_text_pass_state_is_separate` (open pass A at full text with a protocol that declares the plan; title/abstract `pass_progress` unchanged); `test_session_may_join_both_stages_but_not_both_passes_of_one_stage`; `test_agreement_refuses_shared_session_within_stage`; `test_full_text_amendment_stales_only_full_text_decisions` (Review Focus 5); `test_full_text_refused_without_declared_plan` (R-13).
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement by threading `stage`; no behaviour change at the default. **Step 4:** Full suite, `mypy --strict`, ruff pass. **Step 5:** Commit `feat(screening): stage-aware passes, calibration, agreement, audit`.

### Task 4: Eligibility and pinned full-text batches

**Files:** Create `services/fulltext_screening.py`; modify `services/screening.py` (`_enqueue`); Test `tests/test_fulltext_eligibility.py`.

**Interfaces:**
- Produces: `class EligibleWork(StrictModel)`: `work_id`, `document_id`, `conversion_id`; `class FulltextQueue(StrictModel)`: `eligible: list[EligibleWork]`, `not_retrieved: list[str]`; `fulltext_queue(project: Project) -> FulltextQueue` per rulings 3 and B2 ruling 5 (event-order default conversion), read-only. Full-text `ScreenBatchContent` gets `stage` (default `title-abstract`) and its `records` carry `{work_id, title, document_id, conversion_id}` for full text (no abstract needed; the screener reads the document through `document_read`); instructions for the full-text framings state the quote rule (cite the anchor, quote verbatim from it) instead of the title/abstract rule. `_enqueue` builds batches from `fulltext_queue` at the full-text stage and records the pinned `conversion_id` in each task's content.

- **Also (from the Task 3 review):** `sample_considered` and `sample_extensions` gain a `stage` column (key includes it; default `title-abstract`) with a `PROJECTION_VERSION` bump (update its single pin in `test_fulltext_index.py`). Pass B's full-text dual sample is drawn from the eligible works at open and extended whenever works become eligible later (a new `SampleExtended` with `stage=full-text`, exactly as at title/abstract), so documents that arrive or convert after pass B opens still enter the sample at the declared fraction. `_calibration_population(project, stage)` and `stage_population` now also require a converted live document at full text. `calibration._was_drawn` reads a per-stage flag from the projection instead of scanning the event log.
- [ ] **Step 1: Tests.** `test_eligible_are_promoted_with_a_converted_document`; `test_full_text_sample_extends_when_works_become_eligible`; `test_title_abstract_sample_tables_unchanged`; `test_promoted_without_conversion_is_not_retrieved` (Review Focus 2); `test_batch_pins_conversion_and_ignores_later_conversion` (convert again with a bumped converter version after enqueue; the task still names the first); `test_dual_sample_applies_at_full_text`; `test_ineligible_works_never_queued`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests pass. **Step 5:** Commit `feat(screening): full-text eligibility and pinned batches`.

### Task 5: Recording full-text decisions with anchor-verified quotes

**Files:** `services/screening.py` (`screen_record`, `_item_issues`); Test `tests/test_fulltext_screen_record.py`.

**Interfaces:**
- Consumes: B2 `resolve_anchor(project, conversion_id, anchor_id) -> Anchor`, `quote_in_element(element_markdown, quote) -> bool`.
- Produces: at the full-text stage `_item_issues` requires `anchor`, refuses an anchor absent from the task's pinned conversion for that work (`items.<i>.anchor`), refuses a quote not verbatim in that anchor's element (`items.<i>.quote`), and refuses a criterion whose `applies_at` is not `full-text`/`either`; the decision event stores `stage=FULL_TEXT`, `anchor` and the task's `conversion_id`. Each item is validated alone; valid items are written.

- [ ] **Step 1: Tests.** `test_valid_item_written_with_anchor_and_conversion`; `test_quote_at_wrong_anchor_rejected` (Review Focus 3); `test_quote_spanning_cells_rejected`; `test_anchor_missing_from_conversion_rejected`; `test_title_abstract_only_criterion_rejected_at_full_text`; `test_valid_items_survive_invalid_neighbours`; `test_exclude_still_names_ex_criterion_and_rationale`; `test_decision_supersedes_prior_in_same_pass_and_stage`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests pass. **Step 5:** Commit `feat(screening): anchor-verified full-text decisions`.

### Task 6: Document read gate for full-text screeners

**Files:** `services/document_read.py`, `mcp/server.py` (`document_read` gate); Test `tests/test_document_read_gate.py`.

**Interfaces:**
- Produces: `document_read` takes the caller's session; a session joined to a title/abstract pass is refused (unchanged); a session joined to a full-text pass is allowed only for a work in its own pass queue and only for the conversion pinned in a task it holds or has completed; any other session behaves as before. The MCP layer passes `project.session` and no longer calls the blanket `_refuse_pass_session` for this tool.

- [ ] **Step 1: Tests.** `test_ft_screener_reads_own_queue_pinned_conversion`; `test_ft_screener_refused_other_work` (Review Focus 4); `test_ft_screener_refused_other_conversion`; `test_ta_pass_session_refused`; `test_no_other_pass_verdicts_exposed`; `test_non_pass_session_unchanged`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement the check in the service (the MCP wrapper only passes the session). **Step 4:** Tests pass, including B2's `test_mcp_document.py`. **Step 5:** Commit `feat(document): full-text screeners read their own queue`.

### Task 7: Full PRISMA, status, check, trace

**Files:** `services/prisma.py`, `services/fulltext_status.py` (reuse), `services/check.py`, `services/trace.py`, `services/methods.py`, `cli/render.py`; Test `tests/test_prisma_full.py`.

**Interfaces:**
- Produces: `PrismaFlow` replaces `full_text: Literal[…]` with `full_text: FullTextBoxes`: `sought` (title/abstract included), `not_retrieved` (count and, per route, the latest reason counts), `assessed`, `excluded` (by criterion, `unspecified` for none), `pending`, `included` (full-text `INCLUDED`), `provisional`; `included` of the top level means included in the review when the full-text stage has run, else the title/abstract count marked provisional. `check` adds `fulltext-decision-stale-document` (warning) for a decision whose pinned conversion is not the work's current default. `trace` returns, for a full-text decision, the anchor, conversion, document, attempt, work and criteria chain. `methods_report` states the full-text plan and sessions. All numbers are computed.

- [ ] **Step 1: Tests.** `test_boxes_sum_and_are_derived` (sought = not retrieved + assessed + pending; assessed = included + excluded); `test_not_retrieved_has_route_reasons`; `test_slice1_flow_unchanged_before_full_text_runs`; `test_check_lists_stale_document_decision`; `test_trace_full_text_decision_chain`; `test_methods_mentions_full_text_plan`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests pass. **Step 5:** Commit `feat(report): full PRISMA with full-text boxes`.

### Task 8: Tools, commands and skill

**Files:** `mcp/server.py`, `cli/main.py`, `cli/render.py`, plugin skill `rf-screen`; Tests `tests/test_mcp_fulltext_screening.py`, `tests/test_cli_fulltext_screening.py`, `tests/test_skills.py` (extend).

**Interfaces:**
- Produces: MCP `screen_next(project, role, model, skill, pass_label, stage="title-abstract")` and `screen_record(..., items)` where an item may carry `anchor`; `screen_agreement`, `audit_sample`, `calibration_label` and the CLI commands `factory calibration|agreement|audit|resolve` take `--stage` (default `title-abstract`); `factory status` shows per-stage progress. The `rf-screen` skill gains a full-text section: read the document with `document_read` for the pinned `conversion_id`, quote verbatim from one anchor, cite it, never rely on outside knowledge, same verdict rules.

- [ ] **Step 1: Tests.** MCP: full-text `screen_next` serves a pinned batch; `screen_record` writes an anchored decision; an unknown stage value returns a structured error and writes nothing; tool list pinned with no new tools. CLI: full-text calibration draw/label, agreement, resolve and audit run with `--stage full-text`; default behaviour unchanged. Skills test: the full-text section exists and names `document_read` and the quote rule.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement (skill text by a Sonnet implementer; concise, no marketing language). **Step 4:** Tests pass. **Step 5:** Commit `feat(screening): full-text stage over MCP and CLI; rf-screen full-text mode`.

### Task 9: Acceptance and docs

**Files:** Test `tests/test_acceptance_fulltext_screening.py`; modify `docs/specs/slice-2.md` ("Implemented in plan 2C"), `CLAUDE.md` status.

- [ ] **Step 1: Tests (acceptance 4 and 13).** `test_two_passes_to_agreement_at_full_text` (calibrate, two sessions, κ, one disagreement resolved by the human, audit sample); `test_unverifiable_quote_rejected_valid_written` (acceptance 4); `test_prisma_full_text_boxes_from_events` (acceptance 13); `test_rebuild_matches` (state hash and PRISMA after rebuild equal); `test_slice1_acceptance_still_passes` (existing slice-1 acceptance tests unchanged).
- [ ] **Step 2:** Run; fix until PASS. **Step 3:** Docs. **Step 4:** Full suite, mypy, ruff. **Step 5:** Commit `test(screening): plan 2C acceptance; docs`.

## Self-review notes

- Spec coverage: user flow 4, acceptance 4 and 13, R-13 (declared plan), R-30–R-39 at full text (Tasks 3–5), the read gate B2 deferred (Task 6). Extraction, comparability and the evidence report belong to plans D and E.
- Types: `RunStage`, `task_kind(stage, label)`, `EligibleWork.conversion_id` and the decision `anchor`/`conversion_id` fields are used with the same names in Tasks 1–8.
- Risk: Tasks 2 and 3 touch the slice-1 core; their regression gate is the unchanged slice-1 suite. Tier: Tasks 1–6 are critical (screening, protocol, events, index) and get Sonnet task reviews.
