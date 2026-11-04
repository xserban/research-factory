# Coverage Map, Leaderboard Timelines and Horizon Views Implementation Plan (slice 7b, sub-plan V-B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** Slice 4b is merged first: the horizon states the latest search or watch date per source. No projection change.

> **Dependencies.** V-A merged (`ViewMeta`, `view_meta`, `to_json`, `views/render.py`). Plan 2E (`group_id`, `evidence/pareto.py`, `ReportSpec`, evidence-report rulings 2, 5, 6) and plan D (`final_rows`, `grouped_rows`, `FinalRow`) merged. G2-D/G2-C (confirmed ideas, idea members, lineage edges) merged. Slice 4 is not required: without watches the horizon is the last search date, which the views state.

**Goal:** Give the evidence and lineage data three time- and coverage-oriented views — a methods × comparability-group coverage map (counts only), a record timeline and per-year frontiers inside one comparability group, and horizon activity series per idea and year — without ranking across groups and without loading all rows.

**Architecture:** Task 1 adds per-group accessors in `services/evidence_groups.py` so that views read one group at a time (the evidence report keeps using `grouped_rows`). `services/coverage.py` and `services/horizon.py` build read models defined in `model/views.py`; pure helpers in `views/timeline.py` compute records and per-year frontiers from a list of dated points using `evidence/pareto.py`. Renderers extend `views/render.py`.

**Tech Stack:** as plan 2E (`decimal.Decimal`); no new dependency.

**Spec:** `docs/specs/slice-7b-views-writing.md` rulings 5, 6, 7, 26; acceptance 3, 4, 17 (coverage). Decisions 41, 42 item 3, 52; R-05, R-45.

## Rulings made in this plan
1. **Group accessors [confirm].** `group_index` returns one summary per comparability group computed by SQL over the key cells of current final rows (normalised as `grouped_rows` does), with `group_id` from plan 2E; `rows_of_group(project, group_id)` returns exactly the rows `grouped_rows` would put in that group, computed by running the plan-D final-row fold only for the works whose key cells match. Equality with `grouped_rows` is a test on every fixture of plans D and 2E.
2. **Method normalisation.** Coverage rows use `normalise_for(method_name field, value)` (plan D); variants are not separate rows (a variant column would invite a ranking table). Ideas × groups uses `result_row` links of live, final contribution `result` items whose row lies in the group.
3. **Dates.** A row's date is `Work.dates.published` of its work; rows of undated works are counted per group (`undated`) and listed by work id; no other date is used (spec ruling 6 option a).
4. **Records.** Within (group, value unit), independent rows sorted by (date, work id, row key); a row is a record when its canonical value is strictly better than every row with an earlier date; all rows sharing the best value at the first date are records. Copied rows are never records (evidence-report ruling 6). Direction from the group (evidence-report ruling 5); `direction-unknown` or `direction-conflict` → no timeline, notice.
5. **Per-year frontiers.** For each year with at least one new dated row, and each declared cost axis of the pack (`ReportSpec.frontier_costs`), the Pareto frontier of independent rows dated up to and including that year, computed with `evidence/pareto.py` (same partitions by unit and resolution as 2E ruling 6). A frontier point lists `trace_id` (`rk_…/value`).
6. **Horizon series [confirm].** Per year: included works per confirmed idea (members, after merges); confirmed ideas whose origin is dated that year; stated or confirmed `builds-on`/`improves-on` edges by the citing work's year; records per group. Undated items counted separately. Header notice `corpus-horizon` listing, per source, the latest search run date (and watch run when slice 4 exists) and the sentence "works published after these dates are not in the corpus". No other statistic; no label "emerging".
7. **Bounds.** `coverage_view` lists at most `VIEW_MAX_NODES` methods and `VIEW_MAX_GROUPS = 200` groups by (works desc, id); counts are complete. `view_timeline` is per group; `view_horizon` lists at most 200 ideas and summarises groups by records-per-year counts only.

## Global Constraints
- No value or rank crosses comparability groups; coverage cells hold counts only (decision 41, R-45).
- Read-only; every number derived; every output names filter and `as_of`.
- Views never read the library and carry no document text; timelines carry `trace_id`s, not quotes.
- `view_*` tools refused to pass sessions; agent views follow `agent_evidence` (no audit error rate).
- TDD; `uv run pytest -m "not network and not slow"`; `mypy --strict`; ruff; coverage ≥ 90%.

