# Import A: Parsing, Archiving and Splitting an Existing Library — Implementation Plan (slice 3d)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** Task 5 bumps `PROJECTION_VERSION` by one from the value it finds. Slice M is merged before this plan: the import module (kind `retrieval`) is declared in `services/modules/imports.py` in the task that adds its events (Task 3).

> **Dependencies.** Slice-1 plans (search, dedup, seeds) and plan 2A (library, `sniff_identifiers`) merged. Independent of slices 3a–3c. Import-B and Import-C consume this plan's Interfaces blocks exactly. Every existing test passes unchanged except the `PROJECTION_VERSION` pin.

**Goal:** Read a BibTeX file, a CSL JSON file or a folder of PDFs into allow-listed import records, archive the export verbatim in the library, record the import as one event, draw a development/held-out split when the import precedes the search, and project imports and records into the index.

**Architecture:** Pure parsers in a new package `factory/imports/` (`bibtex.py`, `csl.py`, `pdfs.py`, `model.py`, `registry.py`) return `ParsedImport` values; `services/imports.py` archives, validates, splits and records; `index/imports.py` folds `import.recorded` and `import.split_drawn` into `imports` and `import_records`. No network; no agent tool (imports are CLI only, decision 46 item 7 pattern).

**Tech Stack:** Python 3.11, pydantic, SQLAlchemy core, typer; new dependency `bibtexparser>=1.4.1,<2` (spec ruling 18); `pypdf` already present.

**Spec:** `docs/specs/slice-3d-regions-import.md` rulings 17–20, 23; acceptance 11, 13 (split part), 17 (rebuild part).

## Rulings made in this plan

1. **Allow-list.** `ImportFields` holds exactly: `title`, `authors` (list of display names, at most 50, then `et al.` flag), `year`, `doi`, `arxiv`, `url`, `venue`, `type` (`article|inproceedings|preprint|book|thesis|report|other`), `abstract` (at most 5,000 characters, truncation flagged), `tags` (at most 50, each at most 60 characters). Anything else in the export is ignored after hashing. `record_sha256` is the SHA-256 of the record's raw source text (the BibTeX entry as `bibtexparser` re-serialises it with sorted fields; the CSL item as canonical JSON; the PDF file's bytes).
2. **arXiv in BibTeX.** `eprint` with `archivePrefix = arXiv` (case-insensitive), or `journal = arXiv preprint arXiv:<id>`, or a DataCite arXiv DOI, gives `arxiv`; DOIs and arXiv ids are normalised with `normalize_doi` and `normalize_arxiv` (`model/work_ids.py`).
3. **Attachments.** BibTeX `file` (Zotero form `Description:path:mime;…`) and CSL `attachments` are read for the first `application/pdf` file; the record keeps `attachment = (path_sha256, content_sha256 | None)`; the bytes, when readable relative to the export's folder, go to the library at import time (spec ruling 24). A missing file gives `content_sha256 = None`.
4. **Parse outcomes.** Each raw record is `parsed`, `no-title-no-identifier` (kept, unresolvable), or `malformed` (counted; nothing kept but its hash). The import is refused (nothing written) only when the file cannot be read as its format at all.
5. **Split timing.** A split is drawn when no `search.run_started` of purpose `search` exists at import time; seed `random_seed` is drawn from the clock's microseconds unless given, and recorded. Records are split with `draw_split` (seeds service) over `(record key, year)`. After the first search run, `import.split_drawn` records `mode = post-search` and no parts. The researcher may decline a pre-search split (`--no-split`): `mode = declined`, no parts, and every coverage report of the import is labelled `optimistic` (Import-C).

## Global Constraints

- The platform never calls a model. Events are the source of truth; the index is written by the projector alone; the projector reads `blobs/`, never the library.
- No note, `annote`, abstract beyond the allow-list, or file path enters an event or a git-tracked blob; paths are hashed.
- Invalid input writes nothing and returns structured errors (`FactoryValidationError` with `ValidationIssue`s).
- Business logic in `services/`; parsers are pure; `cli/` parses and formats only.
- `uv run pytest -m "not network and not slow"`, `mypy --strict`, ruff pass; coverage ≥ 90% for `services/` and `model/`.

## Review Focus

