# Document Conversion, Library Storage and `document_read` Implementation Plan (slice 2, sub-plan B2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn every retrieved document into canonical Markdown plus manifest in the project library, record it as an event, and let agents read it by anchor (`document_read`), with the quote primitive that plans C and D need.

**Architecture:** B1 delivered `factory/document/` (anchors, anchoriser, `Converter`, `convert`, our LaTeXML-HTML converter). B2 adds the event model and projection (`document.converted`, `document.conversion_failed`), a converter registry, a conversion service that stores Markdown and manifest as library blobs, a read service with the gate and pagination, a verbatim quote check, `check` integration, a CLI group and one MCP tool. The choice of converters for LaTeX and PDF depends on decision 49, so wiring them is the last task and everything before it runs without it. Decision 49 was decided on 2026-11-05 and Task 8 wired the choice.

**Tech Stack:** as plan B1. No new dependencies until Task 8 (optional extras).

**Spec:** `docs/specs/slice-2.md` (Canonical document; Verification, quote check; acceptance 2, 3, 7 in part, 15 in part). Rulings 1–8 of `docs/plans/2026-11-03-converter-bakeoff.md`. Decisions 39, 40, 46–48.

## Rulings made in this plan

1. **Document version = conversion.** A document (`doc_…`) is one retrieved source. Each conversion of it by a (converter, converter version) pair is one *conversion* (`cnv_…`); quotes cite a conversion, so old anchors stay resolvable (acceptance 3).
2. **Idempotent conversion.** Converting a document with a (converter, version) pair that already has a conversion writes nothing and reports `unchanged`. A bumped converter version writes a new conversion; the old one stays readable by `conversion_id`.
3. **Failures are events, not errors.** No converter for the media type, converter tool absent, or a converter/manifest error each write `document.conversion_failed` with a fixed-vocabulary reason (never an exception message, which may embed document text) and the batch continues. A missing raw blob is reported in the summary only (`raw-missing`, no event): `check` already reports it and `fulltext restore` fixes it.
4. **Actors.** Conversion is the researcher's act (ruling 6 of B1): events carry the human actor. Agents only read.
5. **Default conversion** of a work: the latest conversion (by event order) of the first live converted document in order arxiv-html, arxiv-source, oa-pdf, researcher-supplied. `document_id` or `conversion_id` overrides.
6. **Paging.** Segments are the manifest's non-cell anchors in document order. A page stops after `limit` segments or once `max_chars` of text is reached (at least one segment is always returned). A segment longer than 8000 characters is cut and flagged `truncated`; a single anchor read (`anchor=`) returns up to 40000 characters, also flagged. Cells are read through their own anchor.
7. **Quote normalisation** (declared): Unicode NFKC (folds ligatures), soft hyphens and zero-width characters removed, whitespace runs collapsed to one space, ends stripped. Case is preserved. The element text compared is the plain text of its Markdown (markup and escapes removed), not the Markdown source.
8. **Tiers** (memory `sdd-review-tiers`): Task 1 (events, index) gets a Sonnet task review; Tasks 2–7 Haiku; Task 8 is gated and reviewed on Haiku.

## Global Constraints

- All plan-A and B1 constraints hold. No model calls; no LLM in conversion. Events carry hashes, counts and fixed vocabulary only; **no document text in any event, warning or error message**.
- Literature (raw, Markdown, manifest) lives only in the git-ignored library; no test may write it to a tracked path.
- `uv run pytest -m "not network"`, `mypy --strict` (new and changed files) and ruff pass. Coverage ≥ 90% for `services/` and `model/`.
- Business logic in `services/`; `mcp/` and `cli/` parse, call, format.

## Review Focus

1. A converter that raises `ManifestError` on one document writes `document.conversion_failed` with reason `conversion-error`, stores no blob, and the rest of the batch still converts (Task 3).
2. A media type no registered converter accepts (e.g. a PDF before Task 8) records `no-converter`; `document_read` for a work with only that document is refused with a message naming `factory document convert` (Tasks 3, 4).
3. Converter version bump → second conversion; the first is still readable by `conversion_id` and its manifest unchanged (Tasks 3, 4).
4. A quote differing from the element only by ligature, NBSP, soft hyphen or line break matches; one differing by a word, or empty after normalisation, does not (Task 2).
5. A deleted Markdown blob: `document_read` fails naming `factory document convert --restore`, `check` warns, and the restore regenerates the same hash (Tasks 4, 5).

