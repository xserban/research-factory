# Version pairs and identifier-less works (IDEA-56)

Status: accepted by the researcher 2026-11-11 (scope "importer fix + dedup version pairs"; rulings below are Claude's recommendations, adopted under the standing rule). Decision 117. Branch `plan-version-pairs` from `plan-8-suggest-select`. Testing is paused: mypy and ruff only, no tests written or run (see the untested-work list).

## Evidence (pilot `agentic-science`, 2026-11-11)

Seven included works with a PDF on disk could not be attached (demo log, 2026-11-10). Traced in the index:

| Works | What happened | Cause |
| --- | --- | --- |
| nagele, navarro, wehr | Preprint and journal record merged by DOI; the file's DOI matches both records: `ambiguous` | `import_folder` matches every record (`list_works`), absorbed ones included |
| kim (GPT-6 Astra), qian (HypoForge) | Merged by title+author; the file's arXiv id matches the absorbed arXiv record: `not_promoted` | same: promotion is read on the absorbed record, not the canonical work |
| gim, jayesh | No identifier on any record; files named by work id | the filename is read for DOIs and arXiv ids only |

Separately, the screened corpus holds 318 unmerged pairs with normalised-title similarity ≥ 85, many identical titles. The cascade's title rule requires the same first surname; the misses are records whose first author differs in metadata (a year parsed as a surname, `20262026-…`; author order differing between arXiv and journal; romanised against native script). These are version pairs or duplicate records that the cascade, rightly tuned against false merges, leaves apart.

## Part A: the importer reads merged works

`services/fulltext_import.py`, `cli/render.py` (`import_lines`). No event, table or projection change.

1. **Canonical resolution.** Each corpus record maps to its canonical work through the active merges (absorbed → primary); a canonical work's keys are the union of its members' keys. A file's matches are the distinct canonical works whose keys it carries. Promotion is read on the canonical work.
2. **Ambiguity names its candidates.** `ambiguous` entries carry the candidate canonical work ids, and the CLI prints them.
3. **Work-id filenames.** A filename whose stem is a work id without its `rf:` prefix (`gim2026-development-llm-framework-47c90889.pdf`) matches that work (resolved to its canonical work). It is the researcher's own naming, like a filename identifier, and is not title-checked.
4. **First-page title match.** A file with no identifier and no work-id name is compared, on its first page, with the titles of the promoted canonical works. Exactly one title found → `identity_unchecked` with that work named; it is imported only when the researcher passes it in `accept`. Never imported silently. More than one → `ambiguous` with the candidates.

## Part B: version-pair proposals in dedup

Core dedup; critical module. Gate floor human in every mode.

### Rulings (decision 117)

1. **Candidates are computed, never merged automatically.** Among canonical works, a pair is a candidate when normalised-title `token_sort_ratio` ≥ 95, the shorter title has at least 4 tokens, the years differ by at most 2 (or one is missing), and the pair is not in one group, not blocked and not decided. First-author agreement is not required (that is the cascade's rule and the cause of the misses); the shared surnames across both author lists are shown as evidence. Version-link conflicts (`versions.link_conflicts`) are candidates too, with basis `version-link`.
2. **The researcher decides each pair:** `same` or `different`, with a rationale. Event `dedup.pair_decided` (human actor; payload `work_a < work_b`, `decision`, `rationale`, `basis` with score and source). The latest decision for a pair is in force.
3. **Effect through the cascade, so reconciliation keeps it.** `same` pairs are passed to `dedup()` as forced unions (`joined`), with rule `version-pair`; `different` pairs join the blocked set. A `dedup_run` or incremental run therefore produces, keeps or reverts the merge like any other. A block wins over a join: a manual revert of such a merge blocks the pair as today.
4. **Identifiers and primary:** `merge_works` as today (the ranked primary keeps its identifiers and fills empty ones from the others).
5. **Counts:** a version pair counts once, as one work. Duplicates removed (PRISMA) includes it; the PRISMA report states, in the identification box notes, how many merges rest on a researcher's `same` decision, so the change is never silent.
6. **Late merges:** both records keep their screening decisions and miner rows (existing behaviour for late merges). A new check code `version-pair-outcome-conflict` (warning) lists merged groups whose members' final title/abstract outcomes differ.
7. **Surfaces:** CLI only in v1: `factory dedup pairs [--limit N]` (candidates with evidence, best first), `factory dedup pair <work_a> <work_b> same|different --rationale TEXT`. No MCP tool; the agent relays the command (`project_status` `human` lists the count of open candidates).

### Tasks

1. Model `PairDecided` in `model/dedup.py`; register `dedup.pair_decided` in `events/catalog.py`; table `dedup_pair_decisions` and handler in `index/dedup.py` (total: a non-human actor, a pair not sorted or a self pair changes nothing); wire in `index/default.py`; `OMITTED_WHEN_EMPTY`; `PROJECTION_VERSION` 74 → 75; ownership and gate `dedup.version_pair` in `services/modules/dedup.py`.
2. `dedup_cascade.dedup(..., joined=...)` forced unions with rule `version-pair`, blocks winning; `services/dedup.py` reads joined pairs (`joined_pairs`) and passes them in `_reconciliation`; same in `services/dedup_incremental.py`.
3. `services/version_pairs.py`: `candidates(project, limit)` (ruling 1, bounded by title-token blocking as `nearmiss` does), `decide_pair(project, actor, a, b, decision, rationale)` (validates both works exist and are canonical, sorted pair, human actor through `require_gate`).
4. PRISMA note (ruling 5), check code (ruling 6), human queue count (ruling 7).
5. CLI commands and rendering.
6. Regenerate `docs/MAP.md`; backlog IDEA-56 → accepted (this plan); decision row 117.

## Pilot run (after build)

Dry run on a copy of the pilot project: `factory fulltext import ~/Documents/research-factory-pilot/staging-7` and `factory dedup pairs`; report where each file lands and the candidate count before anything touches the real project.

## Later

Miner rows and documents of an absorbed record are not moved to the primary. Candidate thresholds are not calibrated; the pilot's 318 pairs at ≥ 85 are the calibration set once the researcher has decided a sample.
