# Import B: Resolution, Admission and Attachments — Implementation Plan (slice 3d)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** `LIBRARY_IMPORT` is appended after slice 4a's `SUPPLIED` (built first): `OTHER_METHODS = (CITATION_CHASE, SEED_ADMISSION, HAND_SEARCH, SUPPLIED, LIBRARY_IMPORT)`; any `database` provenance still wins. Fuzzy-match confirmation is the slice-M gate `import.resolution_confirm` (presets as `reference.link_confirm`), checked through `require_gate`. Bumps `PROJECTION_VERSION` by one from the value it finds.

> **Dependencies.** Import-A merged; slice 3a (G1: `services/reference_resolve.py`, `references/match.py`, `sources/reflist.py`, `decide_reference` and its confirmation policy) merged. Import-C consumes this plan's Interfaces. Every slice-1, slice-2 and G1 test passes unchanged except the `PROJECTION_VERSION` pin; PRISMA and search-report output of a project without imports is byte-identical.

**Goal:** Resolve every import record to a work identity with the slice-3a resolver, confirm fuzzy matches under the slice-3a policy, admit `corpus` imports as screened candidates with `library-import` provenance through recorded searches, and attach export-named PDFs to promoted works.

**Architecture:** `resolve_entries` is generalised to a structural `Resolvable` protocol so import records and reference entries share one resolver. Admission mirrors snowball rounds: `import.admission_planned` names the queries before any runs; resolved records go to OpenAlex/arXiv as `id_list` queries of the new purpose `import`, the rest to the offline `importlist` source (a copy of the `reflist` pattern). Attachments reuse `record_supplied_document` (plan 2A).

**Tech Stack:** as Import-A.

**Spec:** `docs/specs/slice-3d-regions-import.md` rulings 20–24; acceptance 12, 14, 15.

## Rulings made in this plan

1. **`Resolvable`.** `typing.Protocol` with read-only attributes `ordinal: int`, `doi`, `arxiv`, `url: str | None`, `year: int | None`, `first_author`, `title`, `venue: str | None`. `ReferenceEntry` satisfies it unchanged; `ImportResolvable` (a frozen dataclass built from an `ImportRecord`; `first_author` is the surname of `authors[0]`) does too.
2. **Confirmation.** `decide_import(...)` applies `_confirmer` from `reference_resolve.py` unchanged (human in every mode; in `pilot`, a second agent whose session neither proposed nor resolved the record). The quotes it requires are the record's title (from the record blob) and the candidate's title, as in G1.
3. **`library_sources`.** `ProtocolSpec.library_sources: tuple[LibrarySource, ...] | None = None`; `LibrarySource(name: str, format: ImportFormat, role: ImportRole)`; amendable, hashed, omitted while `None`. An import is admitted only when an entry with the import's `collection` (or `name = "default"` when no collection) and format exists with role `corpus` (pilot, systematic); `exploratory` admits and reports the gap.
4. **Admission order.** One admission per import (`import.admission_planned` refuses a second unless the first's runs all failed, mirroring `09016c4`'s snowball retry rule). Admission is refused while the import has unconfirmed or ambiguous records (they are listed); unresolved records go to `importlist`.
5. **Provenance.** `ProvenanceMethod.LIBRARY_IMPORT = "library-import"` appended to the enum and last in `OTHER_METHODS`; `QueryPurpose.IMPORT = "import"`; works from OpenAlex/arXiv import queries carry `source` = that source, method `library-import`; works from `importlist` carry `source = "importlist"`.

## Global Constraints

- As Import-A. Lookups are probe-purpose (outside the corpus); admission queries are import-purpose (corpus-entering, gated). Network tests marked `network`; offline tests use the existing fake source factories.
- `PrismaFlow` and `SearchReport` identities (`_identities_hold`) still hold with the new method.

## Review Focus

1. `resolve_entries` gives identical `Resolution`s for the same fields given as `ReferenceEntry` and as `ImportResolvable` (Task 1, `test_resolver_parity`).
2. A project without imports produces byte-identical PRISMA and search-report JSON before and after this plan (Task 4, `test_prisma_unchanged_without_imports`).
3. A work found by a database search and imported counts as database, never twice (Task 4, `test_database_precedence_over_import`).
4. An attachment is never recorded for an unpromoted work (Task 5, `test_attach_requires_promotion`).

## File Structure

- Modify `services/reference_resolve.py` (protocol), `model/work.py`, `model/search.py`, `model/protocol.py`, `services/protocol_rules.py`, `services/protocol.py` (`search_authorization` with `import_id`), `services/search.py` (`register_query(..., import_id=None)`), `services/prisma.py`, `sources/registry.py`.
- Create `sources/importlist.py`, `services/import_resolve.py`, `services/import_admit.py`, `services/import_attach.py`; extend `model/imports.py`, `index/imports.py`, `cli/main.py`.
- Tests: `test_import_resolve.py`, `test_library_sources.py`, `test_importlist_source.py`, `test_import_admit.py`, `test_import_prisma.py`, `test_import_attach.py`, `test_cli_import_admit.py`.

