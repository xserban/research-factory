# Lineage Graph Projection, Queries, Export and Tools Implementation Plan (slice 3b, sub-plan G2-D)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: ready — rulings adopted 2026-11-04; depends on G1 (slice 3a) being built.** G1 ruling 14 is adopted as option (b) (parsed fields plus `entry_sha256`, no raw entry text in events); the graph uses G1 link states and work ids only, and exports carry no entry text and no quotes.

> **Reconciled with the code 2026-11-04 (overnight).** G1 Tasks 1–6 and G2-A Tasks 1–3 are built; G2-A Tasks 4–5, G2-B and G2-C are consumed as their (reconciled) plan texts state. Changes: Tasks 1–5 now implement ruling 10 — the whole-graph `load_graph` is replaced by indexed reads (`graph_node`, `index_neighbours`, streamed `iter_nodes` / `iter_edges`); the value types move to a pure module `lineage/graph.py` (pure helpers no longer import a service); `lineage/paths.py` takes a `Neighbours` lookup and traverses level by level; `graph_status` uses SQL aggregates plus G2-C `relation_counts`; exports stream (`iter_graph_export`) and the MCP cap is checked before rendering; `graph_edges` gets the composite indexes; a `slow` scale test is added (Task 3). Consumed G2-C names gain `relation_views` and the `idea_members(work_id)` index (added to G2-C). `PROJECTION_VERSION` 23 → 24 stated. G3-A/B/C now consume `graph_node` instead of `load_graph(...).node`.

> **Dependencies.** G2-A, G2-B, G2-C merged (Interfaces consumed exactly); G1 merged (events `reference.extracted`, `reference.resolved`, `reference.resolution_decided`; tables `reference_extractions`, `reference_links`).

**Goal:** Project papers, ideas and `cites` / `builds-on` / `improves-on` edges into rebuildable index tables, answer bounded deterministic lineage queries over them with an explicit status filter, and export the result as JSON or Graphviz DOT.

**Architecture:** `index/graph.py` holds handlers that maintain `graph_nodes` and `graph_edges` from G1 and lineage events (chained with the existing handlers of the same event types). Pure value types (`GraphFilter`, `GraphNode`, `GraphEdge`, `Graph`, `Neighbours`) live in `lineage/graph.py`. `services/lineage.py` reads the projection by indexed SQL — one node, or one node's edges of given types in one direction, or an ordered page — and overlays only what it read (corpus membership, relation staleness and decisions from G2-C, idea merges), applying a `GraphFilter`; no call loads the whole graph (ruling 10). Pure helpers `lineage/paths.py` (level-by-level traversals over a `Neighbours` lookup) and `lineage/export.py` (serialisation, streamable) run unchanged on an in-memory fixture graph and on the index. `mcp/` and `cli/` parse and format.

**Tech Stack:** as plan D; stdlib `collections.deque`, `json`; no layout engine, no new dependency (spec ruling 4).

**Spec:** `docs/specs/slice-3b-lineage.md` User flow 6; rulings 4, 10, 14; Design "Graph projection", "Queries", "Export"; "Ideas" (derived idea edges); Index tables `graph_nodes`, `graph_edges`; MCP `graph_status`, `graph_query`, `graph_export`; CLI `factory graph`; acceptance 10 (`cites` part), 13, 14, 15. Proposed R-xx(f), R-xx(g).

## Rulings made in this plan

Rulings marked **[adopted 2026-11-04]** were Adopted 2026-11-04 (researcher's standing approval of the recommendation); G2-E records them in the *Proposed* decision when built. G3 (slice 3c) stores its layer in its own tables and never writes `graph_nodes` / `graph_edges`; it adds an optional `layer` parameter to `graph_query`, `graph_export` and `graph_status` (G3-C Task 1, which updates this plan's pinned tool-signature test).

