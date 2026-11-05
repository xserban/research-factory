# Slice 3c (G3) — Intuition and foundations layer

Status: **rulings adopted** · 2026-11-04 · Builds on [00-system.md](00-system.md), slices 1, 2, 3a and 3b; must satisfy [01-rigour.md](01-rigour.md) R-01, R-02, R-04, R-05, R-40, R-43, R-47, R-51, plus the proposed requirements below. Implements sub-slice G3 of [outlines/lineage-graph.md](outlines/lineage-graph.md) (backlog IDEA-33). G1 is [slice-3a-references.md](slice-3a-references.md); G2 (contributions, lineage graph) is [slice-3b-lineage.md](slice-3b-lineage.md) and is a prerequisite. Rulings marked **[adopted 2026-11-04]** adopt the outline's recommendations or fill a gap; each was Adopted 2026-11-04 (researcher's standing approval of the recommendation), keeping its recommended option. Two controller rulings of the same date tighten the outline: layer rows live in their own tables, never in G2's graph tables (ruling 3), and agent-drafted concept text is reviewed by a human (`concept.reviewed`, ruling 2). Plan G3-C records all rulings as one *Proposed* decision when the slice is built.

## Goal
Add to the lineage graph a layer that explains **why** an idea works and **which foundations it rests on**, without ever letting that explanation pass for evidence. The layer has two node classes: **interpretation** nodes (an agent- or human-written explanation attached to an idea or paper) and **background-concept** nodes (a concept brought in from elsewhere, with a short explanation, an approved source and `uses` edges from the ideas that rely on it). Everything in the layer is labelled *interpretation*, carries provenance and a review state, and is excluded by construction from every count, evidence table, frontier, PRISMA figure and statement of result.

Pilot for acceptance: **best linear attention mechanism for vision models** — for at least one idea in the lineage (for example a kernel-feature approximation of softmax attention) an interpretation and a background-concept node with `uses` edges are recorded, reviewed by the researcher, and shown in the export visibly separate from the evidence layer.

## User flow
1. The lineage graph of G2 exists (confirmed ideas, stated and confirmed edges). `intuition_next` serves the next idea or paper node that has no live interpretation, together with the contribution items and verified quotes of its member papers.
2. Claude drafts an interpretation (`interpretation_record`): a short text, one target, and between one and five **sources**, each either a verified quote from a corpus paper (anchor and verbatim span) or a cited source (a reference entry or work in the corpus). A text with no source is refused.
3. When a paper brings in an outside idea, Claude proposes a **concept** (`concept_propose`) and a `uses` link (`concept_link`). The researcher supplies or approves the first source of each concept (textbook, survey, corpus paper) in the CLI; Claude drafts the concept's explanation from that source, with quotes.
4. A `uses` link is **stated** when a verified quote of the citing paper contains the concept's name or a recorded alias, or the paper cites the concept's approved source; otherwise it is **inferred** and waits for a human (as G2).
5. The researcher reviews in the CLI: marks an interpretation or a concept definition `reviewed` or `wrong`, writes a replacement (`supersede`), or approves a concept's source. Every state change is a new event; nothing is edited or deleted.
6. `graph_query` and `graph_export` take a `layer` filter. The default view is the evidence layer only; the interpretation layer is opt-in, and when shown every node and edge of it carries the label `interpretation` and its review state.
7. `trace` from an interpretation or concept returns its sources, provenance and review history; `check` lists unreviewed items, stale sources and concepts without an approved source.

## Rulings (adopted 2026-11-04)

Rulings 1–2 answer outline open questions 3 and 4; the rest are this spec's own.

