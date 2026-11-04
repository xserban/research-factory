# Lineage Graph Projection, Queries, Export and Tools Implementation Plan (slice 3b, sub-plan G2-D)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: provisional — depends on the unconfirmed [confirm] rulings of slice-3b-lineage.md and on G1 ruling 14 (reference text in events; recommended: parsed fields plus a hash).** The graph uses G1 link states and work ids only; exports carry no entry text and no quotes.

> **Dependencies.** G2-A, G2-B, G2-C merged (Interfaces consumed exactly); G1 merged (events `reference.extracted`, `reference.resolved`, `reference.resolution_decided`; tables `reference_extractions`, `reference_links`).

**Goal:** Project papers, ideas and `cites` / `builds-on` / `improves-on` edges into rebuildable index tables, answer bounded deterministic lineage queries over them with an explicit status filter, and export the result as JSON or Graphviz DOT.

**Architecture:** `index/graph.py` holds handlers that maintain `graph_nodes` and `graph_edges` from G1 and lineage events (chained with the existing handlers of the same event types). `services/lineage.py` loads the projected graph, overlays what depends on services (corpus membership, relation staleness and decisions from G2-C, idea merges) and applies a `GraphFilter`; pure helpers `lineage/paths.py` (queries) and `lineage/export.py` (serialisation) work on the loaded graph. `mcp/` and `cli/` parse and format.

**Tech Stack:** as plan D; stdlib `collections.deque`, `json`; no layout engine, no new dependency (spec ruling 4).

**Spec:** `docs/specs/slice-3b-lineage.md` User flow 6; rulings 4, 10, 14; Design "Graph projection", "Queries", "Export"; "Ideas" (derived idea edges); Index tables `graph_nodes`, `graph_edges`; MCP `graph_status`, `graph_query`, `graph_export`; CLI `factory graph`; acceptance 10 (`cites` part), 13, 14, 15. Proposed R-xx(f), R-xx(g).

## Rulings made in this plan

1. **What is projected, what is overlaid. [confirm]** The projector writes event-derived facts only: `graph_edges` rows for every `cites` edge (one per resolved or confirmed G1 link, id `cit:<rex_id>:<ordinal>`) and every relation (id = `relation_id`), with `live` (0/1: the G1 extraction is live; the relation is not superseded), `base_status` (`cites`: `stated` for `identifier`/`title-exact`, `confirmed` for `confirmed`; relations: their proposal status) and `decision`; `graph_nodes` rows for every work that is a source or target of an edge or an idea member, and every idea. Corpus membership, relation staleness and idea merges are overlays computed by `services/lineage.py` on read, because they depend on dedup state and the amendment ledger, which plan D also evaluates in services. Rebuilding gives identical rows (acceptance 15).
2. **Cites from G1 (spec ruling 11).** A link enters as an edge when `reference.resolved` states `resolved`, or a human or second-agent `confirm` decision resolves it; a `reject` decision sets `decision = reject` (hidden); `propose-*` decisions change nothing; a new `reference.extracted` for the same work sets `live = 0` on the earlier extraction's edges. Unconfirmed, ambiguous and unresolved links are never edges.
3. **Effective status.** Lineage edges take `RelationView.effective` (G2-C). `cites` edges are their base status, `rejected` when rejected, and are never `inferred` or `stale` (a superseded extraction removes them: `live = 0`).
4. **Filter (spec ruling 14).** `GraphFilter(include_inferred=False, include_stale=False, edge_types=all three, include_ideas=True)`. Default view: `stated` and `confirmed` edges, confirmed and unmerged ideas. `include_inferred` adds `inferred` edges and `proposed` ideas; `include_stale` adds `stale` edges; `rejected` never appears. Every result and export names its filter.
5. **Paths and traversal (spec ruling 10).** Lineage traversal follows `builds-on` and `improves-on` edges (either type, `improves-on` implying `builds-on` in queries) from the later work to the earlier. `ancestors(n)` follows edges out of `n`; `descendants(n)` follows them backwards. `path(a, b)` is the shortest by edge count from `a` to `b` along edge direction; ties are broken by the lexicographically smallest node-id sequence. Bounds: `MAX_DEPTH = 8` (a larger requested depth is clamped and reported), `MAX_RESULTS = 500` nodes (`truncated = True` beyond it).
6. **`no_stated_base` categories. [confirm]** Population = G2-A contribution population. A work with a live `builds-on` edge in the filter is excluded; the others fall into exactly one category, in this order: `unextracted` (no `current` contribution unit), `not-stated` (a final `not-stated` base-idea item), `target-outside-corpus` (a final base-idea item whose cited entry links to a work outside the corpus and no lineage edge to a corpus work), `no-relation` (all others: base-idea items without a qualifying relation).
7. **Idea edges (spec "Ideas").** Idea X *builds-on* idea Y when a member of X has a `stated` or `confirmed` `builds-on` edge to a member of Y (X ≠ Y, after merges). Derived on read, labelled `derived`, never stored; included in exports when `include_ideas`.
8. **Exports (spec ruling 4, acceptance 14).** JSON: one object `{"filter": …, "nodes": […], "edges": […]}`, keys sorted, nodes by id, edges by `(source, edge_type, target, edge_id)`, compact separators, trailing newline. Node: `id`, `type`, `scope` (`corpus|external`, papers), `title` (bibliographic metadata from the work record, papers only), `name` (ideas), `members` (ideas). Edge: `id`, `type`, `source`, `target`, `status`, `basis` (relation `basis_item`, or `rex_id:ordinal` for `cites`), `flags`, `derived`. No quotes, notes or entry text. DOT: `digraph lineage`, a comment line with the filter, papers as ellipses, ideas as boxes; `stated` solid, `confirmed` solid with label `confirmed`, `inferred` dashed with label `inferred`, `stale` dotted with label `stale`, `cites` gray, `derived` bold with label `derived`. Same ordering; byte-identical across rebuilds.
9. **MCP size cap.** `graph_export` over MCP refuses an export with more than `MCP_EXPORT_MAX_EDGES = 2000` edges (field `query`, "too large; use a query or the CLI"); the CLI has no cap.