## Review Focus
1. `rows_of_group` equals `grouped_rows` on every plan D/2E fixture (Task 1, `test_group_accessors_equal_grouped_rows`).
2. A coverage cell never contains a value (Task 2, `test_coverage_has_no_values` — every leaf is an int).
3. Records with ties at the same date, a copied row with a better value, and an undated row (Task 3, `test_record_rules`).
4. The evidence report is byte-identical before and after this plan (Task 1, `test_evidence_report_unchanged`).

## File Structure
- Create `services/evidence_groups.py`, `services/coverage.py`, `services/horizon.py`, `views/timeline.py`.
- Modify `model/views.py`, `views/render.py`, `mcp/server.py`, `cli/main.py`.
- Tests: `tests/test_evidence_groups.py`, `tests/test_coverage.py`, `tests/test_timeline.py`, `tests/test_horizon.py`, `tests/test_views_b_cli_mcp.py`, `tests/test_coverage_scale.py` (`slow`).

### Task 1: Per-group accessors

*Tier: critical (must equal the evidence grouping exactly).*

**Files:** Create `services/evidence_groups.py`; Test `tests/test_evidence_groups.py`.

**Interfaces:**
- Consumes: `grouped_rows`, `final_rows`, `FinalRow`, `GroupKey` (`services/extraction_agreement.py`); `group_id` (`services/evidence_report.py`); `normalise_for`.
- Produces: `class GroupSummary(StrictModel): group_id: str; key: list[tuple[str, str]]; works: int; rows: int; independent: int; copied: int`; `group_index(project: Project) -> list[GroupSummary]` (ordered by key); `rows_of_group(project: Project, group_id: str) -> list[FinalRow]` (unknown id → `FactoryValidationError` field `group_id`); `final_rows_for(project: Project, work_ids: Collection[str]) -> list[FinalRow]` (the plan-D fold restricted to these works; equal to the filter of `final_rows`).

- [ ] **Step 1: Tests.**
```python
@pytest.mark.parametrize("fixture", PLAN_D_AND_2E_FIXTURES)
def test_group_accessors_equal_grouped_rows(fixture):           # Review Focus 1
    g = grouped_rows(fixture)
    assert {s.group_id for s in group_index(fixture)} == {group_id(k) for k in g.groups}
    for k, rows in g.groups.items(): assert rows_of_group(fixture, group_id(k)) == rows
def test_final_rows_for_equals_filter(fixture): ...
def test_summary_counts_equal_independence_counts(fixture): ...
def test_unknown_group_rejected(fixture): ...
def test_evidence_report_unchanged(fixture): ...                 # Review Focus 4: snapshot before/after
```
- [ ] **Step 2:** FAIL. **Step 3:** Implement (SQL to find candidate works per key; fold via the plan-D function on those works only). **Step 4:** tests, mypy, ruff. **Step 5:** Commit `feat(views): per-group evidence accessors`.

### Task 2: Coverage map

*Tier: standard.*

**Files:** Create `services/coverage.py`; extend `model/views.py`; Test `tests/test_coverage.py`, `tests/test_coverage_scale.py`.

**Interfaces:**
- Produces (`model/views.py`): `class CoverageCell(StrictModel): independent: int; copied: int; works: int`; `class CoverageView(StrictModel): meta: ViewMeta; groups: list[GroupSummary]; methods: list[str]; cells: dict[str, dict[str, CoverageCell]]` (method → group_id → cell; absent = no rows); `ideas: list[str]`; `idea_cells: dict[str, dict[str, CoverageCell]]`.
- Produces (`services/coverage.py`): `VIEW_MAX_GROUPS = 200`; `coverage_view(project: Project) -> CoverageView`.

- [ ] **Step 1: Tests.** `test_cells_count_rows_by_method_and_group`; `test_coverage_has_no_values` (walk the JSON: every leaf of `cells` is an int; Review Focus 2); `test_variants_fold_into_method`; `test_idea_cells_only_with_result_links`; `test_bounds_and_truncation`; `test_deterministic`; `@slow test_coverage_scale` (2·10^5 rows, < 5 s).
- [ ] **Step 2–4.** **Step 5:** Commit `feat(views): coverage map of methods by comparability group`.

### Task 3: Timelines (pure) and `view_timeline`

*Tier: standard.*

**Files:** Create `views/timeline.py`; extend `services/horizon.py` (create), `model/views.py`; Test `tests/test_timeline.py`.

