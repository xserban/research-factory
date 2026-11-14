# The hypotheses engine: from the literature stream to a registered hypothesis (plan, 2026-11-14)

Status: plan only, written unattended overnight (lane E, item E2); nothing built, nothing run, no decision applied. Builds on slice 6 (`docs/specs/slice-6-hypotheses.md`, decisions 67 and 68, R-50 to R-54 and R-120 to R-125), slice M gates, slice 3b and 3c (lineage, interpretation layer), the layer, lifecycle and step products of 2026-11-13, the feed (slice 4c) and the inbox (slice 4a). Direction: part 7 of `docs/plans/2026-11-13-main-hub.md` ("the hypotheses engine ... exist and have not been run on a real corpus. First step: run each on `agentic-science` and record what works, what fails and what the researcher needs from it").

How this plan was made: I read the specs, the model file `platform/src/factory/model/hypotheses.py`, the module table in `docs/MAP.md`, the skill `rf-ideate` and the backlog entries named below. I did not read the service code line by line and ran nothing, so statements about what the code does are taken from specs, docstrings and the map; items marked **to check** need a read of the code first.

## 1. What exists (built, v1, not run on a real corpus)

| Part | Where | What it does |
|---|---|---|
| Property vocabulary, method and problem cards | `services/vocabulary.py`, `cards.py`, `card_import.py`; skill `rf-cards`; gates `hypotheses.property_approve`, `hypotheses.assertion_confirm` (human) | Typed properties, human-approved; cards assert them with verified quotes or rows; stated versus inferred |
| Matching | `services/matching.py`; MCP `match_query` | Per problem, which cards satisfy, conflict with or leave unknown each property; transfer flag |
| Finders | `services/finders.py`; MCP `finder_contradictions`, `finder_gaps`, `contradiction_propose` | Numeric conflicts inside comparability groups of the evidence report; empty cells of a declared grid (methods or cards by one comparability key); agent-proposed claim contradictions stay inferred until a human confirms |
| Leads | `services/leads.py`; MCP `lead_record`, `lead_decide`, `lead_list`; CLI `factory leads` | A lead of at most 600 characters with at least one resolvable trigger (R-120); the prior list (parked and discarded leads, earlier hypotheses, closed directions sharing a trigger); promote, park or discard by a human in pilot and systematic |
| Hypotheses | `services/hypotheses.py`, `hypothesis_review.py`, `hypothesis_gates.py`; MCP `hypothesis_draft`, `hypothesis_review_next`, `hypothesis_review`, `hypothesis_register`; skills `rf-ideate`, `rf-critic` | Draft from a promoted lead (kind experiment or literature, a decision rule from a fixed menu, the falsifier sentence printed by the platform); independent critic session on the artefact only; registration freezes `H@`; model cut-off declaration and the R-53 contamination flag |
| Experiments | `services/experiments.py`, `xruns.py`, `xrun_accounting.py`, `reproduction.py`; skills `rf-experiment`, `rf-run` | Designs with `E@`, freeze and unlock nonce, baselines that must reproduce, budgets, ingestion of runs executed elsewhere |
| Evaluation and registry | `services/evaluation.py`, `directions.py`, `benchmark_ledger.py` | The outcome is computed by the registered rule (R-121); refuted, inconclusive and abandoned items and discarded leads are rows of the failed-directions registry, never removed (R-52, R-124) |
| Gates | slice M table (`docs/specs/slice-M-modules.md`): `hypotheses.lead_decide`, `hypotheses.register`, `experiments.freeze_unlock` (floor agent, preset human in pilot and systematic); `experiments.accept_baseline`, `hypotheses.close` and others (floor human) | Declared per mode; overridable in the protocol's `gate_policies` |

Products of the literature stream that a lead could draw on:

