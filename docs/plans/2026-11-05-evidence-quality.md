# Evidence Quality Implementation Plan (backlog triage, plan EQ)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Proposed 2026-11-05 (backlog triage, `2026-11-05-backlog-triage.md`).** Items marked [confirm] await the researcher.

> **Dependencies.** Base `d66387f` or later. Task 6's tools land after MS, which owns the tail of `mcp/server.py`; Tasks 1 to 5, 7 and 8 do not wait. Paths are relative to `platform/` unless they start with `plugin/`.

**Goal:** Per-paper appraisal with a declared instrument (IDEA-21, R-41), the check of copied results against their source (IDEA-23), and admitted miners reaching the evidence report (iterate line 89b).

**Basis:** None of these exists: no `appraisal` symbol in `services/`, `model/`, `mcp/` or `cli/`, and `check.py:1991` flags undeclared copies but compares no value. Decisions 42 item 2 (typed items, judgement by a human, no overall score), 44 (deferred out of slice 2, design kept), 41, 51, 57, 91; R-13, R-41, R-45, R-51. Spec text: `docs/specs/slice-2.md` "Appraisal". `evidence: true` admits a miner, but `services/modules/evidence.py` reads `BuilderReads(miners=())`, so its rows reach no group.

**Projection:** Tasks 1 and 3 bump `PROJECTION_VERSION` (one each, from the value found). Tasks 2, 4 to 8 do not.

## Proposed decision (number fixed at merge)

**PD-6. Appraisal rides on the extraction machinery [confirm].** Options: (a) a third extraction scope beside evidence and contribution, as G2-B added contributions (`ScopeKey`, shared passes, agreement, audit, staleness); (b) a registered miner per instrument; (c) a separate service. **Recommended: (a).** Item-level answers with verified quotes are what the scope already does; (b) would need calibration before a protocol may count it (decision 57), which an instrument item does not call for; (c) would copy the queue. Items typed `judgement` never enter a task: a human records them.

**First instruments [confirm].** Recommended: one built-in `ml-evidence-v1`, from the NeurIPS checklist (reference M14), since the pilot corpus is the researcher's and may be ML. PROBAST and RoB 2 are data, added when a biomedical project declares them; a project may declare its own items. AACODS waits for plan SG.

**Required when.** R-41 is `S (P: grey only)`. A protocol without the section is complete in `exploratory` and `pilot`; `systematic` gets a `check` gap, not a refusal, as with other promotion gaps.

## Rulings made in this plan

1. **Item kinds.** `platform`: computed by a named rule from a fixed menu (`code-url-present`, `dataset-named`, `seeds-reported`, `hardware-reported`, each a deterministic pattern over the conversion). `agent-span`: `yes|no|unclear` with a verified quote in one anchor; `unclear` needs no quote. `judgement`: `yes|no|unclear` from a human, with a rationale, shown the agent-span answers of the same work.
2. **No overall score (decision 42).** No total, weight, grade or sort by quality exists in any output.
3. **Reports show, never filter.** The evidence report gains an optional per-work appraisal column. Nothing is dropped by it. A sensitivity view is Later.

## Global Constraints

- The instrument is hashed, declared before appraisal starts (R-13, R-45), and amended like `extraction_schema`, omitted from `P@` while absent, so existing ids are unchanged.
- Dual pass and audit rates follow the schema's sampling fields. Staleness on document or instrument change follows the extraction rules.
- Every new event type, task kind, protocol section and check code is declared in `services/modules/appraisal.py` in the same task.

## Review Focus

1. No output carries an aggregate of items (scan the renderers and JSON).
2. An agent cannot write a `judgement` item, through any route, on rebuild too.
3. A project without the section has unchanged hashes and outputs.

## File Structure

Create `model/appraisal.py`, `index/appraisal.py`, `services/appraisal.py`, `services/modules/appraisal.py`, `packs/ml_evidence_appraisal.py`, `services/copied_check.py`, `plugin/skills/rf-appraise/SKILL.md`. Modify `model/protocol.py`, `model/extraction.py`, `services/protocol_rules.py`, `services/extraction.py`, `services/document_read.py`, `services/check.py`, `services/methods.py`, `services/evidence_report.py`, `services/modules/evidence.py`, `services/trace.py`, `cli/main.py`, `cli/render.py`, `mcp/server.py`, `index/default.py`, `events/catalog.py`.

### Task 1: Instrument and protocol section

*Tier: critical (hashing). Bumps the projection.*

**Interfaces:** `AppraisalItem(id, statement, kind, rule | None, applies_to)`, `AppraisalInstrument(name, version, items, dual_sample, audit_fraction, audit_minimum)`; section `appraisal_instrument` in `ProtocolSpec`, `_OMITTED_WHEN_NONE`, the digest; `ScopeKey` value `appraisal`; tables `appraisal_answers`, `appraisal_judgements`. Gaps: duplicate ids, an unknown rule, `dual_sample` out of range; a `check` gap in `systematic` when absent.

