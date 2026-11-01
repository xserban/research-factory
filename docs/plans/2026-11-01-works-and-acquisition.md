# Works and Acquisition Implementation Plan (slice 1, sub-plan 2 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Literature enters the factory: queries are registered with their PRISMA-S fields, OpenAlex and arXiv are searched exhaustively with every raw page archived before parsing, retrieved records become content-identified `Work`s with provenance, and deduplication merges are recorded as reversible events — all usable through two new MCP tools (`search_run`, `dedup_run`).

**Architecture:** Ported, tested modules from research-factory-old (`ids.py` → `model/work_ids.py`, `model.py` → `model/work.py`, `sources/*`, `dedup.py` → `services/dedup_cascade.py`) are adapted to the event model. A search is a sequence of events: `query.registered` (by the caller), then `search.run_started`, one `search.page_archived` per raw page as it arrives, `search.records_parsed` per page, and `search.run_finished` (all by the platform). Works are a projection keyed by the content-derived work ID; records with the same ID collapse into one work with several provenance rows. Cross-identifier duplicates are found by the ported 4-stage cascade and recorded as `dedup.merged` / `dedup.reverted` events; the merged view is computed at read time.

**Tech Stack:** as plan 1 (Python 3.12, uv, pydantic 2, SQLAlchemy Core, typer, mcp 2.x) plus `httpx` (adapters, `httpx.MockTransport` in tests) and `rapidfuzz` (title similarity).

**Spec:** `docs/specs/00-system.md` (§3 work IDs, §4, §7), `docs/specs/01-rigour.md` (R-01–R-03, R-21–R-23, R-26), `docs/specs/slice-1.md` (In scope rows Models/Identity/Sources/Dedup; acceptance criteria 2, 3, 4, 14). Approved split: plan 2 = works, IDs, sources, dedup; protocol gating of searches, seeds and probe are plan 3; citation chasing as a service and PRISMA counts are plan 5. Code origin: `~/Projects/research-factory-old/src/rf/` and `~/Projects/arxiv-miner/src/core/arxiv_throttle.py`.

## Global Constraints

- All plan-1 constraints hold (no model calls; services hold logic; append-only events; projector is the only index writer; validate before write; mypy --strict; ruff; coverage ≥ 90% for `factory.services` and `factory.model`; offline tests, `network` marker for live ones).
- Port **with tests**: every test case in the old `tests/test_ids.py`, `tests/test_dedup.py`, `tests/test_openalex.py`, `tests/test_arxiv.py` is carried over (adapted to new signatures), not dropped. Do not copy `cli.py`, storage, or the PubMed adapter.
- R-21: adapters never request relevance-sorted or "top N" subsets on their own; arXiv sorts by `submittedDate`; OpenAlex uses cursor paging and sends no `sort` parameter. A caller-supplied `limit` makes the run `partial` with a note.
- R-23 / acceptance 14: `reported_count` and `retrieved_count` are both stored; a run with `retrieved_count < reported_count` and no note is invalid and cannot be recorded.
- R-03: every raw page is stored as a blob and recorded in a `search.page_archived` event **before** its records are parsed.
- R-02 / acceptance 2: a `Work` cannot be constructed without at least one `Provenance`.
- Contact address for polite API use comes from env `FACTORY_MAILTO` via `Settings.mailto`; never hard-coded.
- Rate limits: arXiv ≥ 3.0 s between requests to `export.arxiv.org`; OpenAlex ≥ 0.1 s to `api.openalex.org`.
- Rulings carried from plan 1 apply: R3 (advance the FixedClock ≥ 1 ms between writes of different sessions in tests); projector handlers are total (never raise on a valid event sequence); agent-written events carry model, skill and `input_blob`.
- Commit after each task on branch `plan-2-works-acquisition`; commit trailer names the authoring model (`Co-Authored-By: Claude <Model> 5.5 <noreply@anthropic.com>`).
- All commands below run from `platform/` unless stated.

## Review Focus

1. **A search dies mid-run** (network error on page N). Pages already archived must stay recorded, the run must finish `partial` (or `failed` with no records) with a resume token, and resuming must continue without re-counting. → Task 8 tests `test_failure_mid_run_records_partial_with_resume_token`, `test_resume_continues_and_links_runs`.
2. **The same paper arrives twice** — within one run (duplicate entries across pages), across runs, or from two sources under bridged identifiers. Exactly one work, one provenance row per (work, run), no double counting. → Task 8 `test_same_work_from_two_runs_has_two_provenance_rows`, Task 11 `test_datacite_doi_and_bare_arxiv_id_are_one_work`.
3. **The source reports more than it delivers** (OpenAlex untitled records, arXiv duplicates). The run must say why; a silent shortfall cannot be recorded; `status` shows it. → Task 5 `test_complete_run_with_unexplained_shortfall_is_invalid`, Task 8 `test_status_lists_shortfalls`.
4. **Dedup is run again** after new records arrive or after a human reverted a merge. Unchanged merges are not re-recorded; a manual revert is never silently undone. → Task 10 `test_rerun_is_idempotent`, `test_manual_revert_is_not_reapplied`.
5. **Non-Latin or accented metadata** (CJK titles, diacritics, empty author lists). IDs stay deterministic and valid; nothing crashes. → Task 2 `test_cjk_and_accented_titles_produce_stable_ids`.

---

## File Structure

