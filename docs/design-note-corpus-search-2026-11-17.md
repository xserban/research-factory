# Design note: arguing hypotheses against the corpus (IDEA-88)

Status: draft for a spec · 2026-11-17 · rulings below were made by the researcher on 2026-11-17; nothing here is a *Decided* entry yet
Replaces: the first version of this note (same date), which was built around passage retrieval (RAG) alone.

## 1. Purpose

The factory exists to bounce hypotheses off the literature and obtain arguments, not only to generate hypotheses. This note designs that function:

- **Spar**: the researcher states a hypothesis; the corpus is read for arguments against it and then for it; the result is a recorded **argument sheet** with checked quotes and a computed coverage statement.
- **Ask**: a NotebookLM-like question over the same pipeline, lighter, not recorded unless asked.

## 2. Rulings (researcher, 2026-11-17)

| # | Topic | Ruling |
|---|---|---|
| 1 | Technique | Not retrieval alone: a **candidate funnel** in which every available source proposes papers, and tiers decide how deeply each is read (§4). |
| 2 | Bias guard | Arguments **against** are written first. When a sheet will feed a lead, a **separate session** writes the case for. |
| 3 | Modes | **Explore** (cheap, capped) and **Prepare** (exhaustive, before registration). |
| 4 | Default scope | The **core layer** (~95 works); a sheet may widen or narrow it. |
| 5 | Ask | Same pipeline, lighter: no against/for split; not recorded unless the researcher asks. |
| 6 | Digest | A **paper profile** built from what is already mined: `m-summary` v2, the label miners, the eight technique miners, and **claims** (plan 2D), which must first be extracted for the core layer. No new summary miner. |
| 7 | Filter | Claude maps the hypothesis to miner categories as a **tick list with counts**; the researcher ticks; the selection is recorded on the sheet. |
| 8 | Search | v1: **keyword** (SQLite FTS5) as a source and safety net. Meaning-based search later, after its own evaluation, without changing the pipeline. |
| 9 | Tiers | Tier 1 full text, tier 2 partial, tier 3 profile only (§6). |
| 10 | Assessment | A sheet ends with **Claude's balance**, labelled as Claude's judgement; the researcher may record their own beside it. |
| 11 | Budget | Explore: at most **15 works** in tier 1; above that Claude stops and asks (continue, or switch to Prepare). |
| 12 | Success (v1) | **≥ 80 %** of the papers listed in test set B appear among a sheet's candidates; the researcher rates **~30 arguments**. |

## 3. Why not retrieval alone

| Question kind | Example | Needs | Technique |
|---|---|---|---|
| Lookup | "Which papers evaluate on GPQA?" | A few passages | Search |
| Structural | "What builds on AI Scientist?" | Relations | Lineage graph, taxonomies |
| Global | "What are the arguments against H?" | Every relevant paper | Reading all of the scope |

Spar is a global question. Top-k retrieval returns what the queries matched and hides what they missed; for the case against a hypothesis, unsearched evidence is the bias risk itself. The funnel therefore reads every in-scope paper at least at profile level, and uses search to propose and locate, not to bound what is considered.

## 4. Architecture: the candidate funnel

```
Hypothesis H (versioned) · mode · scope
   │
   ├─ Miners ─── works carrying the ticked categories (label, technique, m-summary enums)
   ├─ Graph ──── works related to those by lineage edges (stated or confirmed)
   ├─ Search ─── works with keyword hits (if the index exists)
   └─ Claims ─── works with claims whose statement bears on H (if extracted)
   │
   ▼  candidate table: union, each work with the sources that proposed it
   │
   ├─ Tier 1  full text ─── ticked category, or ≥ 2 sources
   ├─ Tier 2  partial ───── one source only
   └─ Tier 3  profile ───── every other work in scope; promoted to tier 1 if relevant
   │
   ▼
Against pass → For pass (separate session in Prepare / for leads) → Balance
   │
   ▼
Argument sheet (event) with computed coverage
```

Each source is optional. A missing source (no search index, claims not extracted for a work) is skipped and named in the coverage statement.

## 5. Sources

### 5.1 Miners (filter)

