# Existing assets

Reviewed 2026-10-31. Rule: extract only what clearly earns its place; nothing is copied wholesale.

## arxiv-miner (`~/Projects/arxiv-miner`, v0.1.0)

Local desktop app (FastAPI + browser UI, SQLite): fetches recent arXiv papers by category, embeds title + abstract locally, ranks by a like/dislike classifier, and scores papers against "topics" (folders of reference PDFs). ~6.4k lines incl. tests; offline test suite.

Effectively a prototype of **production line 2 (keep current) for arXiv, with seeded regions** — but its core idea (learning personal taste) is relevance ranking, not research selection.

### Extract (candidates)
| Component | Why | Changes needed |
| --- | --- | --- |
| `core/arxiv_throttle.py` (polite rate limit, 429 back-off with Retry-After) | Needed for every literature source | Generalise to a per-host limiter |
| `core/arxiv_fetcher.py` + id batch lookup | arXiv source adapter | Add keyword queries; HTTPS |
| `core/pdf_extractor.py` (Zotero folders, arXiv-id resolution, heuristic fallback, file hash, records extraction method) | Line 3 (start from own corpus); extraction method is provenance on extraction quality | Title/abstract only; full text with positions (for span verification) needs a separate parser later |
| `services/exporter.py` (BibTeX/CSV/JSON) | Exports from the graph | Adapt to graph data |
| Test practice (offline by default, `network` marker, fresh data folder per test) | Keep the discipline | — |

### Keep as patterns only (re-implement, don't copy)
- Append-only schema migrations, version stored in the database, backup before migration, refuse newer schemas, WAL.
- Atomic file writes; plain-JSON persistence (no pickle); compatibility checks on load.
- Record which model produced every derived artefact (e.g. `embedding_model` column).
- Topic scoring idea: a seeded region scores candidates and reports **which seed** they matched (explainable routing). Only relevant if we adopt embeddings.
- Separability check (`leave_one_out_accuracy`): are regions distinct? Only relevant if we adopt embeddings.
- Development process skills in `.github/skills` (TDD, systematic debugging, subagent-driven development, writing plans, code review) — candidates for the factory's Claude Code plugin, after review.

