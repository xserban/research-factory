# View Contract, Processing Depth and Onion View Implementation Plan (slice 7b, sub-plan V-A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** Slice 3d is merged first: the regions overlay reads reviewed focus-region snapshots (`regions_of`), empty with a stated notice when none exist. No projection change.

> **Dependencies.** G2-D merged (`graph_nodes`, `graph_edges` with indexes on `(source, edge_type)`, `(target, edge_type)`; `GraphFilter`; overlays in `services/lineage.py`); G3-C merged (layer stays out of this view); G1 `included_works`. X-A is independent. The regions overlay is a stub until the slice-3 regions plan lands (it fills `OnionNode.regions`); a 7a presenter may consume the JSON. When slice M lands, `view_*` builders register as builder modules without signature change.

**Goal:** Define the common read-model header for all views, compute each work's processing depth, and build the onion view: rings of works at hop distance 0..k from the included corpus over stated and confirmed graph edges, with complete counts and bounded node lists, rendered as JSON, Markdown and DOT.

**Architecture:** `model/views.py` holds `ViewMeta`, `ViewNotice` and the onion read models. `services/views.py` computes `as_of` (last projected event id) and builds `ViewMeta`. `services/depth.py` computes processing depth for a batch of work ids with SQL. `services/onion.py` expands rings level by level using indexed reads on `graph_edges`, keeps the visited set in a connection-local `TEMP` table (no write to the index file), and asks `services/lineage.py` for the effective status of only the lineage edges it touches. Pure renderers in `views/render.py`.

**Tech Stack:** as G2-D; SQLAlchemy `text()`; no new dependency.

**Spec:** `docs/specs/slice-7b-views-writing.md` rulings 1–4, 25, 26; acceptance 1, 2, 17 (onion part). Decision 43 (no seed marking), slice-3b ruling 14 (status filter named).

