# Notices, Versions and Bounded Propagation Implementation Plan (slice 4b, sub-plan living-C)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** Slice 3b is merged, so Task 6's lineage step is built. Gates `living.notice_assess` and `living.document_prefer` are slice-M decision gates (floor `human`). Bumps `PROJECTION_VERSION` by one from the value it finds; the Crossref and OpenAlex `network` tests stay in v1.

> **Dependencies.** Plan living-A merged (cycles, `CycleHook`, `dedup_new`, `work_keys`). Plans 2A–2E merged (routes, refresh, `default_conversion`, plan-D row staleness, evidence report). Slice 3b (lineage) optional: Task 6's lineage step is built only if `services/lineage.py` exists, otherwise it is recorded as a follow-up in the plan's completion notes. May run in parallel with living-B.

**Goal:** For every work the project depends on, the platform observes retractions, withdrawals, corrections, expressions of concern, newer versions and published versions from source metadata, records them with source and date, lets a human assess them, and marks as doubtful only the affected work's rows, claims and edges, computed at read time.

**Architecture:** Identifier lookups run as search runs with a new `QueryPurpose.STATUS` (archived, never corpus works, never PRISMA identification). `services/notices.py` and `services/versions.py` derive `notice.observed`, `version.observed` and `version.linked` from the parsed responses. One pure function, `model/notices.py::notice_state`, turns notice and assessment events into per-work states; the evidence report, extraction staleness, lineage, `check`, `trace` and the digest all read it. `document.preferred` is consulted by `default_conversion`, so plan-D's existing "pins a document other than the current one" rule does the restaling.

**Tech Stack:** as living-A; a new adapter `sources/crossref.py` on the existing `sources/http.py` client (polite pool `mailto`, throttle).

**Spec:** `docs/specs/slice-4b-living-corpus.md` rulings 11–15; acceptance 9, 10, 11, 14, 16 (network part).

## Rulings made in this plan

1. **Dependent works.** `dependent_works(project)` = works with final outcome `INCLUDED` at title/abstract or full text, ∪ works with a live extraction row or claim in any scope. Indexed query; never a corpus scan. [confirm]
2. **Coverage order.** Each cycle checks up to `notice_budget` dependents, least recently checked first (last status run whose records named the work), ties by work id. A work never checked comes first. Full coverage takes `ceil(|dependents| / budget)` cycles; `check` reports `notice-coverage-age` (advisory) for dependents unchecked for more than `3 × ceil(...)` cycles. [confirm]
3. **Lookup batching.** OpenAlex: `filter=doi:<a>|<b>…` or `openalex:` ids, at most `CHASE_CHUNK` per query (existing constant). Crossref: one query per DOI with `filter=updates:<doi>` unless the network test of Task 2 shows that repeated `updates:` filters are OR-ed, in which case `CHASE_CHUNK` per query. arXiv: `id_list` of bare ids (no version), at most `CHASE_CHUNK`. [confirm]
4. **Notice identity.** `(work_id, kind, notice_doi or source)`; a repeat observation writes nothing. A Crossref record of type `retraction` / `correction` / `withdrawal` / `expression_of_concern` (its `update-to[].type`) maps to the kind; any other update type is ignored and counted in the run note. OpenAlex `is_retracted = true` without a Crossref notice yields kind `retraction`, `notice_doi = None`, `notice_date = None` (reported as "date not stated by source"). `reinstatement` is observed only from Crossref update type `reinstatement` if present; otherwise it is a human assessment `keep-flagged`. [confirm]
5. **Version observations.** `version.observed` when the arXiv response's `vN` exceeds the `source_version` of the work's current arXiv-route document. `version.linked` when OpenAlex lists a location with `version = publishedVersion` and a DOI different from the work's DOIs, or arXiv returns a `doi`/`journal_ref`; identifiers are normalised by `Identifiers`. A link whose DOI is already an identifier or alias of a **different** work is not written; it is reported as `version-link-conflict` (a dedup question for the human, R-26). [confirm]
6. **Preference validity.** `document.preferred` names a live document of the same work; a later preference supersedes; preferring the automatic default again clears the override. [confirm]

