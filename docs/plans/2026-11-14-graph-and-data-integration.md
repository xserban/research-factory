# Graph and data integration: new papers, miners, citations and what is shared between projects (plan, 2026-11-14)

Status: plan only, written unattended overnight (lane E, item E3); nothing built, nothing run, no decision applied. Builds on slices 3a to 3d (references, lineage, intuition, regions), 4a to 4c (inbox, living corpus, feed), M (miners, shared mining store), the main hub plan (`2026-11-13-main-hub.md`, part 7: "data integration across miners (one table of works with every miner's typed values), the graph ... First step: run each on `agentic-science` and record what works, what fails and what the researcher needs from it"), the hub feed plan (`2026-11-13-hub-feed.md`) and backlog IDEA-36, IDEA-04, IDEA-56, IDEA-57.

How this plan was made: from the specs, plans, backlog entries and the module table in `docs/MAP.md`. I did not read the service code line by line and ran nothing. Statements about behaviour come from those documents; items marked **to check** need a read of the code or a run on a copy of the pilot. The pilot's own events were not opened.

## 1. What the graph shows today

Built (v1, decisions 82 and 83 proposed, pilot runs set aside by decision 74): `graph_status`, `graph_query` (ancestors, descendants, path, papers without a stated base, improvements on a node, bounded depth) and `graph_export` (JSON and Graphviz DOT, deterministic, naming its filter) over a projection with typed tables and no free labels (R-86). Edge types are `cites`, `builds-on`, `improves-on`; each edge is `stated` (a verified quote plus a deterministically resolved target), `confirmed` (human) or `inferred`; default views show stated and confirmed only (slice 3b rulings 10, 11, 14). The interpretation layer (`explains`, `uses`) has its own tables and is shown only with `layer = all`, labelled (slice 3c rulings 3 and 7).

What the pilot (`agentic-science`) has, from the backlog and plans: references extracted for 371 works with 497 resolved links among 370 works (IDEA-57, 2026-11-11); reference layers (scheme v3, calibration labels partly pending); `m-layer`, `m-stages`, `m-lifecycle` and other miner rows. Its recorded protocol of 2026-11-13 has `contribution_schema` null, so no contribution items exist and therefore no `builds-on` or `improves-on` edges and no ideas; the graph can hold `cites` edges only, derived from reference links (expected, **to check** by a run). Cards, leads and the intuition layer were not run either. So today the graph for the pilot is a citation graph; the lineage the slice describes is unbuilt on real data.

## 2. How a new paper flows today (read from the specs)

1. **Feed** (`services/feed.py`, hub page `/feed/`, not yet run live): arXiv listings ranked against the project's core-layer works; entries are outside the corpus. The human reacts (`like`, `dislike`, `save`, `dismiss`) or sends.
2. **Inbox:** `send` adds the paper as an inbox item (channel `feed`); `inbox_resolve` looks it up as a `supplied` query under the protocol's `supplied_links` gate; the record enters the corpus as a pending work with provenance method `supplied` (slice 4a).
3. **Dedup and screening:** unchanged, blind to route and note (R-101). Title and abstract, then full text.
4. **Acquisition and conversion** (slice 2) for promoted works.
5. **References** (slice 3a): `references_extract` for the newly included work; its entries link to works; resolved works missing from the corpus become snowball candidates.
6. **Graph:** the projection derives edges from reference links and contribution items. A `cites` edge exists when a link is resolved or confirmed.
7. **Core and feed references:** an included work marked core by a human joins the reference set and the next ranking uses it (slice 4c, user flow 7).

## 3. Gaps in that flow

**F1. Earlier works citing the new one.** When paper N enters the corpus after the references of paper M (already extracted) were resolved, M's entry for N was unresolved or a snowball candidate. Whether it re-links to N automatically, or only after a re-resolve (`references re-resolve`, mentioned in IDEA-57's state note), is **to check**. If it does not, the graph misses `cites` edges into every newly added work until someone runs it, and the in-corpus citation count is understated.

**F2. No single record of where a paper is in the flow.** The discovery report (slice 4a) gives per-route counts at four levels; nothing shows one feed item through reaction, send, resolve, screening, full text, conversion, reference extraction and the graph. The researcher cannot see where a sent paper is stuck (for example, converted but not extracted).

**F3. The citations product is not built (IDEA-57).** In-corpus counts can be computed from `reference_links`; external counts (OpenAlex `cited_by_count`) have no event with source and date, and the daily budget limited the one run to 171 of 370 works.

**F4. No table of works with every miner's typed values.** Each miner's rows are read through its own commands and pages; the explorer prototype (`ops/screeners/explorer.py`, a prototype outside the platform) joins some. A researcher cannot sort or filter works by layer, stage, class and citations together from the platform's own outputs.

**F5. Contributions and ideas not run.** No `contribution_schema` in the pilot, so G2 has produced nothing there. The deep-dive and lifecycle plans use miners, not G2; the two overlap (a `base-idea` item and a lifecycle stage are different questions about the same text).

