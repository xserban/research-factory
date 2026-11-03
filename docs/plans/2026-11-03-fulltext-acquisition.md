# Full-Text Acquisition Implementation Plan (slice 2, sub-plan A of A–E)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Slice 2 overview

Slice 2 is built in five sub-plans, all without pilot data (decision 47). **A** (this plan) acquires full text: route adapters, attempt events, the version rule, researcher-supplied import and the project-local library. **B** converts every raw source to canonical Markdown with stable anchors and provides `document_read`. Its converter is chosen by a bake-off on a fixed off-topic ML test set, whose raw sources come from A's `routes=` option, so B needs A. **C** adds full-text screening and the full PRISMA flow, and needs B's anchors for verified quotes. **D** adds the extraction schema, extraction, verification, dual extraction, agreement and audit; it needs B, and its protocol fields come before reading (R-13). **E** builds the evidence report, the trace extensions to cells and claims, and the `ml-benchmark` pack; it needs D. The order is A → B → C → D → E; C and D can overlap once B lands. After E, the linear-attention pilot runs end to end (AC 16) and re-checks the bake-off on its included works.

---

**Goal:** Every work promoted at title/abstract screening gets full text fetched by legal routes in a fixed order, or a recorded not-retrieved outcome with per-route reasons. Researcher-supplied PDFs can be imported. All raw sources live in a git-ignored, content-addressed library that `check` audits and that can be restored by hash.

**Architecture:**
- **Route adapters** live in `sources/fulltext/`. Each one turns a work into a `RouteResult`, with no events and no storage.
- **`services/fulltext.py`** orders the routes, applies the gate and the version rule, writes the raw bytes to the library, and records the events. Fetching produces `fulltext.fetch_started` (the triggering actor), one `fulltext.attempted` per route tried, `fulltext.document_added` per new document and `fulltext.source_changed` per hash mismatch.
- **The projection** gains four tables. It reads events only and never touches the library.
- **Surfaces:** `services/fulltext_status.py`, `check` and `trace` read the projection. The MCP tools and the CLI only parse input and format output.

**Tech Stack:** as slice 1 (Python ≥ 3.11, uv, pydantic, SQLAlchemy, httpx via `PoliteClient`, typer, mcp), plus `pypdf` used only to read identifiers from a PDF's first page.

**Spec:** `docs/specs/slice-2.md` (Full-text acquisition, Storage and licensing; acceptance 1, 15 and the acquisition parts of 14 and 16). Also `docs/specs/00-system.md` §3, §4.3 and §7, and `docs/specs/01-rigour.md` R-01–R-05. Decisions 39, 42.1, 44, 46 and 47 are binding. Prerequisite: slice 1 is merged (`main` at `6bc43c7` or later).

## Rulings made in this plan (confirmed by the researcher 2026-11-03; decision 46)

1. **Version within the route.** Routes are tried in fixed order. "Latest available version" means the latest version the successful route offers: for arXiv, the latest `vN` from the arXiv API at fetch time. A version of record from a later route is not compared by date across routes in slice 2.
2. **First success, or the named routes.** By default `fulltext_fetch` stops at the first route that retrieves. `routes=[…]` tries exactly the named routes in canonical order and does not stop on success; plan B's bake-off uses this. Every route tried is one `fulltext.attempted`.
3. **Document identity** is (work, route, source_version), and the document's ID is minted once. A newer `source_version` on the same route is a new document with `supersedes = <previous document>`. Documents on different routes never supersede each other.
4. **OA PDF location** comes from an OpenAlex lookup at fetch time (by DOI, else by the arXiv DataCite DOI). The response is archived in `blobs/`, which is git-tracked: it is metadata, not literature.
5. **Licence** is `str | None` with `licence_status ∈ {reported, not-reported}`. The arXiv routes record `not-reported`.
6. **Gate:** a work is fetchable once `final_outcomes(project)[work] == Outcome.PROMOTE`. There is no protocol gate in A; the "declare before reading" gate goes on `document_read` (plan B) and on extraction (plan D).
7. **Researcher-supplied import** works on a folder (no Zotero) and is CLI-only (human actor). It is allowed at any time and is recorded as an attempt on route `researcher-supplied`.
   - Matching uses identifiers only: an arXiv ID or DOI from the filename, else from the first-page text (`pypdf`).
   - Only promoted works receive documents. Unmatched, ambiguous or non-promoted files are listed in the command output, and nothing is written for them.
   - The matching is a fresh implementation; arxiv-miner's `pdf_extractor` is a pattern only.