1. **Who confirms inferred `uses` links [adopted 2026-11-04].** The reviewer of record or a delegated human, in the CLI. An agent proposes, never confirms (R-51); no second-agent confirmation exists in any mode (as slice-3b ruling 3).
2. **Concept sources [adopted 2026-11-04].** The researcher supplies or approves the first source for each concept (a textbook, survey or corpus paper, given as citation text and, when in the corpus, a work id). A concept without an approved source stays `unreviewed` and is **hidden from default views**, including the interpretation layer's view. The agent drafts the concept's text from the approved source, with quotes; the researcher may write the first version instead (a human-authored node, `author = human`). Every concept definition, agent- or human-written, takes the review path of interpretations: a human records `concept.reviewed` (`reviewed` or `wrong`) with the states, writer rule and self-review flag of rulings 6 and 8; a redefinition returns the concept to `unreviewed`.
3. **Node classes [adopted 2026-11-04].** Nodes have a `class`: `evidence` (paper, idea) or `interpretation` (interpretation node, concept node). Edges incident to a node of class `interpretation` (`explains`, `uses`) have class `interpretation`, whatever the status of their basis. Layer nodes and edges are stored in the layer's own projection tables (`layer_nodes`, `layer_edges`); G2's `graph_nodes` and `graph_edges` are not altered and hold evidence rows only, so the separation does not rest on a class filter. A `uses` link whose basis is a verified quote is *stated* as to what the paper says; it remains a graph relation, not a result.
4. **Interpretation shape [adopted 2026-11-04].** `text` ≤ 600 characters (`INTERPRETATION_MAX_CHARS`), one target (idea or paper node), 1 to 5 sources, each with a `role` (`supports` or `background`). Short and source-bound makes an explanation checkable by the reviewer; the platform checks length, targets and quotes, not whether the text is correct.
5. **Sources are mandatory [adopted 2026-11-04].** An interpretation without at least one source is refused. A speculation the agent cannot ground is not recorded in the project; it belongs in the session or in `docs/backlog.md`.
6. **Review states [adopted 2026-11-04].** Live state is computed from events: `unreviewed` (default), `reviewed`, `wrong`, `superseded`. Only a human sets `reviewed` or `wrong`; `superseded` is set by the platform when a new interpretation names the earlier one in `supersedes`. The writer of an interpretation never reviews it (R-51); a human who wrote an interpretation cannot review it either, and a second human or the reviewer of record does. A reviewed interpretation can later be marked `wrong`; the history keeps every state.
7. **Default visibility [adopted 2026-11-04].** In the interpretation layer, `unreviewed` and `reviewed` interpretations are shown (unreviewed ones with the label `unreviewed interpretation`); `wrong` and `superseded` ones are hidden but remain in the log and in `interpretation_history`. Concept nodes without an approved source, merged concepts and concepts reviewed `wrong` are hidden (ruling 2); an approved concept whose definition is `unreviewed` is shown with the label `unreviewed interpretation`. Hidden items are counted and the count is reported by every view.
8. **Human authorship [adopted 2026-11-04].** A human may write an interpretation or concept text (`author = human`, no model fields); it takes the same review path, reviewed by a different human where more than one exists, otherwise by the same human with the flag `self-reviewed` (reported, since R-51 cannot be met with one person). Humans are distinguished by `actor.user`.
9. **Stale sources [adopted 2026-11-04].** When a source quote's document version is superseded, the interpretation keeps its review state and gains the flag `source-stale`, listed by `check`; the reviewer re-reviews or supersedes. Nothing is changed automatically.
10. **Concept identity [adopted 2026-11-04].** A concept is identified by its name and aliases (case-folded); two concepts merge by a recorded, reversible `concept.merged`. No automatic detection of synonyms.
11. **Exports [adopted 2026-11-04].** Default exports exclude the layer. With `--with-interpretation` the export includes it, with `class`, `label` and `review_state` on every node and edge, a distinct DOT style (dashed, labelled "interpretation") and a header line stating that the layer is not evidence.

## Design

