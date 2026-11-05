# Slice 3b (G2) — Contribution extraction and the idea lineage graph

Status: **rulings adopted** · 2026-11-04 · Builds on [00-system.md](00-system.md), slices 1, 2 and 3a; must satisfy [01-rigour.md](01-rigour.md) R-01–R-05, R-13–R-15, R-37, R-40, R-43, R-44, R-46, R-47, R-51, plus the proposed requirements below. Implements sub-slice G2 of [outlines/lineage-graph.md](outlines/lineage-graph.md) (backlog IDEA-30 and IDEA-32). G1 (references, snowballing) is [slice-3a-references.md](slice-3a-references.md); G3 (interpretation and concept layer) is [slice-3c-intuition.md](slice-3c-intuition.md). Rulings marked **[adopted 2026-11-04]** adopt the outline's recommendations or fill a gap; each was Adopted 2026-11-04 (researcher's standing approval of the recommendation), keeping its recommended option. Plan G2-E records them, with the plans' own rulings, as one *Proposed* decision when the slice is built.

## Goal
Read every included paper for what it builds on, what it adds, what it reports and what it concedes, record each statement as an anchored, verified quote, and draw the result as a **lineage graph**: papers (and human-confirmed ideas) joined by `cites`, `builds-on` and `improves-on` edges, each edge traceable to a reference link or to the paper's own words. A path from a base idea through its improvements to current methods must be readable from the graph, and no edge may exist without a basis.

Pilot for acceptance: **best linear attention mechanism for vision models** — a lineage path from a base attention formulation to a current linear-attention vision backbone is read from the graph with every edge sourced.

## User flow
1. **Declare before reading (R-13, R-45):** the protocol gains a `contribution_schema` section (pack `contribution`, dual-extraction sample, audit settings). Changes are amendments with blast radius (R-14, R-15).
2. For each included work that has a current G1 reference extraction, Claude reads the work's pinned conversion through `contribution_next` / `contribution_record` and records **items** of four kinds: `base-idea`, `addition`, `result`, `limitation`. Each item carries an anchor and a verbatim quote; the platform verifies both. A paper that states no base idea is closed with a `not-stated` item; the agent does not fill the gap.
3. Dual extraction on the declared sample, field-level agreement, human resolution and audit run through the plan-D machinery (R-46, R-37).
4. Claude proposes **relations** (`relation_propose`) from items. A relation whose target the platform can resolve deterministically (the item cites a reference entry that G1 resolved) is **stated**; any other relation (target chosen by the agent, or no basis quote) is **inferred** and waits for a human.
5. The researcher confirms or rejects inferred relations and proposed **ideas** (named groupings of papers) in the CLI. Nothing the agent proposes enters default views as inferred or confirmed on its own.
6. `graph_query` and `graph_export` read the lineage: ancestors, descendants, lineage paths, papers without a stated base, improvements on a node. Default views show stated and confirmed edges only; inferred edges appear on request, labelled.
7. `trace` from any edge returns the quote, anchor, document version, retrieval attempt, work, screening decisions, protocol and question; `check` lists missing, stale and unconfirmed items.

## Rulings (adopted 2026-11-04)

Rulings 1–3 answer outline open questions 1–3; ruling 4 answers question 11; the rest are this spec's own.

