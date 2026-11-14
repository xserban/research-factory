# Flow transparency: every PRISMA number by source, down to the work

Status: draft for the researcher's validation (2026-11-14). Not started.
Depends on: `services/prisma.py` (`prisma_flow`, `full_text_boxes`), `services/dedup.py`, `services/agreement.py` (`final_outcomes`, `exclusion_criteria`), `fulltext_attempts` table, the `trace` tool, the hub (`site_prisma.py`, `site_explorer*.py`).

## Goal

Every number reported for the survey can be opened: split by source, then listed work by work, then followed for one work through every step that kept or removed it. No number in the report is a dead end.

Key results:
1. Each PRISMA box shows its count per source (arXiv only, OpenAlex only, both, other methods).
2. Each box (and each per-source cell) opens the list of works behind it, with title, source, query, and the step's reason.
3. Each work has a trail: found by which query and run, merged with what and by which rule, each screening decision (pass, verdict, criterion, rationale, quote), each full-text attempt (route, reason), the full-text decision, and what was mined.
4. Records that never became works (skipped within a run, lost to a failed page) are listed with their titles from the archived raw pages.
5. A check asserts that the work-level ledger sums to the reported flow; a mismatch is an error, not a footnote.

## Why (the pilot as it stands)

Computed 2026-11-14 from the events (read-only script, same services as `report_prisma`):

| step | arXiv only | both | OpenAlex only | not canonical |
|---|---:|---:|---:|---:|
| screened (title/abstract) | 228 | 1260 | 2646 | 0 |
| excluded at title/abstract | 110 | 422 | 1701 | 0 |
| included at title/abstract | 118 | 838 | 945 | — |
| full text not retrieved | 91 | 588 | 835 | 30 |
| of which never attempted | 90 | 582 | 741 | 29 |
| of which attempted and failed | 1 | 6 | 94 | 1 |
| full text retrieved | 27 | 250 | 110 | 7 |
| included at full text | 26 | 243 | 93 | 6 |

Three things the current report hides:
- "1544 not retrieved" is mostly **not sought**: 1442 promoted works were never attempted. The real failures (about 100) are almost all OpenAlex-only works with no arXiv id and no open-access PDF.
- 37 works on the full-text list are not canonical (merged into another work after promotion). Their counts must be reconciled, not silently carried.
- OpenAlex reported 4074 for the main query and 4072 were kept; 14 were skipped as untitled or duplicate within the run. Those titles exist only in the archived pages.

## Design

### 1. Work ledger (service, no model)
`services/flow_ledger.py`: `flow_ledger(project) -> list[LedgerRow]`, one row per identified record (canonical works and absorbed duplicates). Fields: work id, title, year, sources, query ids, run ids, canonical id (if merged) and merge rule, title/abstract outcome and criterion, pass A/B verdicts, full-text state (`retrieved`, `attempted-failed` with route reasons, `not-sought`), full-text outcome and criterion, mined (yes/no). Built from the same functions as `prisma_flow`; it adds no new judgement and writes nothing.

Invariant: grouping the ledger reproduces every count of `prisma_flow`. `factory check` gains a rule for it.

### 2. Flow by source
`prisma_flow_by_source(project)`: the flow counts keyed by source group. `report_prisma` gains an optional `by_source` block; the PRISMA SVG is unchanged (PRISMA 2020 form), the split is a table beside it.

### 3. Records that never became works
`skipped_records(project)`: reads the archived raw pages of each run (`search.page_archived` blobs) and lists records not parsed into a work (untitled, duplicate within run), plus each run's reported-minus-retrieved gap with the failure note. Titles are shown as the source gave them.

### 4. Not sought versus not retrieved
`full_text_boxes` separates "not yet sought" from "sought, not retrieved" (PRISMA 2020 counts only sought reports as not retrieved). The methods text says how many promoted works were never attempted and why (the run stopped; decision needed on whether to resume).

### 5. Hub: Flow explorer
New hub product under Sources/Corpus: the flow as a table of boxes × source groups; every cell is a link to a filtered work list (title, sources, query, step, reason; sort, search, CSV download). Each title opens the work trail.

### 6. Hub: Work trail
One page per work: an ordered list of its events (via `trace`), grouped by step, each with actor, model, time, and the quote or reason. Merged duplicates link to each other.

### 7. MCP and CLI
`report_prisma(by_source=true)`, `flow_works(box, source)` and `flow_trail(work_id)` for agents; `factory report flow --by-source` and `factory report flow-works BOX` for the CLI. Thin wrappers only.

## Broader: what the project folder holds that the hub does not show

Inventory of `data/projects/agentic-science/` on 2026-11-14. The hub has 23 products (acquisition, agreement, bibliography, citations, conversion, costs, dashboard, explorer, feed, layers, lifecycle, miners, PRISMA, queue, results, steps, synthesis, taxonomy, wiki, …). What exists but is not reachable from it:

**A. Already in the events, never shown (no new data needed).**
| data | events | hub use |
|---|---|---|
| raw search responses | 1286 `search.page_archived`, 873 `search.records_parsed`, run notes (401 failures, resumes, skipped) | per-query page: every run, its pages, gaps and skipped titles (section 3) |
| screening rationales and quotes | 5508 `screening.decision_recorded`, 517 resolutions | per-work trail; per-criterion list with the quote that excluded each work |
| dedup | 433 merges, 33 reverts | merge list with both titles and the rule; reverted merges marked |
| protocol history | 5 recorded, 27 amendments, 4 deviations, 3 press reviews | protocol timeline: what changed when, and which decisions ran under which version |
| probe | 26 measures, 75 archived pages, 3 failures | how the queries were chosen (term yields) |
| researcher decisions | 63 suggested, 60 selected | decision log page: option offered, option taken, by whom |
| calibration and audit | 60 + 60 calibration labels, 89 audit labels, 80 check labels | gold-label pages per pass and per miner version |
| full-text attempts | 1104 attempts by route | acquisition page split by source and route (section 4) |

**B. Files that are records of the study but sit outside the events.** Register each as a hashed document (an event naming path and sha256) and show it read-only, with its versions:
- `docs/`: research plan (v1, v2, v3 rejected, final), research questions, goal definition, review protocol (Markdown and PDF), demo log, status notes. Hub: a "Study documents" product with version history.
- `validation/`: converter bake-off cases and reports (decision 49), coverage, `missing-153`. Hub: "Conversion validation", linked from the conversion product.
- `inputs/reference-layers/`: scheme versions v1–v3 and calibration label TSVs. Check first whether the `reference.layer_*` events already carry them; if so, link, otherwise register.
- `inputs/pdfs`, `inputs/staging-*` (131 PDFs): hand-supplied full texts. Hub: list which were adopted into the library and which were not.

**C. Operational working files.** Not study records; index, do not integrate:
- `ops/screeners/` (3475 files: per-batch prompts, outputs and agreement summaries of agent runs), `ops/overnight/`, agent prompts. Hub: a "Runs" page listing each session with its files, linked from the run's events where a run id matches; files with no matching event are flagged as unlinked.
- `archive/` (superseded explorer, vault, dashboard, test scratch): link once from a "Superseded" note; no rendering.

**D. One rule for all of it.** The hub is built from events (IDEA-55). A file appears in the hub only through an event that names its path and hash. A new check lists files under the project folder that no event references, so nothing is silently outside the record.

## Tasks (one branch `flow-transparency`, small commits)

1. Ledger service and its invariant (critical module: index reads; rf-builder-critical, Sonnet).
2. Flow by source, `report_prisma` block (rf-builder).
3. Not-sought split in `full_text_boxes`, methods sentence (rf-builder-critical: changes a reported PRISMA number).
4. Skipped-records reader over archived pages (rf-builder).
5. Hub flow explorer page (rf-builder).
6. Hub work trail page on `trace` (rf-builder).
7. MCP and CLI wiring (rf-builder).
8. Reconcile the 37 non-canonical full-text works (investigation first; fix or decision entry).
9. Regenerate `docs/MAP.md`; backlog status; one Sonnet review of the branch.

Second branch `hub-records` (after validation of the first): the event-only pages of A (one task per page), the document registration event and "Study documents" product (B), the unreferenced-files check (D), the runs index (C).

### Branch 2 tasks (`hub-records`, cut from `flow-transparency` db96864, 2026-11-15)

Already shown by the dashboard product and therefore dropped from A: researcher decisions, protocol view, PRESS reviews, probe rounds. Calibration and audit labels are left for a later pass (the miners product covers miner calibration).

- R1 (rf-builder): hub product "Search and deduplication" (group Sources): per registered query its runs (status, reported, retrieved, notes), archived pages, gaps and skipped records (`flow_skipped`); every merge with both titles, rule, active or reverted; the merged-after-screening conflicts (`dedup.merged_after_screening`).
- R2 (rf-builder-critical, new event): `file.registered` (path relative to the project folder, sha256, kind: study-document | validation | input | other, title, supersedes); service, CLI `factory files register PATH --kind K [--title T]` and `factory files list`; registration of an unchanged file is idempotent, a changed file is a new version; hub product "Study documents" (group Overview) listing registered files by kind with versions, Markdown rendered as HTML and other files linked.
- R3 (after R2): `factory check` rule `unreferenced-files`: files under the project folder that no event names (excluding `events/`, `blobs/`, `library/`, `.index/`, `site/`), as a warning with the count by top-level folder; and a "Runs" hub page listing `ops/` agent-run files grouped by batch prefix, linked to a run id where an event names it, others flagged as unlinked.

Tests are written with each task (TDD), but not run while the testing pause holds; mypy and ruff must pass.

## Researcher rulings (2026-11-14)
- Source groups: three groups, arXiv only / OpenAlex only / both (no double counting); other methods as a fourth group when present.
- The 1442 never-attempted works: report as is, labelled "not yet sought", separate from "sought, not retrieved". No fetch resume before the first results.
- Scope: branch 1 (`flow-transparency`, tasks 1–9) first; branch 2 (`hub-records`) after branch 1 is validated.
