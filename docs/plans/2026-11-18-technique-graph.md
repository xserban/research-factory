# The technique graph: a landscape of techniques, variants, origins and evidence, built from the technique miners (plan, 2026-11-18)

Status: plan for the researcher's validation (2026-11-18). Nothing built, nothing run, no model called; the pilot's events were counted read-only, nothing was written. Backlog: IDEA-78 (technique comprehension layer, technique-landscape process and graph of ideas), part A5 and B7 of `docs/plans/2026-11-14-technique-comprehension.md`; builds on IDEA-83 (technique miner, merged 2026-11-15; part C of the same plan), IDEA-50 (taxonomies), IDEA-53 (agreement) and the lineage slice (3b) and intuition slice (3c).
Depends on: `services/lineage.py` (graph service), `index/lineage.py`, `index/graph.py`, `index/intuition.py`, `services/site_taxonomy_registered.py`, `services/site_lifecycle.py` (precedent for a stage page), `services/finders.py`, the MCP tools `graph_query`, `graph_export`, `idea_propose`, `relation_propose`, `interpretation_record`, `lead_record`, `finder_gaps`.
Binding: `00-system.md` (events append-only, index a projection, MCP conventions), decision 82 (lineage rulings; ruling 1 is departed from below), decision 83 (intuition layer), decision 120 (taxonomies), decision 127 (technique layer as per-stage taxonomies and derived miners), rigour R-87 (interpretation never evidence).
Context read for this plan: the researcher's request of 2026-11-18; the draft `docs/design-note-corpus-search-2026-11-17.md` (untracked, not edited), which fixes how a graph fits the sparring funnel (its ruling 6 digest, its "Graph" source of candidates).

## 1. Goal and non-goals

Goal. One place where the researcher, and Claude on their behalf, can see the techniques that AI research systems use, stage by stage, and ask four things of it: which techniques exist at a stage and how widely used; for one technique, its variants, where it comes from, what problems it addresses and what evidence supports it; which technique and problem pairs nobody has tried; and where a new idea sits relative to what is known, with checked quotes. The hypotheses engine reads the same structure to combine and transfer techniques (`2026-11-14-hypotheses-engine.md`, gap G1).

First version (this plan, section 9): a **derived, read-only, labelled-exploratory projection** of what the eight technique miners already recorded, joined to the reference links and work layers, with a hub page, a CLI view and two MCP read tools. No new event type in the first slice.

Non-goals.
- No new mining pass, no model call, no change to the technique miners, taxonomies or codebooks. The miners stay exploratory.
- No effect comparison across papers (A6 of the comprehension plan: different benchmarks, models, budgets). Evidence level is a count, with its settings named.
- No count from this layer enters any report (rule of `2026-11-13-lifecycle-stage-deep-dive.md` section 8: uncalibrated rows are for reading).
- No automatic idea or relation creation. Lineage ideas and relations keep decision 82's human confirmation.
- No problem layer from mining in v1 (section 4: there is no problem miner; the prior text is not recorded).
- No layout engine, no external JavaScript or CSS; no meaning-based search (IDEA-88's own scope).
- Not a replacement for IDEA-83 item (d) (relations `reuses`, `corrects`, `re-invents`), nor for the teach-back regime (B4).

## 2. User stories

1. **Browse by stage.** "Show me the landscape of techniques at ideation": a matrix of stage by technique with the number of works using each, drill down to the works, each with the miner's quote and anchor.
2. **One technique.** "What are the variants of tournament ranking, where did it come from, what problems does it address, what evidence supports it": the technique's uses (one row per work, the miner's `described_as` per use), status (core, reused-cited, standard, ...), evidence level, the works it is reused from by citation, and the source quote of each row.
3. **Unexplored pairs.** "Which technique and problem pairs are unexplored" and the simpler "which stage has few techniques with an independent test": through the finders' gap report (empty cells of a declared grid, "not found in this corpus"), over a grid the technique graph supplies.
4. **Bounce an idea.** Claude is given an idea in chat; it looks up the graph for the techniques the idea touches, lists near neighbours and the evidence, places the idea (as an interpretation anchored on verified quotes, and optionally as a lead with triggers) and says what is known, what is untested and what is only asserted. The researcher accepts or discards.