1. **Idea node identity [adopted 2026-11-04].** Papers are the only evidence-bearing nodes. An `Idea` node is a named grouping of papers, created by a proposal (`idea_propose`, agent or human) and **confirmed by a human**; its `origin` is the introducing paper, its name is taken from a name stated in a verified quote. Naming variants merge by a recorded, reversible `idea.merged` (R-26 spirit). No automatic clustering. An unconfirmed idea is not drawn in default views.
2. **Contribution fields live in a generic pack [adopted 2026-11-04].** A small pack `contribution` (version 1) that any project may enable, independent of the domain pack; `ml-benchmark` keeps the result rows (comparison data). A `result` item here may reference the `row_key` of an existing `ml-benchmark` row in the same work; it never duplicates that row's values into the evidence table.
3. **Who confirms inferred edges [adopted 2026-11-04].** The reviewer of record (R-39) or a delegated human, in the CLI. An agent may propose, never confirm (R-51). Unlike the fuzzy reference links of G1 (slice-3a ruling 3), **no second-agent confirmation exists for inferred relations or ideas, in any mode**.
4. **Graph tooling [adopted 2026-11-04].** The platform provides queries and export (JSON, Graphviz DOT) only. No layout engine; rendering is a view built elsewhere (an artifact, Graphviz) from the export and is not a source.
5. **A second schema section, one machinery [adopted 2026-11-04].** `ProtocolSpec.contribution_schema: ExtractionSchema | None = None` (the plan-D type: `pack`, `pack_version`, `fields`, `comparability_keys` (empty, unused), `dual_extract_sample`, `audit_fraction`, `audit_minimum`, `claims` = false). It is amendable, hashed, and omitted from every hash while `None`, so existing `P@` ids are unchanged (slice-2 and plan-D pattern). Recording is refused until it is declared (pilot, systematic; a promotion gap in exploratory).
6. **Rows carry a pack discriminator [adopted 2026-11-04].** Contribution items are rows in the plan-D extraction event family (`extraction.pass_opened`, `extraction.recorded`, `extraction.closed`), each tagged with its scope (`evidence` or `contribution`): `extraction.recorded` through its `schema_ref`, the other events through an optional `pack` field whose absence (every event written before G2) means evidence. A session joins at most one pass across both scopes (decision 37 independence extended). Tasks, pinning, dual extraction, supersession, staleness and the audit are the plan-D services parameterised by pack; verification (`quote_in_element`, number check, anchors) is reused unchanged. Plan-E interfaces (`final_rows`, `grouped_rows`, `independence_counts`, `live_claims`) filter on the evidence schema's pack and never return a contribution row (acceptance 7). *This is the one change to plan-D code and is covered by plan G2-A.*
7. **Item kinds and the pack [adopted 2026-11-04].** Pack `contribution` v1 fields: `item_kind` (`base-idea|addition|result|limitation|not-stated`), `name` (the named method, paper or principle; check `text-in-quote`), `statement` (check `text-in-quote`, required except for `not-stated`), `cited_entry` (integer ordinal of a G1 reference entry; check: exists in the work's current reference extraction), `compared_to` (text, `text-in-quote`; for `improves`), `metric`, `value`, `unit` (numeric check as R-44, only for `result`), `result_row` (an `ml-benchmark` `row_key`, checked to exist for the work). `FieldDef` gains an optional `allowed` tuple (enumeration) and a pack-level `row_key_fields` (the fields whose canonical values, with the anchor, form the `row_key`, so dual extraction can align rows that have no cell). Any pack change is a new `pack_version`.
8. **`not-stated` [adopted 2026-11-04].** A work with no stated base idea is closed with one item `item_kind = not-stated`, `absent_kind = base-idea`, and no quote. It is accepted for `base-idea` and `limitation` only. A unit closes only when `base-idea` and `limitation` are each covered (by an item or `not-stated`) and at least one `addition` is recorded; absence of an `addition` is an unclosed unit, not a statement. A unit with no `result` item (a paper without empirical results) closes only with a recorded `reason` on `extraction.closed`. The count of `not-stated` papers is reported (computed). The platform cannot check absence; the audit sample includes `not-stated` items.
9. **Population and version [adopted 2026-11-04].** The population is the works with final outcome `INCLUDED` at the last declared stage, a pinned current conversion, and a current G1 extraction (a work without one is listed `no-references`, not silently skipped; it may be read with `cited_entry` unavailable and its edges inferred). A new document version makes the work's items stale (plan-D ruling 5); a new G1 extraction of the same document makes `cited_entry` values stale until re-verified (ruling 12).
10. **Edge types and direction [adopted 2026-11-04].** Edges point from the later work to the earlier: `A builds-on B` and `A improves-on B` mean A states its dependence on B. `cites` points from citing to cited. `improves-on` implies `builds-on` in queries (a path may use either) but both are stored separately.
11. **Stated versus inferred [adopted 2026-11-04].** An edge is `stated` when (a) its basis is a verified contribution item whose quote the platform has checked and (b) its target is resolved deterministically: the item's `cited_entry` has a G1 link that is `resolved` (identifier, title-exact or confirmed). Every other relation is `inferred`: a target chosen by the agent from the quote's words, a target with an unconfirmed link, or no basis item. An inferred edge may carry a basis quote, but it is labelled `inferred` until a human confirms it; confirmation creates a `confirmed` edge, still labelled as human-confirmed. `cites` edges have the status of their G1 link (`resolved` or `confirmed`; unconfirmed links are not drawn, matching slice-3a R-xx(b)).
12. **Staleness [adopted 2026-11-04].** A relation derived from a superseded or stale item, or whose `cited_entry` belongs to a superseded reference extraction, is `stale`: kept in the log, hidden from default views, listed by `check`. Re-recording the item (a new row) and re-proposing the relation restores it; nothing is edited.
13. **Idea proposals need a quote [adopted 2026-11-04].** `idea_propose` names a group, its origin work and members; the name must occur verbatim in a verified quote of the origin (an item `name`), checked by the platform. Members are works whose items carry the name or whose `builds-on` edges lead to the origin; the platform lists candidates, the human confirms.
14. **Default views [adopted 2026-11-04].** Counts and queries default to `stated` and `confirmed` edges; flags `include_inferred` and `include_stale` widen the view and every output row carries its status. A statistic always names the status filter it used.

## Design

### Contribution items (platform verifies, agent reads)
The agent reads the pinned conversion through `document_read` and records one row per item. The platform checks, per item (the plan-D checks, reused): the anchor resolves in the pinned conversion; the quote is verbatim in the anchored element; each text-in-quote field (`name`, `statement`, `compared_to`) occurs in the quote after the declared normalisation; a numeric `value` occurs in the quote or cell (R-44); `cited_entry` exists in the work's current G1 extraction and, when the quote contains a citation marker, the marker maps (G1 marker tables) to that entry, otherwise the item is stored with `marker: absent` and the entry is the agent's declaration, flagged. Invalid items are rejected with structured errors; valid items of the same call are written (partial acceptance as in plan D).

Items are atomic claims in the sense of R-40: one locator, one verified span, corrections supersede. Item kinds map to the pack as follows.
| Kind | Content | Typical use in the graph |
| --- | --- | --- |
| `base-idea` | What the paper says it builds on: a named method, paper or principle; optionally a cited entry | `builds-on` |
| `addition` | What the paper says it adds over that base | `improves-on` (with `compared_to`), idea naming |
| `result` | The reported improvement; numeric value with unit, optional link to an `ml-benchmark` row | numeric support of `improves-on` |
| `limitation` | A stated limitation or failure case | displayed beside the node; no edge |
Whether a statement is a *base idea* or an *addition* is the agent's reading of the paper's own sentence; the skill gives the discriminating wording rules (for example "we build on", "following", "in contrast to") and requires the quote to carry them. The platform does not classify.

**Dual extraction and audit.** Pass A and pass B run on `dual_extract_sample`, with the plan-D independence rules (sessions, models, reversed field order). Rows align on `row_key` (pack-declared fields plus anchor). Compared fields: `item_kind`, normalised `name`, `cited_entry`, canonical `value`; quote and anchor are not compared (plan-D ruling 10). Disagreements go to the human. The audit draws from agreed field values (including `not-stated` items and `cited_entry` values) with the plan-D size rule and `EXTRACTION_ERROR_CEILING`.

### Relations (agent proposes, platform classifies)
`relation_propose` takes `source_work`, `target` (a work id, or an idea id), `edge_type` (`builds-on|improves-on`), `basis_item` (the id of a live contribution row of the source work) and an optional free `note` (not evidence). The platform: verifies the basis item is live and of kind `base-idea` or `addition`; computes the target from the item's `cited_entry` through the current G1 link; sets `status = stated` when that target equals the proposed target and the link is `resolved`, else `inferred` (recording why: `no-cited-entry`, `target-differs`, `link-unconfirmed`, `no-basis`); flags `uncited-base` when no reference entry of the source work resolves to the target. Relations with no basis item are accepted only as `inferred` and must carry a `note`. A relation whose target is an idea is always `inferred` (reason `target-differs`) and its basis must be a live contribution item. The agent cannot set the status. A relation proposed twice for the same (source, target, type) is idempotent on the live relation.

`relation_decide` is a human act (CLI only): `confirm` (inferred → `confirmed`) or `reject`. Each is an event that supersedes the previous decision; a rejected relation stays in the log and is hidden. The CLI actor is recorded, and no MCP tool decides a relation, so an agent session cannot reach the decision path (R-51).

### Ideas
`idea_propose` (agent) and `idea_define` (human) create an idea proposal; `idea_decide` (human) confirms or rejects; `idea.merged` / `idea.unmerged` are reversible and record the reason. An idea's `members` are works; its `origin` is one member. Idea-level edges are derived views: idea X *builds-on* idea Y when some member of X has a stated or confirmed `builds-on` edge to a member of Y; the derivation is computed and labelled `derived`, never stored as an event.

### Graph projection (platform, deterministic)
The graph is a rebuildable projection (R-05, proposed R-xx(g)). Nodes: `paper` (work id; includes candidates and cited-only works from G1, marked `corpus` or `external`) and `idea`. Edges: `cites` (from G1 links), `builds-on`, `improves-on` (from relations), each with its event-derived base status (`stated|confirmed` for `cites`, the proposal status for relations), liveness, latest decision and `basis` (reference link id or contribution row id). The graph tables hold only event facts: corpus membership (`corpus`/`external`), staleness, idea merges and the resulting effective status (`stated|confirmed|inferred|stale|rejected`) are applied at read time by `services/lineage.py`. The projector alone writes `graph_nodes`, `graph_edges`; no table is written by services. The graph is defined as views over the projection tables; ordering is deterministic (work id, then edge type), so rebuilds produce identical rows.

**Queries (read-only, deterministic, bounded depth and size).** `ancestors(node, depth)`, `descendants(node, depth)`, `path(a, b)` (shortest by edge count over `builds-on`/`improves-on` edges in the active status filter, ties broken by work id), `no_stated_base()` (included works without a live `base-idea` stated or confirmed edge, separated into exactly one of `unextracted`, `not-stated`, `target-outside-corpus`, `no-relation`), `improvements_on(node)`, `cited_by_at_least(k)`. Results carry node and edge ids and statuses, never prose. **Export:** JSON (nodes, edges with status and basis ids) and DOT (status as edge style; inferred dashed with label). Exports contain no document text beyond the stored quotes already in events, and carry the active status filter.

### Deterministic versus agent
| Platform (deterministic, tested, offline) | Agent (Claude via MCP) |
| --- | --- |
| Verify anchors, quotes, numbers; reject non-verbatim items; compute `row_key`, agreement, audit draws | Read the paper; record base idea, addition, result, limitation with anchor and quote; declare `not-stated` |
| Resolve a relation target from `cited_entry` and the G1 link; set `stated`/`inferred`; flag `uncited-base` | Propose relations and ideas; write a note for an inferred relation |
| Project nodes and edges; run queries; derive every count and statistic; export | Never sets a status, count, hash or id |
| Enforce that agents cannot confirm; mark stale items and edges | — |
Every agent-written event carries model, skill version and `input_blob` (R-04). Interpretation text does not exist in this slice (G3); `note` fields are labelled `agent-note`, are never counted and never appear in default exports.

## Events (schema 1; names as fixed in plans G2-A–G2-C)
| Event | Payload (summary) |
| --- | --- |
| `extraction.pass_opened` / `extraction.recorded` / `extraction.closed` | plan-D events, tagged with scope `contribution` (`schema_ref` `contribution@1` on `recorded`, `pack = "contribution"` on the others); `closed` with `reason` for units without a `result` or without items |
| `relation.proposed` | `relation_id` (`rel_<ULID>`), `source_work`, `target` (work or idea id), `edge_type`, `basis_item` (row id or null), `note`, computed `status`, `status_reason`, `resolved_target`, `reference_extraction_id`, `flags`; agent provenance (R-04) |
| `relation.decided` | `relation_id`, `decision` (`confirm|reject`), `rationale`, `actor = human`; supersedes the previous decision |
| `idea.proposed` | `idea_id` (`ida_<ULID>`), `name`, `name_item` (row id of the verified quote), `origin`, `members`, provenance |
| `idea.decided` | `idea_id`, `decision` (`confirm|reject`), human |
| `idea.merged` / `idea.unmerged` | `into`, `from`, `reason`; reversible |
No event is edited. Corrections supersede (R-40). Plan-D extraction events remain the only carriers of document text (quotes).

## Index tables (projections, written only by the projector)
`contribution_items` (view over `extraction_rows` where `pack = contribution`, with the verification columns), `relations` (live row folds the latest decision; staleness is computed on read), `ideas`, `idea_members`, `graph_nodes`, `graph_edges`. `extraction_rows` gains an indexed `pack` column. The graph is views over these tables. Rebuild determinism (slice-1 AC 1) holds.

## MCP tools and CLI
| Tool | Purpose | Actor |
| --- | --- | --- |
| `contribution_next` | Serve the next (work, pass) unit with its pinned conversion and the reference entries available for `cited_entry` | agent |
| `contribution_record` | Record items (batched, partial acceptance, `finish` flag as plan-D `extract_record`) | agent |
| `relation_propose` | Propose a relation from an item | agent |
| `idea_propose` | Propose an idea with origin and members | agent |
| `graph_status` | Counts by node type, edge type and status; unextracted works (all computed) | read |
| `graph_query` | `ancestors`, `descendants`, `path`, `no_stated_base`, `improvements_on`, `cited_by_at_least`; status filter | read |
| `graph_export` | JSON or DOT text of a query result or the whole default view | read |
Pass sessions are refused `graph_*` and `relation_propose` as for plan-D agreement (decisions 37, 48). Names follow `<area>_<verb>`; mutating tools validate fully and write nothing on failure (00-system §7).
CLI: `factory contributions status|list|agreement|resolve|audit` (the plan-D commands with `--pack contribution`), `factory relations list|confirm|reject`, `factory ideas list|define|confirm|reject|merge|unmerge`, `factory graph build|status|query|export`, with `factory check` and `factory trace` extended. Services: `services/contributions.py` (a thin parameterisation of `services/extraction.py`), `services/relations.py`, `services/ideas.py`, `services/lineage.py` (projection access and queries); pure helpers in `factory/lineage/` (`classify.py` for the stated/inferred rule, `paths.py`, `export.py`). `mcp/` and `cli/` parse and format only. Skills: `rf-contributions` (reading and recording), `rf-lineage` (relations and ideas), each with a version hash.

## Check findings
`contribution-missing-extraction` (included work without a current contribution unit; warning in pilot, error in systematic) · `contribution-stale` (items pinned to a superseded document) · `contribution-schema-missing` (promotion gap) · `relation-stale` · `relation-unconfirmed` (count of inferred edges awaiting a decision; advisory) · `relation-uncited-base` · `relation-without-basis` (a stated edge with no live basis item or link: a broken-chain check, error) · `idea-unconfirmed` · `graph-extraction-missing` (work with items but no current G1 extraction) · `contribution-error-ceiling`. Messages never contain document text.

## Rigour requirements
Existing, in scope:
- **R-01, R-02:** every edge resolves to a reference link or a verified item, and through it to document, run, query and source.
- **R-04:** model, skill version and `input_blob` on every agent-written event.
- **R-05:** node, edge and `not-stated` counts and every graph statistic are derived from events.
- **R-13, R-45, R-14, R-15:** the contribution schema is declared before reading; amendments stale affected rows (plan-D ruling 12 applied to the `contribution_schema`).
- **R-26:** idea merges are recorded and reversible; an item resolving to a corpus work reuses its work id.
- **R-37, R-46:** dual extraction on the declared sample, field agreement, human audit with a stated error rate.
- **R-40, R-44:** items are atomic with verified quotes; result values pass the number check; corrections supersede.
- **R-43, R-47:** items pin one recorded document version; no literature text leaves the local library except verified quotes.
- **R-51:** the proposer never confirms.

Proposed (numbering continues slice-3a's R-xx(a)–(d); the rows are R-84 (e), R-85 (f) and R-86 (g) in 01-rigour.md):
- **R-xx(e) (proposed) Stated versus inferred relations.** An edge is `stated` (verified quote plus a deterministic target) or `inferred`; inferred edges need human confirmation, are labelled wherever shown and are excluded from default views and from every statement of fact. All modes.
- **R-xx(f) (proposed) Edge basis.** Every edge carries a basis (reference link or live contribution row) and an edge without one cannot be written; `trace` resolves any edge to the question. All modes.
- **R-xx(g) (proposed) Graph as projection.** Nodes, edges and statistics are rebuildable from events; deleting the index and rebuilding gives identical tables. All modes.

## In scope
Pack `contribution` and the `contribution_schema` protocol section · plan-D generalisation (pack discriminator, `allowed`, `row_key_fields`, filters in plan-E interfaces) · contribution recording, verification, dual extraction, agreement, audit · relations with the stated/inferred rule · ideas with human confirmation and reversible merge · graph projection, queries and export · tools, CLI, check, trace · skills `rf-contributions`, `rf-lineage`.

## Out of scope
Interpretation nodes, background-concept nodes and review states (G3); regions, labels, onion and cluster views (slice 3 proper); the portfolio-level and cross-project graph (IDEA-04); prose synthesis and related-work writing (slice 7); literature watch (slice 4); the consistency check of copied results (IDEA-23); automatic clustering of ideas; citation-function classification by the platform; bibliometric indicators and centrality as quality proxies; automatic inclusion by graph position; a layout engine; any model call by the platform.

## Acceptance criteria
1. **Schema before reading.** `contribution_record` is refused until the protocol declares `contribution_schema`; a log without it replays to identical `P@` ids.
2. **Quote verification.** An item with a non-verbatim quote or with a `name`/`statement` absent from its quote is rejected; valid items of the same call are written; no document text appears in an error.
3. **Number check.** A `result` value absent from its quote or cell is rejected; a copied value is flagged as in R-44.
4. **`not-stated`.** Accepted for `base-idea` and `limitation` without a quote, refused for `addition` and `result`; a close with no items and no reason is refused; a close without an `addition`, or without base-idea or limitation coverage, is refused; a close without a `result` needs a reason; the count is derived.
5. **Cited entry.** A `cited_entry` that does not exist in the work's current G1 extraction is rejected; a quote whose marker maps to a different entry is flagged.
6. **Dual extraction and audit.** Pass independence, row alignment on `row_key`, field agreement, human resolution and the audit draw behave as plan D with `pack = contribution`; the error rate is reported.
7. **Separation from the evidence table.** With contribution rows present, `final_rows`, `grouped_rows`, `independence_counts`, `live_claims` and the evidence report are identical to the state without them.
8. **Stated rule.** A relation whose item cites a resolved entry equal to the proposed target is `stated`; one whose target differs, whose link is unconfirmed, or with no item is `inferred`; the agent cannot set the status.
9. **Confirmation.** Only the CLI confirms or rejects; an agent session cannot; a rejection supersedes; an inferred edge is absent from default queries and exports until confirmed.
10. **Edges carry basis.** Every `builds-on`/`improves-on` edge resolves to a live item and every `cites` edge to a resolved or confirmed link; a relation with neither cannot be stored as stated.
11. **Staleness.** A new document version, a superseded item, a changed G1 extraction or an amendment that removes a field marks dependent edges `stale`; they leave default views and appear in `check`.
12. **Ideas.** A proposal whose name is not in a verified quote is rejected; an unconfirmed idea is not drawn; a merge and its reversal restore the previous graph exactly.
13. **Queries.** On a constructed graph, `ancestors`, `descendants`, `path`, `no_stated_base`, `improvements_on`, `cited_by_at_least` return the expected deterministic results and respect the status filter; results are bounded.
14. **Export.** JSON and DOT carry status and basis ids; a DOT file marks inferred edges; exports are byte-identical across rebuilds.
15. **Rebuild.** Deleting the index and rebuilding gives identical `graph_nodes` and `graph_edges` and the same state hash.
16. **Trace.** `trace` from an edge returns edge, relation, item, quote, anchor, document version, retrieval attempt, work, screening decisions, protocol and question.
17. **Check.** Each finding of the list appears in a constructed case; none carries document text.
18. **Pilot.** On the linear-attention pilot, a lineage path from a base method to a current method is readable with every edge `stated` or `confirmed`; the numbers of `not-stated`, `inferred`, `stale` and `uncited-base` items and the contribution error rate are reported.
19. **Quality.** `mypy --strict` and ruff pass; coverage ≥ 90% for `services/` and `model/`; TDD per project rule; the plan-D generalisation, the classification rule and the projection by subagent-driven development.

## Dependencies
| Slice / plan | Needed for |
| --- | --- |
| G1 ([slice-3a](slice-3a-references.md)) | `b<n>` anchors, `reference_links` (resolved/confirmed), citation contexts, work identity of cited works, candidates |
| Plan D (extraction) | Pack mechanism, verification, dual extraction, agreement, audit, supersession, staleness; generalised by plan G2-A |
| Plan C (full-text screening) | Which works are included at full text |
| Plan E (evidence report, trace) | Trace extension; separation tests extended; `final_rows` filter |
| Plans A, B (library, conversion) | Pinned conversions and anchors |

## Proposed sub-plans
| Plan | Content | Tier |
| --- | --- | --- |
| G2-A | Pack `contribution` v1, `FieldDef.allowed`, `row_key_fields`, `contribution_schema` protocol section, readiness rules and amendment staleness; the pack discriminator on plan-D events, tasks and projection; plan-E interfaces filtered by pack | critical |
| G2-B | Contribution recording: `contribution_next`/`contribution_record`, `cited_entry` check against G1, `not-stated`, dual extraction, agreement, resolution, audit; skill `rf-contributions`; CLI | critical |
| G2-C | Relations and ideas: classification rule, events, decisions, merge/unmerge, staleness, human-only confirmation; skill `rf-lineage` | critical |
| G2-D | Graph projection, queries, export, `graph_*` tools and CLI | standard |
| G2-E | `check` findings, `trace` extension, separation tests, acceptance and pilot run | standard |
G2-A to G2-C each end in a state where the earlier slices' tests pass unchanged.

## Open questions
1. **Granularity of the base idea.** One item per cited predecessor or one per sentence? Recommendation: one item per named predecessor (one `name`), so each relation has exactly one target; the skill splits sentences naming several.
2. **Works with no G1 extraction.** Read them anyway? Recommendation: yes, flagged `graph-extraction-missing`; their relations can only be inferred.
3. **Edge weights and strength.** Should `improves-on` carry the numeric gain? Recommendation: no; the gain is shown from the linked `result` item, never stored on the edge.
4. **Cross-version edges.** An edge to a work's preprint versus its published version: Recommendation: edges attach to the work id (versions are linked under R-26), and the document version is carried by the basis item.
5. **Idea scope in multi-project corpora.** Recommendation: project-local in this slice; cross-project reuse is IDEA-04.
6. **Reading cost.** Dual extraction of all items for every work may be costly. Recommendation: the declared `dual_extract_sample` (pilot default 0.3, as the evidence schema) with the audit as the bound on the error rate.
7. **Whether `limitation` items feed any statistic.** Recommendation: shown beside nodes, counted by kind, never used in selection or ranking.

## Implemented in plans G2-A to G2-E

Built as specified: pack `contribution` v1 and the `contribution_schema` section, contribution recording with dual extraction, agreement, resolution and audit, relations and ideas with the stated/inferred rule, the graph projection with bounded queries and JSON/DOT export, `check` findings and `trace` kinds `relation`, `idea`, `cites` and `quote`. MCP tools: `contribution_next`, `contribution_record`, `relation_propose`, `idea_propose`, `graph_status`, `graph_query`, `graph_export`. CLI groups: `factory contributions`, `factory relations`, `factory ideas`, `factory graph`, with `factory check` and `factory trace` extended. Skills: `rf-contributions`, `rf-lineage`. Acceptance 1–17 run in one flow in `tests/test_acceptance_lineage.py` (marked `slow`, hand-written documents, no network); 19 is the quality gate. Acceptance 18 (the linear-attention pilot) is not run: pilot steps are set aside (decision 74). Notes:
- `check` has one finding beyond the list, `contribution-closed-without-items`, and withholds `contribution-error-ceiling` from the agent view (decision 82).
- An item of a work that notices exclude from the synthesis makes its relations `stale` (reason `basis-retracted`).
- A stale row is never superseded, so `contribution-stale` names a work only while one of its units is not current.