- **Evidence layer and graph:** `graph_query` (including `no_stated_base`, improvements on a node) and `graph_export`; contribution items (pack `contribution`); the intuition layer (interpretations, concepts), labelled `interpretation` and never evidence (R-87).
- **Layers and lifecycle (2026-11-13):** `m-layer` v1 (core, applied, benchmark layers; uncalibrated, 6 pass disagreements), `m-stages` v1 (9 stages, agreement 0.981 on mode, no calibration), `m-lifecycle` v2 (calibrated pass A; the researcher's gold labels pending), `m-stage-steps` v1 (tonight, exploratory; plan `2026-11-13-lifecycle-stage-deep-dive.md`).
- **Stream intake:** the feed (ranked arXiv listings, outside the corpus), the link inbox (`supplied`), watch cycles (slice 4b). A feed paper enters the corpus only through the inbox and screening (slice 4c ruling 1).

State of the pilot project (read-only look at its recorded protocol of 2026-11-13, `ops/screeners/protocol-current-2026-11-13.json`): `hypothesis_plan` is null, `gate_policies` is null, `contribution_schema` is null, the extraction pack is `ai-research-system` (not `ml-benchmark`). Decision 74 set the pilot runs of slices 3 and 6 aside, so lineage, cards, leads and hypotheses have never been run on `agentic-science`.

## 2. What is missing between the stream and a registered hypothesis

The findings below are gaps in the connection, not in the parts. Each names the evidence in the repository.

**G1. The finders cannot see the products the researcher actually has.** `find_gaps` takes methods (final evidence rows or method cards) against one declared comparability key of the evidence schema, and `finder_contradictions` reads the evidence report's `method_conflicts` (slice 6, rulings 9 and 10; `finders.py`). The pilot's rows are miner rows (`m-stages`, `m-lifecycle`, layers) and extraction rows of the `ai-research-system` pack, which have no `ml-benchmark` comparability keys. So "which lifecycle stages are covered by few systems", "which stage has no system with a check" or "which layer has no work for a family" cannot be asked, although this is the kind of gap the deep-dive plan will produce (part 4, candidates absent from our process).

**G2. A lead cannot cite a stream item as such.** Trigger kinds are `work`, `row`, `claim`, `item`, `idea`, `interpretation`, `concept`, `card`, `match`, `conflict`, `gap`, `contradiction`, `lead`, `hypothesis`, `direction`. There is none for a feed entry, an inbox item, a miner row or a lifecycle cell. Whether a miner row is citable as `item` (extraction id) or `row` (`rk_` key) is **to check** (`EXTRACTION_ID_RE`, `ROW_KEY_RE` in the model file). Feed entries are deliberately not corpus records, so they should not become triggers directly (see D3).

**G3. A hypothesis needs a test the project can run.** The two test kinds are an experiment design (needs comparability keys, a baseline resolving to a final evidence row, runs executed elsewhere) and a literature window (needs a declared search after registration and later rows comparing two methods in one comparability group). A review project of AI-scientist systems has neither kind of row. What would a testable hypothesis be there? Candidates: "systems that report a verification step also report X" (a comparison over miner rows); "a stage found in at most k systems is absent from our process" (a computed claim, not a hypothesis about nature). Whether miner rows may be a hypothesis's evidence is the question R-142 answers for evidence admission (calibrated before evidence) and R-125 for own results.

**G4. No volume handling between finders and the human.** A finder or an agent can produce many candidate leads; the human sees `lead_list` and the check `lead-undecided`. Nothing orders them by what the platform can compute (number of independent triggers, overlap with the prior, age of the trigger's basis), and nothing batches the decision ("promote, park, discard" across ten leads with the grounds shown), as slice 8's loop does for protocol items.

**G5. Gates have defaults, not a recorded plan, for this project.** With `hypothesis_plan` and `gate_policies` null the mode's presets apply (pilot: human for lead decision, registration and design freeze). That is correct but unrecorded for the pilot; the minimum number of seeds, default confidence level and test-access limit are not declared.

**G6. The skill does not read the new products.** `rf-ideate` step 1 starts from `match_query`, the two finders, and "the lineage and interpretation views". It does not name the layers, the lifecycle rows, the step rows, the feed or the graph queries `no_stated_base` and improvements, and it has no rule for labelling exploratory (uncalibrated) rows as such in a lead.

**G7. Lead quality has no measure.** Leads are `interpretation` class and never counted as evidence, so no calibration applies, but nothing computes how often leads are promoted, how many promoted ones are refuted, or how often the prior would have caught a lead that was later discarded as a duplicate. Without a rate the engine cannot be judged after the first run (the plan for the lifecycle miner states the same lesson: a figure from gold, not from the agent).

**G8. Statistics beyond the menu, multiple metrics, external tracker, cards at scale** are the slice's own open questions 2 to 5 (`slice-6-hypotheses.md` §Open questions); they stay open here unless the first run needs them.

**G9. Cross-project use.** Cards import is by recorded copy (`card.imported`, slice 6 ruling 8). With a main hub of several projects, which leads and failed directions are visible across projects is not settled (see the graph-and-data plan, `2026-11-14-graph-and-data-integration.md`).

## 3. Principles kept (not open)

- The platform never calls a model and never judges: it computes matches, gaps, versions, states, outcomes; agents propose; the proposer never decides, reviews or registers (R-51).
- A lead without a resolvable trigger cannot be written (R-120). Triggers are corpus items; stream items outside the corpus enter through the inbox first (4a and 4c).
- Hypotheses and tests are registered before evidence is examined (R-50); the outcome is computed by the registered rule (R-121); failed directions stay (R-52, R-124); own results stay apart from reported ones (R-125).
- Rows from uncalibrated miners are exploratory: labelled wherever shown, excluded from counts that enter a report (the rule of the 2026-11-13 deep-dive plan, section 8, and R-142).
- No new event type without a note in the backlog. This plan proposes none; where a part could need one it says so and offers an option without.

## 4. Parts, in order (tests first for every part)

**Part 0. Run what exists on a copy of the pilot (no code).** Copy `data/projects/agentic-science/events` to a scratch root (as the live checks of other plans do; never the pilot itself). Run, with the researcher's tools, a vocabulary of a few properties, `match_query` for one problem description, both finders, a lead with a `work` trigger, a draft and a critic review on the copy. Record what works, what fails and what the researcher needs, in a note under `docs/plans/` (dated). This is part 7's first step in the main-hub plan, and it decides how large parts 1 to 3 need to be. No test beyond the existing suites.

**Part 1. A grid over typed rows that are not evidence rows (G1).** A builder `finder_cells`, a sibling of `finder_gaps`, that takes two axes over rows of a named registered miner or taxonomy (for example `m-stages` stage by mode, or a lifecycle stage by actor) and reports empty and thin cells with the corpus definition, as `finder_gaps` does. Rules: the builder reads calibrated rows by default; rows of an uncalibrated miner are included only with an explicit flag, and every output row then carries the label `exploratory`; every output carries a key (hash of its inputs) so a lead can cite it as a `gap` trigger with its row exactly as shown (the existing builder-trigger shape, no change to the trigger enum). Tests first: a fixture with a small miner pack: cell counts, empty-cell listing bounded as in ruling 10, determinism of the key, the label on uncalibrated input, refusal of an unknown miner or axis with structured errors and nothing written, a lead citing the cell accepted and a stale key flagged `trigger-changed` as for other builders. No event, no table beyond the builder's read of the index. **To check:** how miner rows are held in the index (the `extraction_*` family with the miner's name as `pack`) and whether `row_key` can be used as the cell's member list.

**Part 2. The graph and the layers as lead sources (G2, G6).** Check, with tests, that a trigger can cite what a lead needs: a work (exists), a contribution item (`item`), a graph finding. If `no_stated_base` and "improvements on a node" need citing, expose them as builder rows through the same shape as part 1 (a `gap` trigger with a key and the row), again without a new trigger kind. Tests: a fixture graph with a paper without a stated base; the lead cites it; changing the graph changes the key. No change to the graph services.

**Part 3. The lead queue for the human (G4).** A computed, read-only view `lead_queue`: open leads with the number of distinct triggers, the prior list, the age and state of each trigger's basis (current, stale, trigger-changed), and the grounds as recorded; ordering is a fixed deterministic rule stated on the page (for example trigger count, then date), never a model judgement. A batch act for the human, `factory leads decide --batch FILE`, applies promote, park or discard with a reason to listed ids, each still its own `lead.decided` event (existing event, existing gate). Tests first: ordering is deterministic; a batch with one invalid id writes nothing for that id and reports it (partial success as the MCP convention says); the actor is the human; an agent may not run the batch. Hub page: the queue and the registry as a "Directions" page built from events (the hub is lane C's area; this plan only names the page).

