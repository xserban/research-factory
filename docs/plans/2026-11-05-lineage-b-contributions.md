# Contribution Recording, `cited_entry` Check, Agreement and Audit Implementation Plan (slice 3b, sub-plan G2-B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: ready — rulings adopted 2026-11-04; depends on G1 (slice 3a) being built.** G1 ruling 14 is adopted as option (b): events carry parsed fields and `entry_sha256`, no raw entry text, and `reference_entries` has no text column. Entries are served to the agent as anchor, label and parsed fields only (`EntryBrief`); the agent reads an entry's text through `document_read` at its `b<n>` anchor.

> **Dependencies.** G2-A merged (its Interfaces blocks are consumed exactly); G1 merged (tables `reference_extractions`, `reference_entries`, `reference_links`, `citation_contexts`; `LinkState`, `Confidence`, `REX_ID_RE`; `current_extraction`, `included_works`). Plan D's `ml-benchmark` rows exist only where the project declares an evidence schema; `result_row` is then checked against them.

**Goal:** Let Claude record contribution items (base idea, addition, result, limitation, `not-stated`) from a pinned conversion, with the platform verifying quotes, numbers, cited reference entries and markers, and run dual extraction, agreement, human resolution and audit for them through the generalised plan-D machinery.

**Architecture:** `services/contributions.py` is a thin parameterisation of plan D: it calls `next_unit` / `record_unit` with `scope=CONTRIBUTION`, a `ContentHook` that attaches the work's reference entries and an `ExtraCheck` / `CloseCheck` that apply the contribution-specific rules. G1 reads go through one module, `services/reference_view.py`; the marker rule is a pure helper in `factory/lineage/cited.py`. Agreement and audit are plan-D services called with `scope=CONTRIBUTION`.

**Tech Stack:** as plan D; no new dependencies.

**Spec:** `docs/specs/slice-3b-lineage.md` User flow 2–3; rulings 7, 8, 9; Design "Contribution items", "Dual extraction and audit"; MCP `contribution_next`, `contribution_record`; CLI `factory contributions`; skill `rf-contributions`; acceptance 2–6. Open questions 1, 2, 6 adopted as recommended.

## Rulings made in this plan

