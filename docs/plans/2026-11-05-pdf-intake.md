# PDF Intake Implementation Plan (backlog triage, plan PI)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Proposed 2026-11-05 (backlog triage, `2026-11-05-backlog-triage.md`).** Items marked [confirm] await the researcher. Tasks 1 to 3, 4 and 6 need no ruling beyond PD-1 and can start at once.

> **Dependencies.** Base `d66387f` or later (W-A, W-B). Nothing in flight. Paths are relative to `platform/` unless they start with `docs/` or `plugin/`. Task order inside the plan: 1, 2, then 3 to 9 in any order, 10 last.

**Goal:** A researcher can point the factory at a local folder of PDFs and have each one reach `document_read`, with its identity under the researcher's control and its conversion stated honestly, before decision 49 is taken.

**Why first.** Verified on the base on 2026-11-05 by walking the CLI on three synthetic PDFs in a scratch root and by reading the code:

1. `factory document convert` passes `default_converters()`, which is LaTeXML HTML only (`cli/main.py:2275`, `document/registry.py:29`). Docling and PyMuPDF4LLM are written (`document/docling.py`, `document/pymupdf4llm.py`) but no command reaches them, so every PDF records `no-converter`. No PDF can be read, screened at full text or extracted. This is the blocker.
2. A PDF with no identifier and no metadata title parses as `no-title-no-identifier`. `import admit` skips it, prints no count (`_Plan.unadmittable` is computed and dropped), and nothing lets the researcher name it: `import confirm` accepts only `unconfirmed` or `ambiguous` records.
3. A junk metadata title becomes the work: `Microsoft Word - draft7.docx` was admitted as `rf:anon-microsoft-word-draft7-…`.
4. `import show --researcher` lists ordinals with no file name, so the researcher cannot tell which file a record is. The manifest holds path hashes only.
5. A second admission is refused once any earlier run retrieved records, so a record fixed after the first admission could never enter.
6. `_gaps` requires a source and a query in every mode, so a project whose corpus is only the researcher's library cannot be made ready.
7. Works from `importlist` carry no abstract, even when the export holds one.
8. `methods` and `check` say nothing about which converter produced a document.

**Architecture:** Conversion gains an explicit, per-command opt-in to the optional converters; `default_converters()` and decision 49 are untouched. The folder import keeps paths in its library manifest (git-ignored) and gains a human `import describe` overlay on records. Admission becomes incremental. `check` and `methods` state provisional conversions.

**Tech Stack:** as slices 2 and 3d. Docling and PyMuPDF stay optional extras, never core dependencies (`pyproject.toml`).

**Spec and decision basis:** `docs/specs/slice-2.md` (Canonical document; open question 1); `docs/specs/slice-3d-regions-import.md` rulings 17 to 24; decisions 39, 40, 46 items 7 and 9, 47, 49 (pending), 53, 60; R-01, R-03, R-05, R-47. IDEA-26. Iterate lines 22 (`_Plan.unadmittable`) and 80 (tags after confirmation).

**Projection:** Task 5 bumps `PROJECTION_VERSION` by one from the value it finds (base value 49). Tasks 1 to 4 and 6 to 10 change no table.

## Proposed decisions (numbers are fixed at merge; do not edit `docs/decisions.md` from this plan until the researcher confirms)

