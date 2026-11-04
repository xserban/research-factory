# Outline — References, snowballing and the idea lineage graph

Status: **future outline, not binding** · 2026-11-04 · Backlog IDEA-30, IDEA-31, IDEA-32, IDEA-33. Becomes slice specs when scheduled; until then it constrains nothing. Earliest sensible point: after slice 2 (needs canonical Markdown with anchors, verified quotes and extraction). Researcher priority: IDEA-31 (references and snowballing) is rated **very important** and is scheduled first.

## Goal
Read every included paper for what it builds on, what it adds, what it reports and what it concedes; take its reference list into the corpus; and draw the resulting lineage as a graph in which a path from a base idea through its improvements to current methods can be read, each edge traceable to the paper's own words. A last layer carries agent-written intuition and background concepts, always labelled interpretation.

Three outputs, in dependency order:
1. A complete, resolved **reference graph** of the corpus and a recorded **snowballing** mechanism that brings missing works in through the project's screening protocol.
2. **Contribution records** per paper (base idea, addition, results, limitations), each an anchored, verified quote.
3. A **lineage graph** (papers and ideas; builds-on, improves-on, cites) and an **intuition layer** (interpretations and background-concept nodes), none of which counts as evidence.

## User flow
1. After full-text screening and conversion (slice 2), `references_extract` runs per included document version: the platform parses the reference list and in-text citation markers from the canonical Markdown, resolves each reference to a work by identifier, and records links and unresolved entries.
2. `references_status` shows counts (parsed, resolved, ambiguous, unresolved, already in corpus, new candidates) and per-format parse quality. The researcher or agent resolves ambiguous and unresolved entries by recorded decisions.
3. `snowball_round` proposes candidates (works cited by included papers and not in the corpus, with derived citation counts) and, on the researcher's go-ahead, registers a snowball run whose records enter dedup and title/abstract screening under the existing protocol. Rounds repeat until the declared stopping rule holds.
4. The agent reads each included paper and records contribution items with anchors and quotes (`contribution_record`). Platform verification rejects non-verbatim quotes.
5. The platform builds the graph projection (`graph_build`, `graph_query`). The agent proposes relations between papers (`relation_propose`); stated relations are accepted by quote verification, unstated ones become `inferred` edges that wait for a human (`relation_confirm`).
6. The agent writes interpretations and background-concept nodes (`interpretation_record`); a human reviews, rejects or supersedes them. Views and exports show interpretation visibly separate from evidence.

## Slice split (suggested order)
| Sub-slice | Content | Backlog | Why this order |
| --- | --- | --- | --- |
| G1 | Reference extraction, resolution, citation contexts, snowball rounds, reference graph projection | IDEA-31 | Highest priority; deterministic; benefits corpus completeness (R-24, R-25) before any graph exists |
| G2 | Contribution extraction (base idea, addition, results, limitations) and stated-relation edges; lineage graph projection, queries and export | IDEA-30, IDEA-32 | Needs G1 links to draw edges between corpus works and slice-2 verified quotes |
| G3 | Intuition and foundations layer: interpretation nodes, background-concept nodes, review states | IDEA-33 | Interpretation-only; meaningful only once the graph exists; lowest rigour risk if last |

G1 stands alone and may be scheduled as a late slice-2 plan (F) or an early slice-3 plan; G2 and G3 belong to slice 3 (graph) and share its graph design. Slice 3's region design (docs/01-concepts.md, background) is not binding here; the lineage graph is one projection within it and must not assume regions.

## What exists today (slice 1) and what changes
- `search_chase` (services/chase.py, model/chase.py) builds OpenAlex `cited_by:` / `cites:` queries for included works with an OpenAlex id and records a `chase.round_started` event; works without an OpenAlex id are reported as unchasable. It depends on source metadata and has no knowledge of the paper's own reference list or citation context.
- Work identity is deterministic (`rf:<surname><year>-<slug>-<hash8>`; DOI, then arXiv ID, then normalised title/first author/year; model/work_ids.py) and dedup is recorded and reversible (services/dedup*.py, R-26). Reference resolution reuses these identity rules: it never invents a second identity scheme.
- G1 **adds** a second chase mechanism (document-based) beside `search_chase`; it does not replace it. Both are supplementary searches under R-25 and both report `provenance.method = citation-chasing` with a distinguishing `via` field (`source-metadata` vs `document-reference-list`). The two sets are compared per round (references found by one and not the other), which doubles as a quality check on each.