Rulings marked **[adopted 2026-11-04]** were Adopted 2026-11-04 (researcher's standing approval of the recommendation); G2-E records them in the *Proposed* decision when built.

1. **Item evidence. [adopted 2026-11-04]** An item's evidence is the anchor and quote of the first field of `CONTRIBUTION_V1.row_anchor_fields` (`name`, `statement`, `compared_to`) that is present with an anchor (`item_evidence`). The marker check uses it; G2-A's row key uses the same anchor.
2. **`cited_entry` check (acceptance 5).** Given `cited_entry = n`: the work must have a current G1 extraction whose `conversion_id` equals the unit's pinned conversion, else rejected (`fields.cited_entry.value`, reason `no-reference-extraction` or `reference-extraction-other-conversion`); entry `n` must exist in it (`entry-unknown`). The marker check (`marker_check`) is then stored on the row as `cited`: `matched` (a G1 context at the item's anchor whose marker token occurs in the quote maps to `n`), `mismatch` (markers in the quote map only to other entries: stored and flagged, not rejected), `absent` (no G1 marker of that anchor occurs in the quote: stored, flagged, the entry is the agent's declaration).
3. **`result_row`.** Must equal the `row_key` of a live evidence-scope row of the same work (`fields.result_row.value`, `result-row-unknown`); its values are never copied.
4. **`not-stated` (spec ruling 8). [adopted 2026-11-04]** A `not-stated` item carries no anchor and no quote on any field (`fields.<f>.quote`, `not-stated-has-no-quote`). Within one unit, a live `not-stated` for kind K and a live item of kind K contradict (`fields.item_kind.value`, `contradicts-recorded-item`). Absence of `addition` or `result` cannot be declared (G2-A pack, `absent_kind` allowed values).
5. **Closing a unit. [adopted 2026-11-04]** `finish` is refused (field `finish`) unless the unit's live items cover `base-idea` (an item or `not-stated`), cover `limitation` (an item or `not-stated`) and contain at least one `addition`. A unit with no `result` item closes only with a non-blank `reason` (stored on `extraction.closed`). A unit with zero items closes only with a `reason` (plan D). This is spec ruling 8 as adopted 2026-11-04 (an explicit, recorded escape for papers without empirical results).
6. **Unit references (spec ruling 9, open question 2).** `contribution_next` attaches `UnitReferences`: `current` (entries listed), `none` (no current G1 extraction: listed `no-references`, `cited_entry` unavailable, relations from it can only be inferred), `other-conversion` (the G1 extraction pins another conversion; treated as `none`).
7. **Granularity (open question 1).** One item per named predecessor; the skill splits a sentence naming several into several items with the same quote.
8. **Counts.** `not-stated` counts, items by kind and marker states are computed from `final_rows(scope=CONTRIBUTION)`; nothing is typed.

## Global Constraints

- All G2-A constraints hold. The platform never calls a model. Events are the source of truth; the index is written by the projector only.
- Every agent-written event carries model, skill reference and `input_blob` (the validated input of the call, including the served entries for `contribution_next`).
- Quotes are the only document text in events; `EntryBrief` carries bibliographic metadata only; no document text in any error or message.
- Partial acceptance as plan D: each item validated alone; valid items of a call are written.
- `mcp/` and `cli/` parse, call a service, format. TDD; `mypy --strict`, ruff; coverage >= 90% for `services/` and `model/`.

## Review Focus

1. A quote containing `[3, 5]` with `cited_entry = 5` is `matched`; with `cited_entry = 4` it is `mismatch` and stored; a quote with no marker at that anchor is `absent` and stored (Task 2, `test_marker_states`).
2. A work whose G1 extraction is replaced after recording: the item is stale, the unit is served again and lists the new extraction's entries; the old item stays readable (Task 3, `test_unit_reserved_after_g1_change`).
3. `cited_entry` given for a `no-references` work is rejected with a reason, not silently dropped, and the rest of the call is written (Task 2, `test_cited_entry_without_references_rejected_others_written`).
4. Pass B records the same base idea at a different paragraph: a `row` disagreement for the human, never auto-aligned (Task 4, `test_different_anchor_is_row_disagreement`).
5. Recording a `not-stated` base idea after a base-idea item in the same unit (or the reverse, in a later call) is refused (Task 2, `test_not_stated_contradiction_across_calls`).

## File Structure

- Create `lineage/__init__.py`, `lineage/cited.py`, `lineage/refs.py` (pure value types for G1 views).
- Create `services/reference_view.py`, `services/contributions.py`.
- Modify `mcp/server.py`, `cli/main.py`, `cli/render.py`, `tests/test_plugin.py` (`SKILLS`); create `plugin/skills/rf-contributions/SKILL.md`.
- Tests: `test_lineage_cited.py`, `test_reference_view.py`, `test_contribution_checks.py`, `test_contribution_record.py`, `test_contribution_agreement.py`, `test_mcp_contributions.py`, `test_cli_contributions.py`; helper `tests/contribution_helpers.py` (G2-A).

---

### Task 1: G1 read view and the marker rule (pure)

*Tier: standard (Sonnet implement, Haiku review).*

**Files:** Create `lineage/__init__.py`, `lineage/refs.py`, `lineage/cited.py`, `services/reference_view.py`; Test `tests/test_lineage_cited.py`, `tests/test_reference_view.py`.

**Interfaces:**
- Consumes: G1 tables and `LinkState`, `Confidence`, `MarkerState`; G2-A `MarkerCheck`, `StoredField`; `normalise_text`.
- Produces (`lineage/refs.py`, frozen dataclasses): `EntryView(ordinal: int, anchor: str, label: str | None, title: str | None, first_author: str | None, year: int | None, doi: str | None, arxiv: str | None, link_state: LinkState, link_work: str | None, confidence: Confidence | None)`; `ContextView(citing_anchor: str, entry: int | None, marker: str, state: MarkerState)`; `ReferenceView(extraction_id: str, work_id: str, conversion_id: str, entries: tuple[EntryView, ...], contexts: tuple[ContextView, ...])` with `entry(ordinal) -> EntryView | None`.
- Produces (`services/reference_view.py`): `reference_view(project, work_id: str) -> ReferenceView | None` (the work's live G1 extraction, entries by ordinal with the live link folded with the latest decision; `None` when none); `reference_view_of(project, extraction_id: str) -> ReferenceView | None` (any extraction, live or not); `is_live_reference_extraction(project, extraction_id: str) -> bool`; `briefs(view: ReferenceView) -> list[EntryBrief]`. Never selects `reference_entries.text`.
- Produces (`lineage/cited.py`): `item_evidence(fields: Mapping[str, StoredField]) -> tuple[str, str] | None` (ruling 1); `marker_check(quote: str, anchor: str, ordinal: int, contexts: Sequence[ContextView]) -> MarkerCheck` (ruling 2; tokens compared with `normalise_text`; only contexts whose `citing_anchor == anchor` and `state == "matched"` count as mapping).

- [ ] **Step 1: Tests.**
```python
def test_marker_states():                                   # Review Focus 1
    ctx = [ContextView("s2.p1", 3, "[3, 5]", "matched"), ContextView("s2.p1", 5, "[3, 5]", "matched")]
    assert marker_check("as in [3, 5], we", "s2.p1", 5, ctx) == "matched"
    assert marker_check("as in [3, 5], we", "s2.p1", 4, ctx) == "mismatch"
    assert marker_check("we follow linear attention", "s2.p1", 5, ctx) == "absent"
    assert marker_check("as in [3, 5], we", "s4.p1", 5, ctx) == "absent"           # other anchor
def test_ambiguous_context_does_not_map(): ...                # state "ambiguous" -> "absent"
def test_item_evidence_order(): ...                           # name, then statement, then compared_to; None for not-stated
def test_reference_view_folds_decisions(project):
    v = reference_view(project, W); assert v.entry(2).link_state == LinkState.RESOLVED and v.entry(2).confidence == Confidence.CONFIRMED
def test_reference_view_none_without_extraction(project): ...
def test_reference_view_never_reads_entry_text(project): ...  # SQL spy: no "text" column selected
def test_briefs_carry_metadata_only(project): assert set(EntryBrief.model_fields) == {"ordinal", "anchor", "label", "title", "first_author", "year", "doi", "arxiv"}
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(lineage): G1 reference view and marker rule`.

### Task 2: Contribution item checks and closure rule

*Tier: critical (the platform's guarantee on cited entries and `not-stated`).*

**Files:** Create `services/contributions.py` (checks only); Test `tests/test_contribution_checks.py`.

**Interfaces:**
- Consumes: G2-A `UnitPin`, `ExtraVerdict`, `ExtraCheck`, `CloseCheck`, `CitedEntry`, `ExtractionRow`, `live_rows(..., scope=)`; Task 1.
- Produces: `contribution_check: ExtraCheck` (rulings 2–4); `contribution_close_check: CloseCheck` (ruling 5). Reasons (fixed vocabulary): `no-reference-extraction`, `reference-extraction-other-conversion`, `entry-unknown`, `result-row-unknown`, `not-stated-has-no-quote`, `contradicts-recorded-item`; close issues on field `finish`: `base-idea-not-covered`, `limitation-not-covered`, `no-addition`, and on `reason`: `no-result-needs-reason`.

- [ ] **Step 1: Tests** (G2-A helper project; work `W` has a current G1 extraction on the pinned conversion with entries 1–6 and contexts at `s2.p1`).
```python
def test_cited_entry_unknown_rejected(): assert issues(cited_entry=9) == {"fields.cited_entry.value": "entry-unknown"}   # acceptance 5
def test_cited_entry_without_references_rejected_others_written(): ...   # Review Focus 3, via record_unit in Task 3
def test_cited_entry_other_conversion_rejected(): ...
def test_cited_stored_with_extraction_and_marker():
    v = contribution_check(project, pin, stored(item_kind="base-idea", name=Q("linear attention [5]", "s2.p1"), cited_entry=5), [])
    assert v.issues == [] and v.cited == CitedEntry(reference_extraction_id=REX, ordinal=5, marker="matched")
def test_mismatch_is_flagged_not_rejected(): ...
def test_result_row_must_exist_for_work(): ...                # other work's row_key -> result-row-unknown
def test_not_stated_has_no_quote(): ...
def test_not_stated_contradiction_across_calls(): ...         # Review Focus 5, both orders
def test_close_requires_base_limitation_and_addition():
    assert close_fields([addition, not_stated("base-idea")]) == {"finish": "limitation-not-covered"}
    assert close_fields([base, addition, limitation], reason=None) == {"reason": "no-result-needs-reason"}
    assert close_fields([base, addition, limitation, result]) == {}
def test_messages_carry_no_document_text(): ...
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement; read G1 through `reference_view` once per call (cache per `UnitPin`). **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(contributions): cited-entry, marker, result-row and not-stated checks`.

### Task 3: `contribution_next`, `contribution_record` and contribution reads

*Tier: critical (recording, pinning).*

**Files:** Modify `services/contributions.py`; Test `tests/test_contribution_record.py`.

**Interfaces:**
- Consumes: G2-A `next_unit`, `record_unit`, `ContributionBatchContent`, `UnitReferences`, `unit_states(..., scope=)`, `stale_extractions(..., scope=)`, `final_rows(..., scope=)`; Tasks 1–2.
- Produces: `CONTRIBUTION_INSTRUCTIONS: str` (fixed text: read only the pinned document; one item per named predecessor; quote verbatim; the wording rules belong to the skill; declare `not-stated` only for base idea or limitation; never infer a base idea); `contribution_next(project, actor, label: PassLabel) -> ExtractNext` (content is a `ContributionBatchContent` with `references` per ruling 6 and `item_rules`); `contribution_record(project, actor, task_id, items: Sequence[ExtractedRowInput], *, finish=False, reason=None, supersedes: Mapping[int, str] | None = None) -> ExtractResult` (= `record_unit(..., extra_check=contribution_check, close_check=contribution_close_check)`; claims always empty).
- Produces (reads): `class ItemView(StrictModel)`: `extraction_id`, `work_id`, `pass_label`, `item_kind`, `absent_kind: str | None`, `name: str | None`, `statement: str | None`, `compared_to: str | None`, `cited_entry: int | None`, `metric: str | None`, `value: str | None`, `unit: str | None`, `canonical: str | None`, `result_row: str | None`, `anchor: str | None`, `quote: str | None`, `document_id`, `conversion_id`, `cited: CitedEntry | None`, `live: bool`, `stale: bool`, `event_id`; `contribution_item(project, extraction_id: str) -> ItemView | None` (any recorded contribution row); `live_items(project, *, work_id: str | None = None, kind: str | None = None, include_stale: bool = False) -> list[ItemView]` (both passes, by extraction id); `final_items(project) -> list[ItemView]` (one per final row of `final_rows(scope=CONTRIBUTION)`, using the extraction id of its `item_kind` field); `class ContributionStatus(StrictModel)`: `units: dict[str, int]` (state -> count), `items_by_kind: dict[str, int]`, `not_stated: dict[str, int]` (absent kind -> count), `markers: dict[str, int]`, `no_references: list[str]`, `other_conversion: list[str]`; `contribution_status(project) -> ContributionStatus`.

- [ ] **Step 1: Tests.**
```python
def test_next_serves_entries_for_current_references():
    b = contribution_next(project, agent_a, PassLabel.A).batch
    assert b.references.status == "current" and [e.ordinal for e in b.references.entries] == [1, 2, 3, 4, 5, 6]
def test_next_marks_no_references_and_other_conversion(): ...
def test_non_verbatim_quote_or_name_rejected_valid_written():     # acceptance 2
    r = contribution_record(project, a, t, [good_base, bad_quote, name_not_in_quote, good_addition])
    assert len(r.rows.written) == 2 and {e.index for e in r.rows.rejected} == {1, 2}
def test_result_value_number_check():                              # acceptance 3
    assert reason_of(contribution_record(..., [result(value="82.5", quote="reaches 82.4% top-1")])) == "number-not-in-text"
def test_not_stated_accepted_for_base_and_limitation_only(): ...   # acceptance 4
def test_close_without_items_and_reason_refused(): ...             # acceptance 4
def test_unit_reserved_after_g1_change(): ...                      # Review Focus 2
def test_correction_supersedes(): ...
def test_event_provenance_and_input_blob_include_served_entries(): ...
def test_status_counts_derived():
    s = contribution_status(project); assert s.not_stated == {"base-idea": 1} and sum(s.items_by_kind.values()) == FINAL_ITEMS
def test_final_items_one_per_final_row(): ...
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests, the plan-D record suites unedited, mypy, ruff. **Step 5:** Commit `feat(contributions): contribution_next, contribution_record, item reads and status`.

### Task 4: Dual extraction, agreement, resolution and audit for contributions

*Tier: critical (dual independence, audit).*

**Files:** Modify `services/contributions.py` (wrappers); Test `tests/test_contribution_agreement.py`.

**Interfaces:**
- Consumes: G2-A `extraction_agreement`, `resolve_extraction`, `extraction_audit_sample`, `extraction_audit_record`, `audit_evidence`, `extraction_audit_report`, `extraction_audit_outstanding`, all with `scope=Scope.CONTRIBUTION`; `EXTRACTION_ERROR_CEILING`.
- Produces: `contribution_agreement(project, actor) -> ExtractionAgreement`; `resolve_contribution(project, actor, work_id, row_key, field, choice, reason, channel) -> str`; `contribution_audit_sample(project, actor, *, random_seed=None) -> ExtractionAuditSampled`; `contribution_audit_record(project, actor, audit_id, work_id, row_key, field, correct, note, channel) -> str`; `contribution_audit_report(project) -> ExtractionAuditReport | None`. Each is the plan-D function with the scope fixed; no new rule.

- [ ] **Step 1: Tests** (acceptance 6).
```python
def test_pass_independence_as_plan_d(): ...                 # same session / same model refused; pass B fields reversed
def test_rows_align_on_row_key_across_passes(): ...         # same kind, normalised name, same anchor
def test_different_anchor_is_row_disagreement(): ...        # Review Focus 4
def test_cited_entry_and_value_compared_statement_not(): ...
def test_human_resolution_chooses_a_b_or_neither(): ...
def test_audit_includes_not_stated_and_cited_entry(): ...
def test_error_rate_reported_and_ceiling(): ...              # 3 of 50 incorrect -> 0.06 above 0.05
def test_agent_cannot_resolve_or_label(): ...
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement the wrappers. **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(contributions): agreement, resolution and audit wrappers`.

### Task 5: MCP tools, CLI and the `rf-contributions` skill

*Tier: Haiku implement and review (surfaces); the skill text by Sonnet.*

**Files:** Modify `mcp/server.py`, `cli/main.py`, `cli/render.py`, `tests/test_plugin.py`; Create `plugin/skills/rf-contributions/SKILL.md`; Test `tests/test_mcp_contributions.py`, `tests/test_cli_contributions.py`, extend `tests/test_skills.py`.

**Interfaces:**
- MCP: `contribution_next(project, pass_label, role, model, skill)` -> `ExtractNext`; `contribution_record(project, task_id, items: list[dict], role, model, skill, finish: bool = False, reason: str | None = None, supersedes: dict[str, str] = {})` -> `ExtractResult` (shape errors are `ItemError`s by index, as `extract_record`). Both use the plan-D actor conventions; replies through `_withheld`. `_refuse_pass_session` already covers contribution sessions through `is_extraction_session`.
- CLI group `factory contributions`: `status`, `list [--work W] [--kind K] [--include-stale]`, `agreement`, `resolve WORK ROW_KEY [--field F] --choice a|b|neither --reason TEXT`, `audit sample|label AUDIT WORK ROW_KEY FIELD --correct/--incorrect [--note]|report`. Human acts use the human actor and channel `cli`.
- Skill `rf-contributions`: independence section as `rf-extract`; procedure: `contribution_next`, read the pinned conversion and the listed entries through `document_read` (an entry by its `b<n>` anchor), record one item per named predecessor, put the discriminating words in the quote ("we build on", "following", "based on", "extends", "unlike", "in contrast to", "improves"), set `cited_entry` only when the quote's marker or the entry text identifies it, `not-stated` only for base idea or limitation, never infer a base idea or a target, correct by superseding, `finish` with `reason` when the paper reports no result; human steps are not the skill's.

- [ ] **Step 1: Tests.** MCP: tool list pinned with the two new names; partial success by index; an unknown pass label writes nothing; a pass session of either scope refused by `report_*`, `check`, `trace`. CLI: `status` prints the computed counts and `no-references` ids; `resolve` writes a human event with `pack = "contribution"`; `audit label` outside the sample refused. Skill: frontmatter name/description; names `contribution_next`, `document_read`, `cited_entry`, `not-stated`, "verbatim", "never infer"; `SKILLS` includes `rf-contributions`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(contributions): MCP tools, CLI, rf-contributions skill`.

## Self-review notes

- **Spec coverage.** Recording and verification (Tasks 2–3; acceptance 2–5), dual extraction, agreement, resolution, audit (Task 4; acceptance 6), tools, CLI, skill (Task 5). Ruling 9's `no-references` listing is Task 3 (`contribution_status`); the `graph-extraction-missing` finding is G2-E.
- **Types used later.** `ReferenceView`, `EntryView`, `ContextView`, `reference_view`, `reference_view_of`, `is_live_reference_extraction`, `item_evidence`, `ItemView`, `contribution_item`, `live_items`, `final_items`, `contribution_status`, `ContributionStatus`.
- **Tiers.** Tasks 2–4 critical (Sonnet reviews), Task 1 standard, Task 5 Haiku.