8. **Changed source.** A re-fetch by the same (work, route, source_version) that hashes differently records `fulltext.source_changed` (expected and observed hash) and keeps the new bytes in the library. The original document stays the reference, and `check` warns until a later decision.
9. **Restore.** `restore_document` re-requests the document's recorded URL. If the hash is equal, it writes the library entry and records an attempt with outcome `restored`. If the hash differs, ruling 8 applies. A researcher-supplied document is restored only by re-importing the identical file.

## Global Constraints

- **No model calls:** `platform/` imports no model SDK.
- **Events are the source of truth:** events are append-only. The index is written only by the projector, and the projection must not read the library.
- **Layering:** business logic lives in `services/`, and `mcp/` and `cli/` only parse and format. Invalid input writes nothing and returns structured `(field, reason)` errors.
- **Library location:** `projects/<slug>/library/sha256/<2>/<62>` (decision 39). No raw full text or document is ever written under `blobs/` or anywhere else that git tracks.
- **What goes in `blobs/`:** the OpenAlex lookup response and the arXiv metadata response, both metadata; also the `input_blob` of an agent-triggered fetch.
- **No secrets in events:** the `mailto` address never reaches an event; URLs pass through `redact()` before they are recorded.
- **Network:**
  - All network goes through `PoliteClient`, with `arxiv.org` and `export.arxiv.org` at 3.0 s and any unlisted host at 1.0 s.
  - Network tests are marked `network`; everything else runs offline against recorded fixtures in `platform/tests/fixtures/fulltext/`.
  - The fixtures are tiny synthetic stand-ins: a minimal LaTeXML HTML page, a 2-file tar.gz, and a 1-page PDF generated in the test. They are never real papers.
- **Quality:** coverage ≥ 90 % for `factory.services` and `factory.model`; `mypy --strict` and ruff pass.
- **Branch and commits:** branch `plan-2a-fulltext-acquisition`. Commit after each task, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commands run from `platform/`.

## Review Focus

1. **The OA "PDF" URL returns an HTML landing page or a login wall with status 200.** Expected: an attempt with outcome `failed` and reason `not-a-pdf`, and no document. → Task 7 `test_oa_landing_page_is_not_a_pdf`.
2. **The arXiv API knows the work but the HTML rendering is missing (404) or is a LaTeXML error page.** Expected: outcome `not-available` with reason `no-html-rendering`, and the e-print route is tried next. → Task 5 `test_html_404_falls_through`, `test_html_without_ltx_document_is_not_available`.
3. **A fetch is interrupted part-way** (transport error after retries on route 2). Expected: route 1's attempt is recorded, route 2 is recorded `failed` with reason `transport`, route 3 is still tried, and the call never raises for a route failure. → Task 8 `test_transport_failure_is_an_outcome`.
4. **The same PDF is imported twice, or a PDF names two corpus works** (e.g. its own arXiv ID and a cited DOI on page 1). Expected: the second import is reported `already-imported` with no event; the two-work file is `ambiguous` and nothing is written. The filename's identifier takes precedence over first-page text. → Task 10 `test_reimport_is_idempotent`, `test_two_identifiers_in_text_is_ambiguous`.
5. **The library is absent** (fresh clone on another machine). Expected: `rebuild` and `fulltext_status` work unchanged, and `check` lists each missing entry as a warning, not an error. → Task 11 `test_status_and_rebuild_without_library`, `test_check_reports_missing_library_entry`.

---

## File Structure

```
platform/src/factory/
  services/context.py          + ProjectPaths.library_dir, Project.library (BlobStore)
  sources/http.py              + PoliteClient.fetch (non-raising), arxiv.org interval, default 1.0 s
  model/fulltext.py            Route, Quality, AttemptOutcome, LicenceStatus, event payloads
  events/catalog.py            + fulltext.fetch_started|attempted|document_added|source_changed
  index/fulltext.py            tables fulltext_fetches, fulltext_attempts, fulltext_documents,
                               fulltext_source_changes; handlers
  index/default.py             PROJECTION_VERSION "16"
  sources/fulltext/__init__.py
  sources/fulltext/base.py     RouteResult, FullTextRoute protocol, ArxivVersionLookup
  sources/fulltext/arxiv.py    ArxivHtmlRoute, ArxivSourceRoute, latest_arxiv_version
  sources/fulltext/oa_pdf.py   OaPdfRoute (OpenAlex lookup)
  sources/fulltext/registry.py default_routes()
  services/fulltext.py         fetch_fulltext, restore_document, FetchSummary
  services/fulltext_import.py  sniff_identifiers, import_folder, ImportReport
  services/fulltext_status.py  FulltextStatus, fulltext_status
  services/check.py            + library and acquisition findings
  services/trace.py            + attempt and document nodes
  mcp/server.py                + fulltext_fetch, fulltext_status
  cli/main.py                  + fulltext import|fetch|status|restore
docs/specs/00-system.md        §3 prefixes fft_, att_, doc_
platform/tests/test_library.py, test_http.py, test_fulltext_model.py, test_fulltext_index.py,
  test_fulltext_routes_arxiv.py, test_fulltext_routes_oa.py, test_fulltext_service.py,
  test_fulltext_restore.py, test_fulltext_import.py, test_fulltext_status.py,
  test_check.py, test_trace.py, test_mcp_fulltext.py, test_acceptance_fulltext.py
platform/tests/fixtures/fulltext/   arxiv_meta.xml, ltx.html, ltx_error.html, openalex_work.json
```