### Do not reuse
| Component | Reason |
| --- | --- |
| `core/embeddings.py` (all-MiniLM-L6-v2) | Embeddings are an open decision for the factory (see decisions.md #9); if adopted, the model is chosen and evaluated for scientific text, not inherited |
| `core/ranker.py` (like/dislike logistic regression) | Personal taste ≠ criterion-based selection; weak features (raw first 10 embedding dimensions, vector norm). Possible later replacement: active-learning screening prioritisation (as in ASReview), with evaluation and a stopping rule |
| 90-day retention of mined papers | The factory keeps its corpus permanently, with provenance |
| Desktop UI, FastAPI routes, single-user module state | Not needed; Claude + MCP tools + generated views replace it during the pilot |

### Gaps relative to the factory
- **Sources:** arXiv only. TAVI clinical, aortic stenosis, CFD/biomechanics literature are mostly elsewhere → OpenAlex, PubMed / Europe PMC, Semantic Scholar needed.
- **Depth:** title + abstract only → enough for routing and screening, not for claim extraction with spans.

## research-factory-old (`~/Projects/research-factory-old`)

Assessed 2026-10-31. Python 3.12, ~2.8k lines in `src/rf` (pydantic models, typer CLI), 150 tests. File-based: every work is a Markdown note with YAML frontmatter; decisions, claims and protocol versions are YAML files; the CLI never calls a model; agents work through task files (`rf screen --next`) and answer files validated on the way back (`rf screen --record`). Built for GitHub Copilot (`.github/skills`, `copilot-instructions.md`).

Measured: **150/150 tests pass**; coverage 54% overall — core modules 85–98% (ids, model, dedup, sources, fulltext, storage, screening), later modules 16–54% (cli 16%, synth 24%, ingest 24%, wiki 27%, entities 27%, probe 37%, lock 38%, claims 48%); `mypy --strict` fails with 11 errors (cli.py, synth.py, claims.py); ruff reports 10 issues.

### Verdict
Its **literature-acquisition and screening core (stages 00–04) is more mature than what we had planned** and should be the basis of those parts of the factory. Its **scope and storage model do not fit the factory** (single question, file-per-work, no graph, no teams). The later stages (claims, wiki, synthesis) are project-specific and weakly tested.

### Reuse — code (port with tests, light changes)
| Module | Why |
| --- | --- |
| `model.py` (`Work`, `Identifiers`, `Provenance`) | One record type for all literature incl. grey; identifiers normalised on construction; **a work cannot exist without provenance** (construction-time invariant) |
| `ids.py` | Deterministic, content-derived IDs; arXiv-DOI bridging (DataCite DOI ↔ bare arXiv ID) |
| `dedup.py` | 4-stage cascade (DOI → other IDs → title+author+year → fuzzy title), union-find merge, reversible merge map; 98% covered |
| `sources/base.py` + `openalex.py`, `arxiv.py`, `pubmed.py` | Common adapter contract; records **reported vs. retrieved counts**; archives raw pages as they arrive; resumable; 85–92% covered |
| `fulltext.py` | Full-text routing and quality labels |
| `screening.py` (core) | Version-qualified criteria (`P@sha:EX03`); `cannot-assess` promotes; exemplar/seed checks per stage; validation at the boundary; supersede-not-edit decisions; 87% covered |

### Reuse — ideas and specs (adopt into our design)
- **Traceability chain** (question → protocol → criterion/query → run → raw payload → record → merge → work → decision → full text → claim → synthesis sentence) with `trace` (both directions) and `check` (fails on any broken link).
- **Rigor modes** (`exploratory` / `pilot` / `systematic`) with **retroactive promotion** that emits a gap list; provenance and protocol versioning are mandatory in every mode.
- **"Amend freely, record always"**: protocols are versioned (hash over criteria, sources, queries, limits — not prose), amendments carry reason, `semantic` flag, and a computed blast radius of stale decisions. Better than our "immutable protocol" wording.
- **Scope probe stage** with positive and negative **seed papers**: known-item recall/precision testing of queries before the protocol is fixed; harvested vocabulary; screening-cost estimate.
- **Dual independent screening + Cohen's κ floor + ~30-record human calibration set**; disagreements always routed to a human.
- **Stage contracts** (input, actor, skills, procedure, output, gate, failure modes) with machine-checkable gates.
- **"Ask when the answer changes what gets recorded; decide when it only changes convenience."**
- Standards: PRISMA 2020, PRISMA-P, **PRISMA-S** (search reporting), MECIR, GRADE / RoB 2 / ROBINS-I (item-level answers, not summary grades), **AACODS** for grey literature.
- The `rf-screen` / `rf-probe` / `rf-derive` skills as drafts for the factory plugin.

### Do not reuse
| Item | Reason |
| --- | --- |
| File-per-work storage and whole-file YAML logs as the store | "Append-only" is by convention (logs are rewritten on save); unsafe with concurrent sessions or several people; the author notes grep degrades at ~300–800 works; no cross-project graph queries |
| `cli.py` (1,550 lines, 16% covered, fails strict typing) | Business logic lives in the CLI; rebuild as services behind MCP tools + thin CLI |
| `claims.py`, `entities.py` | Hard-wired to one survey (design-decision claims; ML evidence classes; Hugging Face model families) despite claiming the protocol defines the schema → must become schema-driven |
| `wiki.py`, `synth.py`, `funnel.py`, `probe.py`, `steps.py` code | Weakly tested; re-derive from specs (stages 05–09 have no written specs) |
| ~50 vendored third-party skills (posters, infographics, grant writing, …), nested duplicates | Noise, unclear licences/provenance; keep only reviewed, relevant ones |
| Copilot-specific setup, `ONBOARDING.md` template, OneDrive/DrvFs workarounds | Not relevant |

### Points where it changes our design
1. **Storage:** combine both approaches — append-only **event files (JSONL) in git as source of truth**, SQLite as a rebuildable index/projection. Keeps git diffs, human/agent readability and replay, adds queries, concurrency control and scale. (decisions #7)
2. **Agent interface:** MCP tools (typed, validated immediately) rather than task/answer files; but **log the exact task payload the agent saw** in the event, which is what made the file approach auditable. (decisions #26)
3. **Independence of dual screening:** the old design relied on Copilot's model picker for model diversity. On Claude subscriptions only, decorrelation comes from different Claude models and independent contexts — weaker; measure agreement rather than assume independence.
4. **Missing in the old design** (still ours to build): graph and regions, several projects sharing knowledge, teams and ownership, living updates and alerts, hypotheses and experiments.

## scaffold (`~/Projects/scaffold`)

Assessed 2026-10-31. A small Python CLI (`skill-scaffold`) that curates ~50 skills in groups (research, development, reporting, writing/IP, management, workflow) and installs them into a repo for GitHub Copilot (`.github/skills`, `copilot-instructions.md`). `skill-origins.json` records where each skill came from (obra/superpowers, K-Dense-AI/scientific-agent-skills, Orchestra-Research/AI-Research-SKILLs, NeoLabHQ/context-engineering-kit, wondelai/skills, local adaptations).

### Issues
- Many origins pinned to `ref: main`, not a commit → not reproducible.
- Local copies have drifted from their recorded origin (e.g. `brainstorming` is listed as from superpowers but is an 18-line generic stub; `literature-search` likewise).
- Some skills call external image-generation APIs (Gemini / "Nano Banana" schematic and infographic scripts in `scientific-critical-thinking`, `markitdown`, `infographics`) → conflicts with the no-API principle; strip those parts.
- Copilot-specific installer; Claude Code plugins and marketplaces now cover installation.

### Keep the idea
- A **skill provenance manifest** (origin repo, path, commit) — pinned to commit SHAs — for every plugin we assemble.

### Sort of the skills
**A. Building the factory (dev process)**
- obra/superpowers set → install the official plugin instead of vendored copies.
- `kaizen`, `kaizen-why` (five whys), `kaizen-cause-and-effect` (fishbone), `kaizen-analyse-problem` (A3) → small verified improvements; root-cause analysis; usable for blameless postmortems.
- `pragmatic-programmer` (tracer bullets, design by contract), `refactoring-patterns` (porting old code), `repo-learning` (studying arxiv-miner / research-factory-old before porting), `agents-md-writing` (adapt for CLAUDE.md), `clarifying-questions-first`, `markdown-mermaid-writing` (diagrams in docs).

**B. Raw material for the factory's research skills (rewrite, don't install as is)**
- `scientific-critical-thinking` references (evidence hierarchy, biases, statistical pitfalls, experimental design, GRADE / RoB) → appraisal stage; remove schematic-generation parts.
- `critical-analysis` → adversarial critic agent (protocol review before use, claim/synthesis review).
- `creative-thinking-for-research` (bisociation, analogy, adjacent possible, constraint manipulation, …) and `brainstorming-research-ideas` (ten ideation lenses) → structured hypothesis generators; record which framework produced each hypothesis (provenance of ideation). Fits cross-domain transfer between graph regions.
- `markitdown` (Microsoft MarkItDown) → candidate PDF/DOCX/HTML → Markdown converter next to a structured PDF parser; drop its AI conversion script.
- `literature-search-arxiv` → superseded by the ported source adapters; keep its query-syntax reference.

**C. Writing about the work (theses, papers) — separate writing plugin, not part of the factory build**
- `ml-paper-writing`, `academic-text-compressor`, `proofreading`, `academic-plotting`, `scientific-visualization`, `humanize-writing` / `humanizer`, `presenting-conference-talks`, `latex-posters`; later also for the "Communicate" production line.

**D. Not relevant to the factory**
- `negotiation`, `horizon-grant-writing`, `call-compliance` (EP PerMed call), `section-objective-analysis` (v1, v2), `wp-evaluator`, `infographics` (external image API); `html-report-design` and `analytical-design` (Tufte) only later, for dashboards; generic stubs `brainstorming` and `literature-search`.

## External: research-superpowers (kthorn/research-superpower)

Checked 2026-10-31 (README only). MIT, experimental, ~129 stars / 30 commits; inspired by obra/superpowers, not part of it. Claude Code plugin for literature search and review: skills for screening rubrics, PubMed search, two-stage relevance (abstract scoring, then full text), parallel subagent screening (50+ papers), citation traversal (Semantic Scholar), open-access finding (Unpaywall), ChEMBL checks, session clean-up. No API keys required. Biomedical/chemistry focus; no arXiv.

Assessment: not a factory component and not suited to the ML pilot (PubMed-centred). Its approach (relevance scoring, intermediate files cleaned up after a session) is weaker than our rigour requirements (criterion-based decisions, dual screening, permanent provenance) — to confirm by reading its skills. Worth mining for ideas: building and testing screening rubrics against known examples (cf. seeds), Unpaywall-based open-access discovery (slice 2), Semantic Scholar citation traversal (snowballing). Possibly handy for quick exploratory biomedical look-ups (e.g. TAVI clinical) outside the factory.

