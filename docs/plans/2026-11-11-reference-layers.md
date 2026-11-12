# Plan: reference layers — group, clean and triage the corpus's references by relevance

Date: 2026-11-11 · Status: T1–T5 built and reviewed (one Sonnet review, findings fixed; mypy and ruff only, testing paused; tests to write listed in the commit messages); L1 scheme v1 drafted at `research-factory-pilot/reference-layers-scheme-v1.json`; next: the researcher records it and labels the calibration sample · Branch: `plan-reference-layers` (from `plan-8-suggest-select` at a67690b, the site hub) · Origin: pilot `agentic-science`, IDEA-57 discussion · Precedes: the citations product (IDEA-57, a later plan)

## Problem

The 371 included works of the pilot have 12,983 parsed reference entries. Resolving each entry to a
work record by lookup costs one source request per entry; 9,827 lookups failed (`source-error`,
the OpenAlex daily allowance, which since 2026-02-13 is about $1 a day with a free key) and only
1,615 links are resolved. Most references are not relevant to the review, so resolving all of them
spends the allowance on works nobody will read.

Measured on the pilot index (2026-11-11):

| | Entries |
|---|---|
| Entries of live extractions | 12,983 |
| With a usable title (> 8 characters) | 6,939 |
| Distinct titles after case-folding | 5,400 |
| No usable title, but a DOI or arXiv id | 1,646 |
| Neither (parser noise: `M`, `Y`, author strings) | about 4,400 |
| Titles cited by two or more corpus works | 541 |

## Approach

Judge relevance on the parsed titles first, and resolve only what survives. Layers are assigned in
stages, as screening is: title, then title and abstract, full text only where needed. References that
meet the review's inclusion criteria are not a layer of context: they are missed candidates and go to
a snowball round, screened under the protocol.

## Principles

1. **Scripts never judge; agents never do bookkeeping.** Grouping, clean-up flags, counts and order are
   computed. Layer assignment is a judgement made by Claude through MCP, recorded with provenance
   (model, skill version, `input_blob`).
2. **The scheme is fixed before assignment.** Layer definitions (criteria and examples) are recorded by
   the researcher before any item is assigned; a changed scheme is a new version, and assignments name
   the version they used.
3. **Ordering is not judging.** The number of corpus works citing an item orders the queue; it never
   assigns a layer.
4. **Nothing is masked.** A held-out seed's work that appears in a reference list is triaged like any
   other item (decision 37.9).
5. **Unassessable is declared.** Entries without a usable title or identifier are counted and reported
   with the reason, never silently dropped.

## Layers (scheme v1, chosen by the researcher on 2026-11-11; criteria and examples set in step L1)

| Layer | Meaning | What follows |
|---|---|---|
| `in-scope` | Meets the review's inclusion criteria | Snowball round, screened under the protocol (L5) |
| `adjacent` | Techniques such systems are built from (agents, tool use, planning, reasoning, retrieval, agent evaluation) | Title and abstract pass (L4); shown in the citations product |
| `background` | Foundations and general context (base models, benchmarks, general ML, philosophy of science) | Counted; shown in the citations product |
| `off-topic` | Unrelated, or noise that survived clean-up | Counted |

## Design

- **Cited item.** A group of reference entries (across all live extractions) that share a normalised
  title: NFKC, case-folded, punctuation removed, whitespace collapsed. Key `ci-` + the first 16 hex
  characters of the SHA-256 of the normalised title. Computed on read from `reference_entries`; no event.
  Each item carries its citing works (distinct), the entries, the earliest year and any DOI or arXiv id
  seen on its entries.
- **Clean-up flags** (computed, versioned as `ITEM_RULES_VERSION`): `too-short` (fewer than 3 words or
  12 characters), `author-list` (the title parses as a list of personal names), `leading-noise` (starts
  with a bracket or punctuation). A flagged entry is `unassessable` with its reason.
- **Titles for identifier-only entries.** The 1,646 entries with a DOI or arXiv id but no title get a
  title from the existing resolution: `references.re_resolve` restricted to identifier lookups (one
  singleton request each). If `re_resolve` cannot be restricted, T2 adds that filter.
- **Events (new):**
  - `reference.layer_scheme_recorded` — version, layers (id, name, criteria, include and exclude
    examples). Human actor only; first-write-wins per version.
  - `reference.layer_assigned` — item key, scheme version, stage (`title` | `abstract`), layer, a short
    rationale, provenance. An agent actor. Last write wins per (item, stage, actor); the item's layer is
    the latest stage's.
  - `reference.layer_labelled` — the researcher's own label for an item in the calibration sample.
- **Index (new table `reference_layers`)**, folded by the projector only: item key, scheme version,
  stage, layer, actor, event id. `PROJECTION_VERSION` is incremented.