```
platform/src/factory/
  config.py                 + Settings.mailto (FACTORY_MAILTO)
  model/
    work_ids.py             ported ids.py: normalisation, arXiv-DOI bridge, work_id()
    work.py                 ported model.py: WorkType, Identifiers, Author, Venue, Dates, Provenance, Work
    search.py               QueryKind, QueryPurpose, QuerySpec, RunStatus, search.* / query.* payloads
    dedup.py                dedup.* payloads
  sources/
    __init__.py
    http.py                 PoliteClient: per-host throttle, Retry-After, retries (from arxiv-miner)
    base.py                 ported base.py: RawPage, SearchResult, PageSink, Source, SourceError
    openalex.py             ported OpenAlex adapter (+ raw filter queries)
    arxiv.py                ported arXiv adapter
    registry.py             SourceFactory, default_sources()
  index/
    search.py               queries, runs, pages, works, provenance tables + handlers
    dedup.py                merges, blocked_pairs tables + handlers
  services/
    search.py               register_query(), run_query(), get_work(), list_works(), search_counts()
    dedup_cascade.py        ported dedup.py (pure): dedup(), merge_works(), Merge, DedupResult
    dedup.py                dedup_run(), revert_merge(), canonical_works()
  mcp/server.py             + search_run, dedup_run tools
  cli/main.py               status shows searches and works
platform/tests/
  test_work_ids.py  test_work.py  test_http.py  test_source_base.py
  test_openalex.py  test_arxiv.py  test_search_service.py
  test_dedup_cascade.py  test_dedup_service.py  test_mcp_search.py
  test_acceptance_acquisition.py  fixtures/ (OpenAlex JSON, arXiv Atom samples)
```

---

### Task 1: Plan-1 carry-over fixes

**Files:**
- Modify: `platform/src/factory/index/index.py`, `platform/src/factory/services/tasks.py`
- Test: `platform/tests/test_index_concurrency.py`, `platform/tests/test_tasks.py`

**Interfaces:**
- Consumes: `Index` (`_locked`, `_refresh_engine`, `_build`), `release_task`, `_require_outcome` (plan 1).
- Produces: no new public names. `Index.connect()` and `Index.state_hash()` hold a **shared** `flock` (`LOCK_SH`) on `.index/lock` while reading; writers keep `LOCK_EX`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_index_concurrency.py
def test_second_index_object_follows_the_others_rebuild(settings, clock):
    p1 = init_project(settings, "demo", "pilot", session=SESSION, clock=clock)
    p2 = open_project(settings, "demo", session=S2, clock=clock)
    p2.index.sync()                                   # p2's engine is open on the current file
    clock.advance(ONE_MS)
    create_tasks(p1, p1.system_actor(), [TaskSpec("demo", 1)])
    p1.index.rebuild()                                # replaces the DB file (new inode)
    assert project_status(p2).tasks.open == 1         # p2 must see the new file, not the unlinked one

def test_readers_wait_for_a_rebuild_in_progress(settings, clock): ...
    # hold LOCK_EX on .index/lock in the test; a reader thread calling p2.index.state_hash()
    # must not finish until the lock is released (assert via threading.Event + short timeout)

# tests/test_tasks.py
def test_release_is_not_reported_as_failed_when_another_session_reclaims_immediately(
        project, project_other_session, agent, agent_other, clock, monkeypatch): ...
    # make the projector apply the release, then (before release_task re-reads) have agent_other
    # claim the task — e.g. monkeypatch services.tasks.get_task to first let p_other claim;
    # release_task must return without raising
def test_release_ignored_by_projector_still_raises(...): ...   # existing F4 behaviour kept
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_index_concurrency.py tests/test_tasks.py -v` → the two new index tests and the reclaim test FAIL.
- [ ] **Step 3: Implement**
  - `connect()` / `state_hash()`: acquire `LOCK_SH` (via a `_locked(shared=True)` variant), call `_refresh_engine()`, read, release.
  - `release_task`: the event was ignored ⇔ after `record`, the task is still `claimed` with `claim_session == actor.session` **and** the same `lease_until` as before the call; only then raise `("task_id", "lease expired before the event was recorded")`.
- [ ] **Step 4: Run to verify pass** — `uv run pytest -v -W error` → all PASS.
- [ ] **Step 5: Commit** — `git commit -m "fix: shared read lock, precise release check, discriminating stale-engine test"`

---

### Task 2: Work identity (port `ids.py`)

**Files:**
- Create: `platform/src/factory/model/work_ids.py`
- Test: `platform/tests/test_work_ids.py`

**Interfaces:**
- Produces (verbatim behaviour of old `rf/ids.py`): `normalize_title(title: str) -> str`, `normalize_doi(doi: str) -> str`, `normalize_arxiv(arxiv_id: str) -> str`, `arxiv_id_from_doi(doi: str) -> str | None`, `work_id(*, title: str, authors: list[str], year: int | None, doi: str | None = None, arxiv: str | None = None) -> str`; constant `WORK_ID_RE = r"^rf:\S+-[0-9a-f]{8}$"`.

- [ ] **Step 1: Port the old tests** — copy every test from `~/Projects/research-factory-old/tests/test_ids.py` (`test_title_strips_accents_punctuation_and_case`, `test_doi_forms_converge`, `test_arxiv_versions_are_the_same_work`, `test_is_deterministic`, `test_doi_is_identity_regardless_of_surrounding_metadata`, `test_arxiv_version_bump_does_not_change_identity`, `test_distinct_works_get_distinct_ids`, `test_slug_is_readable_and_skips_stopwords`, `test_missing_authors_and_year_still_produce_an_id`), changing imports to `factory.model.work_ids`, and add:

```python
def test_datacite_doi_and_bare_arxiv_id_share_an_id():
    a = work_id(title="Linear Attention", authors=["Ada Zhou"], year=2023, doi="10.48550/arXiv.2301.01234")
    b = work_id(title="Linear attention!", authors=["A. Zhou"], year=2024, arxiv="2301.01234v2")
    assert a == b