1. A BibTeX fixture whose entries contain `annote`, `file` paths and personal notes yields events and blobs with none of that text (Task 3, `test_no_private_text_outside_library`).
2. The same file imported twice records two imports with the same `file_hash` and identical record blobs (Task 3, `test_reimport_is_deterministic`).
3. A pre-search import splits; a post-search import does not; agents never see the parts (Task 4, `test_split_only_before_search`).

## File Structure

- Create `imports/__init__.py`, `imports/model.py`, `imports/bibtex.py`, `imports/csl.py`, `imports/pdfs.py`, `imports/registry.py`.
- Create `model/imports.py` (event payloads), `services/imports.py`, `index/imports.py`; modify `events/catalog.py`, `index/default.py`, `cli/main.py`, `pyproject.toml`.
- Tests: `test_imports_bibtex.py`, `test_imports_csl.py`, `test_imports_pdfs.py`, `test_imports_service.py`, `test_imports_index.py`, `test_cli_imports.py`; fixtures under `tests/fixtures/imports/` (hand-written, off-topic titles; no pilot works).

---

### Task 1: Import record model and BibTeX parser

*Tier: critical (what may leave the library).*

**Files:** Create `imports/model.py`, `imports/bibtex.py`; modify `pyproject.toml`; Test `tests/test_imports_bibtex.py`, fixture `tests/fixtures/imports/zotero.bib`.

**Interfaces:**
- Consumes: `normalize_doi`, `normalize_arxiv`, `arxiv_id_from_doi` (`model/work_ids.py`).
- Produces (`imports/model.py`): `ImportFormat(StrEnum)`: `BIBTEX = "bibtex"`, `CSL = "csl"`, `PDFS = "pdfs"`; `ParseOutcome(StrEnum)`: `PARSED`, `NO_TITLE_NO_IDENTIFIER`, `MALFORMED`; `class ImportFields(StrictModel)` (ruling 1); `class Attachment(StrictModel)`: `path_sha256: str`, `content_sha256: str | None`; `class ImportRecord(StrictModel)`: `ordinal: int` (from 1, file order), `outcome: ParseOutcome`, `fields: ImportFields | None`, `record_sha256: str`, `attachment: Attachment | None`, `flags: tuple[str, ...]` (`abstract-truncated`, `authors-truncated`); `@dataclass(frozen=True) ParsedImport(format: ImportFormat, parser: str, parser_version: str, records: tuple[ImportRecord, ...], attachment_bytes: Mapping[str, bytes])` (content hash → bytes, never serialised).
- Produces (`imports/bibtex.py`): `PARSER = "bibtexparser"`; `PARSER_VERSION: str` (the installed `bibtexparser.__version__` plus `+rf1`); `parse_bibtex(data: bytes, base: Path | None) -> ParsedImport`; raises `ImportFormatError(Exception)` (in `imports/model.py`) when the bytes are not BibTeX.

- [ ] **Step 1: Tests.**
```python
def test_latex_accents_and_braces(): r = one('@article{k, title={{\\"U}ber {BERT}}, author={M{\\"u}ller, A. and Li, B.}, year=2021}')
    assert r.fields.title == "Über BERT" and r.fields.authors == ["Müller, A.", "Li, B."] and r.fields.year == 2021
def test_string_macros_and_concatenation(): ...       # @string{j = "J. ML"}, journal = j # " Res." -> venue "J. ML Res."
def test_arxiv_from_eprint_and_journal_and_datacite(): ...   # ruling 2, three forms give the same arxiv id
def test_doi_normalised(): assert one('... doi={https://doi.org/10.1000/ABC}').fields.doi == "10.1000/abc"
def test_keywords_become_tags(): assert one('... keywords={vision, linear attention}').fields.tags == ["vision", "linear attention"]
def test_zotero_file_field(tmp_path): ...             # attachment.path_sha256 set; content_sha256 = sha of the pdf bytes; bytes in attachment_bytes
def test_missing_attachment_file(): ...               # content_sha256 is None
def test_no_title_no_identifier_kept(): ...           # outcome NO_TITLE_NO_IDENTIFIER, fields kept
def test_malformed_entry_counted_not_fatal(): ...
def test_not_bibtex_raises(): with pytest.raises(ImportFormatError): parse_bibtex(b"\x00\x01", None)
def test_record_hash_stable_under_field_order(): ...  # same entry, fields reordered -> same record_sha256
def test_annote_not_in_fields(): assert "annote" not in one('... annote={my private note}').model_dump_json()
```
- [ ] **Step 2:** Run `uv run pytest tests/test_imports_bibtex.py`; FAIL. **Step 3:** Implement; `bibtexparser` with `homogenize_fields`, `convert_to_unicode` customisation; ordinal in file order. **Step 4:** Tests; `uv run mypy --strict src`; `uv run ruff check`. **Step 5:** Commit `feat(imports): import records and BibTeX parser`.