All listed miners of the project are eligible: `m-classification`, `m-descriptors`, `m-design-approach`, `m-mapping`, `m-layer`, `m-lifecycle`, `m-release`, `m-stages`, `m-stage-steps`, `m-summary` and the technique miners (`m-tech-*`, with taxonomies `t-tech-*`).

Mapping H to categories: Claude lists candidate categories across all miners, each with its definition and the number of in-scope works carrying it; the researcher ticks, adds or removes. The ticked set, with miner versions, is recorded on the sheet.

Known weakness: second-pass agreement in the pilot was 0.5–0.7 on enums, so labels miss works. Search, claims and the tier-3 pass are the safety nets; the coverage statement shows which works came only from them.

### 5.2 Graph

Works linked by lineage edges to tier-1 candidates (stated or confirmed edges only; inferred edges are listed, not followed). Depth 1 in v1.

### 5.3 Keyword search (v1)

SQLite FTS5 over **passages**, not anchored elements. Measured on agentic-science (394 converted works, 104,139 anchored paragraph elements, 4.17 M words): the median element has 13 words, 52 % have fewer than 15, about 13,000 are number-only, and boilerplate and code lines appear as elements. Therefore:

- A **passage** is a run of consecutive elements within one section, packed up to N words (N to be set by evaluation, start 250), never crossing a heading; it records the anchors it covers. Anchors stay the citation unit.
- Indexed text: `title › section path` in its own column, plus the passage text.
- Excluded: number-only elements, a fixed boilerplate list, bibliography entries. Code and display math: open (§11).
- The index is a rebuildable projection keyed by conversion id and chunker version; an event records its hashes and counts.
- Claude writes the queries (several phrasings, corpus vocabulary from `term_list`); for Spar, one query set per argument kind, case against first. Queries are recorded on the sheet.
- Results: work, passage, anchors, section path, text, rank; a per-work cap; no relevance verdict.

Measured 2026-11-18 on the branch `plan-chat` code: the core layer resolves to 92 works, 10.1 M characters of canonical Markdown (about 2.5 M tokens at 4 characters per token; an earlier estimate of 1.3 M from word counts was low). The passage cutter yields 7,576 passages over the 93 works of the technique trial (median 133 words, 7 % under 15 words; 2,162 noise elements skipped).

Side finding: the number-only elements suggest that line-number stripping misses some conversions; to be examined as a conversion defect, separately.

