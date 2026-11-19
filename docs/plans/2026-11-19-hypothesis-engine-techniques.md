# The hypothesis engine and the mined ideation techniques: mapping, adoption and the first slice (plan, 2026-11-19)

Status: plan for the researcher's validation (2026-11-19). Nothing built, nothing run, no model called, no web; no event written. Builds on `docs/plans/2026-11-14-hypotheses-engine.md` (the engine plan: its parts, gaps G1 to G9, decisions D1 to D8), slice 6 (`docs/specs/slice-6-hypotheses.md`, decisions 67 and 68, R-50 to R-54, R-120 to R-125), the technique graph plan (`2026-11-18-technique-graph.md`) and the papers chat plan (`2026-11-17-chat-with-a-layer.md`). Decisions up to 140 exist; any decision below is "number to be assigned at merge".

How this plan was made: I read the two plans above, the trigger model (`platform/src/factory/model/hypotheses.py`), `services/leads.py` (`trigger_issues`, `lead_keys`, `prior_for`), the header of `services/claims_digest.py`, `services/technique_rank.py` and the candidate builders in `services/technique_graph.py`, the lead skill `plugin/skills/rf-ideate`, and the hub payload `data/projects/agentic-science/site/hub-ui/data/landscape.json` (the 49 approaches of stage `ideation-hypothesis`: id, name, definition, works). I did not read `hypothesis_review.py`, `hypothesis_gates.py`, `experiments.py`, `evaluation.py`, `directions.py`, `cards.py` or the chat services line by line; statements about them come from the engine plan and the specs and are marked **to check** where a task depends on them. The held-out seeds file was not opened.

The mined techniques are exploratory. The miner `m-tech-ideation-hypothesis` is uncalibrated: agreement between its two passes is 0.46 over all rows and 0.67 over aligned rows for this stage, and no human labels exist. The 49 approaches are what pass A read in the core-layer papers (the works counts below are numbers of works with a pass-A row), not a verified census of the field, and a technique's presence in a published system says nothing about whether it works. Nothing in this plan treats a count as evidence (R-87, R-142).

## 1. Goal and non-goals

Goal. Decide, part by part, which of the mined ideation and hypothesis techniques the platform's hypothesis engine adopts, which it already has, and which it rejects; then fix the first buildable slice (1 to 3 days) that carries the engine from a lead source to a promoted, drafted or parked lead on the real pilot, so that the engine is run, not only built.

Non-goals.
- No model call, key or training in `platform/`. A technique that needs an LLM judge maps to a Claude session working through MCP with recorded provenance (model, skill version, `input_blob`), or it is rejected.
- No change of what counts as evidence. Mined rows and technique candidates stay `interpretation` class, labelled exploratory (R-87, R-142).
- No new test kind, no execution of experiments, no cross-project lead sharing (engine plan G9).
- No code in this document; no change to `docs/backlog.md` or `docs/MAP.md`.

### What exists, and what the pilot has

Built v1 and never run on a real corpus (engine plan section 1): the property vocabulary and cards, `match_query`, the finders, leads (`lead_record`, `lead_decide`, `lead_list`), hypothesis drafts, critic review and registration, experiments, evaluation, the failed-directions registry and the gates. Built since the engine plan: the technique graph with candidate builders (`technique_gaps`, `technique_combinations`, `technique_challenges`, `technique_neighbors`, `derives_from`; exploratory), the ranking arithmetic of `technique_rank.py`, the claims digest (`claims_digest`, miner `m-claims`), the papers chat (selection, passage and meaning search `corpus_search`, argument sheets `sheets.py`) and the skills `rf-ideate`, `rf-critic`, `rf-cards`, `rf-chat`, `rf-technique-bounce`.

The pilot (`agentic-science`) has zero lead, hypothesis, card, idea, interpretation, relation and contribution events (counted read-only on 2026-11-18 for the technique plan; unchanged by this plan). It has about 9,900 extraction rows (miners and the `ai-research-system` pack), resolved reference links (`cites` edges) and the eight technique miners. The recorded protocol has `hypothesis_plan` null and `gate_policies` null, so the pilot-mode presets apply (human lead decision, registration and design freeze).

## 2. The mined techniques mapped onto the engine parts