**Part 4. A recorded plan for the project (G5).** `hypothesis_plan` and `gate_policies` for `agentic-science`, drafted by an agent with the researcher choosing each item (suggest-and-select, slice 8): minimum seeds, default confidence level, test-access limit, and whether any gate departs from the pilot presets. Applied by the researcher as a protocol amendment (a semantic flag decides whether it stales anything; `hypothesis_plan` is omitted from the hash while None, slice 6 ruling 3, so no stale decisions are expected: **to check** by a test on a copy). No platform code.

**Part 5. What a hypothesis may be tested on, for review projects (G3).** Depends on decision D2. Options described there; the code part is small if the recommendation is taken (the literature kind over a declared comparison of calibrated miner rows) and larger otherwise. Tests first: a literature hypothesis whose window comparison reads miner rows; refusal while the miner is uncalibrated; the contamination flag still computed (R-53).

**Part 6. Skill and critic updates (G6).** `rf-ideate` step 1 gains the layers, lifecycle and step cells (`finder_cells`), the graph queries and the rule "state in the lead whether a cited row is exploratory"; `rf-critic` gains one checklist item: "does every cited exploratory row appear as exploratory in the statement". Skill text is data under `plugin/skills/`; the skill hash is computed by the platform. A test that the skill lists only tools that exist (the catalog check of IDEA-60 if it covers this).

