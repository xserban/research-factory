# Slice 1 — Literature review tracer bullet

Status: draft for review · 2026-10-31 · Builds on [00-system.md](00-system.md) and must satisfy [01-rigour.md](01-rigour.md) requirements R-01–R-39 for its stages (pilot and systematic modes).

## Goal

A researcher, working with Claude Code, takes one research idea from a question to a screened, deduplicated corpus with PRISMA counts and a complete trace — with every step recorded as events.

Pilot idea for acceptance: **best linear attention mechanism for vision models** (project B).

## User flow

1. `factory init linear-attention-vision`; set rigor mode (`pilot`).
2. **Question:** Claude interviews the researcher (≤5 questions); the raw goal (verbatim), the decomposed question elements and explicit non-goals are recorded (`Q@sha`).
3. **Seeds:** the researcher names known in-scope papers (positive) and known out-of-scope look-alikes (negative); the platform resolves them to works and draws a recorded random development/held-out split of the positives (R-20).
4. **Scope probe:** Claude proposes candidate queries per source; the platform runs them and reports recall on positive seeds, hits on negative seeds, result counts and harvested vocabulary; iterate until recall is acceptable.
5. **Protocol:** method profile declared (R-60); criteria with IDs (`IN01`, `EX03`), each naming its parent question element or non-goal, with `applies_at` and priority; sources; final queries with all PRISMA-S fields; limits; screening plan, reviewer roles and κ floor declared before screening → `P@sha`. Amendments are allowed at any time, with reason and `semantic` flag; affected earlier decisions are computed and marked stale.
6. **Search:** after a PRESS review of the search strategy (R-61), queries run on OpenAlex and arXiv; raw responses archived as blobs; reported vs. retrieved counts recorded.
7. **Deduplication:** cascade merge; every merge recorded and reversible.
8. **Screening (title/abstract):** two independent passes (A: inclusion framing, B: exclusion framing, reversed criterion order, different Claude models, separate sessions) through `screen_next` / `screen_record`; fresh context and randomised order per batch; seeds pinned as worked examples; every rationale quotes a verified title/abstract span; four verdicts; Cohen's κ per criterion; disagreements and `unsure` routed to the human.
9. **Audit:** the human labels a calibration set (~30 records, incl. seeds) before screening, resolves disagreements and `unsure` records, and audits a random sample of agreed decisions (R-35–R-37).
10. **Supplementary search:** backward and forward citation chasing from included works; seed admission for explained misses (R-24, R-25).
11. **Reports:** PRISMA 2020 flow and PRISMA-S search report derived from events; methods statement disclosing automation; `trace` from any decision back to the question; `check` lists broken links and promotion gaps.

## In scope

| Area | Content | Origin |
| --- | --- | --- |
| Platform core | Event envelope, writer, reader, validation; blobs; SQLite projector with deterministic rebuild; task queue | New (00-system.md) |
| Models | `Work`, `Identifiers`, `Provenance`, `Question`, `Seed`, `Protocol`, `Criterion`, `Query`, `SearchRun`, `Merge`, `Decision`, `Task` | Port `model.py`, `screening.py` models from research-factory-old; adapt to events |
| Identity | Work IDs, arXiv/DOI bridging, title normalisation | Port `ids.py` |
| Sources | Adapter contract (reported vs. retrieved, raw page archiving, resume token); OpenAlex; arXiv | Port `sources/base.py`, `openalex.py`, `arxiv.py`; reuse arxiv-miner's polite rate limiter (generalised per host) |
| Dedup | 4-stage cascade, union-find, reversible merges | Port `dedup.py` |
| Protocol | Versioned hash (prose excluded), amendments, stale-decision computation | Port hashing logic from `lock.py`; amendment logic from research-factory-old spec `RIGOR-MODES.md` |
| Probe | Seed recall/precision per query and source; vocabulary harvesting | Re-implement from spec `stages/01-scope.md` (old code 37% covered) |
| Screening | Validation at the boundary (criterion must exist in the protocol version; exclusion needs a criterion and rationale); `cannot-assess` promotes; supersede-not-edit; dual pass; κ; exemplars | Port `screening.py` core |
| Reports | PRISMA counts, `trace`, `check` (incl. promotion gaps) | New |
| MCP tools | see below | New |
| Plugin skills | `rf-frame`, `rf-probe`, `rf-protocol`, `rf-screen` | Adapt from research-factory-old skills and stage specs |