## 3. What exists and what is missing, honestly

Read from the code and from the pilot's events (counted read-only on `data/projects/agentic-science/events`, 2026-11-18).

| Piece | Where | State |
|---|---|---|
| Lineage graph | `services/lineage.py` (graph service, 1,366 lines), tables `relations`, `ideas`, `idea_members`, `idea_merges` (`index/lineage.py`), `graph_nodes`, `graph_edges` (`index/graph.py`); MCP `graph_status`, `graph_query`, `graph_export`, `relation_propose`, `relation_list`, `idea_propose`, `idea_list` | Built v1, on main. Nodes are works and ideas; edge types `cites`, `builds-on`, `improves-on`. An idea needs a name inside a verified quote of a recorded contribution item; a relation needs a basis item or a note. |
| Interpretation layer | `index/intuition.py` (`layer_nodes`, `layer_edges`, CHECK class = 'interpretation'), `interpretation_record`, `concept_propose`, `layer=all` filter | Built v1. Interpretations explain a target with 1 to 5 sources; concepts are background. |
| Taxonomy product | `services/site_taxonomy_registered.py` | Built (decision 127 item 5): per taxonomy version, categories with computed counts from the derived miner. |
| Technique taxonomies and miners | 8 taxonomies `t-tech-<stage>` v1 and 8 derived miners `m-tech-<stage>` v1, registered in the pilot (9 `taxonomy.registered`, 30 `miner.registered` events in total) | Pass A over the core layer: 95 works in all 8 stages, about 2,230 rows (`v3/MORNING.md`); pass B (Haiku) on 5 to 11 units per stage. Fields per row: `category`, `quote`, `described_as`, attributes `status`, `evidence`, optional `parameters`. |
| Prior codebooks and CSVs | `ops/technique-trial-2026-11-14/v3/codebooks/techniques.csv` (343 entries with mechanism, variants, `origin`, `lineage`, `problems` text), `technique_papers.csv` (1,609 rows) | Exploratory agent text, registered as files, never mined records. |
| Finders | `services/finders.py`: `find_gaps` over methods or cards by a comparability key | Reads evidence-schema rows and method cards; it cannot see miner rows (hypotheses-engine gap G1). |
| Lifecycle page | `services/site_lifecycle.py` | Precedent for a static stage page with drill-down from miner rows. |

What is missing, plainly.
- **The pilot has no idea, relation or contribution events.** Counting event types in the pilot: 9,898 `extraction.recorded`, 1,463 `reference.extracted` and `reference.resolved`, 30 `miner.registered`, 9 `taxonomy.registered`, 10 `file.registered`; none of `idea.*`, `relation.*`, `contribution.*`, `concept.*`, `interpretation.*`. The recorded protocol's `contribution_schema` is null (plan `2026-11-14-graph-and-data-integration.md` section 1), so the pilot's lineage graph holds `cites` edges only, and `idea_propose` cannot be used (it needs a `name_item` from a contribution item).
- **No contribution schema or contribution miner.** The map and contribution miners of part A3 were never built; origins and problems were written only in the exploratory notes and CSV columns `origin`, `lineage`, `problems`, which are untraceable text.
- **The miners are exploratory and uncalibrated.** Agreement between pass A and pass B on all rows is 0.21 to 0.61 by stage (aligned rows 0.48 to 0.73), mostly because passes list different techniques (row recall), not because they disagree on a shared row. The comparison with the prior shows many `new` and `not found` rows and, mostly, `status` and `evidence` omitted on a shared category (`v3/MORNING.md`). No calibration labels for them exist. The graph built from them describes what pass A read, not what is in the papers.
- **About 8 techniques are split in two stage taxonomies** (decision 127, C7 ruling 7): the cross-stage identity of a technique is not recorded.
- **Finders and hypotheses tools** do not read miner rows; they would need a grid supplier (section 8).
- **No graph view of techniques** on the hub; the explorer's lineage and graph views show works only (`services/site_explorer.py`).

## 4. Node and edge model for v1

Principle: derive wherever a deterministic rule from recorded rows exists; record judgement only where a rule cannot decide. Every node and edge carries `class = interpretation` and `state = exploratory`; `state = accepted` exists in the model from the first slice but nothing sets it until the recorded link event (section 5).