## Design

### G1 — Reference extraction and snowballing
**Parsing (platform, deterministic).** Input is the canonical Markdown of one document version, so anchors are stable. The parser locates the bibliography section and splits it into reference entries, each with an anchor (`#s9.p12`, `#b23`), the raw entry text, and parsed fields where recoverable (authors, title, year, venue, DOI, arXiv ID, URL). In-text citation markers are matched to entries, producing **citation contexts**: (citing anchor, reference entry, marker text). Parser name and version are recorded; same document hash and parser version give the same output.

**Quality by input format.** Parse reliability differs and is recorded per document, not assumed:
| Source format (slice 2 route) | Reference structure | Expected reliability |
| --- | --- | --- |
| LaTeX source (`.bbl`/`.bib` in the e-print) | Structured, key-to-entry known | High; use bibliography files directly when present |
| arXiv HTML (LaTeXML) | `ltx_bibitem` elements with ids and in-text links | High |
| JATS XML (later, PMC) | `ref-list` with structured elements | High |
| Other HTML | Bibliography list, varying markup | Medium |
| PDF text | Reference section as flowing text; entry splitting and marker matching heuristic | Weakest; ties parsing to the plan B converter choice |
For PDF-only documents the entry count is compared with the highest in-text marker number where numeric; a mismatch is flagged `parse-incomplete`, never silently accepted.

**Resolution (platform, deterministic, recorded).** Each entry resolves to a work by ordered methods: (1) DOI or arXiv ID present in the entry; (2) match on identifiers returned by a source lookup (OpenAlex works by DOI or arXiv ID); (3) normalised title + first author + year against the corpus and against a title search of OpenAlex, accepted only above a declared similarity threshold and with a unique best match. Each link records `method`, `confidence` class (`identifier`, `title-exact`, `title-fuzzy`), the source response blob, and the version of the matcher. Resolved works absent from the corpus are created as candidates with provenance (citing work, anchor, method). Title-fuzzy links are `unconfirmed` until a human or reviewer decision confirms them; they are drawn in the graph only with that label. Unresolved entries remain listed with the raw text; counts are computed.

**Snowballing.** A snowball round is a recorded supplementary search (R-25): inputs are the included works of the previous round; direction is backward (references) and optionally forward (via `search_chase`); candidates are the resolved, not-yet-in-corpus works. The platform computes, per candidate, the number of included papers citing it (a derived number, shown but not used to include anything). Candidates enter dedup and screening exactly as any record (R-30 to R-38); nothing is auto-included. The **stopping rule** is declared in the protocol before the first round: a maximum number of rounds, or a round yielding no new included works, whichever first. Each round stores PRISMA-S fields (R-22, R-23, R-25): sources, date, reported vs retrieved counts, partial runs.

**Seeds and positives.** Snowballed works that match a positive seed's identity count towards the seed check (R-24); a seed found only by snowballing is reported as such (how it was found), because the primary search missed it.

### G2 — Contribution extraction and the lineage graph
**Contribution records.** For each included paper and document version, the agent records items of four kinds, each an atomic claim (R-40) in the slice-2 extraction schema (a separate field group in the domain pack or a generic pack; open question 2):
- `base-idea`: what the paper states it builds on (named method, paper or principle).
- `addition`: what the paper states it adds over that base.
- `result`: the reported improvement (numeric values follow the R-44 number check; comparison rows already extracted by slice 2 are referenced, not duplicated).
- `limitation`: stated limitations and failure cases.
Each item has an anchor and a verbatim quote verified by the platform (slice-2 verification); the item may name a cited reference (`base-idea` pointing at a reference entry from G1). A paper that states no base idea records `not-stated`; the agent does not fill the gap. The schema is declared in the protocol before reading (R-13, R-45); dual extraction and audit apply as for other fields (R-46, R-37).