**Interfaces:**
- Consumes: `pareto_front` and point types of `evidence/pareto.py` (the implementer uses the names 2E defines), `ReportSpec`, the group direction logic of `services/evidence_report.py` (exposed by 2E as `_direction`; this task promotes it to a public `group_direction(rows, spec) -> tuple[bool | None, DirectionStatus]` without changing behaviour).
- Produces (`views/timeline.py`): `@dataclass(frozen=True) DatedPoint(trace_id: str, work_id: str, row_key: str, year: int | None, value: Decimal, unit: str, costs: Mapping[str, Decimal], independent: bool)`; `records(points: Sequence[DatedPoint], higher_is_better: bool) -> list[DatedPoint]`; `yearly_frontiers(points, higher_is_better, axes: Sequence[str]) -> dict[int, dict[str, list[str]]]` (year → axis → frontier trace ids).
- Produces (`model/views.py`): `TimelineView(meta, group_id, key, direction, units: dict[str, UnitTimeline], undated: list[str], notices)` with `UnitTimeline(records: list[RecordPoint], frontiers: dict[int, dict[str, list[str]]])`.
- Produces (`services/horizon.py`): `timeline_view(project: Project, group_id: str) -> TimelineView`.

- [ ] **Step 1: Tests.**
```python
def test_record_rules():                                         # Review Focus 3
    pts = [p(2019, 70), p(2020, 72), p(2020, 72, wid="b"), p(2021, 71), p(2022, 80, independent=False), p(None, 99)]
    assert [x.trace_id for x in records(pts, True)] == ["t2019", "t2020", "t2020b"]
def test_lower_is_better(): ...
def test_yearly_frontier_monotone_inclusion(): ...               # each year's frontier only from points dated ≤ year
def test_units_never_mixed(project): ...
def test_unknown_direction_no_timeline(project): v = timeline_view(project, G_UNKNOWN); assert v.units == {} and v.notices[0].code == "direction-unknown"
def test_undated_listed(project): ...
def test_trace_ids_resolve(project): ...                         # each trace id accepted by trace()
```
- [ ] **Step 2–4.** **Step 5:** Commit `feat(views): record timelines and yearly frontiers within a group`.

### Task 4: Horizon activity view

*Tier: standard.*

**Files:** Modify `services/horizon.py`, `model/views.py`; Test `tests/test_horizon.py`.

**Interfaces:**
- Consumes: G2-C/G2-D idea and edge reads (`services/ideas.py`, `services/lineage.py` names as G2 defines), `get_work`, search run dates (`services/search.py` run listing; the implementer uses the existing read of `search_runs`), `group_index`, `timeline_view`.
- Produces: `class HorizonView(StrictModel): meta: ViewMeta; years: list[int]; idea_members: dict[str, dict[int, int]]; new_ideas: dict[int, list[str]]; new_edges: dict[int, int]; group_records: dict[str, dict[int, int]]; undated: dict[str, int]; horizon: dict[str, str]` (source → last run date); `horizon_view(project: Project) -> HorizonView`.

- [ ] **Step 1: Tests.** `test_series_equal_hand_counts`; `test_merged_ideas_counted_once`; `test_inferred_edges_excluded`; `test_corpus_horizon_notice_lists_each_source`; `test_no_emerging_label_or_citation_score` (the JSON contains neither "emerging" nor `cited_by_count`); `test_deterministic`.
- [ ] **Step 2–4.** **Step 5:** Commit `feat(views): horizon activity series`.

### Task 5: Renderers, MCP tools, CLI

*Tier: standard.*

**Files:** Modify `views/render.py`, `mcp/server.py`, `cli/main.py`; Test `tests/test_views_b_cli_mcp.py`.

**Interfaces:**
- Renderers: `coverage_markdown(v) -> str`, `coverage_csv(v) -> str`, `timeline_markdown(v) -> str`, `timeline_csv(v) -> str`, `horizon_markdown(v) -> str`, `horizon_csv(v) -> str`. Markdown headers state filter, `as_of`, the corpus horizon and "counts are activity, not quality".
- MCP (read; refused to pass sessions): `view_coverage(project)`, `view_timeline(project, group_id)`, `view_horizon(project)`.
- CLI: `factory view coverage|timeline GROUP_ID|horizon [--format md|json|csv] [--out PATH]`.

- [ ] **Step 1: Tests.** Tool list pinned; pass session refused; CLI outputs equal service JSON/renderers; unknown group → structured error.
- [ ] **Step 2–4.** **Step 5:** Commit `feat(views): coverage, timeline and horizon tools and commands`.

## Self-review notes
- Promoting `_direction` to `group_direction` is a rename with a behaviour-preserving test; the evidence report imports the public name.
- Slice 4 adds watch runs to the horizon notice; nothing else changes.

## Later (not v1)

None: every task of this plan is in v1.
