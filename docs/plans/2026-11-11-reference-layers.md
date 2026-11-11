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