## File Structure

- Create `platform/src/factory/model/document.py` — event payloads and vocabulary.
- Create `platform/src/factory/index/document.py` — projection tables and handlers.
- Modify `platform/src/factory/events/catalog.py`, `platform/src/factory/index/default.py` — register.
- Modify `platform/src/factory/document/anchors.py` — `Manifest.from_json`.
- Create `platform/src/factory/document/quotes.py` — plain text and quote check.
- Create `platform/src/factory/document/registry.py` — `ConverterRegistry`, `default_converters`.
- Create `platform/src/factory/services/document_convert.py` — convert, restore, status.
- Create `platform/src/factory/services/document_read.py` — read, resolve.
- Modify `platform/src/factory/services/check.py` — conversion blobs in the library scan.
- Modify `platform/src/factory/cli/main.py`, `cli/render.py`, `mcp/server.py` — surfaces.
- Tests: `platform/tests/test_document_model.py`, `test_document_index.py`, `test_document_quotes.py`, `test_document_convert.py`, `test_document_read.py`, `test_check_conversions.py`, `test_mcp_document.py`, `test_cli_document.py`, `test_acceptance_document.py`, helper `tests/document_helpers.py`.

---

### Task 1: Events and projection

**Files:** Create `model/document.py`, `index/document.py`; modify `events/catalog.py`, `index/default.py`; Test `tests/test_document_model.py`, `tests/test_document_index.py`.

**Interfaces:**
- Consumes: `StrictModel`, `BLOB_REF_RE`, `ULID_RE`, `DOCUMENT_ID_RE`, `AnchorKind`.
- Produces:
  - `CONVERSION_ID_RE = rf"^cnv_{ULID_RE}$"`.
  - `class FailureReason(StrEnum)`: `NO_CONVERTER="no-converter"`, `CONVERTER_UNAVAILABLE="converter-unavailable"`, `CONVERSION_ERROR="conversion-error"`.
  - `class Converted(StrictModel)`: `conversion_id`, `document_id`, `converter: NonBlank`, `converter_version: NonBlank`, `raw_hash`, `markdown_hash`, `manifest_hash` (all `BLOB_REF_RE`), `counts: dict[str, int]` (keys exactly the `AnchorKind` values, each ≥ 0), `warnings: list[NonBlank]` (≤ 50 items, each ≤ 200 chars).
  - `class ConversionFailed(StrictModel)`: `document_id`, `converter: NonBlank | None`, `reason: FailureReason`, `error_class: NonBlank | None`; `error_class` present exactly when reason is `conversion-error`.
  - Event names `document.converted`, `document.conversion_failed` (schema 1).
  - Tables `document_conversions` (all `Converted` fields; `warnings` as JSON text, `counts` as JSON text, `event_id`; unique on `(document_id, converter, converter_version)`) and `document_failures` (`event_id` PK, the `ConversionFailed` fields).

- [ ] **Step 1: Tests.** `test_document_model.py`: `test_converted_requires_every_kind_count` (missing key → `ValidationError`), `test_converted_rejects_negative_count`, `test_failed_error_class_only_for_conversion_error` (both directions), `test_warning_cap`. `test_document_index.py`: `test_converted_projects_one_row`, `test_repeated_event_changes_nothing` (replay twice, one row), `test_second_version_gives_second_row`, `test_failure_projects`, `test_rebuild_gives_same_state_hash` (follow `test_fulltext_index.py`).
- [ ] **Step 2:** Run `uv run pytest tests/test_document_model.py tests/test_document_index.py -v`; expect FAIL (module missing).
- [ ] **Step 3: Implement** the models, tables and handlers; handlers are total (`on_conflict_do_nothing` on the unique key). Register the two event types and the handlers.
- [ ] **Step 4:** Tests, `uv run mypy --strict src/factory/model/document.py src/factory/index/document.py` and `uv run ruff check` pass.
- [ ] **Step 5:** Commit `feat(document): conversion events and projection`.