---

### Task 1: Generalise the resolver; resolve imports

*Tier: critical (shared with G1).*

**Files:** Modify `services/reference_resolve.py`; Create `services/import_resolve.py`; extend `model/imports.py`, `index/imports.py`; Test `tests/test_import_resolve.py`.

**Interfaces:**
- Consumes: `resolve_entries(project, actor, entries, *, sources) -> ResolutionOutcome`, `Resolution`, `LinkState`.
- Produces (`services/reference_resolve.py`): `class Resolvable(Protocol)` (ruling 1); `resolve_entries(project, actor, entries: Sequence[Resolvable], *, sources)` (signature otherwise unchanged).
- Produces (`model/imports.py`): `class ImportResolved(StrictModel)`: `import_id`, `resolutions: tuple[Resolution, ...]`, `lookup_runs: tuple[str, ...]`, `matcher: str`, `matcher_version: str`; event `import.resolved` (supersedes an earlier one for the same import).
- Produces (`services/import_resolve.py`): `@dataclass(frozen=True) ImportResolvable`; `resolvables(project, import_id) -> list[ImportResolvable]` (outcome `PARSED` or `NO_TITLE_NO_IDENTIFIER`); `resolve_import(project: Project, import_id: str, *, sources: Mapping[str, SourceFactory]) -> ImportResolutionSummary` (`counts: dict[LinkState, int]`); `record_states(project, import_id) -> dict[int, LinkState]`.
- Projection: `import_records` gains `link_state`, `work_id`, `method`, `confidence`.

- [ ] **Step 1: Tests.** `test_resolver_parity` (Review Focus 1, parametrised over identifier, title-exact, fuzzy, ambiguous, unresolved fixtures from `references_service_helpers.py`), `test_corpus_identifier_first`, `test_lookups_are_probe_purpose_outside_corpus`, `test_unresolved_listed_not_dropped`, `test_reresolve_supersedes`, `test_existing_g1_tests_unchanged` (meta: run `tests/test_reference_resolve*.py`).
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(imports): resolve import records with the G1 resolver`.

### Task 2: Confirmation of fuzzy and ambiguous records

*Tier: critical (R-51).*

**Files:** Modify `services/import_resolve.py`, `model/imports.py`, `index/imports.py`; Test `tests/test_import_confirm.py`.

**Interfaces:**
- Consumes: `_confirmer(project, actor, …)` and the decision model of `decide_reference` (`Decision` enum `confirm|reject`).
- Produces: `class ImportResolutionDecided(StrictModel)`: `import_id`, `ordinal`, `decision`, `work_id: str | None`, `rationale`, `quotes: tuple[str, str]`; event `import.resolution_decided`; `decide_import(project: Project, actor: Actor, import_id: str, ordinal: int, decision: Decision, *, rationale: str, work_id: str | None = None) -> None` (writes nothing when invalid: not `unconfirmed`/`ambiguous`, work not a candidate, actor not allowed).

- [ ] **Step 1: Tests.** `test_human_confirms_fuzzy`, `test_agent_cannot_confirm_in_systematic`, `test_second_agent_may_confirm_in_pilot`, `test_resolving_session_cannot_confirm`, `test_ambiguous_needs_named_candidate`, `test_reject_supersedes_confirm`.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(imports): confirm fuzzy import matches under the G1 policy`.

### Task 3: `library_sources` and the `importlist` source

*Tier: critical (protocol hash; corpus-entering source).*

**Files:** Modify `model/protocol.py`, `services/protocol_rules.py`, `services/protocol.py`, `model/search.py`, `model/work.py`, `services/search.py`, `sources/registry.py`; Create `sources/importlist.py`; Test `tests/test_library_sources.py`, `tests/test_importlist_source.py`.

**Interfaces:**
- Produces: ruling 3 types; `ProvenanceMethod.LIBRARY_IMPORT`; `QueryPurpose.IMPORT`; `search_authorization(project, spec, *, deviation_id=None, round_id=None, import_id=None) -> list[ValidationIssue]` (an import-purpose query is authorised only with `import_id` naming an import whose admission planned it); `register_query(..., import_id: str | None = None) -> str`.
- Produces (`sources/importlist.py`): `NAME = "importlist"`; `@dataclass(frozen=True) ImportlistEntry(key, title, first_author, year, doi, arxiv, url, venue, record_sha256)`; `entry_keys(text) -> list[str]` (record keys, `RECORD_KEY_RE`); the source as `reflist` (raw page = canonical JSON of the entries sorted by key; works built with `Work.build`, `source = importlist`, `method = LIBRARY_IMPORT`, `raw_ref` = record key); `importlist_factory(read: Callable[[Sequence[str]], Mapping[str, ImportlistEntry]]) -> SourceFactory` (`sources/registry.py`).