### Nodes

| Kind | Source | Derived or recorded | Notes |
|---|---|---|---|
| `technique` | Category of a `t-tech-<stage>` taxonomy: id `<stage-code>-NN`, name, definition, include and exclude cues | **Derived** (taxonomy event + `taxonomy_view`) | One node per (stage, category). The 8 known cross-stage pairs stay two nodes in v1. Counts (works with a current pass-A row, `not-stated` excluded) are computed. |
| `work` (system) | Corpus work with a row | **Derived** | Id `rf:`; layer from `m-layer` (core, applied, benchmark) shown as a filter, default core. |
| `evidence` | One miner row: quote, anchor, `evidence` attribute (independent-test, own-ablation, own-comparison, asserted-only, reported-failure), `status`, `parameters` | **Derived** | Anchor and quote are the platform-verified ones of the row; the evidence node is the row, never a free statement. Rows that omit an attribute show "not stated" (the largest bucket against the prior). |
| `origin` | See edge `derives-from` | **Derived, candidate** | Not a node kind of its own in v1: an origin is a `work` node reached by a `derives-from` edge. The word "origin" in the UI means "the work the corpus says it comes from", with the basis shown. |
| `problem` | Only in the prior CSV (`problems` column), not mined | **Not in v1** | A problem node needs a recorded reading (a problem miner or a contribution item). Section 5 proposes the later event. v1 shows the prior's problem text on a technique page only as "exploratory prior, not mined", behind a toggle, and never as a node or a count. |

### Edges