## Global Constraints

- As living-A. No status lookup creates or modifies a corpus work; `list_works`, `prisma_flow` and `search_report` ignore `STATUS` runs (as `PROBE`).
- Notice states are never stored in the index; `index/notices.py` stores observations and assessments only.
- No screening outcome, decision or extraction row event is written by this plan; staleness is computed.
- Raw responses archived before parsing (R-03); no document text in events or findings.
- Network tests marked `network`; everything else uses recorded fixture responses under `tests/fixtures/living/`.

## Review Focus

1. A correction assessed `affects` on field `value` stales exactly that work's rows carrying `value` (Task 6, `test_affects_stales_only_named_fields_of_that_work`; row-set equality over a 50-work fixture).
2. `STATUS` runs leave PRISMA and the corpus unchanged (Task 1, `test_status_runs_invisible_to_prisma_and_corpus`).
3. A version link to a DOI held by another work is refused and reported (Task 4, `test_version_link_conflict`).
4. `document.preferred` changes `default_conversion` and stales rows of that work only (Task 5, `test_preference_stales_one_work`).
5. The evidence report with a retracted included work equals the report without that work, plus an `Excluded` entry (Task 6, `test_report_excludes_retracted_by_default`).

## File Structure

- Modify `model/search.py` (`QueryPurpose.STATUS`), `services/search.py` (`list_works`, `search_counts` exclude STATUS), `services/prisma.py`, `services/protocol.py` (`search_authorization`: STATUS queries are platform-built and waived when naming an open cycle, as window queries).
- Create `model/notices.py` (`NoticeKind`, `NoticeObserved`, `NoticeAssessed`, `AssessmentDecision`, `WorkNoticeState`, `notice_state`), `model/versions.py` (`VersionObserved`, `VersionLinked`, `DocumentPreferred`).
- Modify `model/staleness.py` (`notice_stale_rows`).
- Create `sources/crossref.py`; modify `sources/openalex.py` (status parse: `is_retracted`, locations), `sources/arxiv.py` (status parse: version, `doi`, `journal_ref`), `sources/registry.py`.
- Create `services/notices.py`, `services/versions.py`, `index/notices.py` (tables `notices`, `notice_assessments`, `version_observations`, `work_aliases`, `document_preferences`); modify `index/dedup.py` (`work_keys` includes aliases), `events/catalog.py`, `index/default.py`.
- Modify `services/document_read.py` (`_default` honours preferences), `services/extraction.py` (row staleness includes `notice_stale_rows`), `services/evidence_report.py` (`ExcludedReason` adds `retracted`, `correction-pending`; labels), `services/check.py`, `services/trace.py`, `services/living_hooks.py` (`status_hook`), `cli/main.py`, `mcp/server.py`.
- Tests: `test_status_purpose.py`, `test_crossref.py`, `test_notices.py`, `test_notice_state.py`, `test_versions.py`, `test_document_preferred.py`, `test_notice_effects.py`, `test_living_network.py` (`network`).

---

### Task 1: `STATUS` purpose and invisibility

*Tier: critical (PRISMA counts).*

**Files:** Modify `model/search.py`, `services/search.py`, `services/prisma.py`, `services/protocol.py`, `index/search.py`; Test `tests/test_status_purpose.py`.

**Interfaces:**
- `QueryPurpose.STATUS = "status"`.
- `list_works(project, *, include_probe=False)` excludes works whose only provenance is from STATUS runs (as probe works); `corpus_size`, `search_counts`, `prisma_flow`, `search_report` likewise.
- `register_query(..., cycle_id=...)` accepts a STATUS spec only with an open `cycle_id` and kind `id_list` or `filter`.