**Nodes.**
- `Paper` node: a work in the corpus (or a candidate/cited-only work from G1), identified by work ID.
- `Idea` node: a named method family or principle. Identity is the open question 1; default recommendation below.

**Edges.** Each edge records its source and basis; the graph never draws an unsupported edge.
| Edge | Basis | Source |
| --- | --- | --- |
| `cites` | Resolved reference link (G1) | Reference link event; no judgement |
| `builds-on` | Paper states it (contribution item `base-idea`) | Verified quote |
| `improves-on` | Paper states an improvement over a named predecessor | Verified quote, plus the `result` item where numeric |
| `inferred-builds-on` / `inferred-improves-on` | Agent infers from content, not stated | No quote; interpretation provenance; requires human confirmation before it appears in default views |
`cites` edges carry the citation contexts; a `builds-on` edge whose target is not cited by the source paper is flagged `uncited-base`.

**Projection and queries.** The graph is a rebuildable projection (R-05): nodes and edges tables in the SQLite index, written only by the projector from events. Queries are read-only and deterministic: ancestors and descendants of a node, shortest lineage path between two papers, nodes without a stated base, "improvements on X", papers cited by at least k included papers. Export formats: JSON and Graphviz DOT (rendering is a view, not a source).

### G3 — Intuition and foundations layer
- **Interpretation node:** agent-written explanation of why an idea works. Fields: text (short, bounded length), target (idea or paper), supporting references (quotes or cited sources), model, skill version, `input_blob`, review state (`unreviewed`, `reviewed`, `wrong`, `superseded`).
- **Background-concept node:** a concept brought in from elsewhere (e.g. a technique from applied mathematics), with a short explanation, sources, and `uses` edges from the ideas that rely on it. A `uses` edge requires a verified quote from the paper naming the concept, or a cited source; otherwise it is `inferred` and human-confirmed like G2.
- Corrections supersede; nothing is edited. A `wrong` interpretation stays in the log and is hidden from default views.
- **Separation from evidence.** Interpretation and background nodes carry type `interpretation`; they are excluded by construction from claims counts, evidence tables, `report_evidence` frontiers, PRISMA and any statement of result. Views that show them mark them visibly (label and styling), and exports include the label.

## Deterministic vs. agent split (scripts never judge; agents never do bookkeeping)
| Platform (deterministic, tested, offline unless a recorded source lookup) | Agent (Claude via MCP) |
| --- | --- |
| Parse reference lists and in-text markers; compute entry counts and parse-quality flags | Judge ambiguous or fuzzy reference matches when asked (recorded decision with quote of both entries) |
| Resolve references by identifier, recorded method and confidence; store source blobs | Decide whether a candidate is relevant: only through screening, as for any record |
| Create candidates, run dedup, compute citation counts per candidate, snowball PRISMA-S fields, stopping rule checks | Read each paper and record base idea, addition, result, limitation with anchor and quote |
| Verify quotes and numbers (slice-2 rules); reject non-verbatim items | Propose relations between papers (stated: with quote; inferred: labelled) |
| Build and query the graph projection; derive all counts | Write interpretations and background-concept explanations |
| Enforce that interpretation never feeds evidence outputs | Never sets counts, hashes, or identifiers |
Every agent-written event carries model, skill version and `input_blob` (R-04). Interpretation nodes additionally carry review state and are subject to R-51 (the writer does not mark its own interpretation `reviewed`).

## New events (outline; names provisional)
`reference.extracted` (document version, parser, parser version, entry count, marker count, parse flags) · `reference.entry` (document version, entry anchor, raw text, parsed fields) · `reference.resolved` (entry, work ID or none, method, confidence, source blob, matcher version) · `reference.resolution_decided` (human or reviewer confirmation or rejection of a fuzzy link; supersedes) · `citation.context` (citing anchor, entry) · `snowball.round_started` (direction, source works, stopping-rule state; mirrors `chase.round_started`) · `snowball.candidate` (work, citing works, anchors) · `contribution.recorded` (work, document version, kind, anchor, quote, referenced entry, provenance) · `relation.proposed` (source, target, edge type, basis, quote or inference note, provenance) · `relation.confirmed` / `relation.rejected` (human; supersede) · `idea.defined` (name, aliases, members) · `idea.merged` (reversible, as R-26) · `interpretation.recorded` (target, text, sources, provenance, review state) · `interpretation.reviewed` (state change as a new event) · `concept.defined` (background concept, sources).
Candidates and snowballed records reuse existing `search.run` / `search.record` events, with provenance method citation-chasing.