**Part 7. Engine measures (G7).** Computed from events and shown on the Directions page, never typed: leads recorded, promoted, parked, discarded (by reason); promoted leads reaching registration; registered hypotheses by computed outcome; discards that cite `duplicate` or `prior-failure` (the prior working or not). Tests: a fixture event stream with known counts. These counts describe the engine's use; they are not a quality figure of the hypotheses.

**Part 8. Acceptance.** (a) Synthetic: from a fixture miner pack and graph, a cell and a graph finding become two leads; the human promotes one; a draft, an independent critic review and a registration by the human follow, each gate refusing the proposer and an agent registration under pilot mode; the registered hypothesis traces back to the cells and the works (`trace`). (b) Real, on a copy of the pilot (never the pilot): the same sequence with the researcher at the human gates, labelled exploratory until the miners are calibrated. The result is a registered hypothesis or a written reason there is none.

## 5. Human gates in this engine

| Act | Who | Gate | Stops without it |
|---|---|---|---|
| Approve properties; confirm card assertions and contradictions | human | `property_approve`, `assertion_confirm`, `contradiction_confirm` | matches and finders use stated rows only |
| Promote, park or discard a lead | human (pilot, systematic) | `lead_decide` | no draft from an undecided lead |
| Critic review | independent agent session, plus human in systematic | quality regime | `hypothesis_register` refuses an unreviewed draft in pilot and systematic (**to check** in `hypothesis_gates.py`) |
| Register a hypothesis | human | `hypotheses.register` | no `H@` frozen |
| Declare model cut-offs | human | `model.cutoff_declared` | R-53 flag `cutoff-unknown` (error in systematic) |
| Freeze a design, unlock confirmatory runs | human in pilot and systematic | `experiments.freeze_unlock` | no confirmatory result accepted |
| Accept a non-reproduced baseline; close a direction | human | `accept_baseline`, `hypotheses.close` | dependent outcomes flagged |
| Gate policy and plan for the project | human | protocol amendment | presets apply |