- [ ] **Step 1: Tests.** `test_status_runs_invisible_to_prisma_and_corpus` (state with and without a status run: equal `prisma_flow`, `corpus_size`, `final_outcomes`), `test_status_query_needs_open_cycle`, `test_status_run_archives_raw_pages`, `test_agent_cannot_register_status_query` (MCP `search_run` refuses purpose `status`).
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_status_purpose.py tests/test_prisma*.py tests/test_search*.py -q`.
- [ ] **Step 5: Commit** `feat(living): status purpose for identifier lookups`.

### Task 2: Crossref notice adapter and status parsers

*Tier: standard.*

**Files:** Create `sources/crossref.py`; Modify `sources/openalex.py`, `sources/arxiv.py`, `sources/registry.py`; Test `tests/test_crossref.py`, `tests/test_living_network.py`; fixtures `tests/fixtures/living/crossref_updates_*.json`, `openalex_status_*.json`, `arxiv_status_*.xml`.

**Interfaces:**
- `class CrossrefSource` implementing `Source` with `name = "crossref"`, `kinds = frozenset({QueryKind.FILTER})`; query text is a filter expression (`updates:10.1000/x`); records are parsed into `StatusRecord`, not `Work`.
- `@dataclass(frozen=True) class StatusRecord: target: Identifiers; kind: Literal["notice", "version"]; notice_kind: NoticeKind | None; notice_doi: str | None; notice_date: date | None; source_version: str | None; linked: Identifiers | None; venue: str | None`.
- `SearchResult` gains `status_records: tuple[StatusRecord, ...] = ()`; for STATUS specs adapters fill it and leave `works` empty.

- [ ] **Step 1: Tests.** Fixture parses: `test_crossref_retraction_parsed`, `test_crossref_correction_parsed`, `test_crossref_unknown_update_type_ignored_and_counted`, `test_openalex_is_retracted_parsed`, `test_openalex_published_location_parsed`, `test_arxiv_latest_version_and_doi_parsed`. Network: `test_crossref_updates_filter_live` (a known retracted DOI chosen off-topic, never a pilot work), `test_crossref_repeated_updates_filter_semantics` (records whether repeated filters OR; the result selects ruling 3's batching and is written to the test's docstring when run).
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_crossref.py tests/test_openalex*.py tests/test_arxiv.py -q`.
- [ ] **Step 5: Commit** `feat(living): Crossref notice adapter and status parsers`.

### Task 3: Notice observation in the cycle

*Tier: critical.*

**Files:** Create `model/notices.py` (events), `services/notices.py`, `index/notices.py`; Modify `services/living_hooks.py`, `events/catalog.py`; Test `tests/test_notices.py`.

**Interfaces:**
- `class NoticeKind(StrEnum): RETRACTION, WITHDRAWAL, CORRECTION, EXPRESSION_OF_CONCERN, REINSTATEMENT`.
- `class NoticeObserved(StrictModel): notice_id: str (NTC_ID_RE); work_id: str; kind: NoticeKind; notice_date: date | None; notice_doi: str | None; source: str; run_id: str; raw_blob: str`.
- `def dependent_works(project: Project) -> list[str]` (ruling 1; sorted).
- `def notice_check(project: Project, cycle_id: str, *, sources: Mapping[str, SourceFactory], budget: int) -> NoticeCheckSummary` — selects works (ruling 2), registers and runs STATUS queries naming the cycle, writes `notice.observed` for new notices (ruling 4), returns `checked`, `new_notices`, `unchecked_crossref` (dependents without a DOI).
- `def status_hook(project: Project, cycle_id: str, new_work_ids: tuple[str, ...]) -> tuple[str, ...]` — a living-A `CycleHook`; runs `notice_check` and, if `track_versions`, `version_check` (Task 4) and returns their run ids, which living-A records as `watch.cycle_finished.status_run_ids`.