## New index tables (rebuildable projections)
`reference_entries`, `reference_links` (entry to work, method, confidence, status), `citation_contexts`, `snowball_rounds`, `snowball_candidates`, `contributions`, `ideas`, `idea_members`, `relations` (type, basis, status), `interpretations`, `concepts`, `concept_uses`. The graph is views over these tables; no table is written except by the projector.

## MCP tools and CLI (outline)
| Tool | Purpose |
| --- | --- |
| `references_extract` | Parse and resolve references for given document versions; returns counts and flagged documents |
| `references_status` / `references_list` | Counts by format and method; unresolved and ambiguous entries |
| `reference_decide` | Record a decision on an ambiguous or fuzzy link (agent or human) |
| `snowball_round` | Plan (dry run, candidates) and register a round; validated against the protocol gate before writing |
| `contribution_next` / `contribution_record` | Serve the next paper to read; record items with quote verification (batched, partial acceptance as for slice-2 extraction) |
| `relation_propose` / `relation_confirm` | Edges with basis; human confirmation of inferred edges |
| `idea_define` / `idea_merge` | Idea nodes and their members |
| `interpretation_record` / `interpretation_review` | G3 nodes and review states |
| `graph_query` / `graph_export` | Read-only queries and DOT/JSON export |
CLI: `factory references extract|status`, `factory snowball plan|run`, `factory graph build|query|export`, `factory check` additions. Services in `platform/src/factory/services/` (`references.py`, `reference_resolve.py`, `snowball.py`, `contributions.py`, `lineage.py`, `interpretations.py`); MCP and CLI parse and format only. Skills: `rf-contributions` (reading and recording), `rf-lineage` (relations), `rf-intuition` (G3), each with a version hash.

## Rigour requirements
Existing, in scope:
- **R-01, R-02:** every reference link, candidate and edge has a chain back to a document anchor, a run and a source.
- **R-04:** model, skill version, `input_blob` on every agent-written event.
- **R-05:** reference counts, candidate counts, graph statistics derived from events.
- **R-13, R-45:** contribution schema and snowball stopping rule declared before use; changes are amendments (R-14, R-15 stale affected records).
- **R-22, R-23, R-25:** snowball rounds are separate supplementary searches with PRISMA-S fields, reported and retrieved counts, partial-run handling.
- **R-24:** seed check counts snowball-found seeds and reports the route.
- **R-26:** reference-based merges and idea merges are recorded and reversible.
- **R-30 to R-38:** snowball candidates are screened under the same rules; no auto-inclusion.
- **R-40, R-44, R-46, R-37:** contribution items are atomic claims with verified quotes, number check, dual extraction sample and audit.
- **R-43, R-47:** parsing uses recorded document versions in the local library.
- **R-51:** proposer does not review its own interpretation or inferred edge.

Proposed:
- **R-xx (proposed) Reference completeness:** per document, the parsed entry count and the count of distinct in-text markers are both stored; a mismatch is flagged and listed by `check`. Unresolved references are listed, never dropped; the counts parsed, resolved, ambiguous, unresolved sum to the entry count (computed).
- **R-xx (proposed) Link provenance:** every reference link records method, confidence class, matcher version and the source response; fuzzy links need confirmation before they feed candidates or the graph without a label.
- **R-xx (proposed) Snowball discipline:** snowballing rounds, direction and stopping rule are declared in the protocol; a candidate is never included without screening; the count of rounds and yield per round are reported.
- **R-xx (proposed) Stated vs inferred relations:** an edge is `stated` (verified quote) or `inferred` (human-confirmed, labelled); inferred edges never appear in default views or counts as stated.
- **R-xx (proposed) Interpretation is not evidence:** nodes of type `interpretation` and background-concept explanations carry provenance and review state, are excluded from every evidence output by construction, and are labelled wherever shown; a test fails if any evidence report reads them.
- **R-xx (proposed) Graph as projection:** the graph and its statistics are rebuildable from events; deleting the index and rebuilding gives identical edges.