---

### Task 1: The library store and the git-ignore guarantee

**Files:**
- Modify: `docs/specs/00-system.md` §3 (prefixes `fft_` fetch, `att_` attempt, `doc_` document); `platform/src/factory/services/context.py`
- Test: `platform/tests/test_library.py`

**Interfaces:**
- Produces: `ProjectPaths.library_dir -> Path` (`<dir>/library`); `Project.library: BlobStore` rooted there, built in `build_project`.

- [ ] **Step 1: Write the failing tests**

```python
def test_library_lives_under_project_library(project):
    ref = project.library.put(b"%PDF-1.4 x")
    assert project.library.path(ref).is_relative_to(project.paths.dir / "library" / "sha256")

def test_library_paths_are_git_ignored(tmp_path, project):   # AC 15
    # copy the repository .gitignore into a fresh `git init` at tmp_path, lay out
    # projects/demo/library/sha256/ab/<62> and projects/demo/blobs/sha256/ab/<62>;
    # `git check-ignore -q` succeeds for the library path and fails for the blobs path
```

- [ ] **Step 2: Run** `uv run pytest tests/test_library.py -v` → FAIL (no `library`).
- [ ] **Step 3: Implement** `library_dir` and `Project.library`. Edit the two docs.
- [ ] **Step 4: Run** `uv run pytest -v -W error` → all PASS.
- [ ] **Step 5: Commit** `feat(library): project-local git-ignored library; ID prefixes`

---

### Task 2: Non-raising fetch and host intervals

**Files:**
- Modify: `platform/src/factory/sources/http.py`
- Test: `platform/tests/test_http.py`

**Interfaces:**
- Produces: `PoliteClient.fetch(url: str, params: Mapping[str, str | int] | None = None) -> httpx.Response`.
  - Same throttle and retries as `get` (429 with Retry-After, 5xx, transport errors).
  - After the last retry it returns any status ≥ 400 instead of raising; transport errors are still raised.
- Produces: `HOST_INTERVALS` gains `"arxiv.org": 3.0`; a `default_interval: float = 1.0` constructor parameter applies to hosts not in the map.

- [ ] **Step 1: Failing tests** (`httpx.MockTransport`, fake sleep/monotonic as the existing tests do):
  `test_fetch_returns_404_without_raising`, `test_fetch_retries_503_then_returns_it`, `test_unknown_host_waits_default_interval` (two calls to `example.org` → slept ≈ 1.0), `test_arxiv_org_interval_is_three_seconds`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Factor the retry loop so that `get` = `fetch` followed by `raise_for_status()`.
- [ ] **Step 4: Run** `uv run pytest tests/test_http.py -v` → PASS.
- [ ] **Step 5: Commit** `feat(http): non-raising fetch; arxiv.org and default intervals`

---

### Task 3: Full-text model and events

**Files:**
- Create: `platform/src/factory/model/fulltext.py`
- Modify: `platform/src/factory/events/catalog.py`
- Test: `platform/tests/test_fulltext_model.py`