Parts used (the engine plan's parts, with the generation techniques kept in part 1, and the hypothesis object joined to the test kind): 1 lead sources and generation; 2 lead volume and ordering (engine G4); 3 novelty and prior check; 4 critic and review; 5 hypothesis object and test kind (engine G3, D2); 6 memory (failed directions, insight graph); 7 feedback from outcomes; 8 human steering and gates (engine G5).

Reading the tables. Each of the 49 approaches appears exactly once, in the part where it matters most (its primary part); where it also bears on another part the rationale says so. This keeps one class per technique. Classes: EXISTS (a module already does it), ADOPT-FIRST-SLICE (section 5), ADOPT-LATER, NOT-APPLICABLE (needs a model call inside the platform, training, execution, or data the project does not have), REJECT (conflicts with a rigour rule). Where a technique needs a judge, the Claude session is that judge; its output is a recorded suggestion or `interpretation`, never a platform-computed fact. The number in brackets is the count of works with a pass-A row.

### 2.1 Part 1: Lead sources and generation

| Id | Technique (works) | Class | Rationale |
|---|---|---|---|
| idh-17 | Pre-built knowledge graph or method corpus as ideation context (10) | EXISTS | Lineage graph, technique graph (`technique_landscape`, `technique_view`), cards and `graph_query` are the pre-built structure; read by Claude through MCP. |
| idh-19 | Literature search tool inside the generation loop (live domain record) (15) | EXISTS | Passage and keyword/vector search of the corpus (`corpus_search`, decision 140; skill `rf-chat`) is available to the ideating session; results are quotes, not model memory. |
| idh-20 | Retrieval-grounded generation with structural citation validation and a speculation fence (1) | EXISTS | Verified quotes, resolvable triggers (R-120) and the `interpretation` class (R-87) already fence speculation from cited material; no new rule needed. |
| idh-46 | Anchoring ideation on seed papers or a baseline paper (11) | EXISTS | A lead cites `work` triggers; seeds and the chat selection (`rf-chat`) anchor ideation on chosen papers. |
| idh-49 | Idea expansion and adaptation of prior formulations (4) | EXISTS | `hypothesis_draft` expands a lead (at most 600 characters) into a structured spec; adaptation of a prior formulation is done by the session reading the cited rows. |
| idh-18 | Gap and limitation extraction before ideation (14) | ADOPT-FIRST-SLICE | Rows of `m-claims` (stated limitations, `no-limitation-stated`) are read through `claims_digest`; the missing piece is a citable trigger (section 3a). Gap finders `finder_gaps`, `technique_gaps` exist. |
| idh-40 | Cross-domain mechanism transfer and goal-conditioned concept collision (8) | ADOPT-FIRST-SLICE | `technique_combinations` (pairs of approaches from adjacent stages) and `match_query` with its transfer flag are deterministic concept-collision candidates; Claude only words them. |
| idh-05 | Evolutionary operators on an idea population with LLM-judged fitness (10) | ADOPT-LATER | Crossover is covered by combination candidates; LLM mutation over generations and LLM-judged fitness need a repeated judge (see idh-01); after the first run shows the volume. |
| idh-08 | Role-specialised debate panel with a synthesizer (8) | ADOPT-LATER | Roles (contrarian, pragmatist) map to separate Claude sessions on one argument sheet (`sheets.py`, `rf-chat`); a synthesiser is a session act. Wait for sheets to be used on leads. |
| idh-11 | Consensus gap probing with shared visibility across rounds (1) | ADOPT-LATER | Parallel probing sessions with a shared union of gaps: needs several sessions per run; the gap finders supply the union deterministically first. |
| idh-15 | Chain-of-Ideas: citation-ordered literature chains and trend extrapolation (1) | ADOPT-LATER | Citation chains need resolved reference links (`derives_from`, `graph_edges cites`); trend extrapolation is a session reading; build after the first slice shows whether chains add leads. |
| idh-28 | Decomposition of hypothesis generation into inspiration retrieval and composition (1) | ADOPT-LATER | Retrieval of one inspiration at a time then composition: a procedure for `rf-ideate`, adoptable as skill text; effect unmeasured. |
| idh-39 | Prompted anti-obviousness and technology-first question formulation (2) | ADOPT-LATER | Anti-obviousness prompting is skill text with no platform part; the prior list already blocks repeats; measure first. |
| idh-09 | Persona-, profile- and team-grounded ideation (virtual scientist teams) (3) | NOT-APPLICABLE | Personas and author-profile teams need author metadata and simulated authority; there is one researcher and the independence rule (R-51) is about sessions, not personas. |
| idh-16 | Keyword / concept-network ideation with an explore-expand-evolve loop (2) | NOT-APPLICABLE | Keyword co-occurrence network with a review-trained critic: the co-use graph of approaches (`co_used` in the hub payload) already supplies structure without a trained critic. |
| idh-45 | LLM-seeded symbolic hypotheses with deterministic fitting and scientific priors (2) | NOT-APPLICABLE | Symbolic expression fitting is a modelling domain; no use in a literature-review project, and fitting is execution outside the platform. |
| idh-48 | Perception outputs (vision-language) gating exploration and ideas (3) | NOT-APPLICABLE | A vision-language judge of plots; no plots in a review project and an extra model judgement in the loop. |

### 2.2 Part 2: Lead volume and ordering

| Id | Technique (works) | Class | Rationale |
|---|---|---|---|
| idh-43 | Coordinator, shared task state and queue for research directions (including self-organising teams) (12) | EXISTS | Leads have lifecycle states (open, promoted, parked, discarded) and `lead_list`; a multi-worker dispatcher is not needed for one researcher. |
| idh-04 | Over-generate then screen: a seed pool of N ideas, top-k refined (11) | ADOPT-FIRST-SLICE | Over-generate from computed sources, apply a computed screen (prior list, support, overlap), carry the top-k to the human; breadth and depth separated by the lead gate (section 5). |
| idh-01 | Pairwise tournament ranking of candidate ideas (Elo, TrueSkill, win rate) (6) | ADOPT-LATER | Pairwise judging by a Claude session recorded as a suggestion set (slice 8 pattern, provenance recorded) is feasible; position bias and an uncalibrated judge; add only after computed ordering has been used. |
| idh-02 | Listwise K-way ranking per dimension with weighted combination (2) | ADOPT-LATER | Listwise ranking of a whole pool by one session; same conditions as idh-01; the pool is bounded by the lead cap. |
| idh-03 | Single-pass absolute scoring of ideas on a fixed rubric (LLM judge or self-assessment) (12) | REJECT | Scalar scores of novelty and feasibility, above all by the generator itself, break R-51 (proposer never evaluates) and would read as calibrated numbers (R-142, R-87); the critic checklist stays categorical. |
| idh-21 | Monte-Carlo tree search (UCT / progressive widening) over hypotheses or retrieval (6) | NOT-APPLICABLE | Tree search by UCT needs thousands of evaluated nodes and an execution or LLM fitness per node; registration is one hypothesis at a time. |

### 2.3 Part 3: Novelty and prior check

| Id | Technique (works) | Class | Rationale |
|---|---|---|---|
| idh-12 | Novelty check of a candidate idea against a literature search (17) | ADOPT-FIRST-SLICE | Computed overlap of a lead with the corpus (shared triggers, nearest works by `corpus_search`, nearest approaches by `technique_neighbors`) plus the prior list; Claude reads the passages and states what was found, never "novel" (not found in this corpus). |
| idh-13 | Redundancy and diversity filters among candidate ideas (7) | ADOPT-FIRST-SLICE | Diversity of a candidate against the promoted leads by shared `lead_keys` and technique/stage distance is computed; the prior list is the existing redundancy filter. Embeddings stay optional. |

### 2.4 Part 4: Critic and review

| Id | Technique (works) | Class | Rationale |
|---|---|---|---|
| idh-07 | Generator-critic refinement loop (simulated peer review) (19) | EXISTS | `hypothesis_review_next` and `hypothesis_review` with `rf-critic`: an independent session reviews the artefact; revision is a new draft (`supersedes`). Open rounds are human-bounded. |
| idh-47 | Methodological frameworks and structured trajectories as ideation scaffolds (2) | EXISTS | The `framework` field of a lead, `alternatives` (multiple working hypotheses) and the critic checklist already embed falsifiability scaffolds. |
| idh-10 | Multi-model proposal ensembles with cross-model approval voting (3) | ADOPT-LATER | Critic sessions on a different model, with the model recorded in provenance, would reduce shared bias; votes are counted by the platform; needs more than one model session per review. |

### 2.5 Part 5: Hypothesis object and test kind

| Id | Technique (works) | Class | Rationale |
|---|---|---|---|
| idh-36 | Structured hypothesis or proposal object with pre-declared decision criteria (12) | EXISTS | `HypothesisSpec`: typed statement, variables, prediction with margin, decision rule from a fixed menu, falsifier sentence printed by the platform, frozen `H@` (R-50). |
| idh-38 | Pilot probes and best-supported-group selection among hypotheses (6) | EXISTS | The dev/confirmatory split and unlock nonce (`experiments.py`, R-123) are the pilot probe; best-supported-group selection among probes is not built. |
| idh-37 | Hypotheses as executable programs with a statistical or deterministic verifier (3) | NOT-APPLICABLE | Executable-program hypotheses need the platform to run code; it records runs made elsewhere (decision 67). Relevant to experiment projects, not to a review project. |

### 2.6 Part 6: Memory

| Id | Technique (works) | Class | Rationale |
|---|---|---|---|
| idh-22 | Hypothesis/plan tree or DAG with parent-child lineage and back-propagated insights (6) | EXISTS | Triggers of kind `lead`, `hypothesis`, `direction`, `supersedes` and sibling `alternatives` form the lineage of hypotheses; back-propagation is the prior list. |
| idh-33 | Failure and dead-end memory consulted before proposing (14) | EXISTS | The prior list in `lead_record` and the failed-directions registry (`directions.py`, R-52, R-124) are negative-result memory consulted at proposal time; empty on the pilot. |
| idh-34 | Persistent typed insight graph, world model or shared state across rounds (29) | EXISTS | Lineage graph, interpretation layer, technique graph and cards (typed, human-confirmed assertions) are the persistent typed store; all derived or event-sourced. |

### 2.7 Part 7: Feedback from outcomes

| Id | Technique (works) | Class | Rationale |
|---|---|---|---|
| idh-32 | Experiment-outcome feedback into the next round of ideas (24) | EXISTS | `evaluation.py` computes the outcome by the registered rule; outcomes enter the registry and the prior list of later leads. No outcome exists on the pilot yet. |
| idh-24 | Evidence-conditioned belief-update filtering with diversity maximisation (1) | ADOPT-LATER | Filtering untried candidates by verified earlier outcomes is the prior list made quantitative; needs outcomes first; belief updates by a model are not used. |
| idh-25 | Validation-aware evidence reward (Reducible Information Gain) (1) | ADOPT-LATER | Reliability measures computed from results (CI lower bound, bootstrap sign stability) extend `evaluation.py` (slice 6 ruling 16(b) bootstrap); needs experiment projects. |
| idh-35 | Periodic meta-review or meta-reflection over accumulated claims (4) | ADOPT-LATER | A periodic meta-review is a recurring session over `lead_list`, the registry and the engine measures (section 6), recorded as an `interpretation`; build after one cycle of use. |
| idh-23 | Bayesian surprise as the reward for open-ended discovery (2) | REJECT | Bayesian surprise needs a model-stated prior and posterior as the reward; an outcome set from a model number conflicts with R-121 (computed outcome) and treats an LLM belief as evidence (R-87). |
| idh-06 | Execution-fitness evolutionary search (ideas or code scored by running them) (4) | NOT-APPLICABLE | Fitness by running candidates: the platform never executes experiment code (decision 67); evaluation is of registered rules on ingested runs. |
| idh-26 | Principle-guided hypothesis steering (min-max, information gain) (3) | NOT-APPLICABLE | A scoring rule over a pool of principles needs many outcomes per principle; none exist and human steering (idh-41) covers direction choice. |
| idh-27 | Multi-branch principle co-evolution with evidence routing and gated principle lifecycle (1) | NOT-APPLICABLE | Branches of co-evolving principles with evidence routing need a population of executed outcomes and parallel agents; out of scope for a single review project. |
| idh-29 | Training the ideator with reference-grounded rewards (RL with rubric or delta reward) (3) | NOT-APPLICABLE | Training the ideator by RL on resemblance to published papers; the platform never trains or calls a model, and the reward teaches resemblance (also a contamination risk, R-53). |
| idh-30 | Training the ideator or coordinator from execution reward (RL, test-time training) (3) | NOT-APPLICABLE | Training from execution reward; no training in the platform, no execution. |
| idh-31 | Supervised fine-tuning on distilled research-reasoning trajectories (2) | NOT-APPLICABLE | Supervised fine-tuning on distilled trajectories; no training in the platform. |
| idh-44 | Objective-evolving outer loop (1) | NOT-APPLICABLE | An outer optimisation loop on moving objectives needs execution and scorers; objectives are fixed at registration (R-50). |

### 2.8 Part 8: Human steering and gates

| Id | Technique (works) | Class | Rationale |
|---|---|---|---|
| idh-41 | Human steering of goals, ideas and review (22) | EXISTS | Human gates: `hypotheses.lead_decide`, `hypotheses.register`, `experiments.freeze_unlock` (human in pilot and systematic); the researcher also ticks candidates in sparring. |
| idh-14 | Code-enforced or rule-based stage gates (idea check, hard gate, accept/revise/reject) (11) | EXISTS | Code-enforced gates exist: `hypothesis_gates.py`, refusal of an unreviewed draft, R-120 trigger check, quality regime; a gate that does not stop is a defect. |
| idh-42 | Safety and ethics gate on proposed ideas (4) | NOT-APPLICABLE | A safety screen of proposed experiments; a review project executes nothing; out-of-scope is a discard reason (`DiscardReason.OUT_OF_SCOPE`) and scope comes from the protocol. |

### 2.9 Summary of the classification

| Part | EXISTS | ADOPT-FIRST-SLICE | ADOPT-LATER | REJECT | NOT-APPLICABLE | Total |
|---|---|---|---|---|---|---|
| 1. Lead sources and generation | 5 | 2 | 6 | 0 | 4 | 17 |
| 2. Lead volume and ordering | 1 | 1 | 2 | 1 | 1 | 6 |
| 3. Novelty and prior check | 0 | 2 | 0 | 0 | 0 | 2 |
| 4. Critic and review | 2 | 0 | 1 | 0 | 0 | 3 |
| 5. Hypothesis object and test kind | 2 | 0 | 0 | 0 | 1 | 3 |
| 6. Memory | 3 | 0 | 0 | 0 | 0 | 3 |
| 7. Feedback from outcomes | 1 | 0 | 3 | 1 | 7 | 12 |
| 8. Human steering and gates | 2 | 0 | 0 | 0 | 1 | 3 |
| All | 16 | 5 | 12 | 2 | 14 | 49 |
Observations. (1) The engine already has most of what the literature calls memory, human steering, structured hypotheses and the critic: 16 of 49 techniques exist, and none of them has been used on the pilot. (2) The largest non-adoptable group (12 of 14) concerns training, execution fitness and reward shaping from outcomes: the platform has no outcomes to learn from, and never trains or executes. (3) Only five techniques are adopted in the first slice, all of them wiring and computation around leads: gap and limitation extraction as a lead source (idh-18), mechanism transfer as combination candidates (idh-40), over-generate then screen (idh-04), and the two filters in part 3 (idh-12, idh-13). (4) Two are rejected: scalar self-scoring of ideas (idh-03) and Bayesian surprise as a reward (idh-23).

## 3. Lead sources and the trigger question (R-120, gap G2)

A lead needs at least one resolvable trigger (`trigger_issues` in `services/leads.py`). Kinds in `TriggerKind`: `work`, `row`, `claim`, `item`, `idea`, `interpretation`, `concept`, `card`, `match`, `conflict`, `gap`, `contradiction`, `lead`, `hypothesis`, `direction`. Trace kinds are resolved by `dangling_refs` (`work`, `row`, `claim`, `item`, `idea`, `interpretation`, `concept`); table kinds by a row lookup (`card`, `contradiction`, `lead`, `hypothesis`); builder kinds (`match`, `conflict`, `gap`) carry a 16-hex or `grp_` key and the row as shown, and are re-checked against the builder (`trigger-stale` when the builder no longer returns the same row). The `gap` check is specific to `find_gaps`: `_gap_current` accepts only the six keys of a `find_gaps` cell and re-runs `find_gaps`, so a technique candidate cannot reuse `gap` without a change to that function.

### (a) Claims digest and sparring argument sheets

- The m-claims rows (claim types limitation, negative-result, failure-analysis, finding, mechanism, `no-limitation-stated`) are miner rows. A row is citable as `item` (extraction id `ext_...`) or `row` (`rk_...`); whether `dangling_refs` resolves an `ext_` of a miner row is **to check** (G2 of the engine plan said the same; it is the first test of the slice). The `claim` kind (`clm_...`) is the extraction pack's claim, not an m-claims row, and is not used here.
- A lead from stated limitations cites the work (`work`) and the limitation row (`item`): "work W states limitation L; no work in the selection addresses it" is the lead; the platform computes only that the row exists and that no other row of the selection matches the cited keys (a computed support count, not a judgement of whether the limitation is addressed).
- `no-limitation-stated` rows are absence rows and are not triggers on their own (absence in a paper's text is weak: engine plan, risk of treating omission as a finding). They may enter the queue only as a count beside a work.
- A sparring argument sheet (`arg_...` ids) records arguments with verified quotes and work or claim keys. An argument is not a trigger kind. The lead cites the works and rows the argument cites, and names the sheet in the lead text. A new kind `argument` (a table kind, `_TABLE_KINDS` would take `("arguments", "argument_id")`) is possible but not needed for the first slice.
- Smallest change: none (reuse `work` and `item`). Exploratory label: the rows come from an uncalibrated miner; the lead text states "exploratory row" (engine decision D4(a)).

### (b) Technique candidates (gaps, combinations, challenges, derives-from)

- A `ChallengeCandidate` carries `failed` and `supported` use rows, each with an extraction id and quote. A `CombinationCandidate` carries `co_works`, `support_a`, `support_b` and quotes. A `GapCandidate` is an approach at one stage with no row at another. `derives-from` edges rest on `reused-cited` rows plus a resolved reference link.
- Option A (recommended for the first slice): cite what the candidate rests on, with kinds that exist: the `item` triggers of the failed and supported rows for a challenge (at least two, from two works), the `work` triggers of the co-using works for a combination, the `work` triggers of the sources of a gap. Lead text says "technique candidate (exploratory), builder: `technique_challenges` lens core". No enum value, no event, no decision row. Cost: no builder re-check, so the trigger is resolvable but not marked stale when the miner is re-run; the lead stores the miner version in its text and the queue (section 4) recomputes the candidate and shows "candidate no longer produced".
- Option B: a new builder kind `technique-candidate` (key = hash of the candidate kind, approach ids and lens; row = the candidate as shown), validated by a `_technique_candidate_current` beside `_gap_current`. Consequences: an additive value in `TriggerKind` and `_REF_PATTERNS`, a stored row in old and new events (old readers refuse the new value: an enum addition is a schema change), a test per staleness case, and a proposed decision row ("number to be assigned at merge"; scope: the lead trigger enum gains `technique-candidate`, class interpretation, exploratory label required). Worth doing after Option A has produced leads and the researcher wants staleness tracking.
- Option C: extend `find_gaps` with a miner grid so technique gaps become ordinary `gap` triggers (the technique plan's task 8, critical-adjacent). Largest change; also fixes engine G1; not in this slice.

### (c) The lineage graph and cards

The pilot has none (zero idea, card and relation events; `contribution_schema` null), so these sources produce no lead until the contribution miner and card import exist. The triggers `idea`, `card`, `match`, `interpretation` and `concept` already exist; no change is proposed. The lineage `cites` graph is used only as a computed measure (section 4).

### (d) The feed and the inbox

No trigger kind. A feed or inbox paper becomes a lead source only after it is a work in the corpus (screening, then a `work` trigger), as engine decision D3(a) and slice 4c ruling 1 say. No change; the first slice does not use the feed.

### Consequence summary

| Source | Trigger today | Missing | First-slice change |
|---|---|---|---|
| m-claims limitation rows | `work` + `item` or `row` | check that miner-row ids resolve | test only |
| argument sheet | `work`, `item` of its cited rows | an `argument` kind (optional) | none |
| technique challenge, combination, gap | `item` and `work` triggers of the rows | builder kind with staleness (Option B) | none (Option A) |
| lineage, cards | `idea`, `card`, `match` | data on the pilot | none |
| feed, inbox | `work` after inclusion | nothing | none |

## 4. Ordering many leads by what the platform can compute (gap G4)

Principle. The platform computes measures from recorded rows and orders by a fixed rule printed with the result; it never decides which lead is better. Every measure is returned with its components (as `technique_rank.py` returns score components), the page is labelled exploratory, and the order is stable for the same index. No weighted sum of unlike quantities: a lexicographic order with the measures shown, so that a reader sees why a lead is where it is.

Candidate measures, all read-only:

| # | Measure | Computed from | Inspired by |
|---|---|---|---|
| M1 | Support: number of distinct works behind the triggers | trigger refs resolved to works | idh-04 (screen on a computed criterion); idh-13 |
| M2 | Independence: distinct works among them not connected by a resolved `cites` link in the lead's trigger set (components of the citation graph) | `graph_edges` cites | idh-12 (a count from outside the idea itself) |
| M3 | Quote verification: share of cited rows with a platform-verified quote and anchor | extraction and miner rows | idh-20 (structural citation validation) |
| M4 | Evidence level of cited technique rows: share supportive (independent-test, own-ablation, own-comparison), share `reported-failure`, share not stated | `technique_rank.supportive_share` | idh-25 (evidence-based score, as counts, not belief) |
| M5 | Corpus overlap: nearest works to the lead text by keyword and meaning search (top-k scores) and nearest approaches (`technique_neighbors`) | `corpus_search`, technique graph | idh-12 |
| M6 | Diversity against promoted leads: Jaccard of `lead_keys` and technique-stage distance to each promoted lead | `lead_keys` | idh-13, idh-24 (diversity part) |
| M7 | Prior-list hits: parked, discarded and earlier hypotheses and closed directions sharing a key | `prior_for` | idh-33 |
| M8 | Candidate score of the source (popularity, stage, bridge, evidence, generic) | `technique_rank` | idh-40 |
| M9 | Basis age and state: current, stale, candidate no longer produced; miner version served | recompute | idh-14 (deterministic gates) |

Proposed fixed order (to be validated by the researcher, choice 2): leads with an M7 hit on a closed direction last; then M2 descending, M1 descending, M3 descending, M6 ascending (more different from promoted ones first), date. M5 and M4 are shown, not sorted on, because M5 mixes a model-free retrieval score with embedding quality and M4 depends on a sparse attribute (the technique plan reports most rows omit `evidence`).

What stays judgement. Whether a lead is interesting, feasible or novel is a human decision at `lead_decide`, with Claude's reading of the passages as input. Pairwise or listwise ranking of a pool (idh-01, idh-02) is optional later and would be a Claude session writing a suggestion set under the slice 8 pattern with provenance; its position bias and uncalibrated judgement are stated on the page. Scalar self-scores are rejected (idh-03).

Lead volume. The first slice caps the candidate list per source (`limit`, default 20) and the number of leads an agent records per run (a parameter in the skill, not a platform rule; engine D6(a): no platform cap, measure first).

## 5. The first buildable slice (1 to 3 days)

Path: lead source (technique challenges and combinations, claims digest limitations) to a queue ordered by computed measures, to an ideating Claude session recording leads with `lead_record`, to the researcher promoting, parking or discarding (`lead_decide`), to drafts with `hypothesis_draft` for the promoted, to a critic review in another session, and a registration or a recorded refusal. No new event type and no new trigger kind (Option A of section 3b). All new reads are derived and labelled exploratory.

Branch `hypothesis-engine-slice-a`. Tests are written first for each task; while the testing pause holds they are not run (mypy and ruff only). One commit per task; 1 to 3 hours each.

| # | Task | Files | Depends | Agent |
|---|---|---|---|---|
| 0 | Check, by reading code: do `dangling_refs` resolve `ext_` ids and `rk_` keys of miner rows; what `hypothesis_draft` requires of a literature test with a method given by name only; what `hypothesis_register` refuses. Write the answers into this plan's section 8 (docs only). Proposed decision row "lead triggers may cite miner rows and technique-candidate rows, labelled exploratory" (number to be assigned at merge). | `docs/decisions.md`, this plan | none | rf-builder, 1.5 h |
| 1 | Lead candidates read service: from `technique_challenges`, `technique_combinations`, `technique_gaps` (lens core) and `claims_digest` limitation rows, return candidate items each with the exact `triggers` list (kind, ref) to pass to `lead_record`, the source name, the miner version and the exploratory label. Pure read; no lead written. | `services/lead_candidates.py`, `model/lead_candidates.py` | 0 | rf-builder, 3 h |
| 2 | Measures M1 to M9 and the fixed order as a read-only `lead_queue` over open leads and over candidates not yet recorded; each row carries its measures and the rule printed. | `services/lead_queue.py` | 1 | rf-builder, 3 h |
| 3 | MCP read tools `lead_candidates` and `lead_queue` (withheld and pass-session refusal as `graph_query`); CLI `factory leads candidates` and `factory leads queue`. | `mcp/server.py`, `cli/main.py`, `cli/render.py` | 1, 2 | rf-builder, 2.5 h |
| 4 | Skill `rf-ideate` step 1 reads `lead_candidates` and `lead_queue`; rule "state in the lead whether a cited row is exploratory and name the miner version"; the lead text names the technique candidate and the sources; novelty wording rule "not found in this corpus" (never "novel"). `rf-critic` checklist item: every cited exploratory row appears as exploratory in the statement; the critic reads the corpus overlap (M5) and prior hits (M7) before accepting. | `plugin/skills/rf-ideate/SKILL.md`, `rf-critic/SKILL.md` | 3 | rf-builder, 1.5 h |
| 5 | Engine measures (engine plan part 7): counts of leads recorded, promoted, parked, discarded by reason, drafts, registered, refused drafts by reason; computed from events; shown by `factory leads stats`. | `services/lead_stats.py`, `cli` | 0 | rf-builder, 2 h |
| 6 | Acceptance run on a copy of the pilot (never the pilot): one session generates leads from the queue; the researcher decides; a second session drafts and a third critiques; results recorded in a dated note under `docs/plans/`. | note only | 1 to 5 | researcher plus sessions, 3 h |
| Landing | `gen_map.py`, backlog status (built, not reviewed), one Sonnet review with guard mutation on tasks 1 and 2 (build-review lessons). By the lander. | `docs/MAP.md`, `docs/backlog.md` | | |

TDD list (written first, not run while testing is paused):
1. Candidate items equal the builders' output for a fixture; each item's triggers resolve (`trigger_issues` empty); a candidate with fewer than one resolvable trigger is omitted and listed.
2. Every output (JSON, CLI, MCP) carries the exploratory label and the miner version; a test fails if one path omits it.
3. Determinism: same index, same order, byte-identical output; the order rule text is in the output.
4. M1 and M2: two works that cite each other count as one independent work; two that do not count as two.
5. M7: a lead sharing a trigger with a discarded lead is flagged with the earlier lead's id and reason; a closed-direction hit sorts last.
6. M6: a lead equal in keys to a promoted lead scores diversity 0.
7. M9: after a miner re-run changes a cited row, the queue shows the lead as "candidate no longer produced" and does not delete it.
8. Read-only: no event is appended and no table written by any new service; a test opens the index read-only.
9. A lead recorded from a candidate through `lead_record` is accepted; one with a made-up `item` is refused with `triggers.0: unknown`.
10. Pass-session refusal and held-out handling as for `graph_query` (no masking of held-out works, decision 37.9).
11. `report_evidence` and `report_prisma` outputs are identical with and without leads (no lead measure enters a report).
12. Stats: counts equal a fixture stream; no percentage is printed without its denominator.

Human gates in this slice (pilot-mode presets; no `gate_policies` override). The researcher decides every lead (`hypotheses.lead_decide`, human); the critic is a separate session and the proposer never reviews (R-51); registration is human (`hypotheses.register`); design freeze (`experiments.freeze_unlock`) is not reached in this slice. The proposer session must not have run a screening, extraction or contribution pass (the platform refuses it). Engine part 4 (a recorded `hypothesis_plan` and `gate_policies`) stays a researcher choice.

### What a successful first run looks like

Measurable, all computed by task 5 and recorded in the run note:
- At least 15 candidate leads recorded from at least two sources (challenges or combinations, and claims), each with at least two triggers from two works where the source allows it. Zero leads refused for an unresolvable trigger after task 0 (otherwise the refusals are the finding).
- The queue shows the order and its measures for all of them; the researcher promotes between 3 and 8, parks and discards the rest with a reason; the share promoted is reported (it is a use figure, not a quality figure).
- At least 3 promoted leads drafted as hypotheses with a falsifier sentence printed by the platform; each draft reviewed by a separate critic session; the number accepted, revised, refused by the critic reported.
- Registered: whatever the researcher registers, possibly none. A run that ends in 0 registered with a recorded reason per draft (for example "no later-literature rows of the needed comparability key") is a valid result and decides section 8.

### The test-kind question for a review project (engine D2)

The pilot's evidence has no comparability-keyed numeric rows, so an `experiment` hypothesis cannot be tested inside the project: the platform records experiments run elsewhere. A `literature` hypothesis registers a window and a search and is evaluated on later rows comparing two methods in one comparability group; a method may be given by name (the `MethodRef` takes a card, an idea or a name, with an optional evidence row). The classes of hypothesis a technique lead yields, and where each can be tested:

| Lead yields | Example form | Testable in a review project | Otherwise |
|---|---|---|---|
| A technique reported failing by some works and supported by others (challenge) | "Approach A outperforms baseline B under condition C" | Literature window, only when later papers report A against B with comparable keys; the evidence schema of the pilot lacks the keys, so evaluation would give `insufficient-evidence` | An experiment elsewhere; the lead stays a registered direction |
| A pair of approaches not combined in the corpus (combination) | "Combining A and B improves metric M over each alone" | Same as above | Experiment |
| An unaddressed stated limitation (claims) | "Method class X fails under assumption Y" | Literature window if later works test Y; otherwise not testable here | Experiment or a measurement study |
| A claim about the corpus ("stage S has no system with a check") | Computed count | Not a hypothesis about nature; a computed statement. Engine D2(c) would need a decision row | Report as a finding with its definition ("not found in this corpus") |

Recommendation: engine D2(a) with an honest consequence: in the first slice the hypotheses can be drafted and reviewed, and may register with a literature window whose evaluation is expected to return `insufficient-evidence` until later rows exist; whether registration is worth it before an evidence schema with comparability keys exists is the researcher's call (choice 4).

## 6. Risks and how each part is measured

Risks.
- Lead volume: three sources times twenty candidates is more than one person decides on. Mitigation: caps per source, the computed order, batch decisions (engine part 3), measure of leads per promoted.
- False novelty claims: "not found in this corpus" turned into "novel". The corpus is the core layer of one project and the miners omit attributes; a lead's overlap check (M5, M7) is a computed screen, not a literature review. Mitigation: wording rule in the skill, the critic checklist, no "novel" in any output field.
- Exploratory rows treated as evidence: counts from uncalibrated miners reach a hypothesis statement as if they were results. Mitigation: label travels with every row, lead and critic item; the existing `miner-uncalibrated-evidence` check must cover the new services; test 11.
- Critic independence: the same model family as the proposer shares blind spots, and a single researcher is proposer-promoter-registrar. Mitigation: separate sessions (R-51), the `self-reviewed` flag (slice 6 open question 1), a critic on a different model later (idh-10, ADOPT-LATER) with the model in provenance.
- Quality of the mined techniques: 0.46 / 0.67 agreement, pass A only, about 8 techniques split across two stage taxonomies, evidence attribute often missing. A candidate may rest on one pass's reading. Mitigation: show the quote; require the researcher or the critic to open the passage before promotion; do not adopt a technique because it is frequent (works counts show use in AI-scientist papers, not effectiveness).
- Circularity: hypotheses about AI-scientist systems drawn from the same corpus. Mitigation: the literature window counts only rows after registration (engine plan risk 1).
- The first slice produces leads that no test can resolve. Mitigation: the run note lists this as the finding that decides the next slice.

Measures (computed by `factory leads stats`, never typed; use figures, not quality figures):

| Part | Measure |
|---|---|
| 1 Sources | leads per source; share of candidates recorded as leads; share refused for unresolvable trigger |
| 2 Ordering | promotion rate by rank decile of the queue (does the computed order predict the human choice); leads per promoted |
| 3 Prior check | discards with reason `duplicate` or `prior-failure` per lead (a lead that the prior should have caught); overlap score of promoted versus discarded |
| 4 Critic | drafts accepted, revised, refused by the critic; items the critic raised that a later revision fixed |
| 5 Test kind | drafts by kind; drafts whose evaluation is `insufficient-evidence`; refusals at draft or registration by reason |
| 6 Memory | prior-list hits per new lead; directions in the registry |
| 7 Feedback | registered hypotheses by computed outcome (none expected at first); refutation rate once outcomes exist (engine G7) |
| 8 Gates | gate stops per gate; any registration without the human event is a defect |

Lead quality proper (G7) needs outcomes: promotion rate and refutation rate over many leads. Neither is meaningful on a first run of a few dozen leads; they are reported with their denominators and not used to rank techniques.

## 7. Techniques to adopt first, in one view

Adopt in the first slice: idh-18 (gap and limitation extraction as a lead source), idh-40 (combination and challenge candidates), idh-04 (over-generate then screen), idh-12 and idh-13 (computed overlap and diversity).
Adopt later, in this order if the first run supports it: idh-10 (a critic on another model), idh-35 (periodic meta-review), idh-01 and idh-02 (pairwise or listwise ranking by a session, as a recorded suggestion set), idh-24 and idh-25 (outcome-conditioned filtering and reliability measures, once outcomes exist), idh-08, idh-11, idh-15, idh-28, idh-39 (generation procedures as skill text or parallel sessions), idh-05.
Already present, to be used and measured: idh-07, 14, 17, 19, 20, 22, 32, 33, 34, 36, 38, 41, 43, 46, 47, 49.
Rejected: idh-03, idh-23.

## 8. Findings of task 0 (to be filled before task 1)

To be written by task 0: resolution of `ext_` and `rk_` ids of miner rows by `dangling_refs`; what `hypothesis_draft` accepts for a literature test with names only; what `hypothesis_register` and the critic gate refuse; whether `corpus_search` can be called from a lead-candidates service or only through the MCP layer.

## 9. Open choices for the researcher

Q1. Trigger kind for technique candidates.
- A (recommended): no new kind in the first slice; cite the rows and works the candidate rests on (`item`, `work`), label exploratory.
- B: add a builder kind `technique-candidate` with staleness checking now (enum change, decision row, one more task of about 3 hours).
- C: extend `find_gaps` with a miner grid so candidates become `gap` triggers (critical-adjacent, larger).

Q2. Ordering measures.
- A (recommended): a fixed lexicographic order on computed counts (M2, M1, M3, M6, date), with prior hits on closed directions last, all measures shown.
- B: newest first only, measures shown but not sorted on.
- C: A plus a Claude pairwise or listwise ranking recorded as a suggestion set (idh-01, idh-02), shown beside the computed order.

Q3. First slice scope.
- A (recommended): sources = technique challenges and combinations plus claims limitations; queue; skills; stats; acceptance run on a copy of the pilot.
- B: technique candidates only (smaller: about 1 day).
- C: A plus the batch decision act and the hub Directions page (about 3 days).

Q4. Test kind for the review project.
- A (recommended): engine D2(a): literature window over a declared comparison; draft and review in the first run; registration at the researcher's discretion, expecting `insufficient-evidence` until comparability-keyed later rows exist.
- B: experiments only; the review project registers no hypotheses, the leads and directions are still recorded and the experiment goes to a project that runs it.
- C: a new test kind for computed corpus claims (a decision row; not a hypothesis about nature).
- D: do not register in the first run; stop at reviewed drafts.

Q5. Which techniques to adopt first.
- A (recommended): the five of section 7 (idh-18, 40, 04, 12, 13).
- B: A plus a critic on another model (idh-10) in the first run.
- C: only idh-18 and idh-40 (sources), no screen or filters yet.

Q6. Gate policy.
- A (recommended): keep the pilot presets (human lead decision, registration, design freeze) and record the plan afterwards.
- B: lower registration to `agent` with the `autonomy: agent` label for the first run only (engine D7(b)).
- C: add a human gate on the critic review as in systematic mode.

Q7. How exploratory rows may enter leads.
- A (recommended): allowed, labelled exploratory, never as the test of a hypothesis (engine D4(a)).
- B: only rows of a miner after calibration (no m-claims or technique miner qualifies today; the engine would wait).

Q8. Candidate cap per source and per run.
- A (recommended): 20 per source in the tool, no platform cap on recorded leads; measure first (engine D6(a)).
- B: a daily cap on agent-recorded leads.
- C: 10 per source for the first run.