## Acceptance criteria
1. **Parse record:** every included document version with a reference section has a `reference.extracted` event with parser and version; same document hash and parser version give identical entries and anchors.
2. **Format coverage:** a fixed test set includes at least one document per format (LaTeX/bbl, LaTeXML HTML, other HTML, PDF); parse results are scored against hand-checked reference lists; the PDF path states its measured entry recall and is flagged when below a declared floor.
3. **Resolution record:** each entry has a link or an explicit unresolved status; resolution counts sum to the entry count; each link has method, confidence and source blob.
4. **Identity reuse:** a reference resolving to an existing corpus work yields that work's ID; one resolving to a known work with a different identifier form (DOI vs arXiv) does not create a duplicate (R-26 tests).
5. **Fuzzy links:** a title-fuzzy link below the threshold or with two near-equal matches is left ambiguous and appears in `references_status`; no edge is drawn from an unconfirmed link without its label.
6. **Snowball round:** a round writes its definition before any query; candidates are never included without screening decisions; the stopping rule from the protocol is checked and refusals write nothing; PRISMA-S fields present.
7. **Comparison with `search_chase`:** for a round on the same included works, the report lists references found by one mechanism only.
8. **Contribution quotes:** an item with a non-verbatim quote is rejected; valid items in the same batch are recorded; `not-stated` is accepted for a missing base idea.
9. **Schema before reading:** contribution recording is refused until the protocol declares the schema.
10. **Edges carry basis:** every `builds-on`/`improves-on` edge resolves to a verified quote; every `cites` edge to a reference link; an edge without basis cannot be written.
11. **Inferred edges:** invisible in default queries until confirmed; confirmation is a human event; rejection supersedes.
12. **Rebuild identity:** deleting the SQLite index and rebuilding yields identical node and edge tables.
13. **Interpretation separation:** a test fails if any report, claim count, evidence frontier or PRISMA number reads an `interpretation` node; interpretations carry model, skill version and `input_blob`; review states are events.
14. **Trace:** `trace` from a graph edge returns edge, quote, anchor, document version, retrieval attempt, work, screening decisions, protocol, question; from an interpretation returns its sources and provenance.
15. **Check:** `check` lists missing reference extractions for included documents, unresolved counts above a declared ceiling, unconfirmed links in use, and stale contributions after an amendment.
16. **Pilot run:** on the linear-attention pilot, snowballing from the included works runs at least one round; the number of candidates found by reference lists and not by `search_chase` (and vice versa) is reported; a lineage path from a base method to a current method is readable with every edge sourced.
17. **Quality:** `mypy --strict` and ruff pass; coverage ≥ 90% for `services/` and `model/`; TDD per project rule; core modules (reference resolution, graph projection) by subagent-driven development.

## Dependencies on slice 2
| Slice-2 plan | Needed for | Note |
| --- | --- | --- |
| A (acquisition, library) | Document versions, raw sources, researcher-supplied files | G1 parses the latest version only (version rule); a new version supersedes link sets |
| B (Markdown conversion, anchors) | Reference-list parsing and citation contexts | **Parsing quality depends on the converter per format**: LaTeX (`.bbl`) and LaTeXML HTML preserve bibliography structure; other HTML medium; PDF reference sections weakest. G1 should be planned after the bake-off result (decision 47) and its pilot re-check, and should read converter output structure (e.g. bibliography element anchors) rather than re-parse raw formats. Consider asking plan B to emit a `#b<n>` anchor per bibliography entry. |
| C (full-text screening) | Which papers are included | Reuses `final_outcomes` as `chase_sources` does |
| D (schema, extraction, verification) | Contribution items, quote and number verification, dual extraction, audit | G2 is an extension of the extraction schema (separate field group) |
| E (evidence report, trace) | Trace extension; separation from evidence outputs | G3 exclusion tests extend report tests |