## Rulings made in this plan
1. **`as_of` [confirm].** `as_of` is the id of the last event the projector applied (the index's sync cursor; the implementer exposes it as `Index.head() -> str | None` reading the existing cursor, no schema change). An empty log gives `None`.
2. **Edges and direction.** Distance is undirected: a `cites` or lineage edge in either direction joins two works. Default edge set `cites`, `builds-on`, `improves-on` with G2-D's default status filter (`stated`, `confirmed`); `include_inferred` widens it and is stated in the filter. Idea nodes are not ring members (they are groupings, not works); `OnionNode.ideas` lists the confirmed ideas a work belongs to.
3. **Focus.** `included_works(project)`; an explicit `focus` list (work ids) may replace it and is stated in the filter. A focus id that is not a corpus work is a structured error.
4. **Bounds.** `ONION_MAX_RING = 3`; requested larger rings are clamped and a notice `ring-clamped` added. Each ring lists at most `VIEW_MAX_NODES = 500` nodes ordered by (depth rank descending, work id); `truncated` is true when any ring is cut; counts are complete.
5. **Depth rank.** `verified` > `extracted` > `screened` > `indexed`; a work's depth is the highest it reaches (spec ruling 3). `extracted` counts a current evidence or contribution unit; `verified` needs a final row `agreed` or `resolved`, or an audited extraction item.
6. **DOT output.** `graph onion { layout=twopi; root="focus"; … }` with one invisible `focus` node joined to ring-0 nodes, `ring` encoded as edge length; node style by depth (filled for `verified`, solid for `extracted`, dashed for `screened`, dotted for `indexed`); only listed nodes are drawn; a comment line states the filter and truncation. Rendering is Graphviz's job (slice-3b ruling 4).

## Global Constraints
- Read-only: no event written; the index file is never written (TEMP tables live in SQLite's temp database of the read connection and are dropped on close).
- Every output names its filter and `as_of`; every count is derived (R-05).
- No query loads all edges or all works; ring expansion reads only edges incident to the current frontier.
- `view_onion` is refused to pass sessions; no output marks a work as a seed.
- TDD; `uv run pytest -m "not network and not slow"`; `mypy --strict`; ruff; coverage ≥ 90% for `services/` and `model/`.

## Review Focus
1. Counts are complete when node lists are truncated (Task 3, `test_counts_complete_when_truncated`).
2. An inferred edge changes rings only with `include_inferred` (Task 3, `test_inferred_edges_only_on_request`).
3. The index file's bytes and `state_hash` are unchanged after building a view (Task 3, `test_view_writes_nothing`).
4. Scale: ring 2 on 10^5 works / 10^6 edges within 5 s (Task 3, `test_onion_scale`, `slow`).

## File Structure
- Create `model/views.py`, `services/views.py`, `services/depth.py`, `services/onion.py`, `views/__init__.py`, `views/render.py`.
- Modify `index/index.py` (`head()`), `mcp/server.py`, `cli/main.py`.
- Tests: `tests/test_views_meta.py`, `tests/test_depth.py`, `tests/test_onion.py`, `tests/test_onion_scale.py`, `tests/test_views_render.py`, `tests/test_views_cli_mcp.py`.

### Task 1: View header and `as_of`

*Tier: standard.*

**Files:** Create `model/views.py`, `services/views.py`; Modify `index/index.py`; Test `tests/test_views_meta.py`.

**Interfaces:**
- Produces (`model/views.py`): `class ViewNotice(StrictModel): code: str; text: str`; `class ViewMeta(StrictModel): view: str; version: int; project: str; as_of: str | None; filter: dict[str, JsonValue]; truncated: bool = False; notices: list[ViewNotice] = []`.
- Produces (`index/index.py`): `Index.head(self) -> str | None`.
- Produces (`services/views.py`): `view_meta(project: Project, view: str, version: int, flt: Mapping[str, JsonValue], *, truncated: bool = False, notices: Sequence[ViewNotice] = ()) -> ViewMeta`; `to_json(model: StrictModel) -> str` (sorted keys, compact separators, trailing newline).

- [ ] **Step 1: Tests.**
```python
def test_head_is_last_event(project): project.record([ev1, ev2]); assert project.index.head() == ev2.id
def test_head_none_for_empty_log(empty): assert empty.index.head() is None
def test_head_survives_rebuild(project): h = project.index.head(); project.index.rebuild(); assert project.index.head() == h
def test_meta_states_filter_and_as_of(project): m = view_meta(project, "onion", 1, {"max_ring": 2}); assert m.as_of == project.index.head() and m.filter == {"max_ring": 2}
def test_to_json_deterministic(): ...
```
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** tests, mypy, ruff. **Step 5:** Commit `feat(views): view header and log head`.

### Task 2: Processing depth

*Tier: standard.*

**Files:** Create `services/depth.py`; Test `tests/test_depth.py`.

**Interfaces:**
- Consumes: final outcomes (`services/agreement.py::final_outcomes`, both stages), extraction unit state tables (plan D, both scopes via G2-A `Scope`), extraction audit tables.
- Produces: `ProcessingDepth = Literal["indexed", "screened", "extracted", "verified"]`; `DEPTH_RANK: Mapping[ProcessingDepth, int]`; `processing_depths(project: Project, work_ids: Sequence[str]) -> dict[str, ProcessingDepth]` (batched `IN` queries of at most 900 ids; unknown ids map to `indexed` when they are G1 external works, else raise `FactoryValidationError` field `work_ids`); `depth_counts(project: Project, work_ids_sql: str, params: Mapping[str, object]) -> dict[ProcessingDepth, int]` (aggregates over a SQL id set, used by the onion's TEMP table).

- [ ] **Step 1: Tests.**
```python
def test_indexed_only(project): assert processing_depths(project, [W_NEW]) == {W_NEW: "indexed"}
def test_screened_after_final_decision(project): ...
def test_extracted_with_current_unit_either_scope(project): ...        # evidence unit; contribution unit
def test_verified_needs_agreed_or_resolved_or_audited(project): ...    # single-pass row stays "extracted"
def test_stale_unit_is_not_extracted(project): ...                      # amendment makes unit stale → "screened"
def test_external_g1_work_is_indexed(project): ...
def test_counts_match_per_work(project): ...                            # depth_counts == Counter(processing_depths(...).values())
```
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** tests, mypy, ruff. **Step 5:** Commit `feat(views): processing depth per work`.

### Task 3: Onion builder

*Tier: standard (read-only; scale-sensitive).*

**Files:** Create `services/onion.py`; extend `model/views.py`; Test `tests/test_onion.py`, `tests/test_onion_scale.py`.

**Interfaces:**
- Consumes: `included_works`, `GraphFilter`, the G2-D overlay function for relation status (`services/lineage.py`; the implementer uses the function G2-D exposes for edge overlays on a set of edge ids), `processing_depths`, `depth_counts`, `view_meta`.
- Produces (`model/views.py`): `class OnionFilter(StrictModel): max_ring: int = 2; edge_types: tuple[Literal["cites", "builds-on", "improves-on"], ...] = ("cites", "builds-on", "improves-on"); include_inferred: bool = False; focus: tuple[str, ...] | None = None`; `class OnionNode(StrictModel): work_id: str; title: str; year: int | None; depth: ProcessingDepth; scope: Literal["corpus", "external"]; ideas: list[str]; regions: list[str] = []`; `class Ring(StrictModel): distance: int; total: int; by_depth: dict[str, int]; nodes: list[OnionNode]; truncated: bool`; `class OnionView(StrictModel): meta: ViewMeta; rings: list[Ring]; edges_considered: dict[str, int]`.
- Produces (`services/onion.py`): `ONION_MAX_RING = 3`; `VIEW_MAX_NODES = 500`; `onion_view(project: Project, flt: OnionFilter = OnionFilter()) -> OnionView`.

- [ ] **Step 1: Tests.** Fixture: a graph of 12 works (focus 3, ring 1 four, ring 2 five) with one inferred, one stale and one rejected relation.
```python
def test_rings_on_fixture(g): v = onion_view(g); assert [r.total for r in v.rings] == [3, 4, 5]
def test_undirected_distance(g): ...                     # a work citing the focus and a work cited by it are both ring 1
def test_inferred_edges_only_on_request(g): ...          # Review Focus 2
def test_stale_and_rejected_never_count(g): ...
def test_ring_clamped_with_notice(g): v = onion_view(g, OnionFilter(max_ring=9)); assert len(v.rings) == ONION_MAX_RING + 1 and v.meta.notices[0].code == "ring-clamped"
def test_counts_complete_when_truncated(g_wide, monkeypatch): ...    # VIEW_MAX_NODES patched to 2; totals unchanged; truncated True
def test_node_order_depth_then_id(g): ...
def test_explicit_focus_and_unknown_focus_error(g): ...
def test_no_seed_marker(g_with_seeds): assert "SEED" not in to_json(onion_view(g_with_seeds))
def test_view_writes_nothing(g): before = index_bytes(g); onion_view(g); assert index_bytes(g) == before   # Review Focus 3
def test_deterministic_across_rebuilds(g): ...
@pytest.mark.slow
def test_onion_scale(synthetic): ...                     # 1e5 works, 1e6 cites edges, ring 2 < 5 s; Review Focus 4
```
- [ ] **Step 2:** FAIL. **Step 3:** Implement: `CREATE TEMP TABLE onion_seen(work_id TEXT PRIMARY KEY, ring INT)`; for each ring, `INSERT OR IGNORE INTO onion_seen SELECT target, :k FROM graph_edges JOIN onion_seen ON source = work_id WHERE ring = :k-1 AND edge_type IN … UNION SELECT source …`; lineage edges filtered through the G2-D overlay for the edge ids in the frontier only; totals and depth counts by aggregates; node lists by `LIMIT VIEW_MAX_NODES` after ordering. **Step 4:** tests (slow included once locally), mypy, ruff. **Step 5:** Commit `feat(views): onion view over the lineage and citation graph`.

### Task 4: Renderers

*Tier: standard.*

**Files:** Create `views/render.py`; Test `tests/test_views_render.py`.

**Interfaces:**
- Produces: `onion_markdown(view: OnionView) -> str` (one table per ring: work, year, depth, ideas, regions; header with filter, `as_of`, totals and the notice list); `onion_dot(view: OnionView) -> str` (ruling 6).

- [ ] **Step 1: Tests.** Markdown names filter and `as_of`; a truncated ring prints "showing 500 of N"; DOT has `layout=twopi`, one style per depth, escaped titles, and a filter comment; both deterministic.
- [ ] **Step 2–4:** FAIL, implement, pass. **Step 5:** Commit `feat(views): onion renderers`.

### Task 5: MCP tool and CLI

*Tier: standard.*

**Files:** Modify `mcp/server.py`, `cli/main.py`, `cli/render.py` (only to import the renderers); Test `tests/test_views_cli_mcp.py`.

**Interfaces:**
- MCP (read; refused to pass sessions): `view_onion(project: str, max_ring: int = 2, edge_types: list[str] | None = None, include_inferred: bool = False, focus: list[str] | None = None) -> dict` (the `OnionView` JSON).
- CLI: `factory view onion [--max-ring N] [--edge-type T]… [--include-inferred] [--focus ID]… [--format md|json|dot] [--out PATH]`.

- [ ] **Step 1: Tests.** Tool list pinned; invalid `edge_types` → structured error; pass session refused; CLI JSON equals `to_json(onion_view(...))`.
- [ ] **Step 2–4.** **Step 5:** Commit `feat(views): view_onion tool and factory view onion`.

## Self-review notes
- Regions: `OnionNode.regions` is always empty until the regions plan adds a provider; Markdown prints "regions: not defined in this project" as a notice, so the empty column is explained.
- `Index.head()` is the only change to the index module; no table, no projection version change.

## Later (not v1)

None: every task of this plan is in v1.