### MCP tools (slice 1)
`project_status` · `question_record` · `seed_add` · `probe_run` · `protocol_record` · `protocol_amend` · `protocol_deviation` · `search_run` · `search_chase` · `dedup_run` · `calibration_label` · `screen_next` · `screen_record` · `screen_agreement` · `audit_sample` · `audit_record` · `report_prisma` · `report_methods` · `trace` · `check`

## Out of scope (later slices)
Full text and claim extraction; PubMed and other sources; graph, regions and labels; living updates and alerts; embeddings; teams, ownership and server deployment; hypotheses and experiments; user interface.

## Acceptance criteria
1. **Rebuild determinism:** deleting the index and running `factory rebuild` yields the same state hash.
2. **No provenance, no work:** constructing a `Work` without provenance fails.
3. **Deduplication:** the same paper returned by OpenAlex (DataCite DOI) and arXiv (bare ID) becomes one work with two provenance entries; the merge is listed and reversible.
4. **Counts:** for every search run, reported and retrieved counts are stored; a shortfall is visible in `status`.
5. **Validation:** `screen_record` rejects (and writes nothing for) a decision that cites a criterion absent from its protocol version, or an exclusion without criterion or rationale; valid items in the same batch are recorded.
6. **Amendments:** loosening an exclusion criterion marks earlier exclusions citing it as stale; a prose-only change produces no new `P@`.
7. **Probe:** `probe_run` reports recall on positive seeds and hits on negative seeds per query and source.
8. **Dual screening:** κ is computed from passes A and B; disagreements are listed; neither pass can read the other's decisions through the tools.
9. **Trace:** `trace <decision>` returns the chain decision → criterion → protocol version → question; `trace --forward Q@…` lists what the question produced.
10. **PRISMA:** every PRISMA number is derived from events; none is entered by hand.
11. **Agent audit:** every agent decision event carries the model name and an `input_blob` containing the exact task content.
12. **End-to-end:** the pilot project runs through steps 1–11 with ≤ 300 retrieved records; the run is reproducible from the committed events.
13. **Parentage:** a criterion without a parent question element or non-goal is rejected (pilot/systematic).
14. **No truncation:** source adapters never request relevance-sorted subsets; a test fails if retrieved < reported without a recorded reason.
15. **Seed check:** after search, every positive seed is retrieved or carries an explanation and admission route; otherwise `check` fails.
16. **Quotes:** a screening rationale whose quote is not verbatim in the title/abstract is rejected.
17. **Independence recorded:** each pass records model, framing and criterion order; `screen_agreement` refuses to compute κ for two passes with identical configuration.
18. **Calibration and audit:** screening is blocked until the calibration set is labelled; `audit_sample` draws ≥2% (min. 50) of agreed decisions, 3:1 towards exclusions; error rates are reported.
19. **Deviations vs. amendments** are stored separately and both appear in the methods statement.
20. **Promotion:** `check --promote-to systematic` on a pilot project lists the missing items (e.g. single-pass records, missing audit).
21. **Quality:** `mypy --strict` and ruff pass; coverage ≥ 90% for `services/` and `model/`.
22. **Seed hold-out:** the split is drawn by the platform with a recorded random seed; `probe_run`, worked-example selection and agent-facing tools never return held-out seeds; `report_methods` reports held-out and development recall separately.

## Open questions for this slice
- Threshold for acceptable seed recall in the probe (proposal: ≥ 0.9 in `pilot`, 1.0 in `systematic`).
- κ floor in `pilot` mode (proposal: advisory; floor 0.7 in `systematic`).
- How the two screening passes are made independent on Claude only (different models per pass; separate sessions; no shared context) and how that is recorded.
- **Session identity (from plan-1 review):** subagents of one Claude Code session share the MCP server process and hence its session ID, so task claims cannot tell them apart. Proposal: passes A and B run as separate Claude Code sessions (enforced: `screen_agreement` refuses passes sharing a session ID); alternatively a per-agent claim token. Decide in plan 4.
- **Provenance trust (from plan-1 review):** `model` and `skill` are currently tool arguments supplied by Claude. Proposal: the platform computes the skill hash from the plugin's skill file; investigate whether a Claude Code hook can supply the serving model; otherwise store `model` as agent-reported and say so in `report_methods`. Decide in plans 3–4.
