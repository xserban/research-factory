# Watch Plan, Watch Cycles and Incremental Dedup Implementation Plan (slice 4b, sub-plan living-A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** v1 cut: Task 7 (scale test) moved to Later. Task 4 bumps `PROJECTION_VERSION` by one from the value it finds; the watch module (kind `retrieval`) is declared for slice M there. Task 5's `network` test of the window filters stays in v1.

> **Dependencies.** Slice 1, slice 2 plans A–E and slice 3a (G1, for the snowball round authorisation pattern) merged. Slice M (module contract) is not required: the cycle is a hand-written service and moves behind the contract later without changing events. Sub-plans living-B, -C and -D consume this plan's Interfaces blocks exactly.

**Goal:** A project can declare a `watch_plan`, and `factory watch run --due [--all]`, called by an external scheduler, runs one recorded watch cycle per due project: every planned query of every due source re-run as an ordinary search run (full replay or a declared window), new records deduplicated incrementally, counts computed.

**Architecture:** A new protocol section `WatchPlan` (omitted from the hash while `None`, outside `S@`). Pure due and window computation in `factory/living/`. `services/watch.py` opens a cycle under the exclusive index lock, registers and runs queries through the existing `register_query`/`run_query`, then calls `services/dedup_incremental.py`, and closes the cycle with counts recomputed from the run events. Window queries name their cycle as the last ref and are authorised by a waiver in `search_authorization`, mirroring snowball rounds.

**Tech Stack:** Python ≥ 3.11, pydantic, SQLAlchemy core over SQLite, typer, the MCP server already in `mcp/server.py`; no new dependency.

**Spec:** `docs/specs/slice-4b-living-corpus.md` rulings 1–5, 7, 20, 21; acceptance 1–6, 14, 15 (cycle part), 17.

## Rulings made in this plan

1. **Cycle refs.** `watch.cycle_started` refs: `(cycle_id, protocol_id)`; `watch.cycle_finished` refs: `(cycle_id,)`. A query registered for a window names the cycle as its last ref (as `round_id` in `register_query`); a `full` query reuses the registered query whose spec matches the planned query (the earliest such `qry_`), registering one only when none exists (a query planned by a later amendment), and is re-run by `run_query` (the planned text is already authorised). [confirm]
2. **Resume.** An open cycle (started, not finished) is resumed by the next `watch_run`: queries whose run in the cycle completed are skipped; others run again. A cycle older than `CYCLE_STALE_AFTER = 24 h` is closed as `partial` with note `abandoned` before a new one opens. [confirm]
3. **Window filter by adapter.** `Source` gains an optional attribute `window_filter: Callable[[date], dict[str, str]] | None` (default `None`). arXiv: the `submittedDate:[YYYYMMDD0000 TO 999912312359]` clause appended to the query text is not a filter in our `QuerySpec`; the arXiv adapter therefore maps a `filters["listed_since"] = "YYYY-MM-DD"` key to that clause inside `run`. OpenAlex: `filters["listed_since"]` maps to `from_created_date`. The `QuerySpec` therefore differs from the planned one only by `filters["listed_since"]`. [confirm]
4. **Window start.** For a window source, `window_start = (start time of the last cycle in which every run of that source completed) − overlap_days`; with no such cycle, the source runs `full` and that cycle counts as its first full replay. [confirm]
5. **Counts.** `SourceCounts(source, runs, complete_runs, retrieved, new_works, duplicates_in_cycle, window_missed | None, disappeared | None)`; `disappeared` only on full replays: works whose every database provenance comes from earlier runs of the same query and which this replay did not return. Computed by `living/counts.py` from run events and index rows; never passed in. [confirm]

## Global Constraints

