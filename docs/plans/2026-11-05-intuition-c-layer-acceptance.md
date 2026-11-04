# Layer Filter, Labelled Export, Check, Trace, CLI Review and Acceptance Implementation Plan (slice 3c, sub-plan G3-C)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Status: ready — rulings adopted 2026-11-04; depends on G1 and G2 being built.

> **Dependencies.** G3-A and G3-B merged (interpretations, concepts, concept reviews, links, separation harness). G2-D's `graph_query`, `graph_export`, `graph_status` (`services/lineage.py`), their MCP tools and the `factory graph` CLI exist (names: G3-A, "G2 and G1 names consumed"); G2-E's `check` and `trace` extensions are merged, including trace kinds `relation`, `idea`, `cites`, `quote` and G1's `rex_` extraction nodes.

**Goal:** Make the interpretation layer visible on request and only on request, always labelled and separate from the evidence layer; extend `check` and `trace`; give the researcher the CLI review commands; prove the slice's acceptance criteria and run the pilot.

**Architecture:** `services/interpretations.py::layer_graph` assembles the visible layer (nodes, edges, hidden counts) from G3-A/B reads of the layer's own tables; G2's `graph_query`, `graph_export` and `graph_status` take an optional `layer` parameter and attach the layer as a separate part of the result, never merged into the evidence node and edge lists (G2's `load_graph` and graph tables are unchanged). Pure rendering of the layer part (JSON section, DOT cluster, header line) lives in `factory/intuition/export.py`. `check` and `trace` read the layer services; the CLI parses and formats only.

**Tech Stack:** as G3-A; Typer CLI; no new dependencies.

**Spec:** `docs/specs/slice-3c-intuition.md` (user flow 5–7; rulings 7, 11; Separation 4–5; MCP tools and CLI; Check findings; acceptance 5, 8, 9, 13–16). `docs/specs/01-rigour.md` R-01, R-02, R-05, R-51; proposed R-xx(h)–(j).

## Rulings made in this plan

Spec rulings, G3-A rulings A1–A9, G3-B rulings B1–B9 and the rulings below were all Adopted 2026-11-04 (researcher's standing approval of the recommendation), with the controller's stricter A1 (separate layer tables) and extended B2 (`concept.reviewed`). Task 6 records all of them as one *Proposed* decision, kept *Proposed* until the slice is built.

C1. **Layer filter values.** `Layer = Literal["evidence", "all"]`, default `evidence`; the parameter is optional everywhere, so every G2 call without it is unchanged. `all` returns the evidence result unchanged plus a `layer` part: the visible layer nodes attached to the result's evidence nodes (`explains` targets, `uses` from-nodes), the concepts they reach and those concepts' concept→concept closure. `GraphFilter.include_inferred` (G2-D) also widens `uses` links to `inferred`, labelled.
C2. **Visibility.** An interpretation is shown iff `unreviewed` or `reviewed` (spec ruling 7); a concept iff its source is approved, it is unmerged and its definition is `unreviewed` or `reviewed` (G3-B ruling B2); an `explains` edge iff its interpretation is shown; a `uses` edge iff its status is `stated` or `confirmed` (or `inferred` with `include_inferred`) and both endpoints are shown. Hidden items are counted by reason, including `endpoint-hidden` for edges; every view reports the counts.
C3. **Export shape.** Default export: byte-identical to G2's. With `--with-interpretation` (`layer = all`): JSON `{"notice": LAYER_NOTICE, "evidence": <G2 export object>, "interpretation": {"nodes", "edges", "hidden"}}`; DOT: the G2 graph with a first comment line `// LAYER_NOTICE` and a `subgraph cluster_interpretation` (label `interpretation (not evidence)`, nodes and edges `style=dashed`, every label ending in `layer_label(review_state)`), and cross-layer edges drawn dashed. `LAYER_NOTICE = "interpretation layer: not evidence; every item carries its review state"`.
C4. **Unreviewed ceiling.** "Declared ceiling" (spec check findings) is a platform constant `INTERPRETATION_UNREVIEWED_CEILING = 0` in this slice: in `systematic` any unreviewed interpretation or approved, unreviewed concept definition is an error; advisory (warning) otherwise. A protocol field is deferred until the pilot shows the review burden.
C5. **Leak scan.** `layer-leak` serialises each evidence output (the G3-A `evidence_outputs` set, computed by a non-test function `evidence_snapshot(project) -> dict[str, str]` in `services/check.py`) and searches for `\b(?:int|cpt|cul)_[0-9A-HJKMNP-TV-Z]{26}\b`, `"explains:` / `"uses:` edge ids, and `"class": "interpretation"`; any hit is an error in every mode, refs = output names.

## Global Constraints

- All G3-A and G3-B constraints hold. `check` and `trace` messages never contain document text; trace node labels carry ids, kinds, `layer_label(...)` and the interpretation or concept text (agent-written text, not literature), plus quotes only as stored in events.
- Every layer node and edge in any view, export or trace carries `class = "interpretation"` and its review state.
- CLI human acts use `project.human_actor()` and `Channel.CLI`; no new MCP tool performs a human act.
- `mypy --strict`, ruff, `pytest -m "not network"` pass; coverage ≥ 90% for `services/` and `model/`; earlier suites unedited except G2-D's pinned MCP tool-signature test in `tests/test_mcp_graph.py`, which Task 1 updates for the new optional `layer` parameter.

## Review Focus

1. `graph_export` with no `layer` argument after the layer is populated is byte-identical to the export before this plan, for JSON and DOT (Tasks 1, 2).
2. A `uses` edge from a shown paper to a hidden concept is absent from the `all` view and counted `endpoint-hidden`, not silently dropped (Task 1).
3. `factory interpretations review --wrong` without `--note` exits non-zero and writes nothing; `review` of a superseded id prints the reason (Task 5).
4. `trace` back from an interpretation whose quote document was superseded shows `source-stale` and still reaches the document and the question (Task 4).
5. `check` on a project with no layer events emits none of the new codes (Task 3).

## File Structure

- Create `intuition/export.py`.
- Modify `model/intuition.py` (layer read models), `services/interpretations.py` (`layer_graph`, `layer_counts`), `services/lineage.py`, `services/check.py`, `services/trace.py`, `mcp/server.py` (`layer` on `graph_query`/`graph_export`), `cli/main.py`, `cli/render.py`.
- Docs: `docs/specs/slice-3c-intuition.md` (implemented paragraph), `docs/decisions.md` (*Proposed* entry), `docs/specs/01-rigour.md` (R-xx(h)–(j) marked proposed, unchanged text), `CLAUDE.md` status line, `docs/pilot/log.md` (pilot rows).
- Tests: `test_intuition_layer.py`, `test_intuition_export.py`, `test_intuition_check.py`, `test_intuition_trace.py`, `test_cli_intuition.py`, `test_acceptance_intuition.py`.

---

### Task 1: Layer view, `layer` filter and layer counts

*Tier: standard (read paths), with the default-unchanged test reviewed as critical.*

**Files:** Modify `model/intuition.py`, `services/interpretations.py`, `services/lineage.py`, `mcp/server.py`, `tests/test_mcp_graph.py` (G2-D's pinned tool signatures gain `layer`); Test `tests/test_intuition_layer.py`.

**Interfaces:**
- Consumes: `list_interpretations`, `review_counts`, `list_concepts`, `concept_review_counts`, `list_concept_links`, `effective_concept`, `stale_sources`, `layer_label`, `InterpretationHidden`, `ConceptHidden`; G2-D `graph_query`, `graph_status`, `GraphQueryResult`, `GraphStatus`, `GraphFilter`, `QueryKind`.
- Produces (`model/intuition.py`): `LayerNode(StrictModel)`: `node_id`, `node_type: Literal["interpretation", "concept"]`, `class_: str` (serialised `class`, always `interpretation`), `review_state: str`, `label: str`, `name: str | None`, `flags: list[str]`; `LayerEdge(StrictModel)`: `edge_id`, `edge_type: Literal["explains", "uses"]`, `source`, `target`, `class_`, `review_state`, `label`, `basis: str | None`; `LayerHidden(StrictModel)`: `interpretations: InterpretationHidden`, `concepts: ConceptHidden`, `endpoint_hidden: int`; `LayerGraph(StrictModel)`: `nodes: list[LayerNode]`, `edges: list[LayerEdge]`, `hidden: LayerHidden`; `LayerCounts(StrictModel)`: `interpretations: dict[str, int]` (by review state, including hidden states), `concepts: dict[str, int]` (by `ConceptState`, plus `unapproved`), `explains: int`, `uses: dict[str, int]` (by status), `hidden: LayerHidden`.
- Produces (`services/interpretations.py`): `layer_graph(project: Project, *, attach_to: Collection[str] | None = None, include_inferred: bool = False) -> LayerGraph` (ruling C1, C2; `None` = the whole visible layer; deterministic order by id); `layer_counts(project) -> LayerCounts`.
- Produces (`services/lineage.py`, G2-D): `Layer = Literal["evidence", "all"]`; `graph_query(project, query: QueryKind, *, node=None, target=None, depth=3, k=2, flt: GraphFilter = GraphFilter(), layer: Layer = "evidence") -> GraphQueryResult` and `GraphQueryResult.layer: LayerGraph | None = None` (set only for `all`, attached to the result's node ids, `include_inferred` taken from `flt`; excluded from the serialised result when `None`, so default output is unchanged); `graph_status(project, *, layer: Layer = "evidence") -> GraphStatus` with `GraphStatus.layer: LayerCounts | None = None`, filled only for `all` and excluded from the serialised status when `None`, so G2's default output is unchanged; no total across classes anywhere. `load_graph` is unchanged and never returns a layer node. `services/lineage.py` imports the layer only through `services/interpretations.py` (an allowed importer). MCP `graph_query`, `graph_export`, `graph_status` gain `layer: str = "evidence"`.

- [ ] **Step 1: Tests.**
```python
def test_default_query_unchanged_with_layer_populated():           # Review Focus 1, acceptance 8
    before = g2_outputs(plain); assert g2_outputs(layered) == before
def test_all_attaches_layer_separately_and_labelled():             # acceptance 9
    r = graph_query(layered, "descendants", node=BASE_IDEA, depth=3, layer="all")
    assert r.nodes == graph_query(layered, "descendants", node=BASE_IDEA, depth=3).nodes
    assert r.layer and all(n.class_ == "interpretation" and n.label.startswith("interpretation · ") for n in r.layer.nodes)
def test_hidden_items_absent_and_counted():                        # acceptance 5, Review Focus 2
    g = layer_graph(layered)
    assert WRONG_INT not in node_ids(g) and SUPERSEDED_INT not in node_ids(g) and UNAPPROVED_CPT not in node_ids(g)
    assert (g.hidden.interpretations.wrong, g.hidden.concepts.unapproved, g.hidden.endpoint_hidden) == (1, 1, 1)
def test_inferred_uses_only_with_flag(): ...
def test_concept_closure_included_for_attached_nodes(): ...
def test_graph_status_layer_counts_separate_no_total():           # acceptance 8
    s = graph_status(layered, layer="all").model_dump()
    assert "total" not in json.dumps(s) and s["layer"]["interpretations"]["unreviewed"] == N_UNREVIEWED
def test_mcp_layer_parameter_validated(): ...                      # layer="x" -> structured error
def test_wrong_concept_hidden_and_unreviewed_concept_labelled(): ...  # G3-B ruling B2
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement; update the tool-signature pin in `tests/test_mcp_graph.py` (the only G2 test edited by G3). **Step 4:** Tests, the other G2 suites unedited, mypy, ruff. **Step 5:** Commit `feat(intuition): layer view, layer filter and layer counts`.

### Task 2: Labelled JSON and DOT export

*Tier: standard.*

**Files:** Create `intuition/export.py`; modify `services/lineage.py` (`graph_export`); Test `tests/test_intuition_export.py`.

**Interfaces:**
- Produces (`intuition/export.py`, pure): `LAYER_NOTICE` (ruling C3); `layer_json(layer: LayerGraph) -> dict[str, JsonValue]`; `layer_dot(layer: LayerGraph) -> list[str]` (DOT lines of the cluster and the cross-layer edges, ids quoted, labels escaped); `with_layer_json(evidence: dict[str, JsonValue], layer: LayerGraph) -> str` and `with_layer_dot(evidence_dot: str, layer: LayerGraph) -> str` (canonical, deterministic).
- `graph_export(project, fmt: ExportFormat, *, query=None, node=None, target=None, depth=3, k=2, flt: GraphFilter = GraphFilter(), layer: Layer = "evidence") -> str`: `evidence` returns G2-D's string untouched; `all` wraps it per ruling C3.

- [ ] **Step 1: Tests.**
```python
def test_default_export_byte_identical(): assert graph_export(layered, "dot") == graph_export(plain, "dot")   # also "json"
def test_json_with_layer_has_notice_and_labels():
    d = json.loads(graph_export(layered, "json", layer="all"))
    assert d["notice"] == LAYER_NOTICE and d["evidence"] == json.loads(graph_export(layered, "json"))
    assert all(x["class"] == "interpretation" and "review_state" in x for x in d["interpretation"]["nodes"] + d["interpretation"]["edges"])
def test_dot_with_layer_dashed_cluster_and_header():
    dot = graph_export(layered, "dot", layer="all")
    assert dot.splitlines()[0] == f"// {LAYER_NOTICE}" and "subgraph cluster_interpretation" in dot
    assert all("style=dashed" in line for line in layer_lines(dot))
def test_export_deterministic_across_rebuilds(): ...
def test_labels_escaped(): ...                                     # a concept name with a quote character
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(intuition): labelled layer export in JSON and DOT`.

### Task 3: `check` findings

*Tier: standard.*

**Files:** Modify `services/check.py`; Test `tests/test_intuition_check.py`.

**Interfaces:**
- Produces codes and severities (exploratory, pilot, systematic): `interpretation-unreviewed` (warning, warning, error when count > `INTERPRETATION_UNREVIEWED_CEILING`, ruling C4; refs = ids), `concept-unreviewed` (same severities and ceiling; approved, unmerged concepts whose live definition is unreviewed; G3-B ruling B2), `interpretation-source-stale` (warning ×3; from `stale_sources`, interpretation and concept ids), `interpretation-self-reviewed` (warning ×3; self-reviewed interpretations and concept definitions), `concept-source-missing` (warning ×3; concepts without an approved source, rejected included), `concept-link-unconfirmed` (warning ×3; inferred links awaiting a decision), `layer-leak` (error ×3; ruling C5), `concept-cycle` (error ×3; a cycle in non-rejected concept→concept links after merge resolution, computed with `would_cycle`); `evidence_snapshot(project) -> dict[str, str]`. Messages state counts and ids only.

- [ ] **Step 1: Tests.** One positive and one absent case per code (acceptance 14); `test_unreviewed_error_only_in_systematic` (interpretations and concepts); `test_layer_leak_fires_on_planted_reference` (monkeypatch `final_rows` to include an `int_` id → error; also a G2 export carrying `"class": "interpretation"`); `test_concept_cycle_from_constructed_log` (events written directly, bypassing the service refusal); `test_no_new_codes_without_layer` (Review Focus 5); `test_messages_carry_no_document_text`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Existing check suites unedited, mypy, ruff. **Step 5:** Commit `feat(intuition): check findings for the interpretation layer`.

### Task 4: `trace` from and to layer items

*Tier: standard.*

**Files:** Modify `services/trace.py`; Test `tests/test_intuition_trace.py`.

**Interfaces:**
- Produces: `KINDS` gains `interpretation`, `concept`, `concept_link` after `claim`; `_PATTERNS` for `int_`, `cpt_`, `cul_`. Back edges: interpretation → its target (work node or G2-E `idea` node), each quote source → `<conversion_id>/<anchor>` anchor node, each citation → the G1 extraction node `rex_…` (G1 kind) or work node, `supersedes` → prior interpretation; concept → approved source work (when in the corpus), quote anchors, the concept it is merged into; concept link → from-node, concept, basis anchor or entry. Forward: from an anchor, work, idea or concept node, the layer items citing or targeting it. Every layer node's `label` = `"<kind> <id> · " + layer_label(review_state)` plus flags (`source-stale`, `self-reviewed`, `unverifiable-source`), the text, the writer (actor id, model, skill, `input_blob`) and the review history (`interpretation_history` / `concept_history`, the latter with `concept.reviewed` and source decisions) as child nodes of kind `interpretation` with the review event ids. `agent_trace` includes the layer with the same labels.

- [ ] **Step 1: Tests.** `test_trace_interpretation_back_reaches_question` (interpretation → anchor → conversion → document → attempt → work → full-text decision → protocol → question; acceptance 13); `test_trace_interpretation_shows_history_and_provenance`; `test_trace_concept_shows_source_and_uses_links` (acceptance 13); `test_trace_stale_source_labelled` (Review Focus 4); `test_trace_forward_from_anchor_lists_layer_items_labelled`; `test_existing_trace_suites_unchanged`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(intuition): trace interpretations, concepts and links`.

### Task 5: CLI review commands

*Tier: Haiku for implementation and review (surfaces); behaviour is in the services.*

**Files:** Modify `cli/main.py`, `cli/render.py`; Test `tests/test_cli_intuition.py`.

**Interfaces:**
- `factory interpretations list [--state S]… [--target T]` (labelled rows, hidden counts) · `show ID` (text, sources with quote and anchor, writer, `input_blob` content, flags) · `review ID --reviewed|--wrong [--note TEXT]` · `supersede ID --text TEXT --source JSON…` · `history ID` · `write --target T --text TEXT --source JSON…` (human-authored).
- `factory concepts list [--all]` · `define NAME [--alias A]… [--text T] [--source-kind K --citation C [--work W]] [--approve]` · `source ID --source-kind K --citation C [--work W]` (human redefinition with the new source, approved, ruling B1) · `approve ID [--note]` · `reject-source ID --note` · `review ID --reviewed|--wrong [--note TEXT]` (G3-B `review_concept`) · `show ID` · `history ID` · `merge INTO FROM --reason` · `unmerge INTO FROM --reason`.
- `factory concept-links list [--status S]…` · `confirm LINK --rationale` · `reject LINK --rationale`.
- `factory graph export --with-interpretation` maps to `layer = "all"`; `factory graph status --with-interpretation` prints layer counts in their own section.
- `--source JSON` is parsed into `SourceInput` with structured errors; every command exits non-zero on `FactoryValidationError` and prints field and reason.

- [ ] **Step 1: Tests.** `review --wrong` without note fails, nothing written (Review Focus 3); `review` records a human event with channel `cli`; `review` of a superseded id prints `superseded`; `list` default hides wrong items and prints the hidden count; `show` prints the stored quote and anchor and the writer's model; `concepts define --approve` writes two events; `concepts approve` makes the concept visible in `concepts list`, labelled `unreviewed`; `concepts review --reviewed` writes a human `concept.reviewed` and `concepts review --wrong` without `--note` fails; `concept-links confirm` on a stated link fails; `merge` then `unmerge` round-trips; `graph export --with-interpretation` starts with the notice line.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(intuition): CLI review commands for interpretations, concepts and links`.

### Task 6: Acceptance, docs and pilot

*Tier: Haiku for the tests and docs; the pilot is run by the researcher with Claude.*

**Files:** Test `tests/test_acceptance_intuition.py`; modify the docs listed in File Structure.

- [ ] **Step 1: Acceptance tests (spec 1–14, 16).** `test_provenance_on_agent_events` (1) · `test_validation_refusals_write_nothing` (2) · `test_review_events_only_human_and_fold` (3) · `test_writer_cannot_review_and_self_review_flagged` (4) · `test_default_visibility_and_hidden_counts` (5) · `test_concept_hidden_until_source_approved_and_definition_reviewed_by_human` (6) · `test_uses_rule_and_cycle_refusal` (7) · `test_separation_architecture_and_differential` (8; reuses G3-A helpers with the full layer) · `test_labels_in_query_trace_and_export` (9) · `test_stale_source_flag_keeps_state` (10) · `test_merge_round_trip` (11) · `test_rebuild_identical_layer_tables_and_state_hash` (12) · `test_trace_interpretation_and_concept` (13) · `test_every_check_code_constructed` (14) · `test_earlier_acceptance_suites_unchanged` (16 in part).
- [ ] **Step 2:** Run `uv run pytest tests/test_acceptance_intuition.py -v`; fix until PASS; then the full suite, `mypy --strict`, ruff, coverage ≥ 90% for `services/` and `model/`.
- [ ] **Step 3: Docs.** Slice-3c spec: an "Implemented in plans G3-A to G3-C" paragraph naming tools and commands. `docs/decisions.md`: next free number, *Proposed* (kept *Proposed*; the entry is written when the slice is built): "Intuition-layer rulings of slice 3c (spec rulings 1–11) and plans G3-A–C, adopted 2026-11-04 by the researcher's standing approval of the recommendations: layer rows in separate tables (`layer_nodes`, `layer_edges`), G2's graph tables untouched; task-blob input for interpretations; confirmed ideas served by default, papers only when targeted; citation sources by G1 entry key or corpus work; quote sources pin a live document; agent supersedes only its own unreviewed or wrong items; distinct humans by `actor.user`, self-review only with one human; approval bound to a source digest; human review of every concept definition (`concept.reviewed`); unverifiable sources carry no quotes; identity by folded name and alias; stated `uses` by whole-word name in quote or citation of the approved source; concept-to-concept links always inferred; cycle refusal including merges; optional layer filter `evidence|all` with a separate layer part; labelled export with notice; `INTERPRETATION_UNREVIEWED_CEILING = 0`; leak scan by id pattern." `CLAUDE.md` status line. Commit `test(intuition): acceptance; docs`.
- [ ] **Step 4: Pilot (acceptance 15; researcher with Claude, outside `platform/`).** On `linear-attention-vision` with the G2 lineage built: (1) a fresh session runs `intuition_next` with `targets` = the kernel-feature idea and records one interpretation from its served items; (2) the researcher defines or approves one concept (for example random-feature approximation of a kernel) with a textbook or survey source in `factory concepts define … --approve`; (3) Claude proposes `uses` links from the idea's papers (and, when the researcher only supplied the source, drafts the concept's text); (4) the researcher reviews the interpretation and the concept definition (`factory concepts review`) and decides the inferred links in the CLI; (5) `factory graph export --with-interpretation --format dot` and `factory graph status --with-interpretation` are run and their computed counts (unreviewed, reviewed, wrong, superseded, hidden) copied into new rows of `docs/pilot/log.md` with event ids; (6) `factory check` is run and its layer findings recorded. Pilot rows contain ids and counts only, no quotes and no interpretation text; the export file stays under `projects/linear-attention-vision/` and is not committed if it contains quotes. Never open `docs/pilot/heldout-seeds.md`. Commit `docs(pilot): intuition layer pilot rows`.

## Self-review notes

- **Spec coverage.** User flow 5 (Task 5), 6 (Tasks 1, 2), 7 (Tasks 3, 4); ruling 7 visibility (Task 1), ruling 11 exports (Task 2); separation 4 and 5 (Tasks 1, 2, 4); CLI list of the spec (Task 5); check findings (Task 3); acceptance 1–16 (Task 6, with 15 in Step 4). MCP tools other than the `layer` parameter are G3-A and G3-B.
- **Types.** `LayerGraph`, `LayerNode`, `LayerEdge`, `LayerHidden`, `LayerCounts`, `Layer`, `LAYER_NOTICE`, `layer_graph`, `evidence_snapshot` are introduced here; G3-A/B names are used as those plans define them.
- **Risk.** The one change to G2 output shape is optional (`layer` part on `GraphQueryResult`, `GraphStatus.layer`) and absent by default; G2's tables and `load_graph` are untouched; Task 1's and Task 2's default-unchanged tests are the gate.