**Interfaces:**
- Produces, in `model/fulltext.py`:
  - `class Route(StrEnum)`: `ARXIV_HTML="arxiv-html"`, `ARXIV_SOURCE="arxiv-source"`, `OA_PDF="oa-pdf"`, `RESEARCHER="researcher-supplied"`. Canonical order is `ROUTE_ORDER: tuple[Route, ...]`, holding the first three in that order; `RESEARCHER` is never tried automatically.
  - `class Quality(StrEnum)`: `STRUCTURED_HTML="structured-html"`, `LATEX="latex"`, `PDF_TEXT="pdf-text"`, plus `QUALITY: Mapping[Route, Quality]`.
  - `class AttemptOutcome(StrEnum)`: `RETRIEVED`, `NOT_AVAILABLE="not-available"`, `FAILED`, `RESTORED`.
  - `class LicenceStatus(StrEnum)`: `REPORTED`, `NOT_REPORTED="not-reported"`.
  - Payloads (`StrictModel`):
    - `FetchStarted`: `fetch_id`, `work_ids: list[str]`, `routes: list[Route] | None`, `refresh: bool`.
    - `Attempted`: `attempt_id`, `fetch_id: str | None` (None for import and restore), `work_id`, `route`, `url: str | None`, `http_status: int | None`, `outcome`, `reason: str | None`, `retrieved_at: datetime`, `source_version: str | None`, `licence: str | None`, `licence_status`, `media_type: str | None`, `raw_hash: str | None` (library ref), `metadata_blob: str | None` (blobs ref), `document_id: str | None`.
    - `DocumentAdded`: `document_id`, `work_id`, `route`, `quality`, `source_version: str`, `raw_hash`, `media_type`, `attempt_id`, `provenance: Literal["retrieved", "researcher-supplied"]`, `supersedes: str | None`.
    - `SourceChanged`: `document_id`, `attempt_id`, `expected_hash`, `observed_hash`.
- Invariants (model validators):
  - `Attempted`: outcome `retrieved`/`restored` ⇔ `raw_hash` and `document_id` are set; `not-available`/`failed` ⇒ `reason` is set.
  - `Attempted`: `licence` is set ⇔ `licence_status == reported`.
- Catalog: the four types are registered at schema version 1.

- [ ] **Step 1: Failing tests:** `test_retrieved_attempt_requires_hash_and_document`, `test_failed_attempt_requires_reason`, `test_licence_status_consistent`, `test_catalog_registers_fulltext_events`, `test_route_order_excludes_researcher`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(model): full-text routes, attempts, documents`

---

### Task 4: Projection

**Files:**
- Create: `platform/src/factory/index/fulltext.py`
- Modify: `platform/src/factory/index/default.py` (register the tables and handlers; `PROJECTION_VERSION = "16"`)
- Test: `platform/tests/test_fulltext_index.py`

**Interfaces:**
- Produces: tables `fulltext_fetches(fetch_id, event_id, actor_kind)`; `fulltext_attempts` (all `Attempted` fields plus `event_id`); `fulltext_documents` (all `DocumentAdded` fields plus `event_id`, `superseded_by`); `fulltext_source_changes`.
- The `DocumentAdded` handler sets `superseded_by` on the row named by `supersedes`.

- [ ] **Step 1: Failing tests:** `test_attempts_and_documents_project`, `test_supersedes_marks_previous_document`, `test_rebuild_is_identical` (the hash of the rebuilt state equals the incremental one), `test_projection_never_opens_library` (delete `library/`, rebuild, same state hash).
- [ ] **Step 2–4:** Run → FAIL; implement; run → PASS.
- [ ] **Step 5: Commit** `feat(index): full-text projection`

---

### Task 5: Route contract, arXiv version lookup, arXiv HTML route

**Files:**
- Create: `platform/src/factory/sources/fulltext/{__init__,base,arxiv}.py`; fixtures `arxiv_meta.xml` (one entry, `<id>http://arxiv.org/abs/2301.01234v3</id>`, `<arxiv:license>` absent), `ltx.html` (contains `class="ltx_document"`), `ltx_error.html` (status 200, no `ltx_document`)
- Test: `platform/tests/test_fulltext_routes_arxiv.py`

**Interfaces:**
- Produces, in `base.py`:
  - `@dataclass(frozen=True) class RouteResult`: `route`, `outcome: AttemptOutcome`, `url: str | None`, `http_status: int | None`, `reason: str | None`, `content: bytes | None`, `media_type: str | None`, `source_version: str | None`, `licence: str | None`, `metadata: bytes | None` (the response to archive in `blobs/`).
  - `class FullTextRoute(Protocol)`: `route: Route`; `def fetch(self, work: Work, *, version: str | None = None) -> RouteResult`. An explicit `version` pins it, for restore.
  - Routes never raise for an HTTP or content problem; `httpx.TransportError` becomes `failed`/`transport`.
- Produces, in `arxiv.py`:
  - `latest_arxiv_version(http: PoliteClient, arxiv_id: str) -> tuple[str | None, bytes]` returns e.g. `"2301.01234v3"` and the raw API response, via `export.arxiv.org/api/query?id_list=<id>`.
  - `ArxivHtmlRoute(http)` GETs `https://arxiv.org/html/<id>v<N>`.
- Reasons (fixed strings): `no-arxiv-id`, `arxiv-version-unknown`, `no-html-rendering` (404, or 200 without `ltx_document`), `http-<status>`, `transport`.
- `source_version` is the versioned arXiv ID. `media_type` is `text/html`.