## Global Constraints

- All G2-A–C constraints hold. The platform never calls a model. Only the projector writes `graph_nodes` / `graph_edges`; no service writes them.
- Queries are read-only, deterministic and bounded; results carry node and edge ids and statuses, never prose.
- Every statistic names the status filter it used; counts are derived, never typed.
- No document text in any export, result or message; notes never appear in exports.
- `graph_*` tools are refused to pass sessions of any scope.
- TDD; `mypy --strict`, ruff; coverage >= 90% for `services/` and `model/`.

## Review Focus

1. A G1 link confirmed, then rejected by a human: the `cites` edge appears, then disappears from every view; a second extraction of the citing work removes the first extraction's edges (Task 1, `test_cites_follow_link_decisions_and_liveness`).
2. A cycle in the lineage (A builds-on B, B builds-on A, both stated): `ancestors`, `descendants` and `path` terminate and report each node once (Task 3, `test_cycles_terminate`).
3. `path` between nodes connected only through an `inferred` edge: no path by default, a path with `include_inferred`, and the edge is labelled `inferred` in the result (Task 3, `test_path_respects_filter`).
4. A query naming a node that is not in the graph, or an idea that is merged away: a structured error naming the field, nothing else (Task 2, `test_unknown_or_merged_node`).
5. A relation targeting an idea that is later merged: the edge points to the surviving idea in views and exports, and back to the original after unmerge, byte-identically (Task 4, `test_export_follows_merge_and_unmerge`).

## File Structure

- Create `index/graph.py`, `lineage/paths.py`, `lineage/export.py`, `services/lineage.py`.
- Modify `index/projection.py` (`chain`), `index/default.py`, `mcp/server.py`, `cli/main.py`, `cli/render.py`.
- Tests: `test_graph_index.py`, `test_lineage_service.py`, `test_lineage_paths.py`, `test_lineage_export.py`, `test_mcp_graph.py`, `test_cli_graph.py`; fixture `tests/fixtures/lineage/graph_small.json` (a constructed 9-paper, 2-idea graph with every status, used by Tasks 3–4 and G2-E).

---

### Task 1: Graph projection

*Tier: critical (projection, rebuild determinism; spec acceptance 19).*

**Files:** Create `index/graph.py`; Modify `index/projection.py`, `index/default.py`; Test `tests/test_graph_index.py`; update the `PROJECTION_VERSION` pin.