- All slice-1 to 3a constraints hold. The platform never calls a model; no key, no SDK; no daemon, thread, timer or listener in `platform/`.
- Events are the source of truth; the index is written by the projector alone. Due times and counts are computed on read.
- Invalid input writes nothing and returns structured errors. `watch_run` with nothing due writes nothing.
- Business logic in `services/`; pure helpers in `factory/living/` and `model/watch.py`; `mcp/` and `cli/` parse and format only.
- No function loads all works of a project into memory; incremental dedup reads by indexed keys in batches of at most `DEDUP_BATCH = 2_000` records.
- A log without `watch_plan` or watch events replays to identical `P@`, `S@` and state hash except `PROJECTION_VERSION`.
- `uv run pytest -m "not network and not slow"`, `mypy --strict`, ruff pass; coverage ≥ 90 % for `services/` and `model/`.

## Review Focus

1. `watch_plan` omitted from the hash while `None`; outside `S@`; PRESS confirmation carries (Task 1, `test_watch_plan_keeps_s_hash_and_press`).
2. Two concurrent `watch_run` calls write one cycle (Task 4, `test_concurrent_runs_write_one_cycle`).
3. A window query naming a foreign or finished cycle is refused (Task 5, `test_window_query_needs_its_open_cycle`).
4. Incremental dedup followed by `dedup_run` writes nothing (Task 3, `test_incremental_then_full_writes_nothing`, property-based over random corpora).
5. Counts recomputed from events equal those in `watch.cycle_finished` (Task 4, `test_cycle_counts_recompute`).

## File Structure

- Create `model/watch.py` (`WatchSource`, `WatchPlan`, `CycleTrigger`, `CycleStatus`, `SourceCounts`, `WatchCycleStarted`, `WatchCycleFinished`, ids `WCY_ID_RE`).
- Modify `model/protocol.py` (`ProtocolSpec.watch_plan`, `AMENDABLE_FIELDS`, `_OMITTED_WHEN_NONE`), `services/protocol_rules.py` (readiness), `services/protocol.py` (`search_authorization` cycle waiver).
- Create `factory/living/__init__.py`, `living/due.py`, `living/window.py`, `living/counts.py`.
- Create `services/dedup_incremental.py`; modify `services/dedup_cascade.py` only to expose `strong_keys(work)` and `title_bucket_key(work)` (renames of private helpers, old names kept as aliases).
- Create `services/watch.py`, `index/watch.py`; modify `index/default.py` (register), `events/catalog.py`.
- Modify `sources/base.py` (`window_filter`), `sources/arxiv.py`, `sources/openalex.py`.
- Modify `cli/main.py` (`watch` command group), `mcp/server.py` (`watch_status`, `watch_run`).
- Tests: `test_watch_plan.py`, `test_living_due.py`, `test_dedup_incremental.py`, `test_watch_cycle.py`, `test_watch_window.py`, `test_cli_watch.py`, `test_watch_scale.py` (`slow`), `test_watch_network.py` (`network`); helper `tests/watch_helpers.py` (a ready pilot project with PRESS confirmed, fixture adapters `FakeSource` that return scripted pages per call and a scripted `listed` date per record, and a `FixedClock`).

---

### Task 1: `WatchPlan` protocol section and readiness

*Tier: critical (protocol hash).*

**Files:** Create `model/watch.py`; Modify `model/protocol.py`, `services/protocol_rules.py`; Test `tests/test_watch_plan.py`.

**Interfaces:**
- Consumes: `ProtocolSpec`, `protocol_version`, `search_strategy_hash`, `section_digest`, `AMENDABLE_FIELDS`, `MethodProfile.LIVING_REVIEW`, `RigorMode`, `readiness rules` in `protocol_rules.py`.
- Produces (`model/watch.py`):
  - `class WatchSource(StrictModel)`: `source: str`, `interval_days: int = Field(ge=1)`, `mode: Literal["full", "window"] = "full"`, `overlap_days: int = Field(default=7, ge=1)`, `full_replay_every: int | None = Field(default=None, ge=1)`; validator: `window` requires `full_replay_every`.
  - `class WatchPlan(StrictModel)`: `sources: tuple[WatchSource, ...] = Field(min_length=1)`, `notices: tuple[Literal["openalex", "crossref"], ...] = ("openalex", "crossref")`, `notice_budget: int = Field(default=200, ge=0)`, `track_versions: bool = True`, `snapshot_every: int | None = Field(default=None, ge=1)`, `max_consecutive_failures: int = Field(default=3, ge=1)`, `digest_listing_cap: int = Field(default=50, ge=1)`, `until: date | None = None`; validator: unique `source`.