def test_cjk_and_accented_titles_produce_stable_ids():
    for title, author in [("视觉线性注意力", "王伟"), ("Étude de l’attention", "Zoë Müller"), ("", "")]:
        wid = work_id(title=title, authors=[author] if author else [], year=None)
        assert re.fullmatch(WORK_ID_RE, wid) and wid == work_id(title=title, authors=[author] if author else [], year=None)
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_work_ids.py -v` → FAIL (`ImportError`).
- [ ] **Step 3: Port `ids.py`** verbatim into `model/work_ids.py` (module docstring kept; fix only what ruff/mypy require; add `WORK_ID_RE`).
- [ ] **Step 4: Run to verify pass** → PASS; `uv run mypy src tests` clean.
- [ ] **Step 5: Commit** — `git commit -m "feat(model): deterministic work ids (ported)"`

---

### Task 3: Work model (port `model.py`)

**Files:**
- Create: `platform/src/factory/model/work.py`
- Test: `platform/tests/test_work.py`

**Interfaces:**
- Consumes: `StrictModel`, `work_ids`, `ULID_RE`, `BLOB_REF_RE`.
- Produces:
  - `WorkType(StrEnum)` — the old 14 values and `is_peer_reviewed_by_default`.
  - `ProvenanceMethod(StrEnum)`: `DATABASE="database"`, `CITATION_CHASE="citation-chase"`, `SEED_ADMISSION="seed-admission"`, `HAND_SEARCH="hand-search"`.
  - `Identifiers`, `Author`, `Venue`, `Dates` — old fields; `Identifiers` normalises `doi`/`arxiv` with field validators (models are frozen; no `object.__setattr__`); `any_strong()`; `Dates.year`.
  - `Provenance(StrictModel)`: `source: str`, `run_id: str` (`^run_<ULID>$`), `query_id: str` (`^qry_<ULID>$`), `at: AwareDatetime`, `raw_blob: str` (BLOB_REF_RE), `raw_ref: str | None = None`, `method: ProvenanceMethod = DATABASE`.
  - `Work(StrictModel)`: old fields (`id`, `type`, `title`, `abstract`, `language`, `authors`, `identifiers`, `venue`, `dates`, `subjects`, `cited_by_count`, `retracted`, `provenance` with `min_length=1`, `supersedes`, `absorbed`), `Work.build(...)` deriving `id` via `work_id`, property `sources`. All work models add `str_strip_whitespace=True` to the StrictModel config.

- [ ] **Step 1: Write the failing tests**

```python
def test_work_without_provenance_cannot_exist():           # slice-1 acceptance 2
    with pytest.raises(ValidationError):
        Work.build(title="T", provenance=[])

def test_build_derives_the_id_from_content(prov):
    w = Work.build(title="Linear Attention", authors=[Author(name="Ada Zhou")],
                   identifiers=Identifiers(doi="https://doi.org/10.1/X"), provenance=[prov])
    assert w.id == work_id(title="Linear Attention", authors=["Ada Zhou"], year=None, doi="10.1/x")
    assert w.identifiers.doi == "10.1/x"

def test_identifiers_normalise_arxiv_versions():
    assert Identifiers(arxiv="arXiv:2301.01234v3").arxiv == "2301.01234"

def test_provenance_requires_platform_ids_and_blob(): ...   # bad run_id / query_id / raw_blob → ValidationError
def test_sources_are_distinct_in_first_seen_order(prov): ... # two provenance entries openalex, arxiv, openalex → ["openalex", "arxiv"]
def test_round_trips_through_json(prov): ...                 # Work.model_validate_json(w.model_dump_json()) == w
def test_peer_review_default(): ...                          # JOURNAL_ARTICLE True, PREPRINT False
```
Fixture `prov` in conftest: `Provenance(source="openalex", run_id=f"run_{SESSION}", query_id=f"qry_{SESSION}", at=T0, raw_blob="sha256:" + "a" * 64)`.

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_work.py -v` → FAIL.
- [ ] **Step 3: Port `model.py`** into `model/work.py` with the changes above.
- [ ] **Step 4: Run to verify pass** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(model): Work with mandatory provenance (ported)"`

---

### Task 4: Polite HTTP client

**Files:**
- Create: `platform/src/factory/sources/__init__.py`, `platform/src/factory/sources/http.py`
- Modify: `platform/pyproject.toml` (add `httpx>=0.27`), `platform/src/factory/config.py` (`mailto`)
- Test: `platform/tests/test_http.py`, extend `platform/tests/test_config.py`

**Interfaces:**
- Produces:
  - `Settings.mailto: str | None = None`; `Settings.load` reads env `FACTORY_MAILTO`.
  - `HOST_INTERVALS: Mapping[str, float] = {"export.arxiv.org": 3.0, "api.openalex.org": 0.1}`.
  - `PoliteClient(client: httpx.Client, *, intervals: Mapping[str, float] = HOST_INTERVALS, retries: int = 4, backoff: tuple[float, float] = (2.0, 60.0), max_retry_after: float = 300.0, sleep: Callable[[float], None] = time.sleep, monotonic: Callable[[], float] = time.monotonic)`, method `get(url: str, params: Mapping[str, str | int]) -> httpx.Response`.
  - `user_agent(mailto: str | None) -> str` → `"research-factory/0.2"` or `"research-factory/0.2 (mailto:<addr>)"`.
  - `default_http(settings: Settings) -> PoliteClient` (httpx.Client: timeout 60 s, `follow_redirects=True`, User-Agent header).

Behaviour of `get` (one lock per instance; per-host last-request time):
```
for attempt in 0..retries:
    wait until now - last[host] >= intervals.get(host, 0); last[host] = now
    try: response = client.get(url, params=params)
    except httpx.TransportError: if attempt == retries: raise; sleep(min(backoff[1], backoff[0] * 2**attempt)); continue
    if response.status_code == 429 and attempt < retries:
        sleep(min(float(Retry-After) if numeric else backoff[0] * 2**attempt, max_retry_after)); continue
    if response.status_code >= 500 and attempt < retries: sleep(min(backoff[1], backoff[0] * 2**attempt)); continue
    response.raise_for_status(); return response
```

- [ ] **Step 1: Write the failing tests** (all with `httpx.MockTransport` and a recording fake `sleep` / fake `monotonic`)