Chunk rules v2 (researcher, 2026-11-18, after inspecting v1: the median passage held one paragraph, 4,073 of 7,482 passages were single paragraphs, 886 had under 30 words, the longest 1,778 words, and related-work and appendix text was indexed like the paper's own results): each passage carries a section kind (front, method, results, discussion, related, appendix, back, other); related-work, appendix and back-matter passages are not indexed, accepting that a related-work sentence no longer points search to the paper it describes (the graph and claims sources cover that); passages under 30 words merge into a neighbouring passage of the same section; for vectors only, a paragraph over about 350 words is embedded as sentence-aligned sub-windows, while the passage and its anchors stay whole for citing. Search can filter by section kind, so the case against can look at results and discussion first. Plan task T3c.

Evaluated 2026-11-18 (core layer, one paper counted once, test set B as in §10): B1 known item in the top 10 papers 47/50 (top 20: 48/50); B2 supporting paper in the top 10 11/12; B2 **contradicting** paper in the top 10 **7/12** (top 20: 8/12). Keyword search finds what shares the hypothesis's words; a contradiction rarely does. It is therefore not sufficient as the source of the case against.

### 5.4 Claims

Claims come from the miner `m-claims` (version 2, registered 2026-11-18; version 1 was withdrawn because its integer row key forced meaningless number quotes). Fields: `claim_type` (finding, mechanism, limitation, negative-result, failure-analysis; absence value no-limitation-stated), `claim_quote` (checked), `about` (own-system, technique, evaluation-method, other-systems, field), `direction`, `evidence_type` (experiment, ablation, human-study, case-study, theory, assertion), `conditions` (optional quote), `strength`. Rows are keyed on `claim_type` and the anchor of `claim_quote`; at most 12 per paper, the paper's own limitations, negative results and failure analyses first. Calibration on 5 papers: the researcher judged all 43 rows correct and none missing (recall, precision and field agreement 1.000). Production pass A over the core layer runs in separate sessions (R-51). The miner is intended as a core miner for other products too. The older plan-2D claim records (2 in the pilot) are not used.

**Matching test, 2026-11-18 (claims reading).** A blind Sonnet session read only a digest of all m-claims v2 rows of the 90 core papers (861 claims, about 40 k tokens) and the 12 B2 hypotheses without answers, and listed up to 10 papers against and 5 for each. The planted contradicting paper was listed in 11 of 12 (keyword search 8, SPECTER2 5), including all four that both search methods missed (ranks 1–7); with keyword search added, 12 of 12. The supporting paper was in the FOR list in 9 of 12. The one miss (B2-g1-02) is the item already judged weak. Caveats: lists are long (about 9 papers per hypothesis, so precision is not measured — the researcher's argument rating, §10, measures it); B2 was written from the same papers' text, which may favour any source built from that text; one paper (gottweis2026) has no mined claims. Conclusion for v1: on a layer whose claims fit one context, Claude reads every paper's claims to propose the case against; keyword search finds passages and adds recall; meaning-based vectors are not used.

**Hybrid test, 2026-11-19 (branch embeddings-search, chunker v4, SPECTER2 base, 6,485 core passages embedded in about an hour on CPU).** Top 10 (top 20) works: keyword B1 47 (48)/50, B2 against 8 (8)/12, supporting 11 (11); vector B1 32 (40), against 5 (8), supporting 9 (11); hybrid by rank fusion B1 46 (47), against 7 (8), supporting 11 (12). Hybrid does not beat keyword at top 10. At top 20 vector finds one contradicting paper keyword misses (B2 item 9), but rank fusion pushes it out; the union of keyword and vector lists (top 20 each) reaches 9/12. Reading the whole claims digest stays best (11/12).

### 5.5 Meaning-based search (embeddings)

**Unit.** One vector per passage (§5.3): the passage is the chunk of the usual retrieval terminology. It is cut along the paper's own paragraphs and sections, not every N tokens, so a hit maps to the anchors it covers and a quote stays checkable. Units: the passage is searched, the anchor is cited, the paper is selected and read.

**Storage.** The vectors are a rebuildable cache, like the keyword index, and are neither events nor part of the projected SQLite index (they are computed from pinned conversions by a named model, not projected from events). Table `passage_vectors(conversion_id, passage_id, model_key, vector)` in the passage sidecar `projects/<slug>/.cache/passage_index.sqlite`; `model_key` = model id, weights hash and chunker version, so a new model, cutter or conversion recomputes only what changed, and older keys stay until pruned so a recorded search can be replayed. Float32 at 768 dimensions is 3 KB per passage (core layer: 23 MB). Per project in v1; a machine-wide store keyed by conversion content is possible later.

**Model.** A local model directory configured in the environment, as `FACTORY_RANKER_MODEL` is for the ranker; its id and weights hash are recorded. A local embedding computes and does not judge, so the rule that the platform never calls a model holds (precedent: the ranker).

**Building.** On demand at the first search over a selection (missing passages only, reported), a full rebuild from the CLI, and `factory check` reports passages without a vector for the configured model.

**Search.** Exact: the query vector is compared with every passage vector of the selection (a mask over one matrix), ties broken by id. Milliseconds at 7.5 k passages, about 0.1 s at 80 k. Exact search is preferred to approximate (HNSW) search because an approximate index can silently drop a near match, which is the failure the case against must avoid, and because a recorded search must replay to the same ranks.

**What is recorded.** Not the vectors. When a search feeds an argument sheet, the sheet records the query, the model key, the selection digest and the passages returned with their ranks.

**Vector database.** Not in v1. All vector access goes through one module (`add`, `search(query, selection, k)`), so a move to an embedded index (sqlite-vec or LanceDB, preferred to a server) changes one module. Move when the searchable corpus passes about 500 k passages, a search takes over a second, or a machine-wide store is wanted; approximate search is then accepted only after a recall check against exact search on test set B.

**Evaluation.** First experiment 2026-11-18: SPECTER2 base (the ranker's model, trained on title and abstract, not on passages; a lower bound) over the core passages, scored on B1 and B2 like the keyword search. Result (7,482 passages, 23 MB, 62 min on the CPU): B1 known item in the top 10 papers 30/50 (keyword 47/50); B2 contradicting paper in the top 10 5/12 (keyword 7/12, and 8/12 with chunk rules v2). Every contradicting paper the vectors found, keyword search found too, so the union adds nothing; four contradicting papers are missed by both. SPECTER2 base on passages is therefore not used. Whether a retrieval-trained model is worth its download is decided after the profile-reading test (§6.1), which targets those four. Chunk rules v2 left B1 unchanged (47/50) and raised the B2 contradicting count from 7 to 8. **Re-measured after the review (chunk rules v4, plan-chat 03b6a90f):** section kinds no longer over-match (a bare lettered heading is an appendix only after the references; whole-heading word lists; the innermost heading decides; a related-work heading nested in a method, results or discussion section keeps that kind); appendices are indexed and tagged, because they hold ablations and extended results (researcher, 2026-11-18). Only related work and back matter are dropped: about 52,000 of 1.06 M words (5 %). Keyword search: B1 47/50, B2 contradicting 8/12 in the top 10, confirmed; the same four contradicting papers are missed.

## 6. Tiers and reading

| Tier | Entry rule | Read | Output |
|---|---|---|---|
| 1 | Ticked miner category, or proposed by ≥ 2 sources, or promoted from tier 3 | Full document (`document_read`) | Arguments with checked quotes |
| 2 | Proposed by one source only | Abstract, profile, the passages found and their neighbours | Arguments with checked quotes; may be promoted to tier 1 |
| 3 | In scope, proposed by no source | Profile only | Promote to tier 1, or "no bearing" (recorded) |

### 6.1 Paper profile (the digest)

A computed, read-only view per work, built from final rows only (no superseded rows, one resolved value per field):

- bibliographic line (title, year, venue);
- `m-summary` v2: problem/gap, core innovation, contribution type, innovation axis, builds on (relation), improves over (aspect);
- label miners: one line per miner with its category values;
- technique miners: technique names per stage;
- claims: statement, type, evidence type, strength.

Quotes and anchors are not shown in the profile; they are fetched when an argument cites them. **Size, measured 2026-11-17:** the raw mined output is ~52k characters per work (median; p90 ~97k), including both passes, superseded rows and JSON structure. The compact profile must be measured once built; if 95 profiles exceed one context, tier 3 runs in batches (e.g. 4 × ~25 works), each batch returning promotions and "no bearing" lines.

## 7. Modes and sessions

| | Explore | Prepare |
|---|---|---|
| Tier 1 | Rule of §6, capped at 15 works; above that Claude asks | Every candidate; cost estimate shown before the run |
| Tier 3 | Profile pass over all in-scope works | Same |
| Against / for | Same session; against section closed before for section opens | For section written by a different session (independence as for `hypothesis_review`) |
| Feeds a lead | Only after re-running as Prepare | Yes (`lead_record`) |

## 8. The argument sheet

Recorded content:

1. Hypothesis text (versioned), mode, scope, ticked categories with miner versions, queries sent.
2. Candidate table: work, sources that proposed it, tier, promotion reason (if any), "no bearing" (if any).
3. Arguments, each: stance (against / for / qualifies), kind (finding, mechanism, analogy, limitation, conflicting result), claim, conditions, anchors with quotes checked by `quote_in_element` at the boundary, Claude's strength rating (labelled as judgement), source claim id when it rests on a claim.
4. Coverage, **computed**: works per tier, works per source, sources unavailable, works with missing profile parts (no claims, unmined), absence statements allowed only over mined fields with an absence policy.
5. Balance: Claude's short assessment (e.g. "weakly supported, only under conditions X"), labelled as judgement; optional researcher assessment.

Events (provisional names): `sheet.opened`, `sheet.candidates_recorded`, `sheet.argument_recorded`, `sheet.section_closed`, `sheet.balance_recorded`. Corrections supersede; nothing is edited. Every agent-written event carries model, skill version and `input_blob`.

## 9. Ask mode

The same sources and candidate table; no stance split; the answer cites anchors with checked quotes. Not recorded unless the researcher asks; when recorded, it is a sheet of kind `ask` without the balance. Small scopes (≲ 10 works) may skip the funnel and read in full.

## 10. Evaluation

### 10.1 Test sets

- **B (primary)**, in three parts (ruling 2026-11-17), with targets reported per part:
  - **B1, known items (~50):** a Claude session that never sees miner output, claims or profiles reads a randomly drawn section of a core work and writes a question or hypothesis that the section answers, paraphrased (no distinctive words copied, so keyword search gains nothing). Target: that work. Tests recall for single works and catches works the miners mislabelled.
  - **B2, planted contradictions (~10):** the same blind session finds, in full text, a finding in one work and a limitation or conflicting result in another, and phrases the finding as a hypothesis. Target: the second work appears as an argument against. Tests the bias guard.
  - **B3, researcher (10–15):** Claude drafts ~25 hypotheses and questions from the project question and taxonomy (not from mined rows), in `docs/testset-b3-drafts-2026-11-17.md`; the researcher keeps 10–15 and supplies the expected works. Tests global questions and real use.
  - Why not all by Claude: expected works chosen from the mined picture would grade the pipeline against its own view; B1 and B2 avoid this by drawing targets from full text in a blind session; B3 carries knowledge from outside the factory.
  - None is drawn from `docs/pilot/heldout-seeds.md` (template §13).
  - Generated 2026-11-17: B1 (50 entries) and B2 (12 entries) in `data/projects/agentic-science/ops/testset-b-2026-11-17/` (method, checks and review in its README); all quotes pass `quote_in_element`; two B2 pairs judged weak. One B2 quote passed only after unescaping `&amp;`: agents copy Markdown, the check compares plain text (IDEA-85), which the argument-sheet tools must handle at the boundary.
- **A (search component only):** category definitions as queries; passages containing that category's mined quotes as targets; recall only (labels are incomplete).

### 10.2 Measures

| Measure | Computed by | Target (v1) |
|---|---|---|
| Paper recall: share of expected works among candidates | Platform | ≥ 80 % |
| Share of expected works reaching tier 1 | Platform | Reported |
| Source credit: which source proposed each expected work | Platform | Reported; decides whether search earns its place and whether meaning-based search is needed |
| Stance recall: known undermining works appear as arguments against | Platform from researcher labels | Reported |
| Argument quality on ~30 arguments: correct / misread / irrelevant | Researcher | Reported; misreads examined |
| Explore against Prepare on 3–5 hypotheses: what Explore missed | Platform | Reported; decides whether the 15-work cap is safe |

## 11. Open questions

1. Code and display math in the keyword index: searchable or excluded?
2. First search index: core layer only, or all 394 converted works?
3. Line-number defect: fix in conversion before indexing, or filter at indexing?
4. Claims extraction for the core layer: which model for pass A, sample size for pass B (the miner regime: 10 % dual, 2 % audit)?
5. Profile size: measure once built; batch size for tier 3 follows from it.
6. Sheets and the idea graph: does an argument become graph material (relation of a claim to a hypothesis), or only the lead?
7. Living loop: when a new work enters the core layer, which open sheets are flagged as stale?
8. Interface: MCP and skill only in v1, or a hub page listing sheets?

## 12. Build order (proposed)

1. Claims extraction on the core layer (existing route; no platform change).
2. Paper profile view (read-only, computed) and its size measurement.
3. Keyword passage index (projection) and `corpus_search`.
4. Sheet events, tools (open, record candidates, record argument, close section, record balance), coverage computation, quote checks at the boundary.
5. Skill `rf-spar` (Explore and Prepare, against-first) and Ask as its light form.
6. Evaluation on test set B; then decide on meaning-based search.

Platform rules apply throughout: no model calls; business logic in `services/`; validation at the boundary; counts and coverage computed, never typed.

## 13. Template for test set B

```
id: B01
kind: question | hypothesis
text: <as you would ask it>
expected_works: <work ids or titles known to answer it>
supports: <for hypotheses: works that support it, if known>
undermines: <for hypotheses: works that undermine it, if known>
note: <optional: why this is a hard case>
```