A gate that does not stop is a defect (see the pilot-2 plan for how that is detected).

## 6. Risks

- **Circularity with the evidence of the review.** Hypotheses about AI-scientist systems drawn from mined rows of the same corpus, tested on the same rows, test nothing (the plan's own "selection bias" risk: core papers are systems describing themselves). Mitigation: the literature kind tests against rows that arrive after registration (a declared window and search), never against the rows that triggered it.
- **Exploratory rows becoming evidence by accident.** Mitigation: the label travels with every cell, lead statement and critic checklist; the check `miner-uncalibrated-evidence` already exists (MAP, miners module) and must cover the new builder.
- **Lead flood.** Mitigation: part 3 (computed queue, batch act); a cap per day of agent-recorded leads is an option, not proposed.
- **Retrofitting the model.** A new trigger kind changes a payload enum (additive for old events, but a schema decision). Mitigation: reuse the `gap` trigger shape.
- **The single researcher is also promoter and gate holder.** Slice 6 open question 1 recommends the `self-reviewed` flag; the critic stays a separate agent session.
- **Claims about the unrun code.** Part 0 exists so that parts 1 to 7 are sized from a run, not from reading.

## 7. Open decisions for the researcher (multiple choice; the recommendation is marked)

**D1. Where to start.**
(a) **Part 0 first, then re-size parts 1 to 7 (recommended)**: the main-hub plan already asks for it, and every other estimate here depends on it.
(b) Build part 1 now from this plan.
(c) Other.

**D2. What may a hypothesis be tested on in a review project like `agentic-science`.**
(a) **The literature kind over a declared comparison of calibrated miner rows, with the window filled by a search after registration (recommended)**: keeps R-50 and R-121 meaning something and reuses the existing rule `literature-direction`.
(b) Only experiments: a review project registers no hypotheses; leads and directions are still recorded.
(c) A new test kind for computed claims about the corpus ("absent from at least k systems"); needs a decision entry and is not a hypothesis about nature.
(d) Other.

**D3. How a feed or inbox paper becomes a trigger.**
(a) **Only after it is a work in the corpus (through the inbox, screening and, if included, as a `work` trigger) (recommended)**: consistent with slice 4c ruling 1 and R-101.
(b) A trigger kind `feed-entry` citing the ranked entry.
(c) Other.

**D4. Exploratory rows as lead material.**
(a) **Allowed with the label `exploratory` carried into the lead and critic checklist; never as the test of a hypothesis (recommended)**.
(b) Not allowed until the miner is calibrated.
(c) Other.

**D5. The lead queue order.**
(a) **A fixed computed order (trigger count, then date) shown on the page (recommended)**.
(b) Newest first only.
(c) An agent proposes an order; the platform records it as a suggestion set (slice 8) and the human selects.

**D6. Cap on agent-recorded leads.**
(a) **No cap in v1; measure first with part 7 (recommended)**.
(b) A daily cap per project.
(c) Other.

**D7. Gate policy for the pilot.**
(a) **Keep the pilot presets and record the plan (part 4) (recommended)**.
(b) Lower registration to `agent` with the `autonomy: agent` label (exploratory preset), for the first run only.
(c) Other.

**D8. Which project runs part 8(b).**
(a) **A copy of `agentic-science` (recommended)**: the corpus exists.
(b) The second pilot's project, after pilot 2 (see `2026-11-14-pilot-2.md`).
(c) Other.

## 8. Not in this plan

Running experiments (the platform never executes experiment code), lab automation (no stage in the factory), cross-project card import beyond slice 6, any model call in the platform, appraisal (IDEA-21), the benchmark ledger changes, and any change to the hub code (lane C).