```python
def test_requests_to_one_host_are_spaced_by_its_interval(): ...   # 3 arXiv GETs at fake t=0 → sleeps [3.0, 3.0] (approx)
def test_hosts_are_throttled_independently(): ...                 # arXiv then OpenAlex back to back → no sleep before OpenAlex
def test_retry_after_header_is_honoured_and_capped(): ...         # 429 Retry-After: 7 → sleep 7 then success; Retry-After: 9999 → sleep 300
def test_server_errors_are_retried_then_raised(): ...             # 503 ×5 with retries=4 → httpx.HTTPStatusError, 4 backoff sleeps 2,4,8,16
def test_transport_errors_are_retried(): ...                      # ConnectError then 200 → returns 200
def test_client_errors_are_not_retried(): ...                     # 404 → HTTPStatusError after one request
def test_user_agent_carries_mailto_only_when_configured(): ...
def test_settings_reads_mailto_from_env(monkeypatch, tmp_path): ...
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_http.py tests/test_config.py -v` → FAIL.
- [ ] **Step 3: Implement** `sources/http.py` and the `Settings` change; `uv add httpx`.
- [ ] **Step 4: Run to verify pass** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(sources): polite per-host HTTP client"`

---

### Task 5: Source contract (port `sources/base.py`)

**Files:**
- Create: `platform/src/factory/sources/base.py`, `platform/src/factory/model/search.py` (enums and `QuerySpec` only; payloads come in Task 8)
- Test: `platform/tests/test_source_base.py`

**Interfaces:**
- Produces:
  - `model/search.py`: `QueryKind(StrEnum)`: `KEYWORD="keyword"`, `FILTER="filter"`, `ID_LIST="id_list"`. `QueryPurpose(StrEnum)`: `PROBE`, `SEARCH`, `CHASE`, `SEED` (values lowercase). `RunStatus(StrEnum)`: `RUNNING`, `COMPLETE`, `PARTIAL`, `FAILED`, `INTERRUPTED`. `QuerySpec(StrictModel)`: `source: str`, `kind: QueryKind`, `text: str` (non-empty, stripped), `purpose: QueryPurpose = SEARCH`, `filters: dict[str, str] = {}`, `limit: int | None = None` (≥ 1).
  - `sources/base.py`: `SourceError(FactoryError)`; `RawPage(ordinal: int, body: str, url: str, fetched_at: datetime)` (frozen dataclass); `PageSink = Callable[[RawPage], str]` — **archives the page and returns its blob ref**; adapters put that ref into each parsed record's `Provenance.raw_blob`.
  - `SearchResult` (frozen dataclass): `source`, `query_sent: str`, `reported_count: int | None`, `works: list[Work]`, `pages: int`, `status: RunStatus` (one of COMPLETE/PARTIAL/FAILED), `skipped: int = 0`, `note: str | None = None`, `resume_token: str | None = None`; properties `retrieved_count` (= `len(works)`), `has_shortfall`. `__post_init__` raises `ValueError` when `status == COMPLETE and has_shortfall and not note` (R-23 / acceptance 14).
  - `Source` (Protocol): `name: str`; `kinds: frozenset[QueryKind]`; `run(spec: QuerySpec, *, run_id: str, query_id: str, archive: PageSink, resume_from: str | None = None) -> SearchResult`.

- [ ] **Step 1: Write the failing tests**

```python
def test_complete_run_with_unexplained_shortfall_is_invalid():
    with pytest.raises(ValueError):
        SearchResult(source="openalex", query_sent="q", reported_count=10, works=[], pages=1,
                      status=RunStatus.COMPLETE)

def test_explained_shortfall_is_allowed(): ...      # same with note="3 untitled records skipped" → ok, has_shortfall True
def test_partial_and_failed_runs_require_a_note(): ...  # PARTIAL or FAILED without note → ValueError; with note → ok
def test_query_spec_validation(): ...               # empty text, limit 0 → ValidationError
```
Rule (state it in the docstring): `note` is required whenever `status != COMPLETE`, and for `COMPLETE` whenever `has_shortfall`.

- [ ] **Step 2–4:** fail → implement → pass (`uv run pytest tests/test_source_base.py -v`).
- [ ] **Step 5: Commit** — `git commit -m "feat(sources): source contract with explicit shortfalls"`

---

### Task 6: OpenAlex adapter (port)

**Files:**
- Create: `platform/src/factory/sources/openalex.py`, `platform/tests/fixtures/openalex_page.json` (2–3 realistic records incl. one DataCite-DOI preprint and one untitled record)
- Test: `platform/tests/test_openalex.py`

**Interfaces:**
- Consumes: `PoliteClient`, `SearchResult`, `RawPage`, `PageSink`, `Work.build`, `Clock`.
- Produces: `OpenAlexSource(http: PoliteClient, *, clock: Clock, mailto: str | None = None, page_size: int = 200)`; `name = "openalex"`; `kinds = {KEYWORD, FILTER}`; `run(...)`; module function `reconstruct_abstract(inverted) -> str | None`; method `to_work(item, *, run_id, query_id, raw_blob, at, method) -> Work | None`.
- Query mapping: `KEYWORD` → `filter=title_and_abstract.search:<text>`; `FILTER` → `filter=<text>` verbatim (used later for `doi:a|b`, `openalex:W1|W2`, `cites:W1`); `spec.filters` items are appended as `,<key>:<value>`. Params always include `per-page` and `cursor` (`*` or the resume token); `mailto` when set; **never** `sort` or `search`.
- `method` for records: `CITATION_CHASE` when `spec.purpose == CHASE`, `SEED_ADMISSION` when `SEED`, else `DATABASE`.
- `skipped` counts untitled records and within-run duplicate IDs; when the run completes with `retrieved < reported`, `note = f"{skipped} records skipped (untitled or duplicate within run)"`, plus `"; source count differs"` if the arithmetic still does not close.
- `limit` truncation → `PARTIAL`, note `"truncated by caller-supplied limit"`. HTTP failure → `PARTIAL` (if any works) else `FAILED`, note `"<ExcType>: <msg>"`, `resume_token` = cursor.