**Interfaces:**
- Consumes: G1 event payloads `ReferenceExtracted`, `ReferenceResolved`, `ReferenceResolutionDecided`; G2-C payloads `RelationProposed`, `RelationDecided`, `IdeaProposed`; `Handler`.
- Produces (`index/projection.py`): `chain(*handlers: Handler) -> Handler` (calls each in order on the same connection and event).
- Produces (`index/graph.py`): tables `graph_nodes(node_id pk, node_type paper|idea, event_id)` and `graph_edges(edge_id pk, edge_type, source, target, base_status, basis, reference_extraction_id, ordinal, live, decision, flags, event_id)` with indexes on `source`, `target`, `edge_type`; `graph_handlers(t) -> dict[str, Handler]` for `reference.extracted`, `reference.resolved`, `reference.resolution_decided`, `relation.proposed`, `relation.decided`, `idea.proposed` (ruling 1, 2). `default_projection` chains them with the G1 and G2-C handlers of the same types. `PROJECTION_VERSION` = base + 1.

- [ ] **Step 1: Tests.** `test_resolved_link_becomes_cites_edge` (`cit:rex_…:3`, `base_status = "stated"` for identifier); `test_unconfirmed_link_is_not_an_edge`; `test_cites_follow_link_decisions_and_liveness` (Review Focus 1); `test_relation_becomes_edge_and_supersession_clears_live`; `test_decision_folded`; `test_idea_and_members_are_nodes`; `test_chain_runs_both_handlers` (G1 and G2-C tables still filled for the same event); `test_rebuild_identical_graph_tables` (acceptance 15: rows of `graph_nodes` and `graph_edges` equal and state hash equal after `index.rebuild()`); `test_projection_version_bumped`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Index suites, G1 and G2-C index tests unedited except the pin; mypy; ruff. **Step 5:** Commit `feat(graph): projected nodes and edges`.

### Task 2: Graph loading, overlays, filter and status

*Tier: standard (Sonnet implement, Haiku review).*

**Files:** Create `services/lineage.py`; Test `tests/test_lineage_service.py`.

**Interfaces:**
- Consumes: Task 1 tables; G2-C `list_relations`, `relation_view`, `list_ideas`, `idea_view`, `resolve_idea`, `EdgeStatus`, `EdgeType`, `DEFAULT_STATUSES`; G2-A `scope_population`, `unit_states(..., scope=)`; G2-B `final_items`, `contribution_item`, `reference_view`, `contribution_status`; `canonical_works`.
- Produces: `@dataclass(frozen=True) GraphFilter(include_inferred: bool = False, include_stale: bool = False, edge_types: tuple[EdgeType, ...] = (EdgeType.CITES, EdgeType.BUILDS_ON, EdgeType.IMPROVES_ON), include_ideas: bool = True)` with `statuses() -> frozenset[EdgeStatus]` and `as_dict() -> dict[str, JsonValue]`; `@dataclass(frozen=True) GraphNode(node_id: str, node_type: Literal["paper", "idea"], scope: Literal["corpus", "external"] | None, title: str | None, name: str | None, members: tuple[str, ...])`; `@dataclass(frozen=True) GraphEdge(edge_id: str, edge_type: EdgeType, source: str, target: str, status: EdgeStatus | Literal["derived"], basis: str | None, flags: tuple[str, ...], derived: bool)`; `@dataclass(frozen=True) Graph(nodes: tuple[GraphNode, ...], edges: tuple[GraphEdge, ...], filter: GraphFilter)` with `node(id) -> GraphNode | None`; `load_graph(project, flt: GraphFilter = GraphFilter()) -> Graph` (rulings 1, 3, 4, 7; nodes of dropped ideas and edges to them removed; edges to merged ideas retargeted); `require_node(graph, node_id, field: str) -> GraphNode` (raises `FactoryValidationError` on `field`, reasons `node-unknown`, `idea-merged` with the surviving id); `class GraphStatus(StrictModel)`: `filter: dict[str, JsonValue]`, `nodes: dict[str, int]` (`paper-corpus`, `paper-external`, `idea`), `edges: dict[str, dict[str, int]]` (edge type -> status -> count, every status, unfiltered), `unextracted: list[str]`, `no_references: list[str]`, `not_stated: int`, `uncited_base: int`; `graph_status(project) -> GraphStatus`.