- Produces (`model/protocol.py`): `ProtocolSpec.watch_plan: WatchPlan | None = None`; `"watch_plan"` in `AMENDABLE_FIELDS` and `_OMITTED_WHEN_NONE`; not in `_SEARCH_STRATEGY_KEYS`.
- Produces (`services/protocol_rules.py`): readiness issues `watch_plan.sources[i].source` (`not an included source`), `watch_plan` (`required for living-review`; error in pilot/systematic, gap in exploratory), `watch_plan.sources[i].mode` (`source has no window filter`) — the last uses `default_sources()[name]` adapter class attribute `window_filter`.

- [ ] **Step 1: Tests.**
```python
def test_absent_watch_plan_keeps_protocol_id(): assert protocol_version(spec) == protocol_version(spec.model_copy(update={"watch_plan": None})) == KNOWN_P_ID
def test_watch_plan_keeps_s_hash_and_press():
    a, b = spec, spec.model_copy(update={"watch_plan": PLAN})
    assert protocol_version(a) != protocol_version(b) and search_strategy_hash(a) == search_strategy_hash(b)
    # amend a PRESS-confirmed ready protocol to add the plan: search_authorization(...) == []
def test_window_requires_full_replay_every(): with pytest.raises(ValidationError): WatchSource(source="arxiv", interval_days=7, mode="window")
def test_living_review_needs_watch_plan_in_pilot(): assert ("watch_plan", "required for living-review") in readiness(pilot_living_spec)
def test_living_review_gap_in_exploratory(): ...   # listed by check --promote-to pilot, not a readiness error
def test_watch_source_must_be_included(): ...      # source "pubmed" not in sources → issue, nothing written
def test_window_on_adapter_without_filter_refused(): ...
```
- [ ] **Step 2:** run, see them fail. **Step 3:** implement. **Step 4:** `uv run pytest tests/test_watch_plan.py tests/test_amendments.py tests/test_protocol*.py -q` passes.
- [ ] **Step 5: Commit** `feat(living): watch_plan protocol section and readiness`.

### Task 2: Due and window computation (pure)

*Tier: standard.*

**Files:** Create `living/due.py`, `living/window.py`; Test `tests/test_living_due.py`.

**Interfaces:**
- Produces (`living/due.py`):
  - `@dataclass(frozen=True) class CycleView: cycle_id: str; started_at: datetime; finished_at: datetime | None; status: CycleStatus; sources: tuple[str, ...]; complete_sources: tuple[str, ...]; full_replay_sources: tuple[str, ...]`.
  - `def next_due(plan: WatchSource, cycles: Sequence[CycleView]) -> datetime | None` — `None` = due now (never run); else the last `finished_at` among cycles covering the source plus `interval_days`.
  - `def due_sources(plan: WatchPlan, cycles: Sequence[CycleView], now: datetime) -> tuple[str, ...]` — sorted; empty when `plan.until` is before `now.date()`.
  - `def consecutive_failures(source: str, cycles: Sequence[CycleView]) -> int`.
- Produces (`living/window.py`):
  - `def window_start(source: WatchSource, cycles: Sequence[CycleView]) -> date | None` (ruling 4; `None` = run full).
  - `def is_full_replay(source: WatchSource, cycles: Sequence[CycleView]) -> bool` — `mode == "full"`, or no complete cycle yet, or the number of complete cycles of the source since its last full replay `>= full_replay_every - 1`.
  - `def window_spec(planned: PlannedQuery, start: date) -> QuerySpec` — `filters | {"listed_since": start.isoformat()}`, purpose `SEARCH`.