- [ ] **Step 1: Port the old tests** — every test in `~/Projects/research-factory-old/tests/test_openalex.py` (`test_positions_are_restored_in_order`, `test_repeated_words_appear_at_every_position`, `test_missing_index_yields_none`, `test_fields_are_carried_across`, `test_identifier_urls_are_stripped_to_bare_ids`, `test_author_orcid_and_affiliation`, `test_unmapped_type_becomes_other_rather_than_a_guess`, `test_conference_abstract_is_not_promoted_to_a_paper`, `test_untitled_records_are_skipped`, `test_provenance_is_attached`, `test_unparseable_json_raises`, `test_follows_the_cursor_until_it_is_exhausted`, `test_reported_count_comes_from_meta`, `test_limit_truncates_and_is_recorded_as_partial`, `test_empty_result_set`, `test_http_error_is_reported_not_swallowed`, `test_mailto_is_sent_when_configured`, `test_no_mailto_is_sent_when_unconfigured`), adapted to `run(spec, run_id=, query_id=, archive=)` with a `PoliteClient(MockTransport, sleep=lambda s: None)`. Add:

```python
def test_never_sends_sort_or_relevance_search(): ...   # inspect every request's params: no "sort", no "search"
def test_each_page_is_archived_before_its_records_are_parsed(): ...
    # archive sink records call order; to_work is wrapped to record too → archive(page n) precedes to_work(records of n);
    # every work.provenance[0].raw_blob equals the ref the sink returned for its page
def test_untitled_record_makes_an_explained_shortfall(): ...   # reported 3, retrieved 2, COMPLETE, note mentions skipped
def test_filter_kind_is_sent_verbatim_with_extra_filters(): ... # FILTER "doi:10.1/a|10.1/b" + filters {"publication_year": ">2019"}
def test_chase_purpose_marks_provenance_method(): ...
@pytest.mark.network
def test_live_small_query(): ...                       # real API, limit=5 → PARTIAL, 5 works, reported_count > 5
```

- [ ] **Step 2–4:** fail → port/adapt → pass (`uv run pytest tests/test_openalex.py -v`).
- [ ] **Step 5: Commit** — `git commit -m "feat(sources): OpenAlex adapter (ported)"`

---

### Task 7: arXiv adapter (port)

**Files:**
- Create: `platform/src/factory/sources/arxiv.py`, `platform/tests/fixtures/arxiv_page.xml` (Atom with 2 entries, one with `arxiv:doi` and `journal_ref`)
- Test: `platform/tests/test_arxiv.py`

**Interfaces:**
- Produces: `ArxivSource(http: PoliteClient, *, clock: Clock, page_size: int = 100)`; `name = "arxiv"`; `kinds = {KEYWORD, ID_LIST}`; `run(...)` (KEYWORD → paged `search_query`, `sortBy=submittedDate`, `sortOrder=ascending`, or `descending` when `spec.limit` is set; ID_LIST → `text` is comma-separated IDs, fetched via `id_list` in batches of `page_size`); `matching(ids: list[str], text: str, *, run_id: str, query_id: str, archive: PageSink) -> set[str]` (ported; used by the probe in plan 3).
- Politeness, 429 and retries now come from `PoliteClient` (remove the old in-class sleeping and tenacity).
- `skipped` counts within-run duplicates; explained-shortfall rule as in Task 6. Resume token = numeric start offset as string.