### Node and edge types
| Type | Class | Content | Basis |
| --- | --- | --- | --- |
| `interpretation` | interpretation | `text`, `target`, `sources`, `author`, provenance, review state | none (it is the agent's reading); sources are quotes or citations |
| `concept` | interpretation | `name`, `aliases`, `text`, `source` (approved), provenance, source state, review state of the live definition | the approved source |
| `explains` (edge) | interpretation | interpretation → idea or paper | the interpretation itself |
| `uses` (edge) | interpretation | idea or paper → concept | `stated` (verified quote with the name/alias, or citation of the approved source) or `inferred` (human-confirmed), as G2 |
| `explained-by` | — | derived view of `explains`; not stored | — |
The evidence layer (G2) is untouched. A concept node may link to other concepts by `uses` (a foundation resting on a foundation); cycles are refused at write time.

### Interpretations
An interpretation is recorded once, immutable. Its sources are verified by the platform: each quote source resolves to an anchor in a pinned conversion of a corpus work and is verbatim (the slice-2 check); each cited-source reference resolves to a G1 reference link or a work id. The platform checks the text length, that the target exists and is `evidence` class, and that sources are not empty. It does not judge whether the text follows from the sources. The input the agent saw (contribution items, quotes, concept sources) is stored as `input_blob` so the reviewer can see exactly what the writer had (R-04).

**Human review.** The researcher uses `factory interpretations list --state unreviewed` to see each item with its text, sources (quote and anchor), the writer's identity and the inputs. Actions: `review --reviewed` (with an optional note), `review --wrong --note` (the note is required for `wrong`), `supersede --text` (writes a human-authored replacement that names the earlier one, which becomes `superseded`), `history` (all events). Rejecting (`wrong`) never deletes; a `wrong` interpretation remains traceable and is excluded from every default view and export.

### Concepts
A concept is proposed with a name and a first source (or without one). `concept_source_approve` (CLI) records the approved source. `concept_propose` by the agent with a source supplied by the agent leaves the concept `unreviewed` and hidden until a human approves that source or replaces it. A concept's explanation text is bounded as an interpretation (≤ 600 characters) and cites quotes from its source. A human reviews each definition (`factory concepts review --reviewed|--wrong`), as for interpretations; approving the source and reviewing the text are separate acts. `uses` links are proposed by `concept_link`; the platform decides stated/inferred by the rule above (name or alias in a verified quote; or a citation of the approved source in the citing paper's reference extraction). Corrections supersede.