- [ ] **Step 1: Tests.** `test_retraction_observed_once`, `test_openalex_only_retraction_has_no_date`, `test_budget_limits_and_rotates`, `test_never_checked_first`, `test_dependents_include_extracted_not_included` (a work excluded later but with live rows is checked), `test_no_doi_listed_unchecked_crossref`, `test_notice_events_rebuild_identical`.
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_notices.py tests/test_watch_cycle.py -q`.
- [ ] **Step 5: Commit** `feat(living): notice observation for dependent works`.

### Task 4: Version observation and aliases

*Tier: critical (corpus identity).*

**Files:** Create `model/versions.py`, `services/versions.py`; Modify `index/notices.py` (`version_observations`, `work_aliases`), `index/dedup.py` (`work_keys` from aliases), `services/dedup_incremental.py`; Test `tests/test_versions.py`.

**Interfaces:**
- `class VersionObserved(StrictModel): work_id; route: Route; source_version: str; run_id: str`.
- `class VersionLinked(StrictModel): work_id; identifiers: Identifiers; venue: str | None; source: str; run_id: str`.
- `def version_check(project: Project, cycle_id: str, *, sources, work_ids: Sequence[str]) -> VersionCheckSummary` (`newer`, `linked`, `conflicts`).
- `def aliases(project: Project, work_id: str) -> Identifiers`; `def newer_versions(project: Project) -> list[VersionObserved]` (still newer than the current document); `def vor_available(project: Project) -> list[str]` (linked works whose default conversion is a preprint route).

- [ ] **Step 1: Tests.** `test_newer_arxiv_version_observed_no_fetch` (no `fulltext.*` event written), `test_newer_version_cleared_after_refresh`, `test_vor_link_adds_alias`, `test_later_database_record_merges_by_alias` (living-A `dedup_new` merges with rule `identifier:doi`), `test_version_link_conflict`, `test_link_changes_no_decision` (`final_outcomes` equal before and after).
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_versions.py tests/test_dedup_incremental.py -q`.
- [ ] **Step 5: Commit** `feat(living): version observation and identifier aliases`.

### Task 5: Human acts — assessment and preferred document

*Tier: critical (human gate).*

**Files:** Modify `model/notices.py` (`NoticeAssessed`, `AssessmentDecision`), `model/versions.py` (`DocumentPreferred`), `services/notices.py` (`assess_notice`), `services/versions.py` (`prefer_document`), `services/document_read.py` (`_default`), `cli/main.py` (`notices list|assess`, `versions list|prefer`), `mcp/server.py` (`notice_list` read; relayed human answers per decision 37 item 6); Test `tests/test_document_preferred.py`, extend `tests/test_notices.py`.

**Interfaces:**
- `class AssessmentDecision(StrEnum): EXCLUDE, KEEP_FLAGGED, NO_EFFECT, AFFECTS`.
- `class NoticeAssessed(StrictModel): notice_id; decision: AssessmentDecision; fields: tuple[str, ...] = (); rationale: str = Field(min_length=1)`; validator: `fields` non-empty iff `AFFECTS`; `AFFECTS`/`NO_EFFECT` only for `CORRECTION`; `EXCLUDE`/`KEEP_FLAGGED` only for the other kinds.
- `def assess_notice(project: Project, actor: Actor, notice_id: str, decision: AssessmentDecision, *, fields: Sequence[str] = (), rationale: str) -> str` — human only; `fields` must be fields of a declared schema (either scope).
- `class DocumentPreferred(StrictModel): work_id; document_id; rationale: str`.
- `def prefer_document(project: Project, actor: Actor, work_id: str, document_id: str, rationale: str) -> str` — human only; ruling 6.