| Kind | Rule | Derived or recorded | State in v1 |
|---|---|---|---|
| `uses` | Work W has a current pass-A row for technique T in stage S; attributes: `status`, `described_as` (the variant, in the miner's words), stage | **Derived** | exploratory |
| `supported-by` | `uses` edge to its evidence node (the row), level = the `evidence` attribute | **Derived** | exploratory |
| `derives-from` (candidate) | W has a `uses` row for T with `status = reused-cited`, and W has a resolved G1 reference link to W2, and W2 has a `uses` row for T. The basis shows the reference entry and the two rows. | **Derived** | exploratory; "candidate" until a person accepts it |
| `earliest-in-corpus` | For T, the work with the earliest publication date among its users | **Derived, labelled as a date rule, not an origin claim** | exploratory; absence from the corpus is not absence from the field |
| `variant-of` | Two users of T whose `described_as` differ: not derived (needs meaning; IDEA-53's judge, not this plan). v1 lists the variants as the uses of one technique, with no variant nodes | **Not in v1** | |
| `addresses` | Technique to problem | **Not in v1** (no problem nodes) | |
| `builds-on`, `improves-on` between works | The lineage graph, as built | **Unchanged**; shown beside when it exists (pilot: none) | |

Edge states are `exploratory` and `accepted` (never `confirmed`, a word lineage already uses with a different rule). `accepted` is set only by a human event (section 5); a rejected candidate is hidden from the default lens and remembered.

### Lenses (saved filters, no stored state in v1)

A lens is a URL-hash or CLI filter, not a recorded object: stage; work layer (default core; `all` widens, labelled); evidence level; status (core contribution, reused-cited, standard, ...); origin (works reachable by `derives-from` from a chosen work); problem (v2). Every lens names itself in the output (as `graph_query` names its filter). A lens never hides the exploratory label.

### Counting rule

Counts are numbers of works (or rows) with a current pass-A row in this lens, per technique. Beside every table the page prints the agreement of the stage's miner (all rows and aligned rows), "exploratory, not calibrated", and the share of rows with no `evidence` attribute. No percentage of the corpus is shown without the corpus definition and the sentence "not found in this corpus".

## 5. Which parts need recorded judgement

1. **Everything in section 4 marked derived needs no event.** The projection is computed from recorded extraction rows, taxonomies, reference links and layers: deterministic, rebuildable, no new event.
2. **Accepting a derived edge (candidate to accepted), or recording a technique identity across stages, or recording a problem.** These need a person's or Claude's judgement. Proposed, not in the first slice: one event family `technique_link.proposed` and `technique_link.decided` (kind `derives-from`, `same-as`, `variant-of`, `addresses`; source and target technique or work or problem key; for judgement not derivable, at least one verified quote with anchor; agent-proposed, human-decided in pilot and systematic modes; provenance model, skill version, `input_blob`; the projector folds the latest human decision). A problem node is a recorded `problem.recorded` (name, at most 300 characters, claimed or observed, quote). **Proposed decision row "to be assigned at merge"** (decisions up to 134 exist), recording: (a) the technique graph is an interpretation layer, derived and rebuildable; (b) it departs from decision 82 ruling 1 (ideas human-confirmed, named from a verified quote, never clustered automatically) because a technique is a taxonomy category chosen by a registered miner, not a lineage idea: technique grouping is automatic by the taxonomy, lineage ideas stay human-confirmed and untouched; (c) derived edges are exploratory and never counted in reports; (d) `accepted` needs a human decision; (e) the departure from the human floors of `idea_confirm` and `relation_confirm` applies only to derived edges, not to the events of 82. In the first slice only (a), (c) apply, so the decision row is written with the slice (task 0) and marked Proposed.
3. **Bouncing an idea** uses events that already exist (section 7), so it needs no new event family.

## 6. Relation to the lineage graph: recommendation

Options: extend `graph_nodes`, `graph_edges` and the layer tables with technique node and edge types; or a separate read-only product over the same inputs.

Recommended: **a separate product, `services/technique_graph.py`, computed at read time from the index, in the shape of the existing graph output** (nodes, edges, the filter named, deterministic order, JSON and DOT). Reasons: (1) lineage tables are the evidence class with typed ids and constraints (`graph_edges` for works and ideas, R-86 typed tables, no free labels); a technique is not a work and its edges are interpretation, so they belong beside `layer_nodes`, not in the evidence tables, and a CHECK on class would refuse them there; (2) a derived layer written to tables by the projector would need a projection bump and a handler for every extraction event, for a view that runs in under a second on 2,500 rows; read-time derivation keeps "scripts never judge, projections are of events" with no schema change; (3) a lineage hub page and `graph_query` keep their behaviour and tests; (4) the later recorded link events (section 5) can get their own projector tables, as the intuition layer did (decision 83 ruling A1: separate tables, graph tables untouched), without migrating v1.
Reuse: the JSON and DOT writers of `graph_export` for output shape (to check whether they are callable on a generic node and edge list; if not, a small writer in the new module, tested for determinism), `layer=all` as the switch by which a work-level view may show technique nodes later, the `_withheld` and `_reply` wrappers in the MCP server, and `site_widgets` and `site_lifecycle` patterns for the page. The lineage `cites` edges are read through `graph_edges` (the resolved reference links) for `derives-from` candidates.

## 7. Using the graph to bounce an idea (Claude's procedure)

Skill `rf-technique-bounce` (new, small; procedure, not code), using existing tools only:

1. `technique_landscape` (new, read-only) for the stages the idea touches; Claude lists candidate techniques as a tick list with counts (as the sparring design, ruling 7); the researcher ticks.
2. `technique_view` for each ticked technique: uses, variants, evidence levels, derived origin candidates. Claude reads the quotes through `document_read` before relying on them.
3. Claude states, labelled as its own reading: what is already done (and by how many works, at which evidence level), the nearest variant, what is asserted only, what is untested (empty cells via `finder_gaps` once a grid exists, task 8).
4. Placement: `interpretation_record` (at most 600 characters, 1 to 5 verified quote sources) targeting the nearest work, which is how an accepted view of the idea is anchored (to check: whether `interpretation_record` accepts a work target without an `intuition_next` task; it needs `task_id`), and `lead_record` with triggers (`work`, `interpretation`, and a `gap` or `match` row where a builder supplied one) when the researcher wants the idea followed up.
5. `idea_propose` and `relation_propose` stay for the lineage graph: they need a contribution item and a confirming human, and the pilot has none; `relation_propose` with a `note` (at most 500 characters, not evidence) is available but is not used for techniques. When the contribution miner exists (a later plan) the `name_item` route becomes usable.
6. Nothing is recorded without the researcher's say-so; the argument sheet of IDEA-88 may cite the technique rows as candidates (its "Miners" and "Graph" sources).

Candidate proposal for this skill: a rule that every sentence about counts says "exploratory, pass A of m-tech-<stage>".

## 8. Hub page, CLI and MCP

### Hub page `Landscape` (static HTML, built from the projection, no external resources)

- **Matrix**: rows = techniques grouped by stage, columns = work layer and evidence level buckets; cell = number of works; row header = technique name with definition on hover (title attribute). Sort by count or id. Stage miner agreement printed above each stage block.
- **Drill-down**: a technique opens the list of works; each row shows `status`, evidence level, `described_as`, the quote and anchor, and a link to the work in the explorer. State and lens in the URL hash (as `site_lifecycle`).
- **Ego graph** of one technique: the technique at the centre, its users as nodes, `derives-from` candidates as arrows, `earliest-in-corpus` marked; drawn as inline SVG with a deterministic layout computed in Python (concentric by date, no library). A technique with more than 40 users shows the top 40 by evidence level and says how many it omitted.
- Every page carries the label "exploratory: uncalibrated miners, pass A, interpretation layer, not evidence" and the miner agreement figures.
- Cost estimate on the pilot (to be measured in task 3): the 2,230 rows, 343 technique nodes and about 95 works make a graph of a few thousand edges; read-time build well under 5 seconds from the index; page set of 1 matrix page plus 343 small technique pages (or one page with embedded JSON, about 1 to 2 MB mostly quotes). Hub build time rises by seconds, not minutes. No model cost.

### CLI

`factory technique landscape [--stage S] [--layer core|all] [--evidence L] [--format table|json]`, `factory technique show T [--ego]`, `factory technique candidates [--accepted|--exploratory]` (read-only; later `link propose/decide` with the event of section 5).

### MCP (read-only first)

`technique_landscape(project, stage?, layer?, evidence?, status?)` and `technique_view(project, technique, layer?)`, both labelled, withheld and refused to pass sessions as `graph_query` is; results carry ids, counts, the lens named, and quotes read through the existing quote path. No tool writes. Writing tools come with the link event (later).

### Finders

`finder_gaps` reads evidence-schema rows or cards. Supplying the grid "technique by evidence level" or "technique by stage" from miner rows needs a third grid source in `finders.py` (a critical-adjacent change, own task, section 9 task 8, after v1). Until then the gap view is the matrix itself: empty and near-empty cells are visible, with the sentence "not found in this corpus"; it is not a finder report. "Technique and problem pairs" waits for problem nodes. `finder_contradictions` (numeric conflicts) has no use here in v1.

## 9. First slice (1 to 2 days): the derived landscape

Branch `technique-graph`. Tests are written first with each task but not run while the testing pause holds; mypy and ruff must pass. One commit each. Estimates 1 to 3 hours.

| # | Task | Files | Depends | Agent |
|---|---|---|---|---|
| 0 | Decision row "to be assigned at merge" (interpretation layer derived, exploratory, departure from 82 ruling 1 limited to derived technique groupings; `accepted` needs a human) and the glossary line; spec note in `00-system.md` only if the MCP list is enumerated there. Docs only. | `docs/decisions.md` | none | rf-builder, 1 h |
| 1 | `technique_graph.py` core: read the 8 derived miners' current pass-A rows (not superseded, `not-stated` and rejected excluded), build technique, work and evidence nodes and `uses`, `supported-by`, `earliest-in-corpus` edges; label fields; counts; lens filter (stage, layer, evidence, status); deterministic order. Read through `services/extraction.live_rows`, `services/taxonomies`, `services/work_layers`. | `services/technique_graph.py`, `model/technique_graph.py` (result models) | 0 | rf-builder, 3 h |
| 2 | `derives-from` candidates from `reused-cited` rows and resolved reference links; basis listed; stale links hidden as in the lineage views. | `services/technique_graph.py` | 1 | rf-builder, 2 h |
| 3 | Hub page: matrix, technique drill-down and ego SVG, miner agreement block, labels; write into the site build next to the taxonomy product. Measure time on a copy of the pilot. | `services/site_technique.py`, `services/site_chrome.py` entry, `site_widgets` reuse | 1, 2 | rf-builder, 3 h |
| 4 | CLI `factory technique landscape|show|candidates`, rendering. | `cli/main.py`, `cli/render.py` | 1, 2 | rf-builder, 2 h |
| 5 | MCP `technique_landscape`, `technique_view`; withheld and pass-session refusal; tool docs. | `mcp/server.py` | 1, 2 | rf-builder, 2 h |
| 6 | Skill `rf-technique-bounce` (procedure of section 7) with the labelling rule; plugin skill file. | plugin skills folder | 5 | rf-builder, 1.5 h |
| 7 | `factory check`: a finding when a landscape lens has a technique whose miner has no registered version or the technique taxonomy is empty (info), and a labelled count in `report_evidence` refusal test: no technique figure may enter a report. | `services/check.py`, evidence report test | 1 | rf-builder, 1.5 h |
| 8 (after v1) | Finders grid source: technique by stage or evidence level; `finder_gaps` accepts `rows_axis = technique`. | `services/finders.py`, `mcp/server.py` | v1 reviewed | rf-builder-critical, 3 h |
| Landing | `gen_map.py`, backlog status (built, not reviewed), one Sonnet review with guard mutation on tasks 1 and 2 (build-review lessons). Done by the lander. | `docs/MAP.md`, `docs/backlog.md` | | |

Value after tasks 0 to 5 (about 1.5 days): the stage landscape, technique pages and the two MCP reads on the real pilot, with no new event and no decision gate beyond the Proposed row.

## 10. Test list (TDD, written first)

1. A fixture with two technique taxonomies and miners and five works: nodes and `uses` edges equal the current pass-A rows; a superseded row and a `not-stated` row produce nothing.
2. Counting: the count per technique is distinct works, not rows; two rows of one work and technique count once.
3. Lens filters: stage, layer, evidence level, status each reduce the output as stated; the lens is named in the result; default layer is core.
4. Labels: every node and edge of every output carries `class = interpretation` and `state = exploratory`; a test fails if any output path omits the label (JSON, DOT, HTML, CLI, MCP).
5. `derives-from`: positive case (reused-cited, resolved link, user at the other end); negative cases: link unresolved, target does not use T, row status `core`, link stale; no edge in the other direction.
6. `earliest-in-corpus` ties are broken by work id and labelled a date rule; a work without a date is skipped and listed.
7. Determinism: two builds on the same index produce byte-identical JSON and HTML; the ego layout is stable.
8. Rebuildability: no table is written; a test fails if the module opens a write connection.
9. A `reported-failure` row shows as a separate bucket, never merged into "evidence".
10. A row without an `evidence` attribute shows "not stated", is counted in the not-stated share, and is never defaulted.
11. Agreement block shows the stage miner's all-rows and aligned-rows rates and the exploratory notice; absent agreement shows "no second pass".
12. Held-out works appear as corpus works (decision 37.9; no masking), and the tool refuses a session that has joined a pass.
13. Report exclusion: `report_evidence` and `report_prisma` output are byte-identical with and without technique rows.
14. HTML contains no external URL, script source or stylesheet link; the page is under the size cap set in the task.
15. MCP withholding (`_withheld`) and CLI/MCP parity on one fixture.

## 11. Risks

- **A fluent landscape of unreliable rows.** Agreement 0.21 to 0.61 means the counts move with the pass; the page may look more certain than it is. Mitigation: labels everywhere, agreement printed beside the stage, counts shown as "works in pass A", the prior comparison linked; no use in reports (test 13).
- **Selection and absence.** Core papers describe themselves; absence in the corpus is not absence in the field. Mitigation: the corpus definition sentence, `earliest-in-corpus` never called "origin".
- **Candidate edges misread as lineage.** A `reused-cited` row plus a cited work using the same technique may be coincidence. Mitigation: the basis is shown; edges stay candidates until accepted; the word "origin" is not used for them.
- **Technique identity.** The same technique under two stage taxonomies, or two techniques merged by a coarse category, are invisible without a judge (IDEA-53) or accepted `same-as` links. v1 shows the 8 known pairs as two nodes and says so.
- **Evidence attribute omitted** on most rows (largest bucket in the prior comparison): the evidence lens may cover a minority of rows. Shown as a share.
- **Decision 82 ruling 1.** Automatic grouping is allowed here only because the grouping is a registered taxonomy applied by a miner; a reviewer may read it as a departure; hence the decision row and the narrow wording.
- **Duplication with the taxonomy product and lifecycle page**: three technique-related views. Mitigation: the landscape links to the taxonomy version and the miner page; no figure is computed twice (it calls the same `derived_counts`).
- **Scope creep** into problems, variants, teach-back: all excluded by section 1 and moved to the later phase.
- **Cost of hub build** and page size at 343 technique pages: measured in task 3; a single-page fallback is available.
- **Pilot schedule.** The living loop may add papers and rerun the miners: the projection is rebuilt from the current rows, nothing cached.

## 12. Later phases (not this plan)

Phase 2: recorded link and problem events (section 5), a problem miner, accepted edges and the `accepted` lens, finder grid (task 8). Phase 3: contribution miner (schema, `name_item`), `idea_propose` on real data, `reuses`/`corrects` relations (IDEA-83 (d)), cross-stage identity through the IDEA-53 judge, variant nodes. Phase 4: the second-project adaptation (factory templates, part B of the comprehension plan), hypotheses engine use (cross-stage transfer candidates as builder rows for leads).

## 13. Open choices for the researcher

Q1. Relation to the lineage graph.
- A (recommended): a separate read-only product computed at read time; lineage tables untouched; its own tables only when recorded link events arrive.
- B: write derived technique nodes and edges into the layer tables (`layer_nodes`, `layer_edges`) through the projector now (projection bump).
- C: extend `graph_nodes` and `graph_edges` with technique types (touches evidence tables, constraint changes).

Q2. First version: derived only, or derived plus recorded links.
- A (recommended): derived only; accepted state, problems and identity links come in phase 2 once the first view has been used.
- B: also build the `technique_link` event family and a human accept step in the first slice (about one more day, critical modules).
- C: derived only, and the researcher marks accept or reject in a CSV outside the platform (not traceable; not recommended).

Q3. Origin.
- A (recommended): "candidate origin" from citations between users of the same technique, plus "earliest in corpus" as a date; neither called an origin until accepted.
- B: only the citation candidates, no date rule.
- C: seed origins from the prior CSV's `origin` column as exploratory text on the page (untraceable agent text, never a node).

Q4. Problems.
- A (recommended): not in v1; a problem miner or `problem.recorded` events in phase 2, with claimed versus observed.
- B: show the prior CSV's problem text as a toggle on the technique page, labelled "prior, not mined".
- C: build a problem miner first and delay the graph.

Q5. Work scope of the default lens.
- A (recommended): the core layer (95 works), widening to all layers on request, labelled.
- B: all layers by default.
- C: core plus adjacent, matching `m-release`'s layer policy.

Q6. Which rows count.
- A (recommended): pass-A rows only, with pass-B agreement shown beside; a row two passes agree on is flagged "seen in both passes" where pass B covers it.
- B: rows of both passes, deduplicated by work and technique.
- C: only rows both passes agree on (small: pass B covers 5 to 11 units per stage).

Q7. The cross-stage duplicate techniques (about 8 pairs).
- A (recommended): keep two nodes in v1 and list the pairs on the page; merge in version 2 of the taxonomies after calibration.
- B: merge them now in the landscape by a hand-written list (a judgement outside events; not recommended).
- C: show the pairs as a "same technique?" candidate edge for the researcher to decide in the later link event.

Q8. Landscape page layout.
- A (recommended): one matrix page plus per-technique pages, the ego SVG on each technique page.
- B: one single page with embedded data and tabs.
- C: matrix only in v1; technique pages and ego graph in phase 2.

Q9. Naming in the UI (the researcher doubts "technique", decision 127 C4).
- A (recommended): "Landscape" for the page, "approach" for a node in the UI, "technique" in the code and tools.
- B: "technique" everywhere.
- C: let the researcher choose after the first view.

Q10. Finder grid (task 8) timing.
- A (recommended): after the first slice has been used on the pilot.
- B: with the first slice.
- C: not built; the matrix is the gap view.