1. **What is projected, what is overlaid. [adopted 2026-11-04]** The projector writes event-derived facts only: `graph_edges` rows for every `cites` edge (one per resolved or confirmed G1 link, id `cit:<rex_id>:<ordinal>`) and every relation (id = `relation_id`), with `live` (0/1: the G1 extraction is live; the relation is not superseded), `base_status` (`cites`: `stated` for `identifier`/`title-exact`, `confirmed` for `confirmed`; relations: their proposal status) and `decision`; `graph_nodes` rows for every work that is a source or target of an edge or an idea member, and every idea. Corpus membership, relation staleness and idea merges are overlays computed by `services/lineage.py` on read, because they depend on dedup state and the amendment ledger, which plan D also evaluates in services. Rebuilding gives identical rows (acceptance 15).
2. **Cites from G1 (spec ruling 11).** A link enters as an edge when `reference.resolved` states `resolved`, or a human or second-agent `confirm` decision resolves it; a `reject` decision sets `decision = reject` (hidden); `propose-*` decisions change nothing; a new `reference.extracted` for the same work sets `live = 0` on the earlier extraction's edges. Unconfirmed, ambiguous and unresolved links are never edges.
3. **Effective status.** Lineage edges take `RelationView.effective` (G2-C). `cites` edges are their base status, `rejected` when rejected, and are never `inferred` or `stale` (a superseded extraction removes them: `live = 0`).
4. **Filter (spec ruling 14).** `GraphFilter(include_inferred=False, include_stale=False, edge_types=all three, include_ideas=True)`. Default view: `stated` and `confirmed` edges, confirmed and unmerged ideas. `include_inferred` adds `inferred` edges and `proposed` ideas; `include_stale` adds `stale` edges; `rejected` never appears. Every result and export names its filter.
5. **Paths and traversal (spec ruling 10).** Lineage traversal follows `builds-on` and `improves-on` edges (either type, `improves-on` implying `builds-on` in queries) from the later work to the earlier. `ancestors(n)` follows edges out of `n`; `descendants(n)` follows them backwards. `path(a, b)` is the shortest by edge count from `a` to `b` along edge direction; ties are broken by the lexicographically smallest node-id sequence. Bounds: `MAX_DEPTH = 8` (a larger requested depth is clamped and reported), `MAX_RESULTS = 500` nodes (`truncated = True` beyond it).
6. **`no_stated_base` categories. [adopted 2026-11-04]** Population = G2-A contribution population. A work with a live `builds-on` edge in the filter is excluded; the others fall into exactly one category, in this order: `unextracted` (no `current` contribution unit), `not-stated` (a final `not-stated` base-idea item), `target-outside-corpus` (a final base-idea item whose cited entry links to a work outside the corpus and no lineage edge to a corpus work), `no-relation` (all others: base-idea items without a qualifying relation).
7. **Idea edges (spec "Ideas").** Idea X *builds-on* idea Y when a member of X has a `stated` or `confirmed` `builds-on` edge to a member of Y (X ≠ Y, after merges). Derived on read, labelled `derived`, never stored; included in exports when `include_ideas`.
8. **Exports (spec ruling 4, acceptance 14).** JSON: one object `{"filter": …, "nodes": […], "edges": […]}`, keys sorted, nodes by id, edges by `(source, edge_type, target, edge_id)`, compact separators, trailing newline. Node: `id`, `type`, `scope` (`corpus|external`, papers), `title` (bibliographic metadata from the work record, papers only), `name` (ideas), `members` (ideas). Edge: `id`, `type`, `source`, `target`, `status`, `basis` (relation `basis_item`, or `rex_id:ordinal` for `cites`), `flags`, `derived`. No quotes, notes or entry text. DOT: `digraph lineage`, a comment line with the filter, papers as ellipses, ideas as boxes; `stated` solid, `confirmed` solid with label `confirmed`, `inferred` dashed with label `inferred`, `stale` dotted with label `stale`, `cites` gray, `derived` bold with label `derived`. Same ordering; byte-identical across rebuilds.
9. **MCP size cap.** `graph_export` over MCP refuses an export with more than `MCP_EXPORT_MAX_EDGES = 2000` edges (field `query`, "too large; use a query or the CLI"); the CLI has no cap.
10. **Scale. [adopted 2026-11-04, researcher's standing approval]** The graph will grow past one project (IDEA-37 shared corpus), so no query loads the whole graph. `graph_edges` has indexes on `(source, edge_type)`, `(target, edge_type)` and `(edge_type)`; `ancestors`, `descendants` and `path` expand the frontier level by level with indexed SQL reads (bounded by `MAX_DEPTH` and the result cap), and overlays (G2-C relation status, idea merges, corpus membership) are computed only for the edges a query touches. `graph_status` counts with SQL aggregates; `graph_export` streams in the deterministic order of ruling 8 (CLI) and keeps the MCP cap of ruling 9. The pure helpers in `lineage/paths.py` take a neighbour-lookup function rather than a loaded `Graph`, so the same code runs on a small in-memory fixture and on the index. A scale test (`test_lineage_scale.py`, marked `slow`) builds a synthetic projection of 50,000 papers and 500,000 `cites` plus 20,000 lineage edges directly in the index and asserts that `ancestors` at `MAX_DEPTH`, `path` and `graph_status` each finish within 2 s and that their results equal the in-memory reference on a sampled subgraph. The projection stays rebuildable from events, so a different store (for example an embedded graph or column database) can replace it later without touching events.

## Global Constraints

- All G2-A–C constraints hold. The platform never calls a model. Only the projector writes `graph_nodes` / `graph_edges`; no service writes them.
- Queries are read-only, deterministic and bounded; results carry node and edge ids and statuses, never prose.
- Every statistic names the status filter it used; counts are derived, never typed.
- No document text in any export, result or message; notes never appear in exports.
- `graph_*` tools are refused to pass sessions of any scope.
- No service, query or status call reads all of `graph_nodes` or `graph_edges` into memory; whole-view exports stream in pages (ruling 10).
- TDD; `mypy --strict`, ruff; coverage >= 90% for `services/` and `model/`; `-m "not network and not slow"` during tasks; the scale test is marked `slow`.

## Review Focus

1. A G1 link confirmed, then rejected by a human: the `cites` edge appears, then disappears from every view; a second extraction of the citing work removes the first extraction's edges (Task 1, `test_cites_follow_link_decisions_and_liveness`).
2. A cycle in the lineage (A builds-on B, B builds-on A, both stated): `ancestors`, `descendants` and `path` terminate and report each node once (Task 3, `test_cycles_terminate`).
3. `path` between nodes connected only through an `inferred` edge: no path by default, a path with `include_inferred`, and the edge is labelled `inferred` in the result (Task 3, `test_path_respects_filter`).
4. A query naming a node that is not in the graph, or an idea that is merged away: a structured error naming the field, nothing else (Task 2, `test_unknown_or_merged_node`).
5. A relation targeting an idea that is later merged: the edge points to the surviving idea in views and exports, and back to the original after unmerge, byte-identically (Task 4, `test_export_follows_merge_and_unmerge`).

## File Structure

- Create `index/graph.py`, `lineage/graph.py`, `lineage/paths.py`, `lineage/export.py`, `services/lineage.py`.
- Modify `index/projection.py` (`chain`), `index/default.py`, `mcp/server.py`, `cli/main.py`, `cli/render.py`.
- Tests: `test_graph_index.py`, `test_lineage_service.py`, `test_lineage_paths.py`, `test_lineage_scale.py` (`slow`), `test_lineage_export.py`, `test_mcp_graph.py`, `test_cli_graph.py`; fixture `tests/fixtures/lineage/graph_small.json` (a constructed 9-paper, 2-idea graph with every status, used by Tasks 2–4 and G2-E, loadable both as an in-memory `Graph` and, through a helper that writes the matching events, as a project).

---

### Task 1: Graph projection

*Tier: critical (projection, rebuild determinism; spec acceptance 19).*

**Files:** Create `index/graph.py`; Modify `index/projection.py`, `index/default.py`; Test `tests/test_graph_index.py`; update the `PROJECTION_VERSION` pin.

**Interfaces:**
- Consumes: G1 event payloads `ReferenceExtracted`, `ReferenceResolved`, `ReferenceResolutionDecided`; G2-C payloads `RelationProposed`, `RelationDecided`, `IdeaProposed`; `Handler`.
- Produces (`index/projection.py`): `chain(*handlers: Handler) -> Handler` (calls each in order on the same connection and event).
- Produces (`index/graph.py`): tables `graph_nodes(node_id pk, node_type paper|idea, event_id)` (index `ix_graph_nodes_type`) and `graph_edges(edge_id pk, edge_type, source, target, base_status, basis, reference_extraction_id, ordinal, live, decision, flags, event_id)` with indexes `ix_graph_edges_source_type (source, edge_type)`, `ix_graph_edges_target_type (target, edge_type)`, `ix_graph_edges_type (edge_type)` (ruling 10); `graph_handlers(t) -> dict[str, Handler]` for `reference.extracted`, `reference.resolved`, `reference.resolution_decided`, `relation.proposed`, `relation.decided`, `idea.proposed` (ruling 1, 2). `default_projection` chains them with the G1 and G2-C handlers of the same types (`index/default.py` merges handler dicts today; same-type keys must be combined with `chain`, not overwritten). `PROJECTION_VERSION` 23 → 24 (after G2-C; if another plan bumped first, add one to the value found).

- [ ] **Step 1: Tests.** `test_resolved_link_becomes_cites_edge` (`cit:rex_…:3`, `base_status = "stated"` for identifier); `test_unconfirmed_link_is_not_an_edge`; `test_cites_follow_link_decisions_and_liveness` (Review Focus 1); `test_relation_becomes_edge_and_supersession_clears_live`; `test_decision_folded`; `test_idea_and_members_are_nodes`; `test_chain_runs_both_handlers` (G1 and G2-C tables still filled for the same event); `test_rebuild_identical_graph_tables` (acceptance 15: rows of `graph_nodes` and `graph_edges` equal and state hash equal after `index.rebuild()`); `test_traversal_reads_use_indexes` (`EXPLAIN QUERY PLAN` of `WHERE source = ? AND edge_type = ?` and of the `target` form uses the composite indexes); `test_projection_version_bumped`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Index suites, G1 and G2-C index tests unedited except the pin; mypy; ruff. **Step 5:** Commit `feat(graph): projected nodes and edges`.

### Task 2: Graph loading, overlays, filter and status

*Tier: standard (Sonnet implement, Haiku review).*

**Files:** Create `lineage/graph.py`, `services/lineage.py`; Test `tests/test_lineage_service.py`.

**Interfaces:**
- Consumes: Task 1 tables; G2-C `relation_views`, `relation_counts`, `relation_view`, `idea_view`, `resolve_idea`, `EdgeStatus`, `EdgeType`, `DEFAULT_STATUSES`, tables `ideas` (`merged_into`), `idea_members` (index on `work_id`); G2-A `scope_population`, `unit_states(..., scope=)`; G2-B `final_items`, `contribution_item`, `reference_view`, `contribution_status`; index tables `works` and `merges` (corpus membership by the rule of `canonical_works`, evaluated for the ids read).
- Produces (`lineage/graph.py`, pure): `@dataclass(frozen=True) GraphFilter(include_inferred: bool = False, include_stale: bool = False, edge_types: tuple[EdgeType, ...] = (EdgeType.CITES, EdgeType.BUILDS_ON, EdgeType.IMPROVES_ON), include_ideas: bool = True)` with `statuses() -> frozenset[EdgeStatus]` and `as_dict() -> dict[str, JsonValue]`; `@dataclass(frozen=True) GraphNode(node_id: str, node_type: Literal["paper", "idea"], scope: Literal["corpus", "external"] | None, title: str | None, name: str | None, members: tuple[str, ...])`; `@dataclass(frozen=True) GraphEdge(edge_id: str, edge_type: EdgeType, source: str, target: str, status: EdgeStatus | Literal["derived"], basis: str | None, flags: tuple[str, ...], derived: bool)`; `@dataclass(frozen=True) Graph(nodes: tuple[GraphNode, ...], edges: tuple[GraphEdge, ...], filter: GraphFilter)` with `node(id) -> GraphNode | None` (a materialised subgraph: a query result, an export part or a test fixture, never the whole projection); `Direction = Literal["out", "in"]`; `Neighbours = Callable[[str, Direction, frozenset[EdgeType]], Sequence[GraphEdge]]` (the filtered edges of one node in one direction, sorted by `(other end, edge_type, edge_id)`); `graph_neighbours(graph: Graph) -> Neighbours` (in-memory adapter); `load_fixture(path) -> Graph`.
- Produces (`services/lineage.py`; re-exports the types above; rulings 1, 3, 4, 7, 10): `graph_node(project, node_id: str, flt: GraphFilter = GraphFilter()) -> GraphNode | None` (one indexed read plus overlays; `None` when absent, filtered out, or an idea merged away); `require_node(project, node_id: str, field: str, flt: GraphFilter = GraphFilter()) -> GraphNode` (raises `FactoryValidationError` on `field`, reasons `node-unknown`, `idea-merged` with the surviving id); `index_neighbours(project, flt: GraphFilter = GraphFilter()) -> Neighbours` (each call is one indexed SQL read on `(source, edge_type)` or `(target, edge_type)`; an idea node also reads the ideas merged into it (`ideas.merged_into`), and edges to merged ideas are retargeted to the survivor; lineage edges take their status from `relation_views` over the relation ids read; `cites` status comes from `base_status`, `decision` and `live` in SQL; derived idea edges (ruling 7) come from member edges through `idea_members` by `work_id`; nodes of dropped ideas and edges to them are removed); `iter_nodes(project, flt) -> Iterator[GraphNode]` (by id) and `iter_edges(project, flt) -> Iterator[GraphEdge]` (by `(source, edge_type, target, edge_id)`), both streaming ordered pages of `GRAPH_PAGE = 1000` rows with overlays per page; `class GraphStatus(StrictModel)`: `filter: dict[str, JsonValue]`, `nodes: dict[str, int]` (`paper-corpus`, `paper-external`, `idea`), `edges: dict[str, dict[str, int]]` (edge type -> status -> count, every status, unfiltered), `unextracted: list[str]`, `no_references: list[str]`, `not_stated: int`, `uncited_base: int`; `graph_status(project) -> GraphStatus` (node counts and `cites` counts by SQL aggregates (`GROUP BY` node type and corpus membership; `GROUP BY base_status, decision, live`); lineage counts from G2-C `relation_counts`; no full-table read).

- [ ] **Step 1: Tests.** `test_index_neighbours_equal_in_memory_on_fixture` (the fixture written as events: for every node, direction and edge-type set, `index_neighbours` equals `graph_neighbours(load_fixture(...))`); `test_corpus_scope_matches_canonical_works`; `test_iter_edges_streams_in_order` (page boundary crossed); `test_default_view_has_stated_and_confirmed_only`; `test_include_flags_widen_and_label`; `test_rejected_never_shown`; `test_unconfirmed_idea_not_drawn` (acceptance 12); `test_corpus_and_external_scope`; `test_derived_idea_edges_labelled_and_not_stored`; `test_unknown_or_merged_node` (Review Focus 4); `test_status_counts_derived_and_name_filter`; `test_every_lineage_edge_has_live_item_and_every_cites_edge_a_link` (acceptance 10: for each edge of `iter_edges(project, GraphFilter(include_inferred=True))`, `contribution_item(basis).live` or a `reference_links` row with state `resolved`).
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests; mypy; ruff. **Step 5:** Commit `feat(graph): indexed graph reads, overlays, filter and status`.

### Task 3: Queries (pure) and their service wrappers

*Tier: standard (Sonnet implement, Haiku review).*

**Files:** Create `lineage/paths.py`; Modify `services/lineage.py`; Test `tests/test_lineage_paths.py`, `tests/test_lineage_scale.py` (`slow`).

**Interfaces:**
- Consumes: Task 2 `Neighbours`, `GraphEdge`, `GraphFilter`, `graph_neighbours`, `index_neighbours`, `require_node`, `graph_status`.
- Produces (`lineage/paths.py`, pure; ruling 5, 10): `MAX_DEPTH = 8`, `MAX_RESULTS = 500`; `LINEAGE_TYPES = frozenset({EdgeType.BUILDS_ON, EdgeType.IMPROVES_ON})`; `@dataclass(frozen=True) QueryResult(query: str, nodes: tuple[str, ...], edges: tuple[str, ...], depth: int | None, truncated: bool)`; `ancestors(nb: Neighbours, node: str, depth: int) -> QueryResult` and `descendants(nb: Neighbours, node: str, depth: int) -> QueryResult` (frontier expanded level by level, one `nb(n, "out" | "in", LINEAGE_TYPES)` call per frontier node, a visited set, stop at `depth` or when the result passes `MAX_RESULTS` (`truncated = True`)); `path(nb: Neighbours, a: str, b: str) -> QueryResult` (level-by-level BFS from `a` along edge direction, bounded by `MAX_DEPTH` levels and `MAX_RESULTS` visited nodes; frontier and neighbours visited in sorted order so the lexicographically smallest node-id sequence wins ties; empty `nodes` when none); `improvements_on(nb: Neighbours, node: str) -> QueryResult` (sources of `improves-on` edges into `node`, their edges); `cited_by_at_least(edges: Iterable[GraphEdge], k: int) -> QueryResult` (pure reference: targets with ≥ k distinct sources over `cites` edges, `k >= 1`, truncated at `MAX_RESULTS`). Nodes sorted by id except `path`, which is in path order.
- Produces (`services/lineage.py`): `class NoStatedBase(StrictModel)`: `filter`, `unextracted`, `not_stated`, `target_outside_corpus`, `no_relation` (each `list[str]`, sorted); `no_stated_base(project, flt: GraphFilter = GraphFilter()) -> NoStatedBase` (ruling 6); `QueryKind = Literal["ancestors", "descendants", "path", "no_stated_base", "improvements_on", "cited_by_at_least"]`; `class GraphQueryResult(StrictModel)`: `query: QueryKind`, `filter: dict[str, JsonValue]`, `nodes: list[dict[str, JsonValue]]` (id, type, scope), `edges: list[dict[str, JsonValue]]` (id, type, source, target, status), `truncated: bool`, `depth: int | None`, `categories: dict[str, list[str]] | None` (for `no_stated_base`); `graph_query(project, query: QueryKind, *, node: str | None = None, target: str | None = None, depth: int = 3, k: int = 2, flt: GraphFilter = GraphFilter()) -> GraphQueryResult` (validates arguments per query: `node`, `target` through `require_node`, `depth` 1..`MAX_DEPTH` clamped with the clamp reported, `k >= 1`; traversals run the pure helpers on `index_neighbours(project, flt)`; `cited_by_at_least` is one SQL aggregate over live, not rejected `cites` rows (`GROUP BY target HAVING COUNT(DISTINCT source) >= :k ORDER BY target LIMIT MAX_RESULTS + 1`); `no_stated_base` reads one `builds-on` neighbour list per population work).

- [ ] **Step 1: Tests** (fixture `graph_small.json`; acceptance 13).
```python
def test_ancestors_and_descendants_expected(nb):            # nb = graph_neighbours(load_fixture(GRAPH_SMALL))
    assert ancestors(nb, "rf:p9", 8).nodes == ("rf:p1", "rf:p3", "rf:p5", "rf:p7")
    assert descendants(nb, "rf:p1", 2).nodes == ("rf:p3", "rf:p4", "rf:p5")
def test_path_shortest_with_tiebreak(nb): assert path(nb, "rf:p9", "rf:p1").nodes == ("rf:p9", "rf:p5", "rf:p3", "rf:p1")
def test_path_respects_filter(nb, nb_inferred): ...        # Review Focus 3
def test_cycles_terminate(nb_cycle): ...                   # Review Focus 2
def test_bounds_clamp_and_truncate(nb_large): assert ancestors(nb_large, "rf:x", 50).depth == MAX_DEPTH and ancestors(...).truncated
def test_traversal_calls_lookup_once_per_frontier_node(nb_spy): ...   # level by level, no whole-graph read
def test_improvements_on_and_cited_by(nb, g): ...
def test_service_queries_equal_pure_on_fixture(project): ...           # graph_query on the projected fixture == pure helpers on load_fixture
def test_no_stated_base_categories_disjoint_and_complete(project):
    r = no_stated_base(project); cats = [r.unextracted, r.not_stated, r.target_outside_corpus, r.no_relation]
    assert sum(map(len, cats)) == len(set().union(*cats)) and set().union(*cats) == EXPECTED_NO_BASE
def test_graph_query_argument_errors(project): ...         # missing node for ancestors; k=0
# tests/test_lineage_scale.py, @pytest.mark.slow (ruling 10)
def test_scale_bounded(tmp_path):
    # 50,000 papers, 500,000 cites and 20,000 lineage edges (with matching G2-C `relations` rows) inserted by SQL into the
    # projected tables of an empty, synced project (no rebuild triggered); ancestors at MAX_DEPTH, path and graph_status
    # each finish within 2 s, and on a sampled subgraph equal the pure helpers run on that subgraph loaded in memory.
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement (level-by-level BFS with a visited set; deterministic neighbour order by node id). **Step 4:** Tests; mypy; ruff. **Step 5:** Commit `feat(graph): bounded lineage queries`.

### Task 4: Export (pure) and the export service

*Tier: standard (Sonnet implement, Haiku review).*

**Files:** Create `lineage/export.py`; Modify `services/lineage.py`; Test `tests/test_lineage_export.py`.

**Interfaces:**
- Consumes: Task 2 `Graph`, `iter_nodes`, `iter_edges`, `graph_node`; Task 3 `GraphQueryResult`, `graph_query`.
- Produces (`lineage/export.py`, pure): `to_json(graph: Graph) -> str` and `to_dot(graph: Graph) -> str` (ruling 8); `iter_json(flt: GraphFilter, nodes: Iterable[GraphNode], edges: Iterable[GraphEdge]) -> Iterator[str]` and `iter_dot(flt, nodes, edges) -> Iterator[str]` (chunks whose concatenation equals `to_json` / `to_dot` of the same graph; each iterable consumed once, in ruling 8's order); `subgraph(graph: Graph, nodes: Iterable[str], edges: Iterable[str]) -> Graph`.
- Produces (`services/lineage.py`): `ExportFormat = Literal["json", "dot"]`; `MCP_EXPORT_MAX_EDGES = 2000`; `export_edge_count(project, flt: GraphFilter) -> int` (exact: SQL count of the `cites` rows in the filter, plus G2-C `relation_counts` for the statuses in the filter, plus derived idea edges); `iter_graph_export(project, fmt: ExportFormat, *, query: QueryKind | None = None, node: str | None = None, target: str | None = None, depth: int = 3, k: int = 2, flt: GraphFilter = GraphFilter()) -> Iterator[str]` (the whole filtered view streamed from `iter_nodes` / `iter_edges` when `query` is `None`, else the query's subgraph, which is bounded); `graph_export(project, fmt, *, query=None, node=None, target=None, depth=3, k=2, flt=GraphFilter(), max_edges: int | None = None) -> str` (`"".join(iter_graph_export(...))`; with `max_edges`, refused on field `query` ("too large; use a query or the CLI") when `export_edge_count` exceeds it, before anything is rendered; ruling 9).

- [ ] **Step 1: Tests** (acceptance 14).
```python
def test_json_shape_and_order(g):
    doc = json.loads(to_json(g)); assert set(doc) == {"filter", "nodes", "edges"}
    assert [e["id"] for e in doc["edges"]] == sorted_by_source_type_target(doc["edges"])
    assert all({"status", "basis"} <= set(e) for e in doc["edges"])
def test_dot_marks_inferred_dashed_and_labelled(g_inferred): assert 'style=dashed, label="inferred"' in to_dot(g_inferred)
def test_no_quotes_notes_or_entry_text(project): ...       # every stored quote, note and entry text absent from both formats
def test_export_byte_identical_across_rebuilds(project):
    a = graph_export(project, "json"); project.index.rebuild(); assert graph_export(project, "json") == a
def test_export_follows_merge_and_unmerge(project): ...    # Review Focus 5
def test_query_export_is_the_query_subgraph(project): ...
def test_streamed_export_equals_whole_on_fixture(g): assert "".join(iter_json(g.filter, g.nodes, g.edges)) == to_json(g)   # also DOT
def test_export_cap_checked_before_rendering(project): ...  # max_edges below the count -> refusal; iter_edges never called
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement (`json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"`; DOT ids and labels quoted with `"` and `\` escaped). **Step 4:** Tests; mypy; ruff. **Step 5:** Commit `feat(graph): JSON and DOT export`.

### Task 5: `graph_*` MCP tools and `factory graph` CLI

*Tier: Haiku implement and review (surfaces).*

**Files:** Modify `mcp/server.py`, `cli/main.py`, `cli/render.py`; Test `tests/test_mcp_graph.py`, `tests/test_cli_graph.py`.

**Interfaces:**
- MCP (read; refused to pass sessions of any scope): `graph_status(project)` -> `GraphStatus`; `graph_query(project, query, node: str | None = None, target: str | None = None, depth: int = 3, k: int = 2, include_inferred: bool = False, include_stale: bool = False)` -> `GraphQueryResult`; `graph_export(project, format: str = "json", query: str | None = None, node: str | None = None, target: str | None = None, depth: int = 3, k: int = 2, include_inferred: bool = False, include_stale: bool = False)` -> text (calls `graph_export(..., max_edges=MCP_EXPORT_MAX_EDGES)`; ruling 9).
- CLI: `factory graph build` (syncs the index and prints `graph_status`), `factory graph status`, `factory graph query KIND [--node N] [--target T] [--depth D] [--k K] [--include-inferred] [--include-stale]`, `factory graph export --format json|dot [--query KIND …] [--out FILE]` (writes the chunks of `iter_graph_export` to stdout unless `--out` is given; no cap).

- [ ] **Step 1: Tests.** MCP: tool list pinned with the three names; each refused to a pass session; `graph_query` with an unknown query returns a structured error; an export above the cap is refused. CLI: `graph query path --node A --target B` prints the path with statuses; `graph export --format dot` output equals `graph_export(project, "dot")`; `graph build` prints counts naming the filter.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests; mypy; ruff. **Step 5:** Commit `feat(graph): graph tools and CLI`.

## Self-review notes

- **Spec coverage.** Projection and rebuild (Task 1; acceptance 15, R-xx(g)), edge basis (Task 2 test; acceptance 10, R-xx(f)), filter and labels (Task 2; ruling 14), queries (Task 3; acceptance 13), export (Task 4; acceptance 14), tools and CLI (Task 5). Ruling 4: no layout engine. `check` and `trace` are G2-E.
- **Types used later.** `GraphFilter`, `Graph`, `GraphNode`, `GraphEdge`, `Neighbours` (`lineage/graph.py`, re-exported by `services/lineage.py`), `graph_node`, `require_node`, `index_neighbours`, `iter_nodes`, `iter_edges`, `iter_graph_export`, `graph_status`, `GraphStatus`, `no_stated_base`, `NoStatedBase`, `graph_query`, `GraphQueryResult`, `graph_export`, `MAX_DEPTH`, `MAX_RESULTS`, tables `graph_nodes`, `graph_edges`, edge ids `cit:<rex_id>:<ordinal>` and `rel_…`.
- **Tiers.** Task 1 critical (Sonnet review); Tasks 2–4 standard; Task 5 Haiku.