### Task 2: Quote primitive and manifest round trip

**Files:** Create `document/quotes.py`; modify `document/anchors.py`; Test `tests/test_document_quotes.py`, `tests/document/test_anchors.py` (add).

**Interfaces:**
- Produces: `Manifest.from_json(data: bytes) -> Manifest` (inverse of `to_json`; raises `ManifestError` on malformed input); `element_plain_text(markdown: str) -> str`; `normalise_quote(text: str) -> str`; `quote_in_element(element_markdown: str, quote: str) -> bool`.

- [ ] **Step 1: Tests.** `test_manifest_json_round_trip` (parse a fixture, `from_json(to_json())` equals the manifest); `test_from_json_rejects_unknown_kind`; `test_plain_text_strips_markup` (`**bold** and \_x\_ [link](u) \`c\`` → `bold and _x_ link c`); `test_quote_matches_across_ligature_nbsp_softhyphen_linebreak`; `test_quote_rejects_changed_word`; `test_quote_rejects_empty_after_normalisation`; `test_quote_is_case_sensitive`; `test_quote_must_be_contiguous`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3: Implement.** Plain text by walking `MARKDOWN.parse` inline children (text, code_inline, softbreak/hardbreak → space, image alt text kept); `normalise_quote` per ruling 7; `quote_in_element` is `normalise(quote)` non-empty and a substring of `normalise(plain_text(element))`.
- [ ] **Step 4:** Tests, mypy, ruff pass.
- [ ] **Step 5:** Commit `feat(document): verbatim quote check and manifest round trip`.

### Task 3: Registry and conversion service

**Files:** Create `document/registry.py`, `services/document_convert.py`, `tests/document_helpers.py`; Test `tests/test_document_convert.py`.

**Interfaces:**
- Consumes: `convert`, `ConverterUnavailable`, `Project`, `library`, `fulltext_documents` rows, `ROUTE_ORDER`.
- Produces:
  - `class ConverterRegistry`: `__init__(converters: Sequence[Converter])`; `for_media_type(media_type: str) -> Converter | None` (first registered that accepts it).
  - `default_converters() -> ConverterRegistry` (only `LatexmlHtmlConverter` until Task 8).
  - `class ConversionOutcome(StrictModel)`: `document_id`, `work_id`, `status: Literal["converted","unchanged","failed","raw-missing","restored"]`, `conversion_id: str | None`, `reason: str | None`.
  - `class ConvertSummary(StrictModel)`: `outcomes: list[ConversionOutcome]` and counts per status (`restored` counts the regenerated conversions of `restore_conversions`).
  - `convert_documents(project: Project, registry: ConverterRegistry, *, work_ids: Sequence[str] | None = None, document_ids: Sequence[str] | None = None) -> ConvertSummary` — targets live (not superseded) documents of promoted works, or the named ones (a named document that is unknown or superseded is a `FactoryValidationError` on `document_ids`). Raw bytes from `project.library`; Markdown and `manifest.to_json()` stored with `library.put`; the stored hash must equal `ConversionResult.markdown_hash`. Events use `project.human_actor()` and one `project.record` per document.
  - `tests/document_helpers.py`: `fetched_document(project, work_id, html: bytes) -> str` (document id, via `fetch_fulltext` with a stub route as in `tests/test_fulltext_status.py`).