- [ ] **Step 1: Port the old tests** — every test in `~/Projects/research-factory-old/tests/test_arxiv.py` (`test_entries_become_works`, `test_reported_count_comes_from_opensearch`, `test_arxiv_id_is_normalized_but_url_keeps_the_version`, `test_metadata_is_carried_across`, `test_every_work_carries_provenance`, `test_malformed_xml_raises_rather_than_returning_nothing`, `test_a_short_page_ends_paging`, `test_caller_limit_is_recorded_as_partial`, `test_raw_pages_are_archived_verbatim`, `test_duplicate_entries_across_pages_are_not_double_counted`, `test_http_error_yields_failed_status_not_an_empty_success`, `test_shortfall_is_visible`, `test_pages_are_archived_as_they_arrive`, `test_a_page_reaches_the_sink_even_when_a_later_page_fails`, `test_failure_records_a_resume_token`, `test_resume_starts_from_the_given_offset`, `test_page_ordinals_continue_across_a_resume`; `test_retry_after_header_is_honoured` moves to Task 4's `test_http.py` and is already covered there). Add:

```python
def test_sorts_by_submission_date_never_relevance(): ...   # every request has sortBy=submittedDate
def test_id_list_kind_fetches_in_batches(): ...           # 150 ids, page_size 100 → 2 requests with id_list
def test_matching_intersects_ids_with_query(): ...        # ported behaviour, archive sink called
@pytest.mark.network
def test_live_id_lookup(): ...                            # real API, ID_LIST "1706.03762" → 1 work, title contains "Attention"
```

- [ ] **Step 2–4:** fail → port/adapt → pass (`uv run pytest tests/test_arxiv.py -v`).
- [ ] **Step 5: Commit** — `git commit -m "feat(sources): arXiv adapter (ported)"`

---

### Task 8: Queries, search runs and the works projection

**Files:**
- Modify: `platform/src/factory/model/search.py` (payloads), `platform/src/factory/events/catalog.py`, `platform/src/factory/index/default.py` (bump `PROJECTION_VERSION` to `"4"`), `platform/src/factory/services/project.py` (`ProjectStatus.search`, `.works`, `.records`)
- Create: `platform/src/factory/sources/registry.py`, `platform/src/factory/index/search.py`, `platform/src/factory/services/search.py`
- Test: `platform/tests/test_search_service.py`; test helper `FakeSource` in `platform/tests/helpers.py`

**Interfaces:**
- Consumes: `Source`, `SearchResult`, `RawPage`, `QuerySpec`, `Work`, `Project`, `BlobStore.put`.
- Produces:
  - Payloads (schema 1): `QueryRegistered(query_id, spec: QuerySpec, interface: str)`; `SearchRunStarted(run_id, query_id, resume_of: str | None = None, resume_from: str | None = None)`; `SearchPageArchived(run_id, ordinal: int, url: str, fetched_at: AwareDatetime, raw_blob: str)`; `SearchRecordsParsed(run_id, raw_blob: str, records: tuple[Work, ...])`; `SearchRunFinished(run_id, status: RunStatus, reported_count: int | None, retrieved_count: int, skipped: int, note: str | None, resume_token: str | None)` with the same note rule as `SearchResult`. Event types: `query.registered`, `search.run_started`, `search.page_archived`, `search.records_parsed`, `search.run_finished`. IDs: `qry_`/`run_` + ULID.
  - `sources/registry.py`: `SourceFactory = Callable[[Settings, Clock], Source]`; `INTERFACES = {"openalex": "OpenAlex REST API (api.openalex.org/works)", "arxiv": "arXiv API (export.arxiv.org/api/query)"}`; `default_sources() -> dict[str, SourceFactory]`.
  - `services/search.py`:
    - `register_query(project, actor, spec: QuerySpec, *, sources: Mapping[str, SourceFactory]) -> str` — validates source known (field `source`), kind in that source's `kinds` (field `kind`), filters only for openalex (field `filters`); writes `query.registered` by `actor`; for agent actors `input_blob` = `blobs.put_json(spec.model_dump(mode="json"))`.
    - `run_query(project, query_id: str, *, sources: Mapping[str, SourceFactory], resume_run: str | None = None) -> RunSummary` — system actor; records `search.run_started`; the `archive` sink puts the page body as a blob and **records** `search.page_archived` immediately (then returns the ref); after the adapter returns, records one `search.records_parsed` per archived page that has records (grouped by `raw_blob`) and `search.run_finished` in a single `project.record` call. Adapter exceptions (`SourceError`, unexpected) → `search.run_finished` FAILED/PARTIAL with note, then re-raise only non-`SourceError`. `resume_run` must name a PARTIAL/FAILED run of the same query with a resume token (field `resume_run`).
    - `RunSummary(StrictModel)`: `run_id, query_id, source, status, reported_count, retrieved_count, skipped, note, resume_token, new_works: int`.
    - `get_work(project, work_id) -> Work | None` (first-seen record with identifiers filled and **all** provenance rows); `list_works(project) -> list[Work]` (sorted by id).
    - `SearchCounts(StrictModel)`: `queries, runs, complete, partial, failed, interrupted: int`, `shortfalls: list[Shortfall]`; `Shortfall(run_id, source, reported_count, retrieved_count, note)`; `search_counts(project) -> SearchCounts` (`interrupted` = started without finished).
  - `ProjectStatus` gains `search: SearchCounts`, `works: int` (distinct work IDs), `records: int` (provenance rows).

Projection (`index/search.py`, handlers total):
- `queries(query_id PK, source, kind, text, purpose, filters JSON, limit, interface, registered_at, actor_id)`.
- `runs(run_id PK, query_id, source, status, started_at, finished_at, reported_count, retrieved_count, skipped, note, resume_token, resume_of, pages)` — `run_started` inserts RUNNING; `page_archived` increments `pages`; `run_finished` sets the rest (ignored if the run is unknown or already finished).
- `pages(run_id, ordinal) PK, raw_blob, url, fetched_at`.
- `works(work_id PK, data JSON, first_event_id)` — on `records_parsed`, insert the record (without provenance) if new; if it exists, fill identifier fields that are null and `abstract` if null (first-seen wins otherwise).
- `provenance(work_id, run_id) PK, query_id, source, method, raw_blob, raw_ref, at` — `on_conflict_do_nothing`.

- [ ] **Step 1: Write the failing tests** (`FakeSource(pages: list[list[dict]], reported: int | None, fail_after: int | None)` builds records via `Work.build` and calls `archive` per page)

```python
def test_run_archives_pages_and_records_works(project, fake_sources):
    qid = register_query(project, project.human_actor(), QuerySpec(source="fake", kind="keyword", text="linear attention"), sources=fake_sources)
    summary = run_query(project, qid, sources=fake_sources)
    assert summary.status == RunStatus.COMPLETE and summary.retrieved_count == 3 and summary.new_works == 3
    st = project_status(project)
    assert (st.works, st.records, st.search.runs, st.search.complete) == (3, 3, 1, 1)
    assert all(project.blobs.exists(p) for p in pages_of(project, summary.run_id))      # R-03

def test_page_archived_event_precedes_its_records(project, fake_sources): ...  # event order in read_all: page_archived(n) < records_parsed(n)
def test_failure_mid_run_records_partial_with_resume_token(project, fake_sources): ...
    # FakeSource fails on page 2 → status PARTIAL, page 1 archived & parsed, resume_token set, note names the error
def test_resume_continues_and_links_runs(project, fake_sources): ...       # run_query(..., resume_run=first) → new run, resume_of=first, no duplicate provenance
def test_same_work_from_two_runs_has_two_provenance_rows(project, fake_sources): ...
def test_identifiers_from_later_records_fill_gaps(project, fake_sources): ...    # first record lacks openalex id, second has it → get_work has both
def test_status_lists_shortfalls(project, fake_sources): ...                # reported 5, retrieved 3, note → appears in search.shortfalls
def test_unknown_source_or_kind_is_rejected_and_writes_nothing(project, fake_sources): ...
def test_agent_registered_query_carries_input_blob(project, agent, fake_sources): ...
def test_interrupted_run_is_counted(project, fake_sources): ...             # write run_started only → interrupted == 1
def test_search_projection_rebuild_equals_incremental(project, fake_sources): ...
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_search_service.py -v` → FAIL.
- [ ] **Step 3: Implement** payloads, catalog entries, projection, registry, service, status fields.
- [ ] **Step 4: Run to verify pass** — `uv run pytest -v -W error` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(search): queries, runs, archived pages and works projection"`

---

### Task 9: Dedup cascade (port `dedup.py`)

**Files:**
- Create: `platform/src/factory/services/dedup_cascade.py`
- Modify: `platform/pyproject.toml` (add `rapidfuzz>=3.10`)
- Test: `platform/tests/test_dedup_cascade.py`

**Interfaces:**
- Produces (old behaviour, pure functions): `TITLE_SIMILARITY_THRESHOLD = 92.0`, `YEAR_WINDOW = 1`; `CascadeMerge` (old `Merge`: `primary`, `absorbed`, `rule`, `records`); `DedupResult(works, merges, input_count)` with `removed`; `merge_works(group: list[Work]) -> Work`; `dedup(works: list[Work], *, blocked: frozenset[frozenset[str]] = frozenset()) -> DedupResult`.
- New: `blocked` pairs of work IDs must never end up in the same group — the union step refuses to join two components if any blocked pair spans them (keep a member set per root).

- [ ] **Step 1: Port the old tests** — every test in `~/Projects/research-factory-old/tests/test_dedup.py` (`test_same_doi_from_two_sources_becomes_one_work`, `test_merge_unions_identifiers`, `test_distinct_dois_are_not_merged`, `test_bare_arxiv_id_and_datacite_doi_are_the_same_preprint`, `test_published_version_becomes_primary_and_supersedes_the_preprint`, `test_near_identical_titles_by_the_same_author_merge`, `test_same_title_by_different_authors_does_not_merge`, `test_distant_years_do_not_merge`, `test_different_titles_do_not_merge`, `test_all_provenance_is_retained`, `test_abstract_is_recovered_from_whichever_record_has_one`, `test_retraction_propagates_through_a_merge`, `test_merge_is_reversible_from_the_map`, `test_output_is_order_independent`, `test_empty_corpus`), with the `w()` helper building `Provenance` in the new shape. Add:

```python
def test_blocked_pair_is_never_merged():
    a = w("Linear Attention for Vision", doi="10.1/a"); b = w("Linear attention for vision", arxiv="2301.00001")
    assert len(dedup([a, b]).works) == 1
    assert len(dedup([a, b], blocked=frozenset({frozenset({a.id, b.id})})).works) == 2

def test_blocked_pair_also_blocks_transitive_joins(): ...  # a~c, b~c, block {a,b} → a and b not in one group
```

- [ ] **Step 2–4:** fail → port → pass (`uv run pytest tests/test_dedup_cascade.py -v`).
- [ ] **Step 5: Commit** — `git commit -m "feat(dedup): four-stage cascade with blocked pairs (ported)"`

---

### Task 10: Dedup service — reversible merges as events

**Files:**
- Create: `platform/src/factory/model/dedup.py`, `platform/src/factory/index/dedup.py`, `platform/src/factory/services/dedup.py`
- Modify: catalog, `index/default.py` (bump to `"5"`), `services/project.py` (`ProjectStatus.merges_active: int`)
- Test: `platform/tests/test_dedup_service.py`

**Interfaces:**
- Consumes: `list_works`, `dedup`, `merge_works`, `Project`.
- Produces:
  - Payloads: `DedupMerged(merge_id, primary: str, absorbed: tuple[str, ...] (sorted, ≥ 1), rule: str, records: int)`; `DedupReverted(merge_id, reason: str (non-empty), manual: bool)`. Types `dedup.merged`, `dedup.reverted`; IDs `mrg_` + ULID; `refs = (primary, *absorbed)`.
  - Projection: `merges(merge_id PK, primary, absorbed JSON, rule, records, status 'active'|'reverted', reverted_reason, manual)`; `blocked_pairs(a, b) PK` (a < b) — a **manual** revert inserts (primary, x) for each absorbed x. Handlers total.
  - `DedupSummary(StrictModel)`: `created: list[str]`, `reverted: list[str]`, `unchanged: int`, `records: int`, `works: int`, `canonical: int`.
  - `dedup_run(project) -> DedupSummary` — system actor. Run `dedup(list_works(project), blocked=…)`; for each cascade merge with absorbed IDs: if an active merge has the same primary and absorbed set → unchanged; else revert (automatic, reason `"superseded by <new id>"`) every active merge sharing a member, and record a new `dedup.merged`. Active merges no longer produced → revert with reason `"no longer matched"`. All events in one `project.record`. Identity collapses (same work ID) are not merges and produce no events.
  - `revert_merge(project, actor, merge_id: str, reason: str) -> None` — unknown or already reverted → `FactoryValidationError` field `merge_id`; empty reason → field `reason`; writes `dedup.reverted(manual=True)` by `actor` (agent ⇒ `input_blob` = blob of `{merge_id, reason}`).
  - `canonical_works(project) -> list[Work]` — applies active merges with `merge_works` (deterministic, sorted by id).
  - `active_merges(project) -> list[DedupMerged]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_cross_identifier_duplicates_become_one_recorded_merge(project, fake_sources): ...
    # published DOI record + arXiv preprint (same title/author/year) → 1 merge, canonical 1, works 2
def test_rerun_is_idempotent(project, fake_sources):
    first = dedup_run(project); second = dedup_run(project)
    assert len(first.created) == 1 and second.created == [] and second.unchanged == 1
def test_new_record_joining_a_group_supersedes_the_merge(project, fake_sources): ...  # old merge reverted (automatic), new merge active
def test_manual_revert_is_not_reapplied(project, agent, fake_sources):
    mid = dedup_run(project).created[0]; revert_merge(project, agent, mid, "different papers")
    assert dedup_run(project).created == [] and len(canonical_works(project)) == 2
def test_revert_validation(project): ...                 # unknown id → field merge_id; empty reason → field reason
def test_status_counts_active_merges(project, fake_sources): ...
def test_dedup_rebuild_equals_incremental(project, fake_sources): ...
```

- [ ] **Step 2–4:** fail → implement → pass (`uv run pytest tests/test_dedup_service.py -v -W error`).
- [ ] **Step 5: Commit** — `git commit -m "feat(dedup): reversible merges recorded as events"`

---

### Task 11: MCP tools, CLI status, acceptance and gates

**Files:**
- Modify: `platform/src/factory/mcp/server.py`, `platform/src/factory/cli/main.py`
- Create: `platform/tests/test_mcp_search.py`, `platform/tests/test_acceptance_acquisition.py`
- Test: extend `platform/tests/test_cli.py`

**Interfaces:**
- Consumes: `register_query`, `run_query`, `dedup_run`, `default_sources`, `make_agent_actor`, `guarded`.
- Produces:
  - `build_server(settings, clock=…, sources: Mapping[str, SourceFactory] | None = None)` (default `default_sources()`).
  - Tool `search_run(project: str, source: str, query: str, role: str, model: str, skill: str, kind: str = "keyword", purpose: str = "search", limit: int | None = None, resume_run: str | None = None) -> dict` — registers the query as the agent, runs it, returns `ok(RunSummary)`; with `resume_run`, the query of that run is reused (no new registration). Docstring: "Run a literature query against OpenAlex or arXiv exhaustively; every raw page is archived and counts are recorded."
  - Tool `dedup_run(project: str, role: str, model: str, skill: str) -> dict` → `ok(DedupSummary)`. Docstring: "Find and record duplicate works; merges are reversible."
  - CLI `status` adds lines `works: <n> (records <m>, merges <k>)` and `searches: <runs> runs (complete <a> / partial <b> / failed <c> / interrupted <d>)` and one `shortfall: <run_id> <source> <retrieved>/<reported> — <note>` line per shortfall.

- [ ] **Step 1: Write the acceptance tests** (real adapters over `httpx.MockTransport` with the fixture files; no network)

```python
def test_datacite_doi_and_bare_arxiv_id_are_one_work(project, mock_sources):   # slice-1 acceptance 3
    # OpenAlex returns doi https://doi.org/10.48550/arXiv.2301.01234; arXiv returns id 2301.01234v2
    for src in ("openalex", "arxiv"):
        run_query(project, register_query(project, project.human_actor(), QuerySpec(source=src, kind="keyword", text="x"), sources=mock_sources), sources=mock_sources)
    work = only_work_with_arxiv(project, "2301.01234")
    assert work.sources == ["openalex", "arxiv"] and len(work.provenance) == 2

def test_published_and_preprint_merge_is_listed_and_reversible(project, mock_sources, agent): ...  # acceptance 3 (cross-id case)
def test_every_run_stores_reported_and_retrieved_and_shortfall_is_visible(project, mock_sources): ...  # acceptance 4
def test_adapters_never_request_relevance_sorting(mock_sources): ...   # acceptance 14: inspect captured requests of both adapters
def test_acquisition_rebuild_is_deterministic(project, mock_sources):
    ...  # after searches + dedup + revert: delete .index, `factory --root … rebuild` → same state hash
```

- [ ] **Step 2: Write the MCP and CLI tests**

```python
@pytest.mark.anyio
async def test_search_run_tool(settings, project, mock_sources): ...   # ok, run summary; query.registered actor is the agent with input_blob
@pytest.mark.anyio
async def test_search_run_validation_error(settings, project, mock_sources): ...  # source "pubmed" → {"ok": False, errors[0].field == "source"}
@pytest.mark.anyio
async def test_dedup_run_tool(settings, project, mock_sources): ...
def test_status_shows_works_searches_and_shortfalls(tmp_path): ...
```

- [ ] **Step 3: Run to verify failure, implement, run to verify pass** — `uv run pytest -v -W error`.
- [ ] **Step 4: Run all quality gates**

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests
uv run pytest -W error --cov=factory.services --cov=factory.model --cov-report=term-missing --cov-fail-under=90
uv run pytest -m network -v        # optional, needs internet; record the result in the report
```
Expected: clean, all pass, coverage ≥ 90%.

- [ ] **Step 5: Update `CLAUDE.md`** Status line → `slice 1: sub-plans 1 (platform core) and 2 (works and acquisition) implemented — see docs/plans/.`
- [ ] **Step 6: Commit** — `git commit -m "feat(mcp): search_run and dedup_run; acquisition acceptance tests"`

---

## Self-review notes

- **Spec coverage:** work IDs and arXiv–DOI bridging (§3) → Task 2; `Work` + provenance invariant (R-02, acceptance 2) → Task 3; adapter contract with reported vs retrieved, raw archiving, resume (R-03, R-21–R-23, acceptance 4, 14) → Tasks 5–8; per-host rate limiter from arxiv-miner → Task 4; 4-stage cascade, union-find, reversible merges (R-26, acceptance 3) → Tasks 9–10; MCP tools (`search_run`, `dedup_run` from the slice-1 list) → Task 11; plan-1 carry-over → Task 1.
- **Interpretation recorded:** a DataCite arXiv DOI and the bare arXiv ID produce the *same* work ID (ported bridging), so acceptance 3's OpenAlex/arXiv case yields one work with two provenance entries and no merge event; "listed and reversible" is demonstrated on the cross-identifier case (published DOI vs preprint), which is the case where a merge exists.
- **Deferred by the split:** protocol gating of `search_run` and the PRESS review (plan 3); seeds and seed checks (plan 3); `search_chase` service and PRISMA counts (plan 5; the OpenAlex `FILTER` kind with `cites:`/`openalex:` is the hook); replay of searches (R-27, P/S modes) is not in slice 1's in-scope list and is not planned here.
- **Not ported:** PubMed adapter, `fulltext.py`, tenacity (replaced by `PoliteClient`).