- [ ] **Step 1: Failing tests** (MockTransport serving the fixtures):

```python
def test_html_route_fetches_latest_version(http_with_fixtures):
    r = ArxivHtmlRoute(http_with_fixtures).fetch(work_with_arxiv("2301.01234"))
    assert r.outcome is AttemptOutcome.RETRIEVED
    assert r.source_version == "2301.01234v3" and r.url == "https://arxiv.org/html/2301.01234v3"
    assert r.licence is None and r.metadata is not None
def test_html_404_falls_through(...): ...           # NOT_AVAILABLE, reason "no-html-rendering", http_status 404
def test_html_without_ltx_document_is_not_available(...): ...
def test_work_without_arxiv_id_is_not_available(...): ...     # reason "no-arxiv-id", no request sent
def test_pinned_version_skips_lookup(...): ...       # fetch(work, version="2301.01234v2") sends only the html GET
```

- [ ] **Step 2–4:** Run → FAIL; implement; run → PASS.
- [ ] **Step 5: Commit** `feat(fulltext): route contract and arXiv HTML route`

---

### Task 6: arXiv LaTeX source route

**Files:**
- Modify: `platform/src/factory/sources/fulltext/arxiv.py`
- Test: `platform/tests/test_fulltext_routes_arxiv.py`

**Interfaces:**
- Produces: `ArxivSourceRoute(http)` GETs `https://arxiv.org/e-print/<id>v<N>`.
  - A gzip tar or a gzip single file is `retrieved`, with `media_type` `application/x-eprint-tar` or `application/x-eprint`.
  - A body starting `%PDF-` is `not-available` with reason `no-latex-source`.
  - The version lookup is shared with the HTML route through a per-call cache: `ArxivVersionLookup` in `base.py`, keyed by arXiv ID and created once per `fetch_fulltext` call.
- Content is stored as received; plan B unpacks it.

- [ ] **Step 1: Failing tests:** `test_eprint_tar_is_retrieved` (tar.gz built in the test), `test_pdf_only_submission_is_not_latex`, `test_version_looked_up_once_for_both_arxiv_routes` (count the API requests = 1).
- [ ] **Step 2–4:** Run → FAIL; implement; run → PASS.
- [ ] **Step 5: Commit** `feat(fulltext): arXiv e-print route`

---

### Task 7: Open-access PDF route via OpenAlex

**Files:**
- Create: `platform/src/factory/sources/fulltext/oa_pdf.py`, `sources/fulltext/registry.py`; fixture `openalex_work.json` (`best_oa_location.pdf_url`, `license: "cc-by"`, `version: "publishedVersion"`)
- Test: `platform/tests/test_fulltext_routes_oa.py`