- [ ] **Step 1: Tests.** `test_default_view_has_stated_and_confirmed_only`; `test_include_flags_widen_and_label`; `test_rejected_never_shown`; `test_unconfirmed_idea_not_drawn` (acceptance 12); `test_corpus_and_external_scope`; `test_derived_idea_edges_labelled_and_not_stored`; `test_unknown_or_merged_node` (Review Focus 4); `test_status_counts_derived_and_name_filter`; `test_every_lineage_edge_has_live_item_and_every_cites_edge_a_link` (acceptance 10: for each edge of `load_graph(include_inferred=True)`, `contribution_item(basis).live` or a `reference_links` row with state `resolved`).
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests; mypy; ruff. **Step 5:** Commit `feat(graph): graph loading, overlays, filter and status`.

### Task 3: Queries (pure) and their service wrappers

*Tier: standard (Sonnet implement, Haiku review).*

**Files:** Create `lineage/paths.py`; Modify `services/lineage.py`; Test `tests/test_lineage_paths.py`.

**Interfaces:**
- Consumes: Task 2 `Graph`, `GraphFilter`, `require_node`.
- Produces (`lineage/paths.py`): `MAX_DEPTH = 8`, `MAX_RESULTS = 500`; `@dataclass(frozen=True) QueryResult(query: str, nodes: tuple[str, ...], edges: tuple[str, ...], depth: int | None, truncated: bool)`; `ancestors(g: Graph, node: str, depth: int) -> QueryResult`; `descendants(g: Graph, node: str, depth: int) -> QueryResult`; `path(g: Graph, a: str, b: str) -> QueryResult` (empty `nodes` when none); `improvements_on(g: Graph, node: str) -> QueryResult` (sources of `improves-on` edges into `node`, their edges); `cited_by_at_least(g: Graph, k: int) -> QueryResult` (targets with ≥ k distinct sources over `cites` edges, `k >= 1`). Nodes sorted by id except `path`, which is in path order.
- Produces (`services/lineage.py`): `class NoStatedBase(StrictModel)`: `filter`, `unextracted`, `not_stated`, `target_outside_corpus`, `no_relation` (each `list[str]`, sorted); `no_stated_base(project, flt: GraphFilter = GraphFilter()) -> NoStatedBase` (ruling 6); `QueryKind = Literal["ancestors", "descendants", "path", "no_stated_base", "improvements_on", "cited_by_at_least"]`; `class GraphQueryResult(StrictModel)`: `query: QueryKind`, `filter: dict[str, JsonValue]`, `nodes: list[dict[str, JsonValue]]` (id, type, scope), `edges: list[dict[str, JsonValue]]` (id, type, source, target, status), `truncated: bool`, `depth: int | None`, `categories: dict[str, list[str]] | None` (for `no_stated_base`); `graph_query(project, query: QueryKind, *, node: str | None = None, target: str | None = None, depth: int = 3, k: int = 2, flt: GraphFilter = GraphFilter()) -> GraphQueryResult` (validates arguments per query: `node`, `target`, `depth` 1..`MAX_DEPTH` clamped with the clamp reported, `k >= 1`).

