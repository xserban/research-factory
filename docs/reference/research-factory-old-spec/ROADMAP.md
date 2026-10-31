# Research Factory — Build Order

The sequencing principle: **one narrow vertical slice end-to-end before any horizontal
broadening.** A pipeline that handles 20 papers completely is worth more than one that
handles 2,000 papers up to step three, because only the end-to-end run tells you whether
the wiki is actually answerable.

Pick a real question of your own for the slice. A synthetic test question will not
surface the failure modes that matter.

---

## Phase 0 — Skeleton (½–1 day)
**Goal: a `Work` survives a round trip to disk and back.**

- `rf/model.py` — `Work`, `Identifier`, `Provenance`, `Claim` as pydantic models
- YAML-frontmatter read/write for `works/<id>.md`; deterministic ID generation
- `rf init`, `rf status` against the project layout
- One adapter only: `openalex`
- Tests: ID stability, frontmatter round-trip fidelity

**Done when:** `rf init demo && rf search --run` writes real work files you can read.

## Phase 1 — Acquisition (2–3 days)
**Goal: many sources in, one clean corpus out, with correct counts.**

- Adapters: `semanticscholar`, `arxiv`, `pubmed`/`pmc`, `crossref`, `url`, `dropfolder`
- `rf dedup` with the 4-stage cascade + `dedup-map.yaml`
- `rf prisma` — identification/screening/included counts derived from corpus state
- Provenance enforced at the model level: a `Work` with no provenance is invalid

**Done when:** the same paper arriving from four sources becomes one work with four
provenance entries, and `rf prisma` reports the duplicate count without help.

## Phase 2 — Full text (3–5 days, the risky one)
**Goal: readable, structured markdown from every acquirable work.**

- Route by best available: PMC XML → arXiv LaTeX → Unpaywall OA PDF → local PDF → HTML
- Extractors: `trafilatura` (HTML), `pymupdf` (fast PDF), GROBID (structured PDF, optional
  container), LaTeX parse for arXiv
- Normalize to markdown with **stable section anchors** — claim locators depend on these
- Record `method` and `quality` honestly; `title-abstract-only` is a valid outcome
- Manual escape hatch: drop a `.md` in `fulltext/<id>/` and it is respected

**Done when:** 20 works of mixed type all yield markdown whose section headings you trust
enough to cite by.

*Do this before the skills. Extraction quality bounds everything downstream, and finding
out late is expensive.*

## Phase 3 — Protocol & screening skills (2–3 days)
**Goal: the judgment layer, auditable.**

- Skills: `refine-question`, `draft-protocol`, `design-queries`
- `protocol.lock` + `deviations.md`
- Skills: `screen-titles`, `screen-fulltext`, `appraise-grey`
- Calibration set: ~30 records you label by hand; agent scored against them before each
  screening run, disagreements shown
- Confidence flags route borderline records to you rather than guessing

**Done when:** `rf prisma` produces a flow diagram you would put in a paper.

## Phase 4 — Extraction & claims (3–4 days)
**Goal: notes that are more than summaries.**

- `extract-work`: methods, data, results, limitations, and atomic claims with locators
- `claims/CLM-*.md` with support/contradict edges
- `rf check` — every claim resolves to a real work + a real section anchor

**Done when:** you can grep a claim ID and land on the exact paragraph that supports it.

## Phase 5 — Wiki & synthesis (2–3 days)
**Goal: the thing you actually use.**

- `rf wiki build` — `index.md`, concept pages, theme/method/year views
- Contradiction surfacing on concept pages
- Skills: `build-wiki`, `synthesize`, `answer-from-wiki`, `audit-trail`
- `answer-from-wiki` must be allowed — and instructed — to say *the corpus does not
  support an answer*. This is the single highest-value behaviour in the system.

**Done when:** you ask your slice question, get a cited answer, and every citation checks out.

## Phase 6 — Harness generation (1 day)
- Generator emitting `.github/skills/<name>/SKILL.md` (Copilot — the convention already
  in use in this repo) and `.claude/skills/*` from
  `skills/*.md`
- Keep the source of truth harness-neutral so this stays a build step, never a fork

## Phase 7 — VS Code interface (later, optional)
Only worth doing once phases 0–6 are in daily use. Likely shape: a tree view over pipeline
state, a screening panel with keyboard include/exclude, and a wiki graph. Nothing here
should become a dependency of the pipeline — the CLI and the files stay the product.

---

## First three commits

1. `rf/model.py` + frontmatter serialization + tests
2. `rf/sources/openalex.py` + `rf search --run`
3. `rf/dedup.py` + `rf prisma` counting

## Open questions to resolve as you go

- **Screening threshold** — how conservative at title/abstract? Over-inclusion costs
  full-text time; over-exclusion is invisible and irrecoverable. Default: include on doubt.
- **Corpus size ceiling** — agent-native grep degrades somewhere in the 300–800 work range.
  That is the trigger to build the vector index, not a date.
- **Claim granularity** — too fine and the wiki is noise, too coarse and it is a summary.
  Calibrate on the slice.
- **Update semantics** — when a search is re-run six months later, new works must enter
  without disturbing existing screening decisions. Design `rf search --run` to be
  incremental from day one; retrofitting this is painful.