- [ ] **Step 1: Tests.** `test_never_run_is_due_now`, `test_due_after_interval_on_fixed_clock`, `test_until_passed_nothing_due`, `test_window_start_skips_partial_cycles` (a partial cycle does not advance the start), `test_full_replay_every_three` (cycles 1 full, 2 window, 3 window, 4 full), `test_window_spec_differs_only_by_listed_since`, `test_consecutive_failures_resets_on_complete`.
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_living_due.py -q`.
- [ ] **Step 5: Commit** `feat(living): due and window computation`.

### Task 3: Incremental deduplication

*Tier: critical (corpus identity; subagent-driven).*

**Files:** Create `services/dedup_incremental.py`; Modify `services/dedup_cascade.py` (public `strong_keys`, `title_bucket_key`, `cascade_match(new: Work, candidates: Sequence[Work], blocked) -> CascadeMerge | None`), `index/dedup.py` (indexed key table `work_keys(kind, value, work_id)` and `work_title_buckets(year, prefix, work_id)` filled by the projector from `search.records_parsed` and merges); Test `tests/test_dedup_incremental.py`.

**Interfaces:**
- Consumes: `dedup`, `merge_works`, `DedupMerged`, `active_merges`, `_blocked_pairs`, `YEAR_WINDOW`, `normalize_title`.
- Produces: `def dedup_new(project: Project, work_ids: Sequence[str]) -> DedupSummary` — under `project.index.exclusive()`, for batches of at most `DEDUP_BATCH` new ids: fetch candidate works by `work_keys` hits and by `work_title_buckets` for years `y ± YEAR_WINDOW`, run the same cascade on `new ∪ candidates ∪ members of their active merges`, and reconcile exactly as `_reconcile` does but restricted to groups touching a new id. `DedupSummary.works` counts the works considered, not the corpus.
- Produces: `def considered_works(project: Project, work_ids: Sequence[str]) -> list[Work]` (for tests and living-C aliases; aliases join `work_keys` in living-C).

- [ ] **Step 1: Tests.**
```python
def test_new_doi_duplicate_merges(): ...                # same DOI, different title casing → one dedup.merged, same rule as dedup_run
def test_title_bucket_merge_within_year_window(): ...
def test_blocked_pair_stays_apart(): ...                # revert_merge, then a third record bridging them: no merge
@given(corpora())                                       # hypothesis; 30 examples; works split into 3 arrival batches
def test_incremental_then_full_writes_nothing(c):
    for batch in c.batches: ingest(batch); dedup_new(p, batch_ids)
    before = event_count(p); dedup_run(p); assert event_count(p) == before
def test_reads_bounded_by_batch(monkeypatch): ...       # spy on list_works: never called
```
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_dedup_incremental.py tests/test_dedup_service.py tests/test_dedup_cascade.py -q`.
- [ ] **Step 5: Commit** `feat(living): incremental deduplication by indexed keys`.

### Task 4: Watch cycle service, events and projection

*Tier: critical (subagent-driven).*

**Files:** Create `services/watch.py`, `index/watch.py`, `living/counts.py`; Modify `model/watch.py` (events), `events/catalog.py`, `index/default.py`; Test `tests/test_watch_cycle.py`.

**Interfaces:**
- Consumes: `register_query`, `run_query`, `RunSummary`, `current_protocol`, `search_authorization`, `dedup_new`, `due_sources`, `window_start`, `is_full_replay`, `window_spec`, `project.index.exclusive()`, `project.ids.new("wcy")`, `project.clock`.
- Produces (`model/watch.py`):
  - `CycleTrigger = Literal["scheduler", "human", "agent"]`; `class CycleStatus(StrEnum): OPEN, COMPLETE, PARTIAL, FAILED`.
  - `class CycleSource(StrictModel): source: str; mode: Literal["full", "window"]; window_start: date | None; full_replay: bool`.
  - `class WatchCycleStarted(StrictModel): cycle_id: str (WCY_ID_RE); protocol_id: str; sources: tuple[CycleSource, ...]; skipped: tuple[str, ...]; trigger: CycleTrigger`.
  - `class WatchCycleFinished(StrictModel): cycle_id; status: CycleStatus (not OPEN); run_ids: tuple[str, ...]; status_run_ids: tuple[str, ...] = (); counts: tuple[SourceCounts, ...]; note: str | None = None`.