### Task 2: CSL JSON and PDF-folder parsers, registry

*Tier: standard.*

**Files:** Create `imports/csl.py`, `imports/pdfs.py`, `imports/registry.py`; Test `tests/test_imports_csl.py`, `tests/test_imports_pdfs.py`.

**Interfaces:**
- Consumes: `ImportRecord`, `ImportFields`, `sniff_identifiers(path) -> tuple[set[str], Source]` (`services/fulltext_import.py`; moved to `factory/imports/pdfs.py` and re-exported from its old module so `test_fulltext_import.py` passes unchanged).
- Produces: `parse_csl(data: bytes, base: Path | None) -> ParsedImport` (CSL `title`, `author[].family/given`, `issued.date-parts`, `DOI`, `URL`, `container-title`, `type`, `abstract`, `keyword`; arXiv from `number` when `publisher` is arXiv, or from URL or DOI); `parse_pdf_folder(folder: Path) -> ParsedImport` (one record per `*.pdf` in sorted path order; fields: identifiers from `sniff_identifiers`, `title` from PDF metadata when present; `record_sha256` = file bytes hash; `attachment` = the file itself); `PARSERS: Mapping[ImportFormat, Callable[[Path], ParsedImport]]`; `parse(format: ImportFormat, path: Path) -> ParsedImport`.

- [ ] **Step 1: Tests.** `test_csl_zotero_export_fields`, `test_csl_arxiv_preprint`, `test_csl_not_json_raises`, `test_pdf_folder_identifier_from_filename`, `test_pdf_folder_metadata_title_only` (no identifier: `fields.title` from metadata, outcome `PARSED`), `test_pdf_folder_nothing_found` (outcome `NO_TITLE_NO_IDENTIFIER`), `test_not_pdf_skipped_and_flagged`, `test_registry_dispatch`, `test_sniff_identifiers_reexported` (`from factory.services.fulltext_import import sniff_identifiers` still works).
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(imports): CSL JSON and PDF-folder parsers`.

### Task 3: `import.recorded` and the import service

*Tier: critical (provenance root of every imported work).*

**Files:** Create `model/imports.py`, `services/imports.py`; modify `events/catalog.py`; Test `tests/test_imports_service.py`.

**Interfaces:**
- Consumes: `parse`, `Project.library.put(bytes) -> str`, `Project.blobs.put_json`, `Project.record`, `Project.events.make`, `Project.ids.new`, `Project.human_actor()`, `canonical_json`.
- Produces (`model/imports.py`): `ImportRole(StrEnum)`: `REFERENCE = "reference"`, `CORPUS = "corpus"`; `IMPORT_ID_RE = r"^imp_[0-9A-HJKMNP-TV-Z]{26}$"`; `RECORD_KEY_RE = r"^imp_[0-9A-HJKMNP-TV-Z]{26}:[1-9][0-9]*$"`; `class ImportRecorded(StrictModel)`: `import_id`, `format: ImportFormat`, `role: ImportRole`, `collection: str | None` (≤ 120 chars), `parser`, `parser_version`, `file_hash: str` (library ref; for a folder, the hash of the canonical JSON list of `(path_sha256, content_sha256)`), `records_blob: str` (blob of `[record.model_dump()]`), `counts: dict[ParseOutcome, int]`, `attachments: int`, `attachments_missing: int`.
- Produces (`services/imports.py`): `class ImportSummary(StrictModel)`: `import_id`, `counts`, `attachments`, `attachments_missing`, `split: Literal["drawn", "post-search", "declined"]`; `record_import(project: Project, path: Path, *, format: ImportFormat, role: ImportRole, collection: str | None = None, random_seed: int | None = None, split: bool = True) -> ImportSummary`; `import_records(project: Project, import_id: str) -> list[ImportRecord]` (from the projection and blob); `record_key(import_id: str, ordinal: int) -> str`.
- Event type `import.recorded` (schema 1), refs `(import_id,)`, human actor.

- [ ] **Step 1: Tests.**
```python
def test_record_import_writes_one_event_and_archives(project, bib_path):
    s = record_import(project, bib_path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE)
    ev = only_event(project, "import.recorded"); assert ev.payload.import_id == s.import_id
    assert project.library.get(ev.payload.file_hash) == bib_path.read_bytes()