**PD-1. Provisional PDF conversion while decision 49 is pending [confirm].** The researcher may opt a command into a named optional converter. The bake-off scores (`experiments/converter-bakeoff/results/scores.json`, 18 off-topic papers, no failures, deterministic) are table fidelity 0.81 for Docling and 0.64 for PyMuPDF4LLM, 1.25 and 0.87 s per page median, tables equal in 33 % and 28 % of papers. **Recommended: Docling for the pilot, PyMuPDF4LLM as the fallback where the models are not available.** Docling is MIT but needs its models supplied (`FACTORY_DOCLING_MODELS`; the model folder is not on this machine, and the library is installed only in the main checkout's environment). PyMuPDF is AGPL-3.0, tolerable as a local optional extra. GROBID has no platform adapter and is not offered. This does not decide decision 49: `default_converters()` is unchanged, and the marks on the 30-table sheet remain the deciding evidence. Conversions are keyed by (document, converter, version), so the later winner adds a conversion beside the provisional one; pinned quotes stay valid against their pinned conversion, and re-extraction on the new conversion is a human choice, as in decision 53.

**PD-2. Researcher-described import records [confirm].** A human may supply bibliographic fields for an import record (`import.record_described`). The original record and its hash are kept (R-03); the description is an overlay of allow-listed fields only (ruling 19). Options: (a) this overlay; (b) require a `.bib` or CSL export instead, which already works and carries attachments; (c) derive titles from the first page automatically. **Recommended: (a), keeping (b) as the path for anyone with a reference manager.** (c) is rejected: a guessed title is an identity claim made by a script, and ruling 24 keeps first-page text out of storage.

**PD-3. Library-only protocol [confirm].** A protocol whose `library_sources` has a `corpus` entry may declare no search source or query in `exploratory` and `pilot`. `systematic` keeps both gaps. Such a run says so in `check` and in methods. Options: (a) as stated; (b) keep the gap and require a small real search; (c) allow it in every mode. **Recommended: (a).** Until this is confirmed the pilot declares one narrow OpenAlex query, which satisfies today's gates. It extends decision 60 and contradicts nothing in it.

**PD-4. `importlist` works keep the record's abstract [confirm].** Ruling 22 builds the work "from the stored fields" and ruling 19 allow-lists `abstract`, but `sources/importlist.py` drops it. Carrying it gives title/abstract screening a text to quote from for `.bib` and CSL imports, and for described records. The text is already in `blobs/` (ruling 19), so nothing new enters git. **Recommended: carry it.** A PDF with no abstract stays screenable: `cannot-assess` needs only a criterion and promotes, so it reaches full text.

**PD-5. Identity check on `fulltext import` (IDEA-26) [confirm].** Decision 46 item 7 made this path "identifiers only". Decision 60 added a title cross-check for the import path only, so a cited DOI on page 1 can still attach a PDF to the wrong work through `fulltext import`. **Recommended: apply the same cross-check; a file whose title is not on its first page is listed `identity_unchecked` and not imported unless the researcher names it.** This tightens decision 46 item 7, so it needs its own entry.

**Not changed.** Imports and conversion stay CLI acts (decision 46 item 7, slice 3d's "imports are CLI only" in decision 60, plan B1 ruling 6). No MCP write tool is added here. See ruling R6 of the triage for the researcher's question on this.

## Global Constraints

- The platform never calls a model. Conversion stays deterministic and offline, OCR off (decision 40). Scanned PDFs stay out of scope; they convert to little or nothing and are reported by the anchor counts of `document status`.
- No literature text in tracked paths. File names and paths stay in the library (ruling 19); the first-page hint is read in memory and printed to the researcher only.
- Withholding belongs to agent paths; `--researcher` output stays complete. No agent surface returns a path, an ordinal, a hint or a held-out part.
- Every new event type and check code is declared in `services/modules/*.py` in the same task (build-order rule 2).
- Projector handlers are total; a hand-written event that fails a guard changes nothing, on rebuild too.
- Existing outputs stay byte-identical for projects that use none of this (golden tests).

## Review Focus

1. A project with no opted-in converter behaves exactly as before.
2. No path, file name or hint reaches `events/`, `blobs/` or any MCP reply. Walk both directories after an end-to-end fixture.
3. `import.record_described` cannot rewrite a record already admitted, and cannot move a record across the held-out split.
4. An incremental admission never admits a record twice and keeps PRISMA counts derived.
5. A provisional conversion is never reported as if decision 49 had chosen it.

## File Structure

Create: `docs/runbook-pdf-pilot.md`. Modify: `document/optional.py`, `document/registry.py`, `services/document_convert.py`, `services/methods.py`, `services/modules/conversion.py`, `services/modules/imports.py`, `services/check.py` (one rule call), `imports/pdfs.py`, `imports/model.py`, `model/imports.py`, `index/imports.py`, `index/default.py`, `events/catalog.py`, `services/imports.py`, `services/import_resolve.py`, `services/import_admit.py`, `services/fulltext_import.py`, `services/protocol_rules.py`, `sources/importlist.py`, `cli/main.py` (`document_app`, `import_app`, `fulltext_app` only), `cli/render.py`.

### Task 1: Opt-in converters

*Tier: standard.*

**Files:** Modify `document/optional.py`, `document/registry.py`, `services/document_convert.py`, `cli/main.py`, `cli/render.py`.

**Interfaces:**
- Produces (`document/optional.py`): `CONVERTERS: Mapping[str, Callable[[], Converter]]` (`docling`, `pymupdf4llm`, `pandoc`); `@dataclass(frozen=True) ConverterInfo(name, accepts, available: bool, version: str | None, reason: str | None, licence: str, active: bool)`; `converter_infos() -> list[ConverterInfo]`; `opted_registry(names: Sequence[str]) -> ConverterRegistry` (the named converters first, then `default_converters()`). An unknown or unavailable name raises `FactoryValidationError` on field `converter`, naming the extra or `FACTORY_DOCLING_MODELS`, before anything is read.
- CLI: `factory document convert --converter NAME` (repeatable; also applies to `--restore`); `factory document converters` (table of `ConverterInfo`; prints that decision 49 is pending).
- `services/document_convert.py::_decide`: a document that already has a live conversion and has no converter in this registry gives `unchanged` with no event. Today a later plain `document convert` would append a `no-converter` failure for every PDF already converted.
- `default_converters()` is not changed; update the docstrings of `document/optional.py`, `docling.py` and `pymupdf4llm.py`, which say "inactive until decision 49", to "opt-in per command until decision 49".

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(document): opt-in converters per command`.

**Tests (later):** `test_default_registry_unchanged`; `test_unknown_converter_refused_nothing_written`; `test_unavailable_converter_names_remedy`; `test_opted_converter_records_name_and_version` (fake converter); `test_second_converter_adds_a_conversion`; `test_plain_convert_after_opt_in_writes_nothing`; `test_restore_with_opted_converter`; a `network`-free Docling smoke test skipped when the models are absent.

### Task 2: Provisional conversions are stated

*Tier: standard (R-01, reporting honesty).*

**Files:** Modify `services/document_convert.py`, `services/methods.py`, `services/modules/conversion.py`, `services/check.py`, `cli/render.py`.

**Interfaces:**
- Produces: `PROVISIONAL_CONVERTERS: frozenset[str]` (`docling`, `pymupdf4llm`, `pandoc`; emptied by the task that wires decision 49); `conversion_census(project) -> list[ConverterCount(converter, version, media_type, documents: int)]` over live conversions.
- Check `conversion-provisional`, severities (warning, warning, error) for exploratory, pilot, systematic: documents whose default conversion comes from a provisional converter. `MethodsReport.conversions` with the census; `render_methods` adds one sentence naming each converter, version and count, and that the choice is provisional, rendered only when a provisional conversion exists.
- `document status` prints, for a `no-converter` failure, the remedy `factory document converters`.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(document): check and methods state provisional conversions`.

**Tests (later):** `test_check_finding_counts_documents`; `test_methods_sentence_only_when_provisional`; `test_methods_unchanged_without` (golden); `test_agent_methods_keeps_the_sentence`.

### Task 3: File names in the researcher's view

*Tier: standard (ruling 19).*

**Files:** Modify `imports/model.py`, `imports/pdfs.py`, `services/imports.py`, `cli/main.py`, `cli/render.py`.

**Interfaces:**
- `Attachment` is unchanged. `ParsedImport` gains `local_paths: Mapping[int, str]` (ordinal to relative path). `_archive` writes the library manifest as `[path_sha256, record_sha256, relative_path]` per record. The manifest is in the git-ignored library, as ruling 19 allows, and `file_hash` keeps naming it, so the event schema does not change. Check for other readers of the manifest before changing its shape.
- Produces: `import_file_names(project, import_id) -> dict[int, str]` (empty for a two-column manifest of an earlier import, and for a library entry that is gone).
- `import show --researcher` gains a `file` column for a `pdfs` import. The default view (hashes, no ordinals) is unchanged.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(imports): file names in the researcher's record view`.

**Tests (later):** `test_researcher_view_lists_files`; `test_old_manifest_reads_without_names`; `test_no_path_in_events_or_blobs`; `test_default_view_unchanged`; `test_import_status_tool_carries_no_path`.

### Task 4: Junk titles and the first-page hint

*Tier: standard.*

**Files:** Modify `imports/pdfs.py`, `imports/model.py`, `services/imports.py`, `cli/main.py`, `cli/render.py`.

**Interfaces:**
- `_metadata_title` returns `None` for a title that matches a fixed list: starts `Microsoft Word`, ends in `.doc`, `.docx`, `.tex`, `.pdf`, `.dvi`, `.indd`; `untitled`; `title`, `document`, `paper`, `manuscript` with optional digits; fewer than 8 characters; no letters. Flag `title-metadata-rejected` on the record. `PARSER_VERSION` becomes `…+rf2`.
- Produces: `first_page_hint(data: bytes) -> str | None` (first non-empty line of page 1, at most 200 characters; a reader failure gives `None`). Never stored.
- CLI: `import show --researcher --hints` reads each attachment from the library and prints the hint in a column, for records with no title. The agent surfaces never call it.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(imports): reject junk PDF titles; first-page hint for the researcher`.

**Tests (later):** `test_title_filter_cases` (parametrised, each pattern and two real-looking titles that pass); `test_flag_recorded`; `test_hint_never_stored`; `test_hint_needs_researcher_flag`.

### Task 5: `import describe`

*Tier: critical (events, identity, projection). Bumps the projection. PD-2.*

**Files:** Modify `model/imports.py`, `events/catalog.py`, `index/imports.py`, `index/default.py`, `services/imports.py`, `services/import_resolve.py`, `services/import_admit.py`, `services/modules/imports.py`, `cli/main.py`, `cli/render.py`.

**Interfaces:**
- Produces: event `import.record_described`, `ImportRecordDescribed(import_id, ordinal, title, authors, year, doi, arxiv, venue, type, abstract, rationale)`, each field bounded as `bounded_fields` bounds it; human actor only. Table `import_descriptions(import_id, ordinal, event_id, fields)`, the latest event winning.
- `describe_record(project, actor, import_id, ordinal, fields, *, rationale) -> None`; refused when the record is malformed, when an admission plan already names it, or when nothing changes. `describe_records(project, actor, import_id, path: Path) -> DescribeSummary` for a CSV of `ordinal,title,authors,year,doi,arxiv,venue` (the CSV is read, never archived, and applied per row with a per-row report).
- `effective_fields(project, import_id, ordinal) -> ImportFields`: description over record. `resolvables`, `importlist_entries`, the `titled` column of `_rows` and `import show` read it. The record's `outcome`, `record_sha256`, split part and `import.recorded` counts are untouched.
- CLI: `factory import describe IMP ORDINAL [--title T] [--author A …] [--year Y] [--doi D] [--arxiv X] [--venue V] [--abstract TEXT] --rationale R`; `factory import describe IMP --csv FILE --rationale R`. After a description the researcher re-runs `import resolve`, which supersedes the earlier resolution (Import-B invariant), so the command prints that reminder.

- [ ] **Step 1:** Implement, bump `PROJECTION_VERSION` and its pin test. **Step 2:** Commit `feat(imports): researcher descriptions of import records`.

**Tests (later):** `test_described_title_resolves`; `test_agent_actor_refused`; `test_admitted_record_refused`; `test_original_record_unchanged`; `test_split_unchanged`; `test_csv_partial_success`; `test_rebuild_identical`; `test_forged_description_changes_nothing` in `tests/test_forged_events.py`.

### Task 6: Incremental admission and honest counts

*Tier: critical (PRISMA, admission).*

**Files:** Modify `services/import_admit.py`, `services/import_resolve.py`, `cli/render.py`, `cli/main.py`.

**Interfaces:**
- `admit_import` refuses only when no record is left to admit. `_plan` leaves out the keys of every earlier plan whose run retrieved them. A later admission is a new `import.admission_planned` with only the new keys. Update the module invariant.
- `AdmissionSummary.unadmittable: int` from `_Plan.unadmittable`; `import_admit_lines` prints it with `factory import show --researcher` as the next step (iterate line 22).
- `_decide_import` in the CLI also calls `import_tags_as_labels` after a confirmation, so a tag does not lag (iterate line 80).
- `resolve_import` keeps the link state of a record whose work is already admitted (iterate line 22d). Today no guard stops a re-resolve from rewriting it, and Task 5 makes re-resolving routine.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(imports): admit newly described records; report what could not be admitted`.

**Tests (later):** `test_second_admission_adds_only_new_records`; `test_nothing_left_refused`; `test_prisma_counts_each_work_once`; `test_unadmittable_counted`; `test_tags_applied_after_confirm`; `test_re_resolve_keeps_admitted_links`.

### Task 7: Abstract on `importlist` works

*Tier: standard. PD-4 [confirm].*

**Files:** Modify `sources/importlist.py`, `services/import_admit.py` (`importlist_entries`).

**Interfaces:** `ImportlistEntry.abstract: str | None`; the work's `abstract` is set from it. The work id does not use it, so ids are unchanged. Update the module docstring, which says abstract is not used.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(imports): importlist works keep the record's abstract`.

**Tests (later):** `test_abstract_reaches_screening_batch`; `test_quote_in_abstract_verifies`; `test_work_id_unchanged_by_abstract`.

### Task 8: Library-only protocol

*Tier: critical (protocol gates). PD-3 [confirm].*

**Files:** Modify `services/protocol_rules.py`, `services/modules/imports.py`, `services/check.py`, `services/methods.py`.

**Interfaces:**
- `_gaps`: when `mode` is exploratory or pilot and `spec.library_sources` has an entry with role `corpus`, the `sources` and `queries` gaps are not raised. `systematic` is unchanged. Readiness and PRESS stay required for the import queries (`search_authorization`, Import-B): confirm that a PRESS review with no query to review can be recorded and confirmed, and if it cannot, make it return an empty finding set rather than waive it.
- Check `search-none` (warning, warning, error): the corpus has no search-purpose run. Methods adds one sentence saying that the corpus is the researcher's library and that no database search was run, with no recall figure implied.
- `seed`-based coverage: confirm that nothing in `screen_next` or `calibrate draw` needs a seed. `check` keeps reporting seed gaps as it does now.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(protocol): a protocol may rest on a declared library alone`.

**Tests (later):** `test_library_only_ready_in_pilot`; `test_library_only_refused_in_systematic`; `test_reference_role_does_not_waive`; `test_prisma_with_no_database_rows`; `test_end_to_end_library_only_to_extraction` (synthetic PDFs, fake converter).

### Task 9: Identity check on `fulltext import`

*Tier: standard (provenance). PD-5 [confirm]. IDEA-26.*

**Files:** Modify `services/fulltext_import.py`, `services/import_attach.py` (expose the title check), `cli/main.py`, `cli/render.py`.

**Interfaces:**
- Move the normalised title-in-first-page check of `import_attach` to a public `title_on_first_page(data: bytes, title: str) -> bool` in `imports/pdfs.py`. `ImportReport.identity_unchecked: list[str]`. A file matched only through first-page text whose work title is not on page 1 lands there. A filename identifier stays accepted, since the researcher named it.
- CLI: `factory fulltext import FOLDER [--accept FILE …]`: `--accept` takes a listed file name and records it, as the researcher's act.

- [ ] **Step 1:** Implement. **Step 2:** Commit `fix(fulltext): cross-check identity of first-page matches`.

**Tests (later):** `test_cited_doi_on_page_one_not_attached`; `test_filename_identifier_accepted`; `test_accept_records_document`; existing `import_folder` tests pass unedited except the new list.

### Task 10: Runbook

*Tier: light.*

**Files:** Create `docs/runbook-pdf-pilot.md`; add a pointer at the head of `docs/runbook-fulltext-usecase.md`, whose status line predates extraction; note the plan in `docs/specs/slice-3d-regions-import.md`'s implemented notes.

**Content:** setup (extras, `FACTORY_DOCLING_MODELS`, `--plugin-dir plugin`); the two routes (`.bib` or CSL with `file` fields, or a bare folder); `--no-split` and what it means (a split draws a third of the researcher's own PDFs as held-out; coverage is labelled `optimistic` without it, ruling 23); `import pdfs`, `show --researcher --hints`, `describe`, `resolve`, `confirm`, `admit`; screening without an abstract (`cannot-assess`); `import attach`; `document converters`, `document convert --converter docling`; what to do when decision 49 lands; what a crash between two admission queries leaves and how to re-run it (iterate line 22e). Each command is checked against `cli/main.py` when written.

- [ ] **Step 1:** Write. **Step 2:** Commit `docs: runbook for a pilot on a folder of PDFs`.

## Self-review notes

- The plan adds no MCP tool, so it does not touch `mcp/server.py` or its pin test, and it stays clear of plan MS.
- `cli/main.py` is touched in `document_app`, `import_app` and `fulltext_app` only.
- `services/check.py` changes by rule registration only. Findings live with the import and conversion hits.
- Not taken: OCR (excluded by slice 2), GROBID adapter, PDF manuscripts (W-C, spec Later, after decision 49).

## Later (not v1)

- Wiring decision 49's winner into `default_converters()` (plan B2 Task 8), emptying `PROVISIONAL_CONVERTERS`.
- PDF manuscripts, after decision 49 and W-C (slice 7b Later).
- A batch command that chains import, resolve and admit, if the pilot shows the separate steps cost more than they give.
- `identity-unchecked` for filename identifiers, if pilot use shows mislabelled files.

## Implementation notes (2026-11-06, branch `plan-pdf-intake`)

Decision 49 landed before this plan was built, so Tasks 1 and 2 shrank: PD-1 is moot, and the opt-in became an override (`--converter NAME`, single-valued), with `document converters` kept as the setup check. `PROVISIONAL_CONVERTERS` and `conversion-provisional` were dropped. Task 2's census and methods paragraph stay, as reporting. Check code `conversion-not-chosen` replaces the provisional one.

Added by following the path to `document_read`, none of it in the tasks above: a record no source knows takes its file through the work `importlist` built from it (the attach step otherwise listed it unresolved for good); `import resolve --described`; a library-only protocol with no seed draws its calibration set without a split (Task 8 asked to confirm no seed was needed: the draw refused); `calibrate draw` prints the works. `import.record_described` carries the plan's fields plus nothing else; the table also holds `pending`. See decision 99.