### Separation from evidence (enforced by construction)
1. **Separate storage.** `interpretations`, `concepts`, `concept_uses`, `layer_nodes`, `layer_edges` are their own projection tables; no evidence table (G2's graph tables included) has a row or column for a layer item.
2. **Separate code paths.** `services/interpretations.py` is imported only by the MCP/CLI wiring, `lineage.py` (for the layer filter) and `check`/`trace`. Evidence services (`extraction_agreement`, the evidence report, claims, PRISMA, `report_methods`) do not import it. An architecture test fails on any such import (AST scan).
3. **Differential test.** A fixture project is built twice, with and without a populated layer; every evidence output (`final_rows`, groups, frontiers, `live_claims`, PRISMA counts, `search_report`, `report_methods` counts) is byte-identical.
4. **Statistics.** `graph_status` reports layer counts separately (`evidence`, `interpretation`) and never a total.
5. **Labels.** Every view, export and `trace` output that includes the layer prints the class and review state.

### Deterministic versus agent
| Platform (deterministic, tested, offline) | Agent (Claude via MCP) |
| --- | --- |
| Verify quote sources and citations; check length, target, non-empty sources; classify `uses` stated/inferred; compute review state, hidden counts and statistics; project; export with labels | Draft interpretation text and concept text from the given sources; propose concepts and `uses` links |
| Enforce that agents cannot review, approve sources or confirm links; mark stale sources | Never sets a review state, status, count, hash or identifier |
| Keep the layer out of every evidence output | — |
Every agent-written event carries model, skill version and `input_blob` (R-04).

## Events (schema 1; names as fixed in plans G3-A–G3-B)
| Event | Payload (summary) |
| --- | --- |
| `interpretation.recorded` | `interpretation_id` (`int_<ULID>`), `target` (idea or paper node), `text`, `sources` (role, kind `quote|citation`, work, anchor, quote, document version, or reference link id), `author` (`agent|human`), `supersedes` (optional), provenance (model, skill version, `input_blob`) |
| `interpretation.reviewed` | `interpretation_id`, `state` (`reviewed|wrong`), `note`, `reviewer` (human), `self_reviewed` flag; supersedes the previous review |
| `concept.defined` | `concept_id` (`cpt_<ULID>`), `name`, `aliases`, `text`, `source` (kind `textbook|survey|corpus-paper|other`, citation text, optional work id, `approved` = false), `author`, provenance, `supersedes` |
| `concept.source_decided` | `concept_id`, `decision` (`approve|reject`), `source`, `reviewer` (human) |
| `concept.reviewed` | `concept_id`, `definition` (event id of the reviewed definition), `state` (`reviewed|wrong`), `note`, `reviewer` (human), `self_reviewed` flag; supersedes the previous review |
| `concept.link_proposed` | `link_id` (`cul_<ULID>`), `from` (idea, paper or concept), `concept_id`, `basis` (quote with anchor, or citation), computed `status` (`stated|inferred`) and `status_reason`, provenance |
| `concept.link_decided` | `link_id`, `decision` (`confirm|reject`), human |
| `concept.merged` / `concept.unmerged` | `into`, `from`, `reason`; reversible |
No event is edited or deleted; review, approval and supersession are new events.

## Index tables (projections, written only by the projector)
`interpretations` (live row with the review state folded from events), `interpretation_sources`, `concepts`, `concept_aliases`, `concept_reviews`, `concept_uses`, `layer_nodes`, `layer_edges` (layer graph rows with `class` and `review_state`), `layer_hidden` (counts). G2's `graph_nodes` and `graph_edges` are unchanged. Rebuild determinism holds.

## MCP tools and CLI
| Tool | Purpose | Actor |
| --- | --- | --- |
| `intuition_next` | Serve the next idea or paper node without a live interpretation, with items and quotes | agent |
| `interpretation_record` | Record an interpretation with sources; validated fully, nothing written on failure | agent |
| `concept_propose` | Define a concept (optionally with a proposed source) | agent |
| `concept_link` | Propose a `uses` link | agent |
| `interpretation_list` | List interpretations by target, state and class (read; labelled) | read |
No MCP tool reviews an interpretation or a concept, approves a source or decides a link. Pass sessions are refused all five (decisions 37, 48); `graph_query`/`graph_export` of G2 gain the `layer` parameter.
CLI: `factory interpretations list|show|review|supersede|history|write`, `factory concepts list|define|source|approve|reject-source|review|history|merge|unmerge`, `factory concept-links list|confirm|reject`, `factory graph export --with-interpretation`, with `check` and `trace` extended. Services: `services/interpretations.py`, `services/concepts.py`; pure helpers in `factory/intuition/` (`classify.py` for `uses`, `validate.py`). `mcp/` and `cli/` parse and format only. Skill: `rf-intuition` (drafting from sources, short and quoted), with a version hash.

## Check findings
`interpretation-unreviewed` (count, advisory in pilot; error above a declared ceiling in systematic) · `concept-unreviewed` (approved concepts whose live definition is unreviewed; severities as `interpretation-unreviewed`) · `interpretation-source-stale` · `interpretation-self-reviewed` (interpretations and concepts) · `concept-source-missing` (concept without an approved source) · `concept-link-unconfirmed` · `layer-leak` (a broken-boundary check: an evidence output referencing a layer id; error, all modes) · `concept-cycle`. Messages never contain document text.

## Rigour requirements
Existing, in scope:
- **R-01, R-02:** every interpretation and `uses` link has a chain to anchors and documents (its sources) and to the run that retrieved them.
- **R-04:** model, skill version and `input_blob` on every agent-written event.
- **R-05:** layer counts, hidden counts and review statistics are derived.
- **R-40:** quote sources are verified spans; corrections supersede, never edit.
- **R-43, R-47:** sources pin a recorded document version; literature text outside verified quotes stays in the local library.
- **R-51:** the writer never reviews, approves or confirms its own output.

Proposed (numbering continues slice-3b's R-xx(e)–(g)):
- **R-xx(h) (proposed) Interpretation is not evidence.** Nodes of class `interpretation` (interpretations and background concepts) carry provenance and a review state, are excluded from every evidence output by construction, and are labelled wherever shown; an architecture test and a differential test fail if any evidence output reads them. All modes.
- **R-xx(i) (proposed) Reviewable interpretation.** An interpretation is source-bound, length-bounded and immutable; review state, supersession and rejection are events; `wrong` items are hidden from default views and never deleted. All modes.
- **R-xx(j) (proposed) Concept sources.** A background concept has a researcher-approved source before it appears in a default view; links to it are stated (verified quote or citation) or human-confirmed. All modes.

## In scope
Interpretation and concept events, services, projections · source verification for quotes and citations · `uses` classification and human confirmation · review lifecycle and human authorship · layer filter and labelled export · the separation tests · tools, CLI, check, trace · skill `rf-intuition`.

## Out of scope
Prose synthesis and explanation text in reports (slice 7); automatic discovery of foundations by the platform; automatic synonym merging of concepts; a shared concept graph across projects (IDEA-04); judging an interpretation's truth by the platform; literature acquisition for concept sources beyond slice 2 (researcher-supplied sources are recorded as citation text; supplying their full text goes through slice 2); regions and onion views (slice 3 proper); any model call by the platform.

## Acceptance criteria
1. **Provenance.** Every `interpretation.recorded`, `concept.defined`, `concept.link_proposed` by an agent carries model, skill version and `input_blob`; a human-authored one carries `author = human` and the CLI actor.
2. **Validation.** An interpretation with no sources, text over 600 characters, an unknown target, a non-verbatim quote or an unresolvable citation is refused; nothing is written; no document text in the error.
3. **Review events.** `reviewed`, `wrong` and `superseded` are produced only by human CLI events or by the platform on supersession; the live state is the fold; the history lists all events; a repeated review supersedes the previous one. The same holds for concept definitions (`concept.reviewed`).
4. **Writer cannot review.** An agent session cannot reach any review, approval or confirmation path; a human who wrote an interpretation is flagged `self-reviewed` when no one else reviews it.
5. **Default visibility.** `wrong`, `superseded` and source-less concepts are absent from default views and counted as hidden; unreviewed items appear only with the label.
6. **Concept sources and review.** A concept stays hidden until `concept.source_decided = approve`; `concept_propose` cannot approve its own source; an approved concept is shown labelled `unreviewed` until a human records `concept.reviewed`, and is hidden when reviewed `wrong`; no agent reaches `concept.reviewed`.
7. **`uses` rule.** A link whose quote contains the concept's name or alias is `stated`; a link citing the approved source is `stated`; any other is `inferred` and absent from default queries until confirmed; a cycle is refused.
8. **Separation.** The architecture test finds no import of the layer modules in evidence services; the differential test shows byte-identical evidence outputs with and without a populated layer; `graph_status` prints layer counts separately.
9. **Labels and export.** Every layer node and edge in a query, `trace` or export has `class = interpretation` and its review state; default exports exclude the layer; `--with-interpretation` includes it, labelled.
10. **Stale sources.** A superseded document version flags dependent interpretations `source-stale` without changing their review state.
11. **Merge.** A concept merge and its reversal restore the previous projection exactly.
12. **Rebuild.** Deleting the index and rebuilding gives identical layer tables and the same state hash.
13. **Trace.** `trace` from an interpretation returns text, sources (quote, anchor, document version, work), provenance and the review history; from a concept, its approved source and `uses` links.
14. **Check.** Each finding of the list appears in a constructed case; `layer-leak` fires when a test fixture makes an evidence output reference a layer id.
15. **Pilot.** The pilot records at least one interpretation and one concept with `uses` edges; the researcher reviews them in the CLI; the export shows them separate from the evidence layer; counts of unreviewed, reviewed, wrong, superseded and hidden items are reported.
16. **Quality.** `mypy --strict` and ruff pass; coverage ≥ 90% for `services/` and `model/`; TDD per project rule; the separation tests and the review lifecycle by subagent-driven development.

## Dependencies
| Slice / plan | Needed for |
| --- | --- |
| G2 ([slice-3b](slice-3b-lineage.md)) | Idea and paper nodes, graph projection, `graph_query`/`graph_export`, the stated/inferred classification pattern, contribution items as inputs |
| G1 ([slice-3a](slice-3a-references.md)) | Reference links for citation sources and for `uses` links by citation |
| Plan D (extraction) | Quote verification primitives (`quote_in_element`) and anchor resolution |
| Plan E (evidence report, trace) | The evidence outputs the separation tests guard; trace extension |
| Plans A, B | Pinned conversions and anchors |

## Proposed sub-plans
| Plan | Content | Tier |
| --- | --- | --- |
| G3-A | Interpretation model, events, validation (sources, length, targets), projection, review lifecycle and human authorship, labels; the separation tests (architecture and differential); skill `rf-intuition` (interpretations) | critical |
| G3-B | Concepts: definition, approved sources, `uses` links with the stated/inferred rule, human confirmation, merge/unmerge, cycle refusal | critical |
| G3-C | `layer` filter in `graph_query`/`graph_export`, labelled DOT/JSON, `check` and `trace` extensions, CLI review commands, acceptance and pilot run | standard |

## Open questions
1. **Second-agent critique.** Should a fresh-context agent be allowed to record a non-binding critique of an interpretation, shown to the reviewer? Recommendation: not in this slice; the reviewer sees the sources and the writer's inputs, which is the check R-51 requires. Revisit after the pilot's review burden is known.
2. **Reviewing at scale.** A graph of hundreds of ideas yields many interpretations. Recommendation: interpretations are written on demand (`intuition_next` serves targets the researcher selects by a node list or a depth from a chosen node), not for every node by default.
3. **Concept sources without full text.** A textbook source cannot be quoted by the platform (no document in the library). Recommendation: such a concept is allowed with citation text only, labelled `unverifiable-source`; its text may not contain quotes, and the reviewer is told.
4. **Human-authored concept text as seed.** Recommendation: allowed and encouraged for the first concepts of a project (ruling 2); the agent then adds links, not text.
5. **Interpretation length.** Whether 600 characters suffices. Recommendation: keep as a platform constant, adjust after the pilot; a longer text is a sign it should be several linked interpretations.
6. **Wording of the label.** Recommendation: `interpretation` for the class (as the backlog), with the review state as a second token (`interpretation · unreviewed`).

## Implemented in plans G3-A to G3-C

Built as specified. Interpretations and background concepts have their own events, tables (`interpretations`, `concepts`, `layer_nodes`, `layer_edges` and their satellites) and services (`interpretations`, `concepts`, `layer_view`, `layer_check`, `layer_trace`); G2's graph tables are neither read nor written by the layer. MCP tools: `intuition_next`, `interpretation_record`, `interpretation_list`, `concept_propose`, `concept_link`; the optional `layer` parameter (`evidence`, the default, or `all`) of `graph_query`, `graph_export`, `graph_status` and `trace`. CLI: `factory interpretations list|show|history|review|supersede|write`, `factory concepts list|show|history|define|source|approve|reject-source|review|merge|unmerge`, `factory concept-links list|confirm|reject`, and `--with-interpretation` on `factory graph status|query|export` and `factory trace`. Skill `rf-intuition`.

- The `layer` filter attaches the layer as a separate part (`layer` in a query result and in the status; `interpretation` beside `evidence` in a JSON export, a labelled cluster in DOT) and never edits the evidence nodes and edges. A result without it is byte-identical to the same result of a project with no layer (acceptance 8). The layer part is read by SQL pages (`iter_layer_nodes`, `iter_layer_edges`), so a whole-view export streams.
- `check` has the findings `interpretation-unreviewed` and `concept-unreviewed` (error in `systematic` above `INTERPRETATION_UNREVIEWED_CEILING = 0`), `interpretation-source-stale`, `interpretation-self-reviewed`, `concept-source-missing`, `concept-link-unconfirmed`, `layer-leak`, `concept-cycle`, and one beyond the list, `layer-review-dropped` (a review the fold did not count: a non-human, or the session that wrote the item). The leak scan runs only when the project has a layer.
- `trace` has the kinds `interpretation`, `concept` and `concept_link`, placed last in the chain order so that G2's pinned order is unchanged. The layer items an anchor, work or idea carries are added only with `layer = all`, so a trace of an evidence node is unchanged by the layer by default.
- Acceptance 15 (the pilot) is not run (decision 74).