- [ ] **Step 1: Tests** (fixture `graph_small.json`; acceptance 13).
```python
def test_ancestors_and_descendants_expected(g):
    assert ancestors(g, "rf:p9", 8).nodes == ("rf:p1", "rf:p3", "rf:p5", "rf:p7")
    assert descendants(g, "rf:p1", 2).nodes == ("rf:p3", "rf:p4", "rf:p5")
def test_path_shortest_with_tiebreak(g): assert path(g, "rf:p9", "rf:p1").nodes == ("rf:p9", "rf:p5", "rf:p3", "rf:p1")
def test_path_respects_filter(g, g_inferred): ...          # Review Focus 3
def test_cycles_terminate(g_cycle): ...                    # Review Focus 2
def test_bounds_clamp_and_truncate(g_large): assert ancestors(g_large, "rf:x", 50).depth == MAX_DEPTH and ancestors(...).truncated
def test_improvements_on_and_cited_by(g): ...
def test_no_stated_base_categories_disjoint_and_complete(project):
    r = no_stated_base(project); cats = [r.unextracted, r.not_stated, r.target_outside_corpus, r.no_relation]
    assert sum(map(len, cats)) == len(set().union(*cats)) and set().union(*cats) == EXPECTED_NO_BASE
def test_graph_query_argument_errors(project): ...         # missing node for ancestors; k=0
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement (BFS with a visited set; deterministic neighbour order by node id). **Step 4:** Tests; mypy; ruff. **Step 5:** Commit `feat(graph): bounded lineage queries`.

### Task 4: Export (pure) and the export service

*Tier: standard (Sonnet implement, Haiku review).*

**Files:** Create `lineage/export.py`; Modify `services/lineage.py`; Test `tests/test_lineage_export.py`.

**Interfaces:**
- Consumes: Task 2 `Graph`; Task 3 `GraphQueryResult`.
- Produces (`lineage/export.py`): `to_json(graph: Graph) -> str` and `to_dot(graph: Graph) -> str` (ruling 8); `subgraph(graph: Graph, nodes: Iterable[str], edges: Iterable[str]) -> Graph`.
- Produces (`services/lineage.py`): `ExportFormat = Literal["json", "dot"]`; `graph_export(project, fmt: ExportFormat, *, query: QueryKind | None = None, node: str | None = None, target: str | None = None, depth: int = 3, k: int = 2, flt: GraphFilter = GraphFilter()) -> str` (whole filtered view when `query` is `None`, else the query's subgraph).

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
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement (`json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"`; DOT ids and labels quoted with `"` and `\` escaped). **Step 4:** Tests; mypy; ruff. **Step 5:** Commit `feat(graph): JSON and DOT export`.

### Task 5: `graph_*` MCP tools and `factory graph` CLI

*Tier: Haiku implement and review (surfaces).*

**Files:** Modify `mcp/server.py`, `cli/main.py`, `cli/render.py`; Test `tests/test_mcp_graph.py`, `tests/test_cli_graph.py`.

**Interfaces:**
- MCP (read; refused to pass sessions of any scope): `graph_status(project)` -> `GraphStatus`; `graph_query(project, query, node: str | None = None, target: str | None = None, depth: int = 3, k: int = 2, include_inferred: bool = False, include_stale: bool = False)` -> `GraphQueryResult`; `graph_export(project, format: str = "json", query: str | None = None, node: str | None = None, target: str | None = None, depth: int = 3, k: int = 2, include_inferred: bool = False, include_stale: bool = False)` -> text (ruling 9 cap).
- CLI: `factory graph build` (syncs the index and prints `graph_status`), `factory graph status`, `factory graph query KIND [--node N] [--target T] [--depth D] [--k K] [--include-inferred] [--include-stale]`, `factory graph export --format json|dot [--query KIND …] [--out FILE]` (stdout unless `--out` is given).

- [ ] **Step 1: Tests.** MCP: tool list pinned with the three names; each refused to a pass session; `graph_query` with an unknown query returns a structured error; an export above the cap is refused. CLI: `graph query path --node A --target B` prints the path with statuses; `graph export --format dot` output equals `graph_export(project, "dot")`; `graph build` prints counts naming the filter.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests; mypy; ruff. **Step 5:** Commit `feat(graph): graph tools and CLI`.

## Self-review notes

- **Spec coverage.** Projection and rebuild (Task 1; acceptance 15, R-xx(g)), edge basis (Task 2 test; acceptance 10, R-xx(f)), filter and labels (Task 2; ruling 14), queries (Task 3; acceptance 13), export (Task 4; acceptance 14), tools and CLI (Task 5). Ruling 4: no layout engine. `check` and `trace` are G2-E.
- **Types used later.** `GraphFilter`, `Graph`, `GraphNode`, `GraphEdge`, `load_graph`, `graph_status`, `GraphStatus`, `no_stated_base`, `NoStatedBase`, `graph_query`, `GraphQueryResult`, `graph_export`, `MAX_DEPTH`, `MAX_RESULTS`, tables `graph_nodes`, `graph_edges`, edge ids `cit:<rex_id>:<ordinal>` and `rel_…`.
- **Tiers.** Task 1 critical (Sonnet review); Tasks 2–4 standard; Task 5 Haiku.