**F6. Between-project visibility is undefined at the data level.** The main hub shows every project in a portal and the feed shares an arXiv fetch cache; the rest is per project. What a second project may see of the first is not stated outside slice 5's `private` visibility (specified, v1 personal tokens) and the cross-project items listed in section 4.

## 4. What is shared between projects and what stays per project

Read from the specs and plans; the **proposed** column is this plan's recommendation.

| Item | Today | Proposed |
|---|---|---|
| Events, protocol, decisions, screening, calibration, audit | Per project (00-system §4; one log per project) | Stay per project |
| Library (raw sources, canonical Markdown) | Per project, git-ignored; "No shared library of literature between projects" (slice M, 00-system §11) | Stay per project; the same paper in two projects is stored twice |
| Work identity | Content-derived id (`rf:<surname><year>-<slug>-<hash8>`), so the same paper has the same id in every project (00-system §3; slice 3d ruling 10) | Use this as the join key for any cross-project view; no mapping table |
| Feed fetch cache | Shared per category set and window, 24 h; reactions and entries per project (hub-feed plan) | Unchanged |
| Reference set of the feed | Per project, its core layer | Unchanged |
| Mining store | A read-only cross-project projection `<root>/.mining/shared.sqlite` of records and digests, never document text (slice M ruling 18); `mine import` re-verifies against the importing project's own conversion; calibration does not travel (ruling 20) | Unchanged; the works table (part 1) reads per project |
| Cards | Cross-project by recorded import, copy with source ids (slice 6 ruling 8) | Unchanged |
| Region snapshots | Read-only adoption by hash (slice 3d ruling 10) | Unchanged |
| Graph | Per project: edges derive from the project's reference links and contribution items | Per project; a combined view, if wanted, is built on read from per-project exports with each edge labelled by project and never merged into one set of decisions |
| External citation counts | None stored | Per work, per source, per date, as events in the project that read them (IDEA-57), or one shared read-only store (decision D4) |
| Held-out seeds | Per project (R-20); the feed filters a held-out seed's work as held; decision 37.9 (read from assistant notes, not re-checked here): a held-out seed's work is not hidden from agent views | Every cross-project view applies each project's own existing rule; check the Decided text of decision 37 before building (**to check**) |

## 5. Parts, in order (tests first for every part)

**Part 0. Run what exists on a copy of the pilot (no code).** Copy `data/projects/agentic-science/events` to a scratch root (never the pilot). Run `graph status`, `graph query` (`no_stated_base`, ancestors of a core work), `graph export` on it; time them; record what works, what fails and what the researcher needs, in a dated note. Also check F1: pick a work added after its citing works were extracted (or simulate with a fixture) and see whether its links appear. The result sizes parts 1 to 5.

**Part 1. The works table (F4).** A read-only builder `works_table` for one project: one row per work with identifiers, year, venue if held, current screening outcome, layer, and for each registered miner the current typed values (enum fields only in columns; quote fields by reference to the row, never copied), each column labelled with its miner version and calibration state (`calibrated`, `exploratory`); in-corpus citation count computed from `reference_links` with its two denominators (documents extracted, links resolved), shown as unknown, never zero, where the work's citers have no extraction. Output: JSON and CSV through the existing export machinery (R-132: deterministic, naming scope and log position, no library text). Tests first: a fixture with two miners and three works; byte-identical output for the same log; a column from an uncalibrated miner carries its label; an unknown count is not 0; no document text in the output. No event.