def test_no_private_text_outside_library(project, bib_with_notes):          # Review Focus 1
    record_import(...); assert not grep_git_tracked(project, ["my private note", "/Users/", "annote"])
def test_reimport_is_deterministic(project, bib_path): ...                   # Review Focus 2
def test_attachment_bytes_in_library(project, bib_with_pdf): ...
def test_unreadable_file_writes_nothing(project, tmp_path): ...             # FactoryValidationError field "path"
def test_actor_is_human(project, bib_path): ...
def test_collection_length_validated(project, bib_path): ...
```
- [ ] **Step 2–5:** Run, FAIL; implement (parse → validate → library puts → blob → one event, under `project.index.exclusive()`); tests, mypy, ruff; commit `feat(imports): record an import with its archived export`.

### Task 4: Development/held-out split

*Tier: critical (held-out discipline, I8).*

**Files:** Modify `model/imports.py`, `services/imports.py`; Test `tests/test_imports_split.py`.

**Interfaces:**
- Consumes: `draw_split(positives, random_seed)` (`services/seeds.py`), search runs in the index (`runs` table, purpose via `queries`).
- Produces: `class ImportSplitDrawn(StrictModel)`: `import_id`, `mode: Literal["drawn", "post-search", "declined"]`, `random_seed: int | None`, `parts_blob: str | None` (blob `{"development": [ordinals], "held_out": [ordinals]}`); event `import.split_drawn` written in the same `project.record` call as `import.recorded`; `import_part(project, import_id, ordinal) -> Literal["development", "held-out", "unsplit"]`; `development_ordinals(project, import_id) -> list[int]`.

- [ ] **Step 1: Tests.** `test_split_only_before_search` (Review Focus 3: a project with a recorded search-purpose run gets `post-search`; a fresh one gets parts whose union is the parsed ordinals and whose sizes follow `draw_split`), `test_split_reproducible_from_seed`, `test_probe_runs_do_not_count_as_search` (probe-purpose runs leave the split on), `test_malformed_records_not_split`.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(imports): development and held-out parts of a pre-search import`.

### Task 5: Projection

*Tier: standard.*

**Files:** Create `index/imports.py`; modify `index/default.py` (`PROJECTION_VERSION` bump, table registration); Test `tests/test_imports_index.py`.

**Interfaces:**
- Produces tables: `imports(import_id PK, format, role, collection, parser, parser_version, file_hash, records_blob, split_mode, split_seed, recorded_at, event_id)`; `import_records(import_id, ordinal, outcome, title, first_author, year, doi, arxiv, url, venue, type, record_sha256, attachment_path_sha256, attachment_content_sha256, part)`, PK `(import_id, ordinal)`, indexes on `doi`, `arxiv`. Abstract and tags are not projected (read from the blob on demand), so the index stays small at 10^5 records.

- [ ] **Step 1: Tests.** `test_projection_rows_match_blob`, `test_part_column_from_split`, `test_rebuild_identical_state_hash` (`factory rebuild` twice), `test_projection_version_bumped`.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(index): imports and import records`.

### Task 6: CLI `factory import bib|csl|pdfs|list|show`

*Tier: standard.*

**Files:** Modify `cli/main.py`, `cli/render.py`; Test `tests/test_cli_imports.py`.

**Interfaces:**
- Produces: `factory import bib PATH --role {reference,corpus} [--collection NAME] [--seed N] [--no-split]`, `factory import csl PATH …`, `factory import pdfs FOLDER …`, `factory import list`, `factory import show IMP [--part development|held-out|all]` (the CLI shows all parts; it is the researcher's view). `--role corpus` is accepted here; its protocol gate is enforced at admission (Import-B).

- [ ] **Step 1: Tests.** `test_cli_bib_prints_counts_and_id`, `test_cli_refuses_missing_file_writes_nothing`, `test_cli_show_lists_parts`, `test_cli_list_orders_by_time`.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(cli): factory import`.

**Verification for the plan:** `cd platform && uv run pytest -m "not network and not slow" && uv run mypy --strict src && uv run ruff check`.

## Later (not v1)

None: every task of this plan is in v1.