- **MCP** (Claude's side): `reference_layer_next` (a batch of items, ordered by citing works then key:
  key, title, year, citing count; title and abstract at stage `abstract`), `reference_layer_record`
  (validated at the boundary: unknown key, unknown layer, wrong scheme version or stage are refused and
  write nothing), `reference_layer_status` (counts by layer and stage, unassessable by reason, items
  left).
- **CLI** (the researcher's side): `factory references scheme record FILE`, `factory references layers
  status`, `factory references layers label` (the calibration sample).

## Steps

| Step | What | Who | Depends on |
|---|---|---|---|
| L0 | Grouping and clean-up (T1, T2), then titles for identifier-only entries (operational) | agents, then me | — |
| L1 | Layer criteria and examples: I propose them as tick lists, the researcher selects and edits; recorded as scheme v1 | researcher + me | — |
| L2 | Calibration: 30 items drawn by stratum (citing count high, medium, low), labelled by the researcher; Claude's title-stage assignments compared; the floor is the one used for title/abstract screening | researcher + me | T3–T5, L1 |
| L3 | Title pass over all assessable items, highest citing count first | me (Claude, via MCP) | L2 passed |
| L4 | Resolve only `in-scope` and `adjacent` items (a few hundred lookups, not 12,983); title and abstract pass on them | agents (T6), then me | L3 |
| L5 | `in-scope` items to a snowball round; screened under the protocol | existing tools, T7 | L4 |

## Tasks for agents

Testing is paused (test-run policy, 2026-11-05): each task passes `mypy --strict` and `ruff`; the
tests named per task are written when testing resumes and recorded in the untested-work list.

| # | Task | Agent | Files |
|---|---|---|---|
| T1 | Cited items and clean-up flags: `services/reference_items.py` (`cited_items(project) -> list[CitedItem]`, `normalise_title`, `item_key`, flags), pure and read-only | rf-builder | new service |
| T2 | Restrict `re_resolve` to identifier lookups (`only_identifiers: bool`), if not already possible | rf-builder-critical | `services/references.py` |
| T3 | Events and fold: models in `model/references.py`, catalog entries, `reference_layers` table and handlers in `index/references.py`, human-only guard on scheme and label events | rf-builder-critical | events, index |
| T4 | Layer service: `services/reference_layers.py` (`next_items`, `record`, `status`, calibration draw and agreement) | rf-builder-critical | new service |
| T5 | MCP tools and CLI commands (parse, call T4, format) | rf-builder | `mcp/server.py`, `cli/` |
| T6 | Stage `abstract`: resolve the shortlisted items' entries by title lookup and serve the abstract | rf-builder | T4 service |
| T7 | Snowball round from `in-scope` items: `snowball_candidates` accepts a layer filter | rf-builder-critical | `services/snowball.py` |

T1 and T3 run in parallel; T4 after both; T5 after T4; T2 is independent. One review of the finished
branch by `rf-reviewer` (guard mutation on the projector handlers), before landing.

## Proposed decision (provisional number, fixed at landing)

Reference layers: relevance layers are assigned to cited items (entries grouped by normalised title),
in stages, by an agent under a scheme the researcher recorded first; the citing count orders the
queue and never assigns a layer; `in-scope` items are snowball candidates screened under the
protocol, never included by their layer; unassessable entries are declared with their reason.

## Parked

- Semantic Scholar as a source (dropped on 2026-11-11 by the researcher; note: one batch request
  carries 500 papers, so a key's 1 request per second is enough for 371 works).
- Reference lists from OpenAlex `referenced_works` in batches, as a second source beside the parsed
  lists.
- The citations product (IDEA-57): counts by layer, in-corpus counts, dated external counts, hub page
  and explorer columns. A later plan, after L3.
- Self-citation flag; refresh schedule for external counts.

## Open questions

1. ~~Two passes at the title stage?~~ Ruled 2026-11-11 by the researcher: one pass at the title stage,
   with the calibration (L2) and an audit sample.
2. Whether a cited item that matches a corpus work by title is excluded from the queue (already in the
   corpus) or kept and counted as an in-corpus citation (the citations product needs it).

## Calibration round 1 and scheme v2 (2026-11-11, with the researcher)

The first four calibration items exposed three faults, so labelling stopped and the scheme was revised
before anything was recorded in the pilot (the first scheme existed only in a scratch copy):

1. **Years were not shown.** 96% of titled entries carry a parsed year (6,683 of 6,939); the sample now
   shows it.
2. **Author fragments survived clean-up** ("Haoyang Su et al"; 330 titled entries contain "et al").
   Rules v3 add an `et-al` flag and extend `author-list`; titles are HTML-unescaped.
3. **Earth layers.** The researcher's model: concentric rings, inner to outer — inner core (general AI
   research system, any domain), applied core (AI research system in one science), mantle (adjacent
   techniques), crust (background), outside (off-topic or invalid). Both cores are in scope and are
   snowball candidates; whether a system does two or more research stages is not judged from a title
   and is checked at full text by the snowball screening. Rationale: about 209 of the included works
   are domain systems, so treating domain work as context would make the snowball miss the corpus's
   own majority type.
4. **Precursor is computed, not judged:** an item whose year is before `precursor_before_year` (2025,
   IN03) is marked as a precursor and not snowballed; an unknown year counts as not a precursor
   (the snowball screening checks IN03 on the record).

Each layer in the scheme now carries `ring` (inner to outer), `snowball` and `abstract` flags; no layer id
is hard-coded. The calibration agent's pass is run by a fresh agent that has not seen the researcher's
labels; scheme examples never include calibration-sample items.

## For the citations and hub plan (requirements from the researcher)

- **Earth-layers view** in the dashboard and hub: concentric rings sized by cited items, inner core at
  the centre; clicking a ring lists its items with citing counts; precursors shaded inside each ring;
  unassessable entries counted outside.
- **Snowball filter:** works that entered through a snowball round are filterable (show only, hide) in
  the explorer and every hub product, computed from each work's provenance (search purpose), never
  typed. The in-corpus citing count is shown beside the layer as a signal of core (computed, not a
  judgement).

## Calibration round 2 (2026-11-11)

The researcher labelled the 30-item sample in a session, item by item; the scheme was revised at each
disagreement with its own criteria (rulings: domain science without AI, single-task scientific ML,
engineering design automation, publishing economics, LLM security and generic ML methods are not
relevant; LLM agents and how LLMs work are background; reasoning and search stay in the mantle only
as agent techniques). Labels: 22 not relevant, 6 background, 1 adjacent, 1 applied, 0 core. The
scheme examples contain no sample title. Because the criteria were sharpened on this sample, the
calibration kappa is optimistic; the audit below is the fair test.

Calibration was run on a scratch copy of the pilot (the MCP servers in use load older code and would
rebuild the index back), and the agent pass by Haiku that had never seen the labels, through a helper
calling the same service functions as the MCP tools.

## Closing tasks (promotion to the factory, researcher request 2026-11-11)

| # | Task | Who |
|---|---|---|
| P1 | Skill `rf-reference-layers` (plugin/skills): the judging procedure | done |
| P2 | Default earth-layers scheme template shipped with the platform (`platform/.../data/layer-schemes/earth-v1.json`, generic wording; a project copies and adapts it to its protocol) | rf-builder |
| P3 | Record the final scheme and the researcher's 30 labels in the real pilot as human events (from `reference-layers-calibration-labels.tsv`, notes kept), once this branch is the code the servers load | researcher + me |
| P4 | **Audit (required):** after the full title pass, a fresh sample of 30 items (not the calibration sample) labelled by the researcher without seeing the agent's layer; plus every item the agent placed in either core, and the 30 most-cited items it placed outside. Reported with kappa and the core recall | researcher + me |
| P5 | Docs: the procedure in the methods report and `docs/MAP.md` regenerated after merge | rf-builder |

## Parked: the pilot run (2026-11-11, researcher decision)

Calibration on the scratch copy passed: Haiku (`claude-haiku-5-5`, skill `rf-reference-layers`) agreed
with the researcher on 28 of 30 items, kappa 0.84 (floor 0.70); per layer: applied 1.00, background
0.89, off-topic 0.83, adjacent 0.65. The two disagreements are search methods ("Illuminating search
spaces by mapping elites": researcher background, Haiku off-topic; "Stream of search": researcher
off-topic, Haiku adjacent). Nothing is recorded in the pilot yet.

The pilot run waits because miner waves (`screeners/run_pass_m.sh`, `screeners/factory-mcp.json`) and
older sessions load the plan-8 code; two codes with different projection versions on one index
rebuild it against each other. Resume when no wave runs:

1. Rebase `plan-reference-layers` onto the current `plan-8-suggest-select` (it moved on; its
   PROJECTION_VERSION is 75): resolve `index/default.py` to the next free version, re-run mypy and
   ruff.
2. Point `.mcp.json` and `research-factory-pilot/screeners/factory-mcp.json` at the
   `plan-reference-layers` worktree (or merge it into the plan-8 line); every open session reconnects
   `factory`; verify with `/proc/<pid>/environ` that no `factory serve` loads other code.
3. Record `research-factory-pilot/reference-layers-scheme-v1.json` (`factory references scheme
   record`) and the 30 labels from `reference-layers-calibration-labels.tsv` (`factory references
   layers label --item --layer --note`).
4. Run the Haiku calibration pass in the pilot (skill `rf-reference-layers`, MCP tools), check kappa,
   then the full title pass (about 3,750 items, batches of 100).
5. Audit (P4), then the citations product with the earth-layers view.

## Snowball dry run (2026-11-11, scratch copy)

`factory snowball plan backward` works on the pilot's data: 506 candidates (resolved links not in the
corpus), ranked by citing works; the top is the core and its precursors (The AI Scientist 2024 cited
by 8 included works; Coscientist, ChemCrow, FunSearch by 4; AlphaEvolve by 3). `snowball run` is
refused because 8 included works are still pending in screening (the round needs a settled corpus).
Not yet exercised: the round's search, merge into works, hand-off to screening and the PRISMA update.
Findings for T7: candidates come only from resolved links and include background and noise (model
reports, the Protein Data Bank, docking software), so the layer filter is what makes the round small;
a round cannot be limited to chosen sources. Resume step: settle the 8 pending screening decisions in
the pilot, then run one backward round after the layer pass and T7.

## Pilot title pass, first run, and round 3 rulings (2026-11-12)

Resumed run: branch rebased onto plan-8 (projection 77 kept, no other branch uses it); both MCP configs
point at this worktree; scheme v1 and the 30 labels recorded in the pilot; Haiku calibration passed
(28/30, kappa 0.84). First run of the title pass: 498 most-cited items, core 38, applied 52,
adjacent 102, background 122, off-topic 184. Paused for six problems:

1. Title variants split one work (The AI Scientist as four items: trailing years, "arXiv preprint",
   "[Preprint]").
2. Core broader than the researcher's expectation; a third of it benchmarks of research agents.
3. The calibration sample held 0 core and 1 applied item: kappa says little about the inner rings.
4. Parsed "titles" that are author lists (DeepSeekMath, SWE-bench, cited by 11 and 6) went off-topic;
   most carry an arXiv ID.
5. Core/applied boundary from titles (Coscientist names no science).
6. Robot scientists and self-driving labs without an LLM went off-topic.

Researcher rulings (round 3):

- **R3.1 Merge duplicates** (reuse the works-dedup tools): items merge when they share an arXiv ID or
  DOI, when their titles are equal after stripping years, venue and preprint notes, or when titles
  are near-equal (rapidfuzz, high threshold, year within one). Automatic; merged counts reported.
- **R3.2 Benchmark ring.** Benchmarks and evaluations of AI research systems get their own ring
  inside the core. Order: core, benchmark, applied, adjacent, background, off-topic.
- **R3.7 Snowball core only** (researcher, 2026-11-12): only the core ring is snowballed; benchmark and
  applied items stay in the citations product. Estimate from the first 500 items: about 6-10 new core
  systems after merging, against about 20 applied and 60 adjacent.
- **R3.3 Identifier wins.** For every entry with an arXiv ID or DOI whose title is known (corpus work,
  resolved link, another entry, or a lookup of the identifier), that title replaces the parsed one.
  Entries without an identifier keep the parsed title and the clean-up flags.
- **R3.4 Core/applied from the title**; the P4 audit corrects known cases (Coscientist).
- **R3.5 Robot scientists and lab automation without an LLM** are background.
- **R3.6 Inner-ring calibration.** Scheme v2 adds 20 items to the sample, drawn from items an agent
  placed in an inner ring under an earlier scheme (10 from v1 core, 5 applied, 5 adjacent); kappa per
  ring is reported. Everything is redone under v2: the researcher relabels the sample, Haiku
  recalibrates, the 498 items are rejudged.

Tasks:

- **T8 (rules v4):** identifier-wins titles and item merging in `services/reference_items.py`.
- **T9 (inner sample):** optional `inner_sample` on the scheme event; the sample's inner stratum.
- **S2:** `research-factory-pilot/reference-layers-scheme-v2.json` (drafted by Claude, confirmed by the
  researcher).

### Follow-up: batched identifier lookup (observed 2026-11-12)

`factory references re-resolve --only-identifiers` on the pilot (about 2,900 entries with a DOI or
arXiv id whose first lookup failed) ran for more than an hour: it walks extraction by extraction and
looks identifiers up per entry, so an id cited by many works is fetched many times. Task **T10**:
collect the distinct identifiers across all live extractions, look them up in batches (OpenAlex
filter with up to 50 DOIs per request; arXiv `id_list`), then write one re-resolve event per
extraction from the shared results. Same events, minutes instead of an hour.

Researcher ruling (2026-11-12): **lookups are targeted, not for all.** T10 looks up only (a) entries
whose parsed title fails a plausibility check (mostly personal names, too few content words,
venue-like) and has a DOI or arXiv id, and (b) core items before a snowball round; both batched.
The full re-resolve was stopped after 195 extractions: identifier entries resolved 3,359 of 4,006
(from 1,122), 647 left; one lookup run was left open by the interrupt (started, not finished).
Assessable items rose to 4,671 (rules v4).