**Part 2. Close the arrival flow (F1, F2).**
(a) After a work is added and converted, a command `references re-resolve --work ID` (or the existing re-resolve, **to check**) re-links earlier entries to it; the result lists the entries now resolved and the graph projection reflects them after rebuild. Tests first with a fixture of two works where the later one is cited by the earlier one's extraction.
(b) A computed status view `flow_status` for sent or supplied items: per inbox item the furthest step reached (resolved, in corpus, screened title/abstract, promoted, full text fetched, converted, references extracted, in graph, marked core) and the blocking reason if known, built from existing events (no new event type). Tests first with a fixture where one item is stuck at each step. Shown as a hub page section (lane C's area; this plan only names it) and as `factory flow status`.

**Part 3. Citations product (F3).** In-corpus counts are part 1. For external counts: an event `work.citations_recorded` (work, source, count, read-at) is **a new event type**: per the project's rule it needs a note in `docs/backlog.md` first; the plan does not build it until that note exists and the researcher chooses a source (D4). Option without a new event: keep external counts outside the event log in a dated, hashed side file that the works table reads and labels `external, read on <date>`; weaker for provenance (R-03 spirit), faster. Tests first for whichever is chosen: a count carries source and date; two sources are never merged; a work with no count is unknown. The OpenAlex budget limit (171 of 370 works) means the first run needs resume; reuse the restartable-step pattern (IDEA-59).

**Part 4. Contributions on the core layer (F5), if chosen (D2).** Declare `contribution_schema` for `agentic-science` (a protocol amendment, the researcher's act; `contribution_schema` is omitted from the hash while None, slice 3b ruling 5, so no stale decisions are expected: **to check**), then run G2 on the core layer only (about 98 works by the layer pass of 2026-11-13, uncalibrated), dual extraction on the declared sample, human resolution, audit; then `relation_propose`, human confirmation of inferred relations. Cost and time are the researcher's to accept; this is the largest part. Labelled exploratory until the layers are calibrated.

**Part 5. A graph page (after part 0).** A hub page for the graph: counts by edge type and status, papers without a stated base, a path view from an export, the layer toggle; built from events like the other products (lane C's area). The default is the evidence layer.

**Part 6. Cross-project reading, minimal (F6).** A read-only works registry `works_in_projects`: for a work id, which projects of the root hold it, and, per project, its own current screening outcome and layer shown separately (decisions are never merged or compared into one verdict). Authorised per project through the authentication seam (a project the viewer may not open does not appear). Hints to other projects (IDEA-04) enter a project only through its inbox as a `supplied` link, never directly. Tests first: two fixture projects sharing one work id; a viewer with access to one sees one row; held-out handling per project's own rule; no decision of project A appears in B's views.

**Part 7. Acceptance.** (a) Synthetic: a fixture project and a fixture second project; a feed entry reacted to, sent, resolved, screened, converted, extracted; `flow_status` follows it; the graph gains `cites` edges into it after re-resolve; the works table shows it with its layer and citations; the registry shows it in both projects. (b) Real, on a copy of the pilot: parts 0 to 2 results shown to the researcher.

## 6. Risks

- **Identifier splits.** A preprint and its journal version have different ids unless merged (IDEA-56); non-NFC spellings split ids (IDEA-66). Cross-project joins on the work id inherit both. Mitigation: the registry lists merged members; tests with a version pair and a decomposed Hangul id.
- **Understated counts.** In-corpus citation counts depend on how many reference lists were extracted and resolved (371 extracted, 497 resolved links at the last count); every count states both denominators.
- **Exploratory columns read as findings.** The works table must label uncalibrated miners wherever shown and in exports (the rule of the 2026-11-13 deep-dive plan, section 8).
- **Cost of part 4.** Contribution extraction on about 98 works is a miner-scale run; the researcher decides.
- **Confidentiality.** The portal shows all projects to the local human today; a registry for a hosted multi-user hub needs the authentication seam and slice 5 `private` visibility. Part 6 must not ship before the seam checks per project.
- **Graph size and rebuild time.** Unknown on real data; part 0 measures it.
- **A held-out seed is an ordinary work in another project.** Applying each project's own rule keeps R-20; a cross-project view must not leak what one project holds out.

## 7. Open decisions for the researcher (multiple choice; the recommendation is marked)

**D1. First step.**
(a) **Part 0 on a copy of the pilot, then re-size (recommended)**: the main-hub plan asks for it and F1 is unknown until run.
(b) Start part 1 (works table) now.
(c) Other.

**D2. Contribution extraction (G2) for the pilot.**
(a) **Core layer only, exploratory, after part 0 shows the graph works (recommended)**.
(b) All included works.
(c) Not now: the graph stays a citation graph; lineage questions are answered by the lifecycle and step miners.
(d) Other.

**D3. One cross-project table or per-project tables plus a registry.**
(a) **Per-project works table and a read-only registry of which project holds which work (recommended)**: keeps decisions per project.
(b) One cross-project table of works with values per project side by side.
(c) Other.

**D4. External citation counts.**
(a) **OpenAlex only, recorded per source and date as events after a backlog note for the new event type (recommended)**; a second source only if the first leaves gaps (an earlier ruling dropped Semantic Scholar for the reference layers; recorded in assistant memory, not re-checked here).
(b) A dated side file read by the works table, no event.
(c) Other.

**D5. Who sends a feed paper into the inbox.**
(a) **The researcher only (as built)**; the feed suggests, the researcher selects (recommended).
(b) The system sends the top N of each run after a human enables it per project.
(c) Other.

**D6. Re-resolving earlier references when a work arrives.**
(a) **A command plus a count in `flow_status` ("n references now resolvable"); run on demand (recommended)**.
(b) Automatic after each inclusion.
(c) Other.

**D7. Cross-project hints (IDEA-04).**
(a) **After part 6, as a flag with a stated reason that enters another project only through its inbox (recommended)**.
(b) Now.
(c) Not built.

**D8. A graph page in the hub.**
(a) **Yes, after part 0 shows what the graph holds (recommended)**.
(b) No; exports and the explorer prototype suffice.
(c) Other.

## 8. Not in this plan

A shared literature library, any change to screening or its blindness, learned ranking of feeds, a combined graph that merges decisions of several projects, the hypothesis engine (see `2026-11-14-hypotheses-engine.md`), authentication beyond the seam of the main-hub plan, and any model call in the platform.