- Produces (`services/watch.py`):
  - `class CycleSummary(StrictModel): cycle_id: str; status: CycleStatus; counts: tuple[SourceCounts, ...]; run_ids: tuple[str, ...]; new_work_ids: tuple[str, ...]`.
  - `def watch_run(project: Project, *, sources: Mapping[str, SourceFactory], trigger: CycleTrigger, actor: Actor | None = None, force: bool = False, after_runs: Sequence[CycleHook] = ()) -> CycleSummary | None` — `None` when nothing is due and not `force`; `after_runs` hooks receive `(project, cycle_id, new_work_ids)` and return the run ids they started (`CycleHook = Callable[[Project, str, tuple[str, ...]], tuple[str, ...]]`), which the cycle records as `status_run_ids`; this is how living-B (sample extension, snapshots; returning `()`) and living-C (status checks) attach without changing this signature. A hook that raises makes the cycle `partial` with the hook's name in `note`.
  - `def watch_status(project: Project) -> WatchStatus` (per source: last cycle, next due, mode, window start, consecutive failures; open cycle id).
  - `def cycles(project: Project) -> list[CycleView]`.
- Produces (`living/counts.py`): `def source_counts(project: Project, cycle_id: str) -> tuple[SourceCounts, ...]`.
- Produces (`index/watch.py`): tables `watch_cycles(cycle_id, started_event, started_at, finished_at, status, protocol_id, trigger)`, `watch_cycle_sources(cycle_id, source, mode, window_start, full_replay, complete)`, `watch_cycle_runs(cycle_id, run_id, query_id, source)`.

- [ ] **Step 1: Tests.** `test_cycle_runs_every_planned_query_of_due_sources`, `test_nothing_due_writes_nothing`, `test_cycle_counts_recompute` (recompute from events equals `watch.cycle_finished.counts`), `test_failed_run_makes_cycle_partial_and_others_run`, `test_open_cycle_resumed_not_doubled`, `test_abandoned_cycle_closed_partial`, `test_concurrent_runs_write_one_cycle` (two threads, one cycle), `test_refused_when_protocol_not_ready` (nothing written), `test_full_replay_reports_disappeared`, `test_new_works_are_pending` (`final_outcomes` gives `PENDING`), `test_hooks_called_once_with_new_ids`, `test_rebuild_identical_watch_tables`.
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_watch_cycle.py tests/test_acceptance_rebuild.py -q`.
- [ ] **Step 5: Commit** `feat(living): watch cycles over recorded search runs`.

### Task 5: Window queries, adapter filters and the cycle waiver

*Tier: critical (search authorisation).*

**Files:** Modify `sources/base.py`, `sources/arxiv.py`, `sources/openalex.py`, `services/protocol.py` (`search_authorization(..., cycle_id: str | None = None)`), `services/search.py` (`register_query(..., cycle_id: str | None = None)`; the last-ref rule shared with `round_id`, both given is an error); Test `tests/test_watch_window.py`, `tests/test_watch_network.py`.

**Interfaces:**
- Produces: `Source.window_filter: ClassVar[bool] = False` (adapters that honour `filters["listed_since"]` set it `True`); arXiv maps it to `AND submittedDate:[YYYYMMDD0000 TO 999912312359]`; OpenAlex to `from_created_date:YYYY-MM-DD`.
- Produces: `search_authorization` waives the planned match iff `cycle_id` names an **open** cycle of the current protocol whose `CycleSource` for `spec.source` is `window` and `spec` equals `window_spec(planned, start)` for some planned query and that cycle's `window_start`.

- [ ] **Step 1: Tests.** `test_window_spec_authorised_with_its_cycle`, `test_window_query_needs_its_open_cycle` (no cycle, finished cycle, cycle of an older protocol: each refused, nothing written), `test_window_with_other_date_refused`, `test_arxiv_maps_listed_since`, `test_openalex_maps_listed_since` (URL contains `from_created_date`), `test_full_replay_counts_window_missed` (fixture: a record listed inside window 1 but absent from its pages appears in the replay → `window_missed == 1`), `test_round_and_cycle_together_refused`. Network (`@pytest.mark.network`): `test_openalex_from_created_date_accepted_without_key` (ruling 2 verification: a 200 with results, else the test documents the failure and window mode for OpenAlex is disabled by setting `window_filter = False`), `test_arxiv_submitted_date_window`.
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_watch_window.py tests/test_search*.py tests/test_snowball*.py -q`.
- [ ] **Step 5: Commit** `feat(living): window queries authorised by their cycle`.