- [ ] **Step 1:** Implement, bump. **Step 2:** Commit `feat(appraisal): instrument as a hashed protocol section`.

**Tests (later):** `P@` unchanged without the section; amendable; each gap.

### Task 2: Platform items

*Tier: standard.*

**Interfaces:** `PLATFORM_RULES: Mapping[str, Callable[[Manifest], PlatformAnswer]]`; `platform_answers(project, work_id) -> list[…]`, computed on read, never stored, with the anchor of the matching text. Nothing is a judgement: a pattern reports presence only.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(appraisal): computed platform items`.

**Tests (later):** each rule on fixtures; determinism; absent reads `not-found`, never `no`.

### Task 3: Agent items

*Tier: critical (passes, quotes). Bumps the projection.*

**Interfaces:** task kinds `appraise_a`, `appraise_b`; `appraisal_next(project, pass_label, *, actor)`, `appraisal_record(project, task_id, items, *, actor, finish, reason)`, following `contribution_next` and `contribution_record`. Events `appraisal.recorded`. Agreement by item, disagreement to a human (`factory appraisal resolve`). Population: works included at the last declared stage with a conversion. Audit by `extraction_audit`'s pattern.

- [ ] **Step 1:** Implement, bump. **Step 2:** Commit `feat(appraisal): dual agent passes over span items`.

**Tests (later):** unverified quote refused; `unclear` needs none; pass independence with evidence passes (decision 37); stale on a new conversion; forged events.

### Task 4: Judgement items

*Tier: standard.*

**Interfaces:** `appraisal_sheet(project, work_id)` (agent answers beside each judgement item); `record_judgement(project, actor, work_id, item, answer, *, rationale)`, human only; CLI `factory appraisal judge WORK ITEM yes|no|unclear --rationale R`, `factory appraisal status|sheet|agreement|resolve|audit-sample|audit-label`.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(appraisal): human judgement items`.

**Tests (later):** agent refused; supersession; a human may change an answer and the first stays in the log.

### Task 5: Report, check, trace, methods

*Tier: standard.*

**Interfaces:** `appraisal_report(project) -> AppraisalReport` (work by item matrix, no totals). `report evidence --with-appraisal`. Check `appraisal-open`, `appraisal-unjudged`, `appraisal-stale`. Trace kind `app_` to anchor, conversion, document. Methods: instrument, version, items by kind, dual rate.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(appraisal): report, check, trace and methods`.

**Tests (later):** review focus 1; goldens without the section; agent view withholds nothing beyond its existing rules.

### Task 6: MCP and skill

*Tier: light. After MS.*

**Interfaces:** MCP `appraisal_next`, `appraisal_record`, `appraisal_status`; skill `rf-appraise`. Reading follows the `document_read` gate for passes.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(appraisal): tools and skill`.

**Tests (later):** pin list; pass rules.

### Task 7: Consistency of copied results (IDEA-23)

*Tier: standard.*

**Interfaces:** `services/copied_check.py::copied_mismatches(project) -> list[CopiedMismatch(row, cited_work, source_row | None, status)]`. For each final copied row with a `cited_work` in the corpus, find the cited work's own final row with identical comparability keys and method. `status`: `match`, `differs` (beyond the tolerance of `finders`), `version-differs` (the cited work's pinned conversion is a later version than the citing paper could have read, by date), `no-source-row`. Check `copied-value-differs` (warning in every mode). Shown in `report evidence` as a flag, never as a correction. The copied row stays the citing paper's statement.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(evidence): compare copied results with their source`.

**Tests (later):** each status; a copied row never becomes independent; tolerance as finders.

### Task 8: Admitted miners reach the report

*Tier: critical (R-45). Iterate line 89b.*

**Interfaces:** `services/modules/evidence.py` declares `BuilderReads` from the protocol's admitted miners. `report_inputs` adds rows of a miner with `evidence: true` when its fields map to the schema's keys, grouped only within identical comparability keys and labelled with miner name and version. Any other admitted miner is listed under a separate heading, as rows with no group. `miner-version-unread` then clears.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(evidence): admitted miners feed the report`.

**Tests (later):** no group mixes keys; exploratory miner rows absent; report golden without miners.

## Self-review notes

- Decision 44 deferred appraisal "out of slice 2", kept the design, and said "when a project needs it". The triage asks the researcher whether the pilot needs it (R11).
- IDEA-08 (citation-gap check) names per-paper assessment as its condition and stays parked: see the triage.

## Later (not v1)

- Sensitivity view by appraisal item, once a project asks for one.
- More built-in instruments.