- [ ] **Step 1: Tests.** `test_converts_html_document` (event written with hashes equal to a direct `convert` of the fixture `latexml_article.html`; library holds Markdown and manifest; counts match the manifest); `test_second_run_is_unchanged_and_writes_nothing`; `test_version_bump_writes_second_conversion` (stub converter wrapper with `version()` changed); `test_no_converter_records_failure` (PDF media type); `test_converter_unavailable_records_failure`; `test_manifest_error_records_failure_and_batch_continues` (Review Focus 1: two documents, first raises); `test_raw_missing_reports_without_event`; `test_named_unknown_document_refused_and_writes_nothing`; `test_event_carries_no_document_text` (scan serialized events for a distinctive sentence of the fixture); `test_library_untracked` (no file under a tracked path).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3: Implement** per the interfaces. Failure reason `conversion-error` stores only `type(exc).__name__`.
- [ ] **Step 4:** Tests, mypy, ruff pass.
- [ ] **Step 5:** Commit `feat(document): converter registry and conversion service`.

### Task 4: `document_read` service

**Files:** Create `services/document_read.py`; Test `tests/test_document_read.py`.

**Interfaces:**
- Produces:
  - `class Segment(StrictModel)`: `anchor`, `kind`, `parent: str | None`, `text`, `truncated: bool`.
  - `class DocumentPage(StrictModel)`: `work_id`, `document_id`, `conversion_id`, `route`, `quality`, `source_version`, `converter`, `converter_version`, `markdown_hash`, `segments: list[Segment]`, `next_after: str | None`, `total_segments: int`.
  - `document_read(project, *, work_id, document_id=None, conversion_id=None, after=None, anchor=None, limit=50, max_chars=20000) -> DocumentPage` per rulings 5 and 6. Gate: the work is `INCLUDED` (`final_outcomes`), a conversion exists. `limit` in 1..200, `max_chars` in 1000..100000, else `FactoryValidationError`. `anchor` and `after` together are refused.
  - `conversion_manifest(project, conversion_id) -> Manifest` and `resolve_anchor(project, conversion_id, anchor_id) -> Anchor` (raises `FactoryValidationError` on field `anchor` if absent) — the entry points plans C and D use with `quote_in_element`.

- [ ] **Step 1: Tests.** `test_default_document_follows_route_order` (arxiv-html beats oa-pdf); `test_pages_cover_every_non_cell_anchor_exactly_once` (page through with `next_after`); `test_work_not_included_refused`; `test_unconverted_work_refused_naming_convert_command` (Review Focus 2); `test_old_conversion_readable_by_id` (Review Focus 3); `test_cell_anchor_read_returns_exact_cell`; `test_long_segment_truncated_and_flagged`; `test_unknown_anchor_refused`; `test_missing_markdown_blob_names_restore` (Review Focus 5); `test_resolve_anchor_matches_manifest`; `test_limits_validated`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3: Implement** reading Markdown/manifest from the library (`BlobStore.get` verifies the hash). The service never writes.
- [ ] **Step 4:** Tests, mypy, ruff pass.
- [ ] **Step 5:** Commit `feat(document): document_read service`.

### Task 5: `check` and restore of conversions

**Files:** Modify `services/check.py`, `services/document_convert.py`; Test `tests/test_check_conversions.py`.

**Interfaces:**
- Produces: `check` reports `library-missing` (documents) and `library-corrupt` for a conversion's Markdown or manifest blob using the existing codes, with the conversion id in the hit key; `restore_conversions(project: Project, registry: ConverterRegistry) -> ConvertSummary` reconverts each conversion with missing blobs using the converter whose name and version match the record; the regenerated Markdown hash must equal the recorded one, else the outcome is `failed` with reason `hash-differs` and nothing is stored under the old record. A registry lacking that version gives `failed` / `version-unavailable`.

- [ ] **Step 1: Tests.** `test_check_warns_on_missing_markdown`, `test_check_errors_on_corrupt_manifest`, `test_restore_regenerates_same_hash` (Review Focus 5), `test_restore_with_other_converter_version_fails_cleanly`, `test_restore_writes_no_event`, `test_no_conversions_no_findings`.
- [ ] **Step 2:** Run; expect FAIL. **Step 3:** Implement. **Step 4:** Tests, mypy, ruff pass.
- [ ] **Step 5:** Commit `feat(document): check and restore for conversions`.

### Task 6: CLI and MCP surfaces

**Files:** Modify `cli/main.py`, `cli/render.py`, `mcp/server.py`; Test `tests/test_cli_document.py`, `tests/test_mcp_document.py`.