- [ ] **Step 1: Tests.** `test_agent_cannot_assess`, `test_affects_requires_fields`, `test_assessment_supersedes`, `test_prefer_requires_live_document_of_same_work`, `test_preference_changes_default_conversion`, `test_preference_stales_one_work` (plan-D unit staleness for that work only; others' units unchanged), `test_preferring_default_clears_override`.
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_document_preferred.py tests/test_notices.py tests/test_document_read*.py tests/test_extraction_stale.py -q`.
- [ ] **Step 5: Commit** `feat(living): notice assessment and preferred documents`.

### Task 6: Read-time effects (pure function and consumers)

*Tier: critical (subagent-driven).*

**Files:** Modify `model/notices.py` (`WorkNoticeState`, `notice_state`), `model/staleness.py` (`notice_stale_rows`), `services/extraction.py`, `services/evidence_report.py`, `services/check.py`, `services/trace.py`, `services/lineage.py` (only if present); Test `tests/test_notice_state.py`, `tests/test_notice_effects.py`.

**Interfaces:**
- `class WorkNoticeState(StrictModel): work_id; flag: Literal["retracted", "correction-pending", "concern", "none"]; synthesis: Literal["excluded", "labelled", "normal"]; stale_fields: tuple[str, ...]; notices: tuple[str, ...]; assessed: bool`.
- `def notice_state(observed: Sequence[NoticeObserved], assessed: Sequence[tuple[str, NoticeAssessed]]) -> dict[str, WorkNoticeState]` — pure; `assessed` pairs are (event id, payload), latest per notice wins; table of spec ruling 12; a reinstatement after a retraction restores the earlier state.
- `def notice_stale_rows(states: Mapping[str, WorkNoticeState], rows: Sequence[tuple[str, str, RowRef]]) -> list[str]` — rows given as (work id, row id, ref); a row is stale when its work's `stale_fields` intersect `ref.fields`; sorted, unique.
- `services/notices.py::work_states(project) -> dict[str, WorkNoticeState]` (indexed read of observations and assessments; only works with notices).
- Evidence report: rows of `synthesis = excluded` works leave groups, frontiers and speed ratios and are counted in `Excluded(reason="retracted")`; `correction-pending` rows stay in groups but leave frontiers, listed as `Excluded(reason="correction-pending")` for frontier purposes; `evidence_report(..., include_notice_affected: bool = False)`; the agent view keeps the exclusions and never shows the flag override.
- Findings: `included-retracted`, `notice-unassessed`, `notice-unchecked-crossref`, `notice-coverage-age`, `newer-version-available`, `version-of-record-available`, `version-link-conflict`. `trace` of a work lists its notices, assessments, version observations and preference.

- [ ] **Step 1: Tests.** Pure: `test_state_table_retraction`, `test_state_table_correction_before_and_after_assessment`, `test_reinstatement_restores`, `test_keep_flagged_returns_rows`. Consumers: `test_report_excludes_retracted_by_default`, `test_include_notice_affected_flag_restores_rows`, `test_correction_pending_leaves_frontier_only`, `test_affects_stales_only_named_fields_of_that_work`, `test_reextraction_queued_for_affected_units_only`, `test_no_screening_outcome_changes`, `test_included_retracted_finding_by_mode`, `test_trace_lists_notices`, `test_lineage_retracted_basis_hidden_by_default` (skipped with reason when slice 3b is absent).
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_notice*.py tests/test_evidence*.py tests/test_extraction*.py tests/test_check*.py -q`.
- [ ] **Step 5: Commit** `feat(living): read-time notice effects with bounded propagation`.

## Verification

`uv run pytest -m "not network and not slow" -q && uv run mypy --strict src && uv run ruff check src tests` from `platform/`; once, `uv run pytest -m network tests/test_living_network.py -q` with `FACTORY_MAILTO` set.

## Self-review notes

- The only change to an existing gate is the cycle waiver for STATUS queries; it mirrors living-A's window waiver and is tested for foreign and finished cycles.
- Status checks run after the cycle's search runs and incremental dedup, so a version-of-record record found by the same cycle's database query is already merged before the alias is written; `test_link_after_same_cycle_merge_is_not_conflict` covers it (Task 4).

## Later (not v1)

None: every task of this plan is in v1.