### Task 6: CLI and MCP entry points for external schedulers

*Tier: standard.*

**Files:** Modify `cli/main.py`, `cli/render.py`, `mcp/server.py`; Test `tests/test_cli_watch.py`, extend MCP tests.

**Interfaces:**
- CLI: `factory watch run [--project SLUG | --all] [--due/--force] [--dry-run] [--json]` — iterates `list_projects(settings)` for `--all`, one project at a time, each in its own `open_project`; an exception in one project is reported and the next runs. Exit code 0 (nothing due or all complete), 1 (any partial or failed), 2 (invalid input). `--dry-run` prints due sources and window starts and writes nothing. `factory watch status [--project SLUG]`, `factory watch plan` (prints the current `watch_plan`).
- MCP: `watch_status()` (read), `watch_run(force: bool = False)` (agent actor, `input_blob`); both refused to pass sessions (`_is_pass_session` rule of decision 48).
- Docs: create `docs/runbook-living.md` (a launchd plist and a cron line; a scheduled Claude routine that calls `factory watch run --due --all`, then `factory digest --all --record`, and delivers the output). A runbook, not a spec; the digest command arrives in living-D, so the runbook marks that step as pending until then.

- [ ] **Step 1: Tests.** `test_cli_watch_run_due_exit_codes` (0, 1, 2 cases on fixtures), `test_cli_all_continues_after_project_error`, `test_cli_dry_run_writes_nothing`, `test_mcp_watch_run_records_agent_provenance`, `test_mcp_watch_refused_to_pass_session`.
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_cli_watch.py tests/test_mcp*.py -q`.
- [ ] **Step 5: Commit** `feat(living): factory watch command and MCP watch tools`.

## Verification

`uv run pytest -m "not network and not slow" -q && uv run mypy --strict src && uv run ruff check src tests` from `platform/`.

## Self-review notes

- Every count in `watch.cycle_finished` is recomputed in a test from the run events.
- No new code path writes the index; `index/watch.py` is a projector module.
- `full` queries reuse their registered query ids, so the PRISMA-S report shows one query row with many dated runs; `window` queries are separate rows tied to their cycle.

## Later (not v1)

Moved here by the v1 cut of 2026-11-04 (decision 74); built after the v1 plans of the build order (`2026-11-05-build-order.md`), in the order listed. Task text is unchanged; references to "Task N" inside a moved task use the plan's original numbering.

### Later L1 (was Task 7): Scale test

*Tier: standard.*

**Files:** Test `tests/test_watch_scale.py` (`@pytest.mark.slow`).

- [ ] **Step 1:** Build a synthetic project with 2·10^5 works (generated records ingested through `search.records_parsed` events in pages of 1,000) and a fake source returning 10^4 records of which 5 % duplicate existing works by DOI and 2 % by title. Run one cycle. Assert: the merges equal a `dedup_run` on a copy; `tracemalloc` peak below a bound proportional to `DEDUP_BATCH` (not to corpus size; the bound is calibrated once and pinned in the test with a comment); wall time recorded, not asserted.
- [ ] **Step 2:** `uv run pytest -m slow tests/test_watch_scale.py -q`.
- [ ] **Step 3: Commit** `test(living): watch cycle scale test`.