**Interfaces:**
- CLI group `factory document`: `convert [--work W]... [--document D]... [--restore]` (the researcher's act), `status` (per live document: converted or not, converter and version, counts, latest failure), `read WORK [--document D] [--conversion C] [--anchor A] [--after A] [--limit N]` (prints segments).
- MCP `document_read(project, work_id, document_id=None, conversion_id=None, after=None, anchor=None, limit=50, max_chars=20000)`; read-only; refused to a session that has joined a pass (`_refuse_pass_session`). There is no MCP convert tool.

- [ ] **Step 1: Tests.** CLI: convert then status shows the conversion; `--restore` after deleting a blob; unknown `--document` exits non-zero with structured error and writes nothing. MCP: `document_read` returns a page; refused for a pass session; refused for a non-included work; `convert` is not a registered tool.
- [ ] **Step 2:** Run; expect FAIL. **Step 3:** Implement as thin wrappers. **Step 4:** Tests, mypy, ruff pass.
- [ ] **Step 5:** Commit `feat(document): CLI group and document_read tool`.

### Task 7: Acceptance and docs

**Files:** Test `tests/test_acceptance_document.py`; modify `docs/specs/slice-2.md` (an "Implemented in plan 2B" note after the plan-2A note), `README.md` document index if it lists plans, `CLAUDE.md` Status line.

- [ ] **Step 1: Tests.** `test_conversion_is_deterministic` (acceptance 2: two projects, same raw, same hashes); `test_old_quote_still_verifies_after_new_version` (acceptance 3: quote verified with `quote_in_element` against the first conversion after a second exists); `test_cell_anchor_resolves_to_one_cell` (acceptance 7, platform part); `test_no_literature_in_tracked_paths` (acceptance 15 part); `test_rebuild_from_events_matches` (index rebuilt equals state hash).
- [ ] **Step 2:** Run; expect PASS or fix. **Step 3:** Docs. **Step 4:** Full `uv run pytest -m "not network"`, `mypy --strict` on changed files, ruff.
- [ ] **Step 5:** Commit `test(document): plan 2B acceptance; docs`.

### Task 8 (decision 49 decided 2026-11-05): Register the chosen converters

Status: the adapters are ported and `default_converters` lists `latexml-html`, docling and pandoc, in that order; pymupdf4llm is not listed. Step 1's two named tests are not written (testing was paused on 2026-11-05). Inputs from decision 49: converter, pinned version and licence per format (LaTeX source, PDF; HTML if pandoc beat `latexml-html`).

**Files:** Create `document/pandoc.py` and/or `document/docling.py` / `document/pymupdf4llm.py` (per the decision) as ports of `experiments/converter-bakeoff/adapters/*`; modify `document/registry.py`, `platform/pyproject.toml` (optional extras, never core dependencies; AGPL/GPL tools only as subprocess or extra, per the licence notes in decision 49); Tests `tests/document/test_<tool>.py` (skip when the tool is absent) using `assert_converter_contract`.

- [ ] **Step 1:** Contract-kit tests plus `test_registry_routes_pdf_to_chosen_converter` and `test_absent_tool_records_converter_unavailable`.
- [ ] **Step 2:** Run; expect FAIL. **Step 3:** Port each adapter; an e-print archive (`application/gzip` or the media type `_eprint_media_type` returns) is unpacked in memory, with member size and count caps, before conversion. **Step 4:** Tests, mypy, ruff pass.
- [ ] **Step 5:** Commit `feat(document): register converters chosen in decision 49`.

## Self-review notes

- Spec coverage: canonical document per version (T3), anchors resolvable per version (T4), determinism and old-anchor stability (T7), quote check (T2), cell resolution (T4, T7), library hashes in events and `check` (T3, T5), `document_read` (T4, T6). Out of this plan: stage-aware screening (C), schema and number check (D), trace to cells (E).
- Types: `Converted.conversion_id` is used unchanged in T3–T6; `resolve_anchor` and `quote_in_element` are the C/D entry points.