**Interfaces:**
- Produces: `OaPdfRoute(http, mailto: str | None)`.
  - Lookup: `api.openalex.org/works/doi:<doi>` (the work's DOI, else `10.48550/arxiv.<arxiv_id>`), with the `mailto` parameter.
  - Then GET `best_oa_location.pdf_url`.
  - `source_version = f"{doi}#{version}"`, e.g. `10.1/x#publishedVersion`.
  - `licence` is the OpenAlex `license` (`reported`), or `not-reported` when null.
  - `metadata` is the lookup body with `mailto` redacted.
- Reasons: `no-identifier`, `not-in-openalex` (404), `no-oa-pdf` (no `best_oa_location` or no `pdf_url`), `not-a-pdf` (body lacks `%PDF-`), `http-<status>`, `transport`.
- Produces: `default_routes(settings: Settings) -> dict[Route, FullTextRoute]` (one shared `default_http`).

- [ ] **Step 1: Failing tests:** `test_oa_pdf_retrieved_with_licence_and_version`, `test_oa_landing_page_is_not_a_pdf`, `test_no_best_oa_location`, `test_arxiv_only_work_uses_datacite_doi`, `test_mailto_never_in_url_or_metadata`.
- [ ] **Step 2–4:** Run → FAIL; implement; run → PASS.
- [ ] **Step 5: Commit** `feat(fulltext): OA PDF route via OpenAlex`

---

### Task 8: Fetch service (gate, order, version rule, changed source)

**Files:**
- Create: `platform/src/factory/services/fulltext.py`
- Test: `platform/tests/test_fulltext_service.py`

**Interfaces:**
- Consumes: `final_outcomes`, `Outcome.PROMOTE` (`services/agreement.py`); `get_work` (`services/search.py`); routes from Tasks 5–7; `Project.library` and `Project.blobs`.
- Produces:

```python
class WorkFetch(StrictModel):
    work_id: str
    attempts: list[str]                 # att_ ids
    documents: list[str]                # doc_ ids added by this call
    status: Literal["retrieved", "not-retrieved", "already-retrieved", "source-changed"]

class FetchSummary(StrictModel):
    fetch_id: str
    works: list[WorkFetch]
    remaining: int                      # promoted works still without any document after this call

def fetch_fulltext(project: Project, *, routes: Mapping[Route, FullTextRoute],
                   work_ids: Sequence[str] | None = None, only: Sequence[Route] | None = None,
                   refresh: bool = False, limit: int = 20,
                   actor: Actor | None = None, input_blob: str | None = None) -> FetchSummary
```

- Validation, all before anything is written:
  - Every listed work must exist and be `PROMOTE`; otherwise `("work_ids", "<id>: not promoted at title/abstract")`.
  - `only` may not contain `researcher-supplied`.
  - `1 ≤ limit ≤ 200`.
- Selection when `work_ids is None`: promoted works without a document, sorted by ID, at most `limit`.
- A work that already has a document is reported `already-retrieved` with no attempt, unless `refresh` or `only` is given.
- Per work, routes run in `ROUTE_ORDER` (filtered by `only`). Without `only`, the run stops after the first `retrieved`. Each result is recorded:
  - `content` goes to `library.put`, `metadata` to `blobs.put`, and the URL is redacted.
  - Same (work, route, source_version) as an existing document:
    - Hash equal: the attempt references the existing `document_id`, and no `DocumentAdded` is written.
    - Hash differs: `SourceChanged` is recorded, the new bytes are kept, and the status is `source-changed`.
  - New `source_version` on a route that has a live document: `DocumentAdded(supersedes=<that document>)`.
- Events: `FetchStarted` goes first, with the triggering actor (an agent's carries `input_blob`). The attempts and documents are system events. Each work's events go in one `project.record` call, so an interrupted call leaves whole works.

- [ ] **Step 1: Failing tests** (stub routes returning canned `RouteResult`s):
  - `test_unpromoted_work_refused_and_nothing_written`
  - `test_first_success_stops`: HTML retrieved, so only 1 attempt.
  - `test_not_retrieved_has_per_route_reasons`: 3 attempts, each with a reason, and status `not-retrieved`.
  - `test_only_routes_fetches_all_named` (bake-off): HTML and source both retrieved, giving 2 documents.
  - `test_newer_arxiv_version_is_new_document_superseding`: v2, then refresh at v3, so `supersedes == doc_v2`.
  - `test_same_version_same_hash_adds_no_document`
  - `test_same_version_new_hash_records_source_changed`: both hashes are in the library.
  - `test_transport_failure_is_an_outcome`
  - `test_limit_and_remaining`
  - `test_agent_trigger_carries_input_blob`
  - `test_no_document_bytes_under_blobs`: walk `blobs/` and assert no stored blob equals any content.
- [ ] **Step 2–4:** Run → FAIL; implement; run → PASS.
- [ ] **Step 5: Commit** `feat(fulltext): fetch service with route order and version rule`

---

### Task 9: Restore by recorded route

**Files:**
- Modify: `platform/src/factory/services/fulltext.py`
- Test: `platform/tests/test_fulltext_restore.py`

**Interfaces:**
- Produces: `restore_document(project: Project, document_id: str, *, routes: Mapping[Route, FullTextRoute], actor: Actor | None = None) -> Literal["present", "restored", "source-changed"]`.
  - If the library already has `raw_hash`, return `present` with no event.
  - Otherwise call `routes[doc.route].fetch(work, version=doc.source_version)` and apply ruling 9. The attempt has `fetch_id=None` and outcome `restored`.
  - `researcher-supplied` is refused: `("document_id", "researcher-supplied: re-import the file")`.

- [ ] **Step 1: Failing tests:** `test_restore_same_hash` (AC 15: delete the entry, restore, entry back, same ref), `test_restore_changed_source_records_event`, `test_restore_present_is_noop`, `test_restore_researcher_supplied_refused`.
- [ ] **Step 2–4:** Run → FAIL; implement; run → PASS.
- [ ] **Step 5: Commit** `feat(fulltext): restore library entry by recorded route`

---

### Task 10: Researcher-supplied import

**Files:**
- Create: `platform/src/factory/services/fulltext_import.py`
- Modify: `platform/pyproject.toml` (add `pypdf>=5`; comment: "identifier sniffing only; not the converter (plan B)")
- Test: `platform/tests/test_fulltext_import.py` (PDFs generated in the test with `pypdf`, containing text such as `arXiv:2301.01234v2`)

**Interfaces:**
- Produces:
  - `sniff_identifiers(path: Path) -> tuple[set[str], str]` returns the normalised ids `{"arxiv:<id>", "doi:<doi>"}` and their source (`filename` | `first-page` | `none`). It reads the filename first; if the filename yields none, it reads page 1 text via `pypdf`. A pypdf exception yields `(set(), "none")`.
  - `class ImportReport(StrictModel)` with `imported: list[tuple[str, str, str]]` (file, work, document), and the lists `already_imported`, `unmatched`, `ambiguous`, `not_promoted`, `not_pdf`: `list[str]` (file basenames).
  - `import_folder(project: Project, folder: Path) -> ImportReport` takes `*.pdf` recursively and processes files in sorted path order.
- Matching: identifiers resolve to corpus works through the normalised DOI and arXiv forms (`normalize_doi`, `normalize_arxiv`, `arxiv_id_from_doi`). Exactly one work means a match; more than one is `ambiguous`.
- Filename DOIs use `_` for `/` (`10.1234_abc.def.pdf`).
- Recording: an attempt (route `researcher-supplied`, `url=None`, `reason=None`, `source_version = "file:" + sha256[:12]`, `licence_status not-reported`) and a `DocumentAdded(provenance="researcher-supplied")`. The actor is `project.human_actor()`. A file whose hash already backs a document of that work is `already_imported`.
- The CLI is `factory fulltext import <folder>` and prints every list of the report.

- [ ] **Step 1: Failing tests:** `test_filename_arxiv_id_matches`, `test_filename_doi_with_underscore`, `test_first_page_arxiv_id_matches`, `test_two_identifiers_in_text_is_ambiguous`, `test_filename_wins_over_text`, `test_unpromoted_work_not_imported`, `test_non_pdf_listed`, `test_reimport_is_idempotent`, `test_import_writes_library_only` (no new file under `blobs/`).
- [ ] **Step 2–4:** Run → FAIL; implement; run → PASS.
- [ ] **Step 5: Commit** `feat(fulltext): researcher-supplied folder import`

---

### Task 11: Status, check and trace

**Files:**
- Create: `platform/src/factory/services/fulltext_status.py`
- Modify: `platform/src/factory/services/check.py`, `platform/src/factory/services/trace.py`
- Test: `platform/tests/test_fulltext_status.py`, `test_check.py`, `test_trace.py`

**Interfaces:**
- Produces:

```python
class WorkFulltext(StrictModel):
    work_id: str
    state: Literal["unsought", "retrieved", "not-retrieved"]
    documents: list[str]                       # live (not superseded)
    reasons: dict[Route, str]                  # latest attempt per route, for not-retrieved
class FulltextStatus(StrictModel):
    promoted: int; unsought: int; retrieved: int; not_retrieved: int
    by_route: dict[Route, int]                 # live documents per route
    works: list[WorkFulltext]
def fulltext_status(project: Project, *, work_ids: Sequence[str] | None = None) -> FulltextStatus
```

- The counts are computed from the projection and the final outcomes only; there is no library access.
- `check` findings (kind, severity in every mode):
  - `library-missing` (warning): a document whose `raw_hash` has no library file.
  - `library-corrupt` (error): the file exists but hashes differently; uses `BlobStore.get`, which raises an integrity error.
  - `source-changed` (warning).
  - `fulltext-unsought` (warning): a promoted work with no attempt.
  - Findings name the document and work IDs. The MCP refusal for pass sessions (decision 43) is unchanged.
- `trace` gains node kinds `document` and `attempt`. Back from a document: document → attempt → work → (existing chain to question). Forward from a work: its attempts and documents.
  - Both are inserted in `_ORDER` between `work` and `decision` (the chain-order list in `trace.py`). Seeds are pruned as before: a document of a seed work shows its work as any work.

- [ ] **Step 1: Failing tests:**
  - `test_status_counts_and_reasons`
  - `test_status_and_rebuild_without_library`
  - `test_check_reports_missing_library_entry`, then `test_check_clean_after_restore`
  - `test_check_corrupt_entry_is_error`
  - `test_check_unsought_promoted_work`
  - `test_trace_document_back_to_question` (AC 14, acquisition part: document → attempt → work → decisions → protocol → question)
- [ ] **Step 2–4:** Run → FAIL; implement; run → PASS.
- [ ] **Step 5: Commit** `feat(fulltext): status, check findings, trace nodes`

---

### Task 12: MCP tools, CLI, acceptance

**Files:**
- Modify: `platform/src/factory/mcp/server.py`, `platform/src/factory/cli/main.py`
- Create: `platform/tests/test_mcp_fulltext.py`, `platform/tests/test_acceptance_fulltext.py`
- Modify: `platform/tests/test_mcp_server.py` (tool list)

**Interfaces:**
- Consumes: Tasks 8–11.
- MCP:
  - `build_server(..., fulltext_routes: Mapping[Route, FullTextRoute] | None = None)`, defaulting to `default_routes(settings)`.
  - `fulltext_fetch(work_ids: list[str] | None, routes: list[str] | None, refresh: bool = False, limit: int = 20, model: str, skill: str)` is an agent act: it stores the arguments as `input_blob` and returns `FetchSummary`.
  - `fulltext_status(work_ids: list[str] | None = None)` returns `FulltextStatus`.
- CLI (`factory fulltext …`):
  - `import <folder>`
  - `fetch [--work ID]… [--route R]… [--refresh] [--limit N]` (human trigger)
  - `status`
  - `restore <doc_id>|--missing`, where `--missing` restores every `library-missing` document that is not researcher-supplied.

- [ ] **Step 1: Failing tests:**
  - `test_mcp_fetch_validation_errors_write_nothing`, `test_mcp_unknown_route_rejected`, `test_mcp_status_shape`
  - `test_cli_import_prints_report`, `test_cli_restore_missing`
  - Acceptance (`test_acceptance_fulltext.py`, offline, using stub routes on a project with promoted works made through the slice-1 helpers):
    - `test_ac1_every_promoted_work_has_attempt_and_record`: after `fetch_fulltext` until `remaining == 0`, every promoted work has ≥ 1 attempt. Each retrieved document's attempt has route, url, source_version, licence_status, retrieved_at and raw_hash. Each not-retrieved work has a reason per route. (Converter and version are plan B's half of AC 1.)
    - `test_ac15_no_literature_in_tracked_paths`: run fetch and import in a temporary git repository with the repository's `.gitignore`; `git status --porcelain --ignored` shows every library file as ignored, and no tracked or untracked-unignored path contains a raw content byte string.
    - `test_ac15_delete_check_restore`
    - `test_ac14_trace_from_document`
  - Network (`@pytest.mark.network`): `test_live_arxiv_html_and_source` on one stable arXiv ID (`1706.03762`). It asserts the outcomes and versions only and writes to `tmp_path`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -v -W error && uv run mypy --strict src && uv run ruff check . && uv run pytest --cov=factory.services --cov=factory.model --cov-fail-under=90` → all pass.
- [ ] **Step 5: Commit** `feat(mcp,cli): fulltext_fetch, fulltext_status, fulltext import/restore; acceptance`

---

## Self-review notes

- **Spec coverage:**
  - The route order (rows 1–3 and 5) maps to Tasks 5–7 and 10.
  - Row 4 (PMC) is out of scope (IDEA-22).
  - Not-retrieved with per-route reasons → Task 8 and Task 11 status.
  - Attempt fields (route, URL, status, retrieved_at, licence, version, raw hash) → Task 3 `Attempted`.
  - The version rule and "new version is a new document" → Task 8 (ruling 1, 3).
  - Library at `library/sha256/<2>/<62>`, git-ignored → Task 1.
  - `check` reports missing entries; re-fetch verifies by hash or records a changed source → Tasks 9 and 11.
  - `PoliteClient` reuse → Task 2.
  - MCP `fulltext_fetch`/`fulltext_status` and CLI import → Task 12.
  - AC 1 → Task 12 (acquisition fields; converter fields are plan B). AC 15 → Tasks 1 and 12. AC 14 (acquisition part) → Task 11. AC 16 (acquisition part) is satisfied by running `factory fulltext fetch` on the pilot after merge; that is not a test.
- **Deferred to later plans:**
  - Plan B: converter, version fields and Markdown documents.
  - Plan C: PRISMA full-text boxes, which will read `fulltext_status`.
  - Plan D: extraction superseded-by-version marking, which reads `fulltext_documents.superseded_by`.
  - Plan E: the copied-result version-mismatch note.
- **Not ported:** research-factory-old `fulltext.py`, which wrote PDFs to a per-work path. Only its idea (routing and quality labels) is kept, as `Route` and `Quality`. arxiv-miner `pdf_extractor` is used as a pattern only (ruling 7).
- **Type consistency:**
  - `Route`, `AttemptOutcome`, `RouteResult`, `FullTextRoute.fetch(work, *, version)`, `fetch_fulltext(..., only=...)` (MCP `routes` maps to `only`), `restore_document`, `import_folder` and `fulltext_status` are used with the same names in Tasks 3–12.
- **Open risk:**
  - arXiv HTML for papers without a LaTeXML rendering can return 200 with an error page; the `ltx_document` marker test is the guard, and the network test confirms it on a live ID.
  - OA PDF hosts vary; unlisted hosts get the 1.0 s default.