- [ ] **Step 1: Tests.** `test_p_id_unchanged_without_library_sources`, `test_library_sources_amendable_and_hashed`, `test_import_query_refused_without_import_id`, `test_importlist_builds_works_from_fields_only`, `test_importlist_malformed_key_fails_run`, `test_importlist_shortfall_named`, `test_provenance_method_round_trip`.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(imports): library_sources protocol section and importlist source`.

### Task 4: Admission and PRISMA

*Tier: critical (PRISMA counts).*

**Files:** Create `services/import_admit.py`; modify `services/prisma.py`, `model/imports.py`, `index/imports.py`; Test `tests/test_import_admit.py`, `tests/test_import_prisma.py`.

**Interfaces:**
- Consumes: `snowball_queries`-style packing (`_pack` chunks of 50 ids), `register_query`, `run_query`, `dedup_run`, `screening.sample_extended` (applied by the existing supplementary-record path).
- Produces: `class ImportAdmissionPlanned(StrictModel)`: `import_id`, `queries: tuple[PlannedImportQuery, ...]` (`source`, `kind`, `text`, `record_keys`); event `import.admission_planned` written before any `query.registered`; `plan_admission(project, import_id) -> list[QuerySpec]` (pure over the projection); `admit_import(project: Project, import_id: str, *, sources: Mapping[str, SourceFactory]) -> AdmissionSummary` (`runs`, `new_works`, `already_in_corpus`, `failed_runs`, `gaps: list[ValidationIssue]`). Refusals (nothing written): role `reference`; protocol not ready or `library_sources` missing (pilot, systematic); unconfirmed or ambiguous records; an earlier admission with a successful run.
- Produces (`services/prisma.py`): `OTHER_METHODS` gains `LIBRARY_IMPORT` last; `PrismaFlow.identified_other` includes it; the search report lists import queries with the import id, file hash, format and parser version.

- [ ] **Step 1: Tests.**
```python
def test_admission_plan_written_before_queries(project_with_import): ...
def test_reference_role_refused(project_with_import): ...
def test_pilot_needs_library_sources(project_with_import): ...
def test_exploratory_admits_with_gap(project_with_import): ...
def test_admitted_works_are_pending_with_library_import_provenance(...): ...
def test_dedup_links_import_to_searched_work(...): ...
def test_database_precedence_over_import(...):            # Review Focus 3
    flow = prisma_flow(project); assert flow.identified_other["library-import"] == 0 and flow.database_total == before + 0
def test_prisma_unchanged_without_imports(snapshot_project): ...   # Review Focus 2, byte-identical JSON
def test_pass_b_sample_extended_for_admitted(...): ...
def test_failed_admission_can_be_retried(...): ...
```
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(imports): admit corpus imports as screened candidates`.

### Task 5: Attachments and the PDF identity check

*Tier: standard (reuses plan-2A recording).*

**Files:** Create `services/import_attach.py`; modify `model/imports.py`, `index/imports.py`; Test `tests/test_import_attach.py`.

**Interfaces:**
- Consumes: `record_supplied_document(project, work_id, *, content, source_version, media_type, actor) -> str | None`, `final_outcomes`, `Outcome.INCLUDED`, `canonical_works`.
- Produces: `class ImportAttachmentLinked(StrictModel)`: `import_id`, `ordinal`, `work_id`, `document_id`; event `import.attachment_linked` in the same `record` call as the document events; `class AttachReport(StrictModel)`: `attached: list[tuple[int, str, str]]`, `not_promoted`, `attachment_missing`, `identity_unchecked`, `already_attached: list[int]`; `attach_import(project: Project, import_id: str) -> AttachReport`. Identity check for `pdfs` imports: `normalize_title(resolved title)` must occur in `normalize_title(page-1 text)`; failures go to `identity_unchecked` and are attached only after `decide_import(..., confirm)` on that record.

- [ ] **Step 1: Tests.** `test_attach_requires_promotion` (Review Focus 4), `test_attach_records_researcher_route_document`, `test_missing_bytes_listed`, `test_pdf_title_cross_check`, `test_identity_unchecked_attached_after_confirmation`, `test_attach_idempotent`, `test_first_page_text_not_stored`.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(imports): attach export-named PDFs to promoted works`.

### Task 6: CLI `resolve|confirm|admit|attach`

*Tier: standard.*

**Files:** Modify `cli/main.py`, `cli/render.py`; Test `tests/test_cli_import_admit.py`.

**Interfaces:** `factory import resolve IMP`, `factory import confirm IMP ORDINAL [--work ID] --rationale TEXT`, `factory import reject IMP ORDINAL --rationale TEXT`, `factory import admit IMP`, `factory import attach IMP`.

- [ ] **Step 1: Tests.** `test_cli_resolve_counts`, `test_cli_confirm_writes_human_decision`, `test_cli_admit_prints_runs_and_gaps`, `test_cli_attach_report_lists`.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(cli): import resolve, confirm, admit, attach`.

**Verification for the plan:** `cd platform && uv run pytest -m "not network and not slow" && uv run mypy --strict src && uv run ruff check`.

## Later (not v1)

None: every task of this plan is in v1.