## Out of scope
Prose synthesis and related-work writing (slice 7); regions, labels, onion and cluster views (slice 3 proper); the portfolio-level and cross-project graph (IDEA-04); literature watch and living updates (slice 4, IDEA-02); consistency check of copied results against the cited paper (IDEA-23); automatic inclusion by citation count or centrality; any model call by the platform (parsing, resolution and graph building are rule-based); citation-function classification by the platform; sentiment of citations; bibliometric indicators (h-index, centrality as quality proxies); full-text acquisition for candidates beyond what slice 2 already does after they are included.

## Open questions (with recommendations)
1. **Node identity of an idea.** A method family or a paper? Recommendation: papers are the only evidence-bearing nodes; an `Idea` node is a named, human-confirmed grouping of papers (the paper that introduced it is its `origin`), created by `idea_define` from the paper's stated name. Aliases merge by recorded, reversible `idea.merged`. No automatic clustering in the first version.
2. **Where contribution fields live.** In the `ml-benchmark` pack or a generic pack? Recommendation: a small **generic `contribution` pack** (four item kinds) that every project can enable, independent of domain pack; domain packs keep result rows.
3. **Who confirms inferred edges and fuzzy reference links.** Recommendation: the reviewer of record (R-39) or a delegated human; an agent may propose, never confirm (R-51). Pilot mode may allow a second agent in a fresh context to confirm fuzzy reference links only (not inferred relations), recorded as such.
4. **Source of background-concept explanations.** Recommendation: the researcher supplies or approves the first source (textbook, survey) for each concept; the agent drafts text from it with quotes; concept nodes without an approved source stay `unreviewed` and are hidden from default views.
5. **PDF reference parsing quality.** Accept weak parsing or improve? Recommendation: ship G1 with the recorded quality flags, prefer the LaTeX/HTML routes for included works when available (route preference does not change, only the use of a second route purely to obtain a bibliography: allow `bbl` retrieval as a separate document role), and measure PDF recall in acceptance criterion 2 before deciding on a layout-model parser such as GROBID (offline, fixed model, as decision 47 allows).
6. **Snowball stopping rule.** Recommendation: declare in the protocol a maximum of two backward rounds and one forward round for `pilot`, stop earlier when a round yields no new included work; `systematic` mode requires an explicit rule and a reported yield per round.
7. **Ranking candidates.** Recommendation: show the derived count of citing included papers and sort by it, without any threshold; screening does the selection. A threshold would be an undeclared truncation (R-21 spirit).
8. **Does a candidate found by a reference list but absent from OpenAlex still enter?** Recommendation: yes, as a `grey`-typed or `other` work identified by normalised title/first author/year with raw reference text as provenance, flagged `no-source-record`; fetch route is researcher-supplied only.
9. **Citation context storage.** Store the sentence around the marker? Recommendation: store only the anchor and marker; the text is read through `document_read`. This avoids copying literature text into git events (storage decision, local library); quotes already stored for contributions remain.
10. **Forward chasing.** Does G1 extend `search_chase`'s forward direction? Recommendation: no; forward remains source-metadata based because a document cannot list its citers. Both directions share the round and stopping-rule logic.
11. **Graph layout and tooling.** Recommendation: no layout engine in the platform; export DOT/JSON and render in artifacts or external tools; the platform provides queries only.
12. **Reuse of the old repo.** `docs/09-existing-assets.md` should be checked before G1 for any reference-parsing code worth porting with tests (CLAUDE.md reuse rule); none is assumed.

## Methodological references (from memory; verify before formal use)
- Wohlin C. Guidelines for snowballing in systematic literature studies and a replication in software engineering. *EASE 2014*.
- Greenhalgh T, Peacock R. Effectiveness and efficiency of search methods in systematic reviews of complex evidence: audit of primary sources. *BMJ* 2005;331:1064–1065.
- Hirt J, et al. Citation tracking for systematic literature searching: a scoping review. *Research Synthesis Methods* 2023.
- Rethlefsen ML, et al. PRISMA-S: an extension to the PRISMA statement for reporting literature searches in systematic reviews. *Systematic Reviews* 2021;10:39.
- Lopez P. GROBID: combining automatic bibliographic data recognition and term extraction for scholarship publications. *ECDL 2009* (reference parsing tool; candidate for the PDF path).
- Cochrane Handbook, chapter 4: searching by checking reference lists and citation searching.
