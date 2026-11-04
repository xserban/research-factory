# Slice 6 — Hypotheses and testing

Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted). Decisions 67 and 68; requirements R-120–R-125.

## Cross-spec reconciliation 2026-11-04

1. **Gate policy through slice M.** Slice M (M-B) is built before this slice (build order). Ruling 14's table is declared as slice-M gates: `hypotheses.lead_decide`, `hypotheses.register`, `experiments.freeze_unlock` (floor `agent`; exploratory preset `agent` with the non-author/non-drafter rule as the module's `proposer_of` hook; pilot and systematic `human`), and `experiments.accept_baseline`, `hypotheses.property_approve`, `hypotheses.assertion_confirm`, `hypotheses.contradiction_confirm`, `hypotheses.close` (floor `human`). Overrides go in the protocol's `gate_policies` section; `hypothesis_plan` keeps only `min_seeds`, the default confidence level and `test_access_limit` (no `gate_policy` field). The critic review is a quality regime, not a gate. The autonomy label `autonomy: agent` is slice M's `Autonomy.AGENT`, computed on read.
2. **Epistemic classes.** The class column of the vocabulary table reads: property definitions `organisation`; cards `evidence` (stated) or `interpretation` (inferred); contradiction proposals and leads `interpretation`; hypotheses, designs, runs, evaluations and registry rows `test` ("registration record", "own result" and "registry record" are all `test`). `test` is the fourth and last class of the closed set (slice-M reconciliation item 7).
3. **Names shared with slice 5.** The ledger of ruling 25 is the **benchmark ledger**: `services/benchmark_ledger.py`, MCP `benchmark_ledger_view`, CLI `factory benchmark-ledger` (slice 5 keeps `ledger` for credit). The design budget's failure reason is `compute-budget-exhausted` and its check finding `compute-budget-exceeded` (slice 5 keeps `budget-exhausted`).
4. **Plan abbreviations.** The experiment plans are **XP-A** and **XP-B** (slice 7b uses X-A and X-B for its export plans). Order: H-A → H-B, H-C → XP-A → XP-B.
5. **Module kinds.** Vocabulary, contradictions, leads, hypotheses and experiment designs are `proposal` modules; cards a `miner` (single pass with human confirmation and audit, declared quality regime); matching, finders, evaluation and the benchmark ledger `builder`s.
6. **Regions (slice 3d)** are built before this slice; v1 keeps the project as the vocabulary scope and as the transfer boundary (ruling 4, 7), and region scope is Later.
7. **Requirements** R-xx(h)–(m) are R-120–R-125 in [01-rigour.md](01-rigour.md) (the letters clashed with slices 3c, 3d and 5).
8. **Projection version.** Each plan that adds an event type or table bumps `PROJECTION_VERSION` by one from the value it finds.

## v1 scope

- **v1:** vocabulary, cards, assertions, verification (H-A without cross-project import); matching, transfer flag, contradiction and gap finders (H-B); leads, prior failures, hypotheses, critic review, gates, R-53 (H-C); designs, runs, ingestion, unlock, budget, access, baselines (XP-A); statistics, rules, evaluation, multiverse, controls, benchmark ledger, registry, check, trace, methods and the automated acceptance with constructed runs (XP-B).
- **Later:** cross-project card import (ruling 8), region-scoped vocabularies and region-based transfer, the pilot with real runs supplied by the researcher (acceptance 25), additional decision rules (open question 2).

Builds on [00-system.md](00-system.md), slices 1, 2 (plan 2E evidence report), 3a, 3b (lineage ideas `ida_`), 3c (interpretation layer); must satisfy [01-rigour.md](01-rigour.md) R-01–R-05, R-14, R-26, R-40, R-47, **R-50–R-54**, plus the proposed requirements below. Implements backlog IDEA-04 (card level), IDEA-05, IDEA-07, IDEA-16, IDEA-17 and production lines 7, 8, 9, 10 (method research), 12 and 16 of [docs/02-production-lines.md](../02-production-lines.md). IDEA-06 (benchmark ledger) is built as the plan-2E evidence report; this slice links to it and does not change it.

**Depends on.** Slice 3d regions ([slice-3d-regions-import.md](slice-3d-regions-import.md), parallel draft) for region-scoped vocabularies and cross-region matching; slice M ([slice-M-modules.md](slice-M-modules.md), parallel draft) for the stage-module, gate-policy and miner contract. The design is valid before both: until 3d lands, a project is the only region; until M lands, each stage below is a hand-written module whose gates, quality regime, checks and methods text are declared in this spec, and moves behind the contract when slice M is built without changing its events.

## Goal
Turn what the corpus says into **registered, falsifiable hypotheses** and turn experiments run elsewhere into **traceable, pre-registered evidence**, so that every hypothesis can be traced back to the literature that suggested it and forward to the runs that tested it, and every refuted or abandoned direction stays on record. The platform records cards, findings, notes, hypotheses, designs, runs and results, computes everything that can be computed (matches, contradictions, gaps, budgets, outcomes under a registered decision rule), and judges nothing. It never calls a model and never executes experiment code.

Pilot for acceptance: **best linear attention mechanism for vision models.** A method card for a confirmed lineage idea (a kernel-feature approximation of softmax attention) is matched against a problem description (high-resolution dense prediction under a memory bound); the match and a numeric conflict from the evidence report trigger a lead; the lead is promoted to a hypothesis, critic-reviewed by an independent session and registered; an experiment design with one baseline reproduction is frozen; runs executed by the researcher outside the platform are ingested; the outcome is computed by the registered rule and, if refuted or inconclusive, appears in the failed-directions registry.

## Vocabulary
The terms of [docs/10-abstractions.md](../10-abstractions.md) apply. New artifacts of this slice:

| Artifact | Id | Version rule | Epistemic class |
| --- | --- | --- | --- |
| Property definition | key `pr:<slug>` | vocabulary hash `V@<sha8>` over live approved definitions | — |
| Method card / problem description | `mcd_<ULID>` / `pbd_<ULID>` | supersession of assertions | evidence (stated assertions), interpretation (inferred) |
| Property assertion | `pas_<ULID>` | supersession | as its basis |
| Contradiction proposal | `ctr_<ULID>` | supersession | interpretation until confirmed |
| Lead (research-idea note) | `led_<ULID>` | immutable; decisions supersede | interpretation |
| Hypothesis | `hyp_<ULID>`, version `H@<sha8>` | content hash over decision-relevant fields | registration record |
| Experiment design | `exp_<ULID>`, version `E@<sha8>` | content hash; amendments before unlock | registration record |
| Experiment run | `xrn_<ULID>` | immutable; results superseded only by a re-run | own result |
| Closed direction | `dir_<ULID>` | immutable | registry record |

"Lead" is used for IDEA-05's idea note so that it is not confused with the lineage `Idea` of slice 3b, which is a named grouping of papers. Computed outputs (matches, contradiction findings, gap cells, outcomes, ledgers) are builder outputs keyed by a hash of their inputs, not artifacts with ids.

## User flow
1. **Vocabulary.** The researcher approves a small property vocabulary (for example `pr:sampling`, `pr:resolution-max`, `pr:memory-scaling`, `pr:dense-prediction`); Claude may propose properties, which stay unusable until approved.
2. **Cards.** Claude drafts method cards for confirmed lineage ideas or single works, and problem descriptions for the project's task, by recording **property assertions**. An assertion backed by a verified quote or an evidence row is `stated`; an assertion from the agent's reasoning is `inferred` and waits for a human. Problem properties may be stated by the researcher (`researcher` basis).
3. **Builders.** `match_query` computes, per problem description, which method cards satisfy, conflict with or leave unknown each required property, and flags **transfer candidates** (methods whose evidence lies outside the project's corpus or region). `finder_contradictions` lists numeric conflicts inside comparability groups with the conditions that differ; `finder_gaps` lists empty cells of a declared method × condition grid ("not found in corpus").
4. **Leads.** Claude records a lead (≤ 600 characters) with at least one trigger (a match row, a finding, a work, a row, a claim, an `ida_`, an `int_`). The platform attaches the failed directions and earlier hypotheses that share a trigger, method or property, so that dead ends are seen before proposing. A human promotes, parks or discards the lead; nothing is deleted.
5. **Hypotheses.** A promoted lead becomes a hypothesis draft: statement, variables, conditions, prediction with a smallest effect of interest, a decision rule from a fixed menu, and a test reference (an experiment design, or a later-literature window). A critic session that neither drafted the hypothesis nor wrote the lead reviews the artefact (not the proposer's reasoning) against a checklist. The gate holder registers it; `H@` is then frozen.
6. **Experiment design.** For experiment hypotheses, an experiment design names the factor (the one variable that changes), the fixed configuration, seeds, multiverse axes with a primary universe, planned ablations, controls, baselines to reproduce (each pointing to an evidence row), datasets with split roles, metrics, the compute budget and the code and environment references. Amendments are recorded until the design is frozen; freezing fixes `E@`.
7. **Runs outside.** Runs are executed by the researcher or a runner outside the platform (local GPU, server; GPU runners later). Each run is registered against a planned cell of the design and its results are ingested from the runner's metrics file through the CLI, never typed by an agent. Baseline reproductions run first; confirmatory runs need an **unlock**, which issues a nonce that confirmatory results must carry.
8. **Outcome.** When the primary cells are complete, the platform evaluates the registered decision rule and records the outcome (`supported`, `refuted`, `inconclusive`) with flags; the researcher adds a conclusion labelled as interpretation and cannot change the outcome. A hypothesis may be abandoned by a human with a reason.
9. **Registry and ledger.** Refuted, inconclusive and abandoned hypotheses, discarded leads and closed directions form the **failed-directions registry**, with the conditions under which they failed. The **ledger** view joins the evidence report's groups with reproduction outcomes (reported versus reproduced). `check`, `trace` and `report_methods` cover every artifact of the slice.

## Rulings (recommended; [confirm] each)

**Scope and placement**
1. **The platform records experiments; it never runs them.** (a) Runs execute outside; the platform records designs, runs, results and provenance. (b) The platform launches runner scripts in a local sandbox. (c) Defer experiments to a later slice. **Recommended (a)** [confirm]: keeps decision 6's spirit (the platform executes nothing that judges or computes results) and leaves GPU runners to slice 5 deployment.
2. **Leads are a project-local artifact distinct from lineage ideas.** (a) New `led_` artifact in the project event log, class interpretation. (b) Reuse `ida_` with a `kind` field. (c) Keep idea notes in a markdown file per project. **Recommended (a)** [confirm]: `ida_` has a strict quote-backed naming rule (slice-3b ruling 13) that a speculative note cannot meet; IDEA-05's open question ("research ideas belong in each project") is answered by the project log.
3. **Hypotheses and designs are their own hashed artifacts; the protocol carries only their policy.** (a) `H@` and `E@` are separate content hashes; `ProtocolSpec` gains an optional `hypothesis_plan` (gate policies, minimum seeds, default confidence level, test-access limit), omitted from the hash while `None`. (b) Hypotheses as a protocol section. **Recommended (a)** [confirm]: hypotheses arise after the protocol and must not change `P@` (and so must not stale screening decisions under R-15).

**Cards and matching**
4. **Property vocabulary.** (a) A controlled vocabulary of typed properties (`enum`, `set`, `bool`, `number` with unit family), human-approved, versioned by `V@`, region-scoped once slice 3d lands and project-scoped before; reversible merges. (b) One global vocabulary. (c) Free labels with later consolidation. **Recommended (a)** [confirm]: matching needs shared keys (docs/01-concepts.md, "shared property vocabulary"); free labels fragment (decision 5's stated risk).
5. **Assertions are their own events, single pass with human confirmation.** (a) `card.asserted` events reusing the quote, number and anchor verifiers; stated/inferred/confirmed as slice 3b; inferred assertions need a human; an audit sample of stated assertions per the plan-D size rule. (b) A plan-D pack `method-card` with dual extraction. **Recommended (a)** [confirm]; implemented as a hand-written module and moved behind the miner contract (IDEA-37) when slice M lands. Dual extraction is disproportionate for cards that summarise already-extracted rows.
6. **Matching is rule-based and unweighted.** (a) Each property declares a match rule (`equal`, `covers`, `at-most`, `at-least`); per (problem, card) the builder reports satisfied, conflicting and unknown properties and orders cards lexicographically (fewest conflicts, most satisfied, fewest unknown, card id). (b) A weighted score. (c) Embedding similarity. **Recommended (a)** [confirm]: no hidden weights to tune after seeing results; decision 9 (embeddings) stays open and untouched.
7. **Transfer flag.** (a) A match row is `transfer` when no member work of the card's subject is included in the problem's project (or, after 3d, lies in the problem's region). (b) Transfer judged by the agent. **Recommended (a)** [confirm]: "established in A, absent from B" (line 8) is a corpus fact, computable and stated as "not found in this corpus".
8. **Cards cross projects by recorded import.** (a) `factory cards import --from <slug> <mcd_>` writes `card.imported` in the target project with source slug, card id and source event ids; quotes are copied; an assertion re-verifies when the target library holds the same document version, else it is labelled `imported-unverified` and treated as inferred. (b) Live read of other projects' indexes. **Recommended (a)** [confirm]: follows IDEA-36's import pattern and keeps every project's log self-contained; paper-level cross-project flags (IDEA-04 proper) stay with slices 3d/4.

**Finders**
9. **Contradictions.** (a) Numeric conflicts are computed from the evidence report's `method_conflicts` (same normalised method and variant, same comparability key, different values beyond a declared tolerance, copied rows excluded), each listing both rows and the `regime` fields that differ; claim-level contradictions are proposed by an agent (`contradiction_propose`, two live claims or items with quotes), stay inferred and need a human. (b) Numeric only. **Recommended (a)** [confirm].
10. **Gaps.** (a) Gaps are empty cells of a declared grid (methods from cards or the evidence table × values of declared comparability keys), bounded at 10,000 cells per query, each reported with the corpus definition (`P@`, last search date, included-work count) and the sentence "not found in this corpus". (b) Agent-proposed gaps. **Recommended (a)** [confirm]; agents may still record a gap as the trigger text of a lead.

**Leads and hypotheses**
11. **Lead decisions.** (a) `promote | park | discard` by a human (pilot, systematic) or by an agent session other than the lead's author (exploratory); `discard` needs a reason from {`duplicate`, `prior-failure`, `out-of-scope`, `infeasible`, `not-falsifiable`, `other`} plus a note. **Recommended (a)** [confirm].
12. **Hypothesis identity.** (a) `H@` hashes statement-independent fields only: variables, conditions, prediction, decision rule, test reference, kind; prose (statement, rationale) is stripped as in `strip_prose`. A registered hypothesis is never edited; a revision is a new `hyp_` with `supersedes`, allowed only before any confirmatory result or literature-window evaluation exists; afterwards the old hypothesis must be evaluated or abandoned first. **Recommended (a)** [confirm]: blocks rescue-by-revision (R-52).
13. **Critic independence (R-51).** (a) The critic session differs from the drafter's session and from the lead author's session; in systematic mode the model also differs. The review task (`hypothesis_review_next`) is built from structured fields, triggers (ids and verified quotes) and the computed prior-failure list only; the lead text and any drafter note are excluded from its `input_blob`. **Recommended (a)** [confirm].
14. **Registration gate policy** (slice-M gates set through `gate_policies`; presets by mode, reconciliation item 1). **Recommended** [confirm]:

| Gate | exploratory | pilot | systematic |
| --- | --- | --- | --- |
| Lead → draft | agent (non-author) | human | human |
| Critic review | optional | 1 agent critic | 1 agent critic (different model) + human |
| Registration | agent (non-drafter) with label `autonomy: agent` | human | human |
| Design freeze, confirmatory unlock | agent (non-drafter) | human | human |
| Accept a non-reproduced baseline | — (flag only) | human | human |

A hypothesis registered under the exploratory policy is labelled and is never reported as confirmatory (IDEA-38: autonomy declared, never mixed silently).
15. **R-53 temporal hold-out.** (a) Literature-tested hypotheses declare a window start; the human declares model training cut-offs (`model.cutoff_declared`); the platform flags `contaminated` when the drafter's or critic's model cut-off is on or after the window start and `cutoff-unknown` when undeclared (error in systematic). (b) Ignore cut-offs for experiment hypotheses too. **Recommended (a)** [confirm]; experiment hypotheses are not affected, because their evidence is generated after registration.

**Experiments**
16. **Decision rules from a fixed menu.** (a) `superiority` (oriented difference treatment − baseline; supported if the CI lower bound exceeds the margin, refuted if the CI upper bound is below it, else inconclusive), `non-inferiority` (same with −margin), `literature-direction` (among later-literature rows that compare the two methods in one comparability group: supported if the share favouring treatment ≥ q with n ≥ n_min, refuted if the share against ≥ q, else inconclusive; n < n_min gives `insufficient-evidence`). CI: paired Student-t on per-seed differences at the declared level, with an embedded quantile table (levels 0.90, 0.95, 0.99; df 1–60). Minimum seeds: 3 (pilot), 5 (systematic). (b) Percentile bootstrap. (c) Free analysis scripts, outcome typed by a human. **Recommended (a)** [confirm]: a bootstrap over three to five seeds is degenerate; (c) makes the outcome a judgement after seeing data.
17. **Outcome is computed.** (a) `hypothesis.evaluated` is written by the platform (`actor.kind = system`) with the input runs, statistic and rule; the human adds `hypothesis.concluded` (interpretation text, ≤ 1,200 characters) and cannot change the outcome; `abandoned` is a separate human act with a reason. **Recommended (a)** [confirm]: applying a pre-registered numeric rule is bookkeeping, not judgement; the judgement was made at registration.
18. **Exploratory versus confirmatory (R-50).** (a) Each dataset carries a split role (`dev`, `confirmatory`) and a content hash; confirmatory runs need `experiment.unlocked`, which requires a frozen design, a registered hypothesis and resolved baselines, and issues a nonce; a confirmatory result without the nonce is refused; each primary cell may be evaluated on the confirmatory split `test_access_limit` times (default 1); an extra access is recorded as a deviation and flags the outcome `test-reused`. **Recommended (a)** [confirm]. The platform cannot detect evaluation that is never recorded; the nonce and the git timestamps of registration events evidence order only.
19. **Who submits results.** (a) A human or a runner (`actor.kind = system`, id `runner-<name>`) through the CLI, from a metrics file in a declared JSON schema; agents may register planned runs but cannot submit results over MCP. (b) Agents also submit through MCP with a file hash. **Recommended (a)** [confirm]: "agents never do bookkeeping"; numbers come from machine output.
20. **Run artifacts.** (a) The metrics file (small, text) is stored as a git blob; checkpoints and full logs stay outside git, referenced by sha256 and a location URI. **Recommended (a)** [confirm] (decision 39 pattern).
21. **Budget.** (a) The design declares GPU-hours, a per-run cap and a maximum run count; registration beyond the maximum is refused; reported hours above the budget are recorded as a deviation; `compute-budget-exhausted` is a failure reason. **Recommended (a)** [confirm].
22. **One variable at a time.** (a) Each run carries a flat configuration map; a treatment–baseline pair is formed only when the maps differ in exactly the factor keys (plus the seed match), computed; other pairs are excluded and counted as `confounded`. Ablations must each differ from the full configuration in one declared component key, checked at design time. **Recommended (a)** [confirm].
23. **Multiverse.** (a) Axes with explicit values; universes are their product, bounded at 256 per design; one primary universe is declared; the decision rule applies to the primary universe; the platform reports the specification curve (per-universe effect and CI) and flags `only-non-primary` when the rule would hold in some universes but not the primary one, and `fragile` when the sign of the effect differs across universes. **Recommended (a)** [confirm].
24. **Baseline reproduction.** (a) A baseline is an evidence row (`row_key`) with its comparability key; a reproduction run in the same key is `reproduced` when the reproduced metric lies within the declared tolerance (absolute or relative, default 1 % relative) of the reported value, else `not-reproduced`; unlock requires every declared baseline to be resolved (`reproduced`, or `not-reproduced` accepted by the gate holder, which is recorded as a deviation and flags the outcome `baseline-not-reproduced`). **Recommended (a)** [confirm] (IDEA-17: reproduce baselines first).
25. **Ledger linkage.** (a) A separate builder `benchmark_ledger` joins `evidence_report` groups with reproduction outcomes and own results, in their own columns; the evidence report and its tests are unchanged. (b) Reproduced values become rows of the evidence report. **Recommended (a)** [confirm]: decision 52's grouping rules stay intact and own results are never merged with reported results (R-125).
26. **Controls (R-54).** (a) A design may declare positive and negative control cells with their expected result (effect present, effect absent); their computed outcomes are reported as the experiment's sensitivity and false-positive checks; at least one of each is required in systematic mode. **Recommended (a)** [confirm].
27. **Failed-directions registry.** (a) A projection over refuted, inconclusive and abandoned hypotheses, discarded leads, not-reproduced baselines and `direction.closed` records (a human closing a direction that never became a hypothesis), each with reason and conditions (budget, data, model, code reference, design `E@`); searchable by method card, lineage idea, property, work and trigger. **Recommended (a)** [confirm].

## Design

### Property vocabulary
A `PropertyDef` has a `key` (`pr:<slug>`), `kind` (`enum | set | bool | number`), `allowed` (for `enum` and `set`), `unit_family` (for `number`, reusing `packs/model.py` `UnitFamily`), `match` (`equal | covers | at-most | at-least`), `applies_to` (`method | problem | both`), `aliases` and a prose `description` (not hashed). Agents propose (`vocabulary.property_proposed`); a human approves or rejects (`vocabulary.property_decided`); merges are reversible (`vocabulary.property_merged` / `_unmerged`, R-26). `V@` hashes the live approved definitions without prose. Assertions name the property key and record the `V@` in force; a merge resolves keys at read time; a removed or changed definition makes dependent assertions `stale`.

### Method cards and problem descriptions
A card is a header event (`card.created`: kind, subject, owner) and a set of assertions. A method card's subject is a confirmed lineage idea (`ida_`, resolved through merges) or a work id; a problem description's subject is the project question (`Q@`) or a named task within it. A `PropertyAssertion` carries the property key, a value (enum value, set, bool, or number with unit), and one basis:

| Basis | Content | Status |
| --- | --- | --- |
| `quote` | work, conversion, anchor, verbatim quote; for `number` the value must pass the number check (R-44); for `enum`/`bool` the value or an alias must occur in the quote | `stated` if all checks pass, else rejected |
| `row` | an evidence `row_key` and field (for example params, FLOPs) | `stated` if the row is final and the value equals its canonical value |
| `researcher` | a human statement (problem descriptions, constraints of the project) | `stated`, actor human |
| `inferred` | agent reasoning, with a note ≤ 500 characters and optional supporting quotes | `inferred` until a human confirms |
| `imported` | copied from another project (ruling 8) | re-verified → `stated`; else `imported-unverified` |

A later assertion of the same (card, property) supersedes the earlier one. Evidence of where a method worked is not typed: the builder lists the evidence-report groups (`group_id`) that contain final rows of the card's member works. Default views use stated and confirmed assertions only.

### Matching (builder)
`match(problem_id, *, statuses, limit, after)` reads the problem's required properties and streams candidate cards through an indexed table `card_props(card_id, property_key, value_norm, number_canonical, status)`, so a query touches only cards that assert at least one required property. Per required property the rule yields `satisfied | conflicting | unknown`. Output rows: card id, subject, counts, the three key lists, `transfer` flag, member works included in the project, evidence groups; paged and ordered as ruling 6. Every result carries `match_key = sha256(problem state, card states, V@, builder version)` so a lead can cite it and `trace` can detect that the inputs have since changed (`trigger-changed`, a flag, not an error).

### Finders (builders)
**Contradictions.** `finder_contradictions(group_id | None)` reads `evidence_report(...)` group by group and, for each `MethodConflict`, emits the pair rows, both values with trace ids, the relative difference, and `differs_in`: the `regime` keys whose values differ between the rows (the "conditions that differ" of IDEA-07). Pairs within the declared tolerance are not conflicts. Claim contradictions (`ctr_`) name two live claims or contribution items with their quotes and the agent's note; they are inferred until a human confirms (`contradiction.decided`), and are shown labelled.

**Gaps.** `finder_gaps(rows_axis, columns_axis, filters)` takes two axes: methods (normalised method names of final rows, or method cards) and one declared comparability key (or a property key of cards); it counts final independent rows per cell with an SQL `GROUP BY` and reports empty cells. The grid size is checked before the query (≤ 10,000 cells, else a structured error asking for a filter). Each empty cell carries the corpus definition and the fixed sentence "not found in this corpus".

### Leads
`lead_record(text, triggers, framework?)` stores a ≤ 600-character note, one or more triggers (each resolved by `dangling_refs`-style lookup; a match or finding trigger stores its key and the row), and an optional ideation framework label (docs/09-existing-assets.md: record which framework produced it). At write time the platform computes `prior` — the ids of failed directions and hypotheses sharing a trigger, card, idea or property — and stores it in the event, so that the critic and the human see what was shown. A lead without triggers is refused (slice-3c ruling 5 applied: an ungrounded speculation does not enter the project).

### Hypotheses
`HypothesisSpec` (agent or human input): `kind` (`experiment | literature`); `statement` (≤ 600 characters, prose); `lead` (optional `led_`, required in pilot and systematic); `treatment` and `baseline` (each a method card, an `ida_` or a method name with evidence row); `metric` (name, direction `higher|lower`, unit family); `conditions` (comparability key values: dataset, task, resolution, …); `prediction` (`direction`, `margin` with unit); `decision_rule` (ruling 16 with its parameters); `test` (`experiment` → the design that names this hypothesis, so that linking a design never changes `H@`; `literature` → window start date, the searches or protocol version that define "later literature", `n_min`, `q`); `alternatives` (sibling `hyp_` ids: multiple working hypotheses). The falsifier is derived from the rule and printed, never typed.

States, computed from events: `draft → reviewed → registered → (evaluated | abandoned)`, with `superseded` for drafts and registered hypotheses replaced before evidence (ruling 12). `hypothesis_review` records the critic's checklist (falsifiable, measurable, single factor, baselines named, rule complete, prior failures addressed, conditions match evidence groups) with `recommend: register | revise | reject` and per-item notes. Registration requires a review with `register` from an eligible critic (ruling 13) under the gate policy (ruling 14). The registration event stores `H@`, the reviewing event id and the gate policy in force.

### Experiment designs
`ExperimentDesign`: `hypothesis` (`hyp_`, must be registered or draft-linked), `factor` (configuration keys that change between treatment and baseline), `base_config` (flat key → scalar map), `code` (repository URI and commit), `environment` (lockfile or container digest), `datasets` (name, version, content hash, split role), `metrics` (name, direction, unit family, primary flag), `seeds` (list), `axes` (multiverse: key → values), `primary_universe`, `ablations` (name → one component key and its ablated value), `controls` (positive and negative cells with expected outcome), `baselines` (evidence `row_key`, tolerance), `budget` (GPU-hours, per-run cap, maximum runs), `test_access_limit`. Validation at the boundary: product of axes ≤ 256; each ablation differs in one key; the primary universe is in the product; baselines resolve to final evidence rows whose comparability key matches the hypothesis conditions. `E@` hashes all decision-relevant fields. Amendments before freeze are free and recorded with reason; after freeze, changes are deviations (R-14); after unlock, a semantic change flags the outcome `deviated`.

### Runs and results
`xrun_register` (agent or human) names the design, cell (universe coordinates, seed, arm: `treatment | baseline | ablation:<name> | control:<name> | reproduction:<row_key>`) and split. The platform computes the run's configuration map from the design and cell and stores it with its hash. Results are ingested with `factory runs record <xrn_> --file metrics.json` (schema: metric values with units, GPU-hours, wall-clock, exit status, environment digest, code commit, optional external tracker run id, and for confirmatory runs the unlock nonce). Checks: metrics match the design's declared metrics and unit families; code commit and environment digest equal the design's, else the run is recorded with `environment-differs` and excluded from pairing; budget and access counts are recomputed. Failed runs (non-zero exit) are recorded and counted, never dropped. A re-run is a new `xrn_` for the same cell; the evaluation uses the first completed run per cell and reports the others (no best-of-n).

### Evaluation, reproduction and ledger (builders writing system events)
`evaluate(hyp_)` runs when every primary-universe cell has a completed run (or on human request, which records `incomplete`). It forms seed-matched treatment–baseline pairs (ruling 22), computes per-seed oriented differences, mean, paired-t CI, applies the rule, computes flags (`test-reused`, `deviated`, `baseline-not-reproduced`, `only-non-primary`, `fragile`, `contaminated`, `cutoff-unknown`, `autonomy:agent`) and writes `hypothesis.evaluated` with the input run ids and a hash of the computation inputs, so that a rebuild recomputes and compares. Literature hypotheses are evaluated on the evidence report restricted to works published on or after the window start. Baseline reproductions write `baseline.evaluated` (reproduced value, reported value, tolerance, verdict). `benchmark_ledger(group_id?)` joins evidence groups with `baseline.evaluated` and own results; own results never enter the group's rows, frontiers or counts.

### Failed-directions registry
A projection `directions` with one row per refuted, inconclusive or abandoned hypothesis, discarded lead, not-reproduced baseline and `direction.closed` record: reason (`refuted`, `inconclusive`, `below-baseline`, `baseline-not-reproduced`, `compute-budget-exhausted`, `no-runnable-code`, `infeasible`, `discarded-lead`), conditions (design `E@`, datasets, budget used, model ids, code commit), and the keys it is searchable by (cards, ideas, properties, works, triggers). `registry_query(keys)` returns matching rows; `lead_record` uses the same query for `prior`. A row is never removed; a later success of a similar direction is a new artifact, and the old row keeps its conditions ("failed here", not "impossible").

### Deterministic versus agent
| Platform (deterministic, tested, offline) | Agent (Claude via MCP) | Human (CLI) |
| --- | --- | --- |
| Verify assertion quotes, numbers, rows; classify stated/inferred; compute matches, conflicts, gaps, prior failures, `H@`, `E@`, configuration maps, pairing, budgets, statistics, outcomes, ledger, registry | Propose properties; draft cards, leads, hypotheses, designs; propose claim contradictions; review as critic; register planned runs | Approve properties; confirm inferred assertions and contradictions; decide leads; register hypotheses; freeze and unlock designs; ingest results; accept non-reproduced baselines; conclude, abandon, close directions; declare model cut-offs |

Every agent-written event carries model, skill version and `input_blob` (R-04).

## Events (schema 1)
| Event | Payload (summary) | Actor |
| --- | --- | --- |
| `vocabulary.property_proposed` / `_decided` / `_merged` / `_unmerged` | definition; decision with rationale; merge with reason | agent or human / human |
| `card.created` | `card_id`, `kind`, `subject`, `owner` | agent or human |
| `card.asserted` | `assertion_id`, `card_id`, `property`, `value`, `unit`, `basis`, computed `status`, `vocabulary_version`, `supersedes` | agent or human |
| `card.assertion_decided` | `assertion_id`, `confirm | reject`, rationale | human |
| `card.imported` | target `card_id`, source slug, source card id, source event ids, assertions with copied quotes and re-verification results | human |
| `contradiction.proposed` / `_decided` | `ctr_`, two refs with quotes, note / decision | agent / human |
| `lead.recorded` | `lead_id`, text, triggers (with keys), framework, computed `prior` | agent or human |
| `lead.decided` | `promote | park | discard`, reason, note | per ruling 11 |
| `hypothesis.drafted` | `hyp_`, spec, computed `H@`, `supersedes` | agent or human |
| `hypothesis.reviewed` | `hyp_`, `H@`, checklist, recommendation | agent (critic) or human |
| `hypothesis.registered` | `hyp_`, `H@`, review event id, gate policy, autonomy label | per ruling 14 |
| `hypothesis.evaluated` | outcome, statistic, CI, n, flags, input runs, inputs hash, rule version | system |
| `hypothesis.concluded` / `.abandoned` | interpretation text / reason, note | human |
| `model.cutoff_declared` | model id, training cut-off date, source note | human |
| `experiment.designed` / `.amended` / `.frozen` / `.unlocked` / `.deviation_recorded` | design, `E@` / change with reason and semantic flag / `E@` / nonce / deviation text and kind | agent or human / human |
| `xrun.registered` | `xrn_`, design, cell, split, configuration map and hash | agent or human |
| `xrun.reported` | metrics, compute, exit status, environment, commit, nonce, blob ref of the metrics file, artifact refs | human or system (runner) |
| `baseline.evaluated` | design, `row_key`, reported and reproduced values, tolerance, verdict, runs | system |
| `direction.closed` | `dir_`, text, reason, conditions, keys | human |
No event is edited; corrections supersede (R-40).

## Index tables (projection only)
`properties`, `property_merges`, `cards`, `card_assertions`, `card_props` (indexed by `(property_key, value_norm)`), `contradictions`, `leads`, `lead_triggers` (indexed by ref), `hypotheses`, `hypothesis_reviews`, `model_cutoffs`, `experiments`, `experiment_amendments`, `xruns` (indexed by `(design, cell_hash)`), `baseline_evaluations`, `hypothesis_evaluations`, `directions`, `direction_keys` (indexed by key). Derived states (assertion staleness, hypothesis state, budget used, access counts) are computed on read. Rebuild determinism holds (slice-1 AC 1).

## MCP tools and CLI
| Tool | Purpose | Actor |
| --- | --- | --- |
| `vocabulary_propose` | Propose a property | agent |
| `card_create`, `card_assert` | Create a card; record assertions (batched, partial acceptance) | agent |
| `card_view` | A card with assertions and statuses | read |
| `match_query` | Matches for a problem description, paged | read |
| `finder_contradictions`, `finder_gaps` | Builders | read |
| `contradiction_propose` | Propose a claim-level contradiction | agent |
| `lead_record`, `registry_query` | Record a lead; search failed directions | agent / read |
| `hypothesis_draft`, `hypothesis_view` | Draft or revise; view with state and falsifier | agent / read |
| `hypothesis_review_next`, `hypothesis_review` | Critic task (artefact-only payload) and review | agent (critic) |
| `experiment_design`, `experiment_view` | Draft or amend a design before freeze; view with budget and access counts | agent / read |
| `xrun_register`, `xrun_list` | Register planned runs; list runs and their status | agent / read |
| `benchmark_ledger_view` | Benchmark ledger for a group | read |

No MCP tool decides a lead (except the exploratory policy), confirms an assertion or contradiction, registers a hypothesis outside the exploratory policy, freezes or unlocks a design, ingests results, accepts a baseline, concludes, abandons or closes. Sessions that have joined a screening or extraction pass are refused every tool of this slice (decisions 37, 43, 48 extended). MCP views follow decision 43 (no held-out recall or label-derived rates).

CLI: `factory vocabulary list|approve|reject|merge|unmerge`, `factory cards list|show|confirm|reject|import`, `factory contradictions list|confirm|reject`, `factory leads list|promote|park|discard`, `factory hypotheses list|show|register|evaluate|conclude|abandon`, `factory models cutoff`, `factory experiments show|freeze|unlock|amend|deviation|accept-baseline`, `factory runs list|record`, `factory benchmark-ledger`, `factory registry [--key K]…`, `factory directions close`. Services: `services/properties.py`, `services/cards.py`, `services/matching.py`, `services/finders.py`, `services/leads.py`, `services/hypotheses.py`, `services/hypothesis_review.py`, `services/experiments.py`, `services/xruns.py`, `services/evaluation.py`, `services/benchmark_ledger.py`, `services/directions.py`; pure helpers in `factory/hypotheses/` (`match.py`, `rules.py`, `stats.py`, `pairing.py`, `tquantiles.py`). Skills: `rf-cards`, `rf-ideate`, `rf-critic`, `rf-experiment`, each with a version hash.

## Check findings
`property-proposed-unapproved` (advisory) · `assertion-inferred-unconfirmed` · `assertion-stale` · `card-imported-unverified` · `contradiction-unconfirmed` · `lead-undecided` · `hypothesis-unreviewed` · `hypothesis-registered-untested` (no design or window) · `hypothesis-cutoff-unknown` (error in systematic) · `hypothesis-contaminated` · `experiment-not-frozen` · `baseline-unresolved` · `xrun-environment-differs` · `xrun-reported-without-registration` (structurally impossible; broken-chain check) · `compute-budget-exceeded` · `test-access-exceeded` · `controls-missing` (systematic) · `evaluation-stale` (inputs hash differs on rebuild: error) · `hypothesis-evaluated-unconcluded` (advisory). Messages carry ids and counts only, never document text.

## Rigour requirements
Existing, in scope: **R-01/R-02** (every hypothesis traces to its triggers and through them to spans; every run to its design and hypothesis); **R-04**; **R-05** (matches, gaps, budgets, statistics, outcomes, registry counts computed); **R-14** (design amendments and deviations separate); **R-26** (property and idea merges reversible); **R-40, R-44** (assertion quotes and numbers); **R-47**; **R-50** (registration before evidence; dev/confirmatory split); **R-51** (critic and gate holders independent of proposers); **R-52** (registry; methods report counts every outcome); **R-53** (cut-off rule); **R-54** (controls).

Added on acceptance (numbers in [01-rigour.md](01-rigour.md)):
- **R-120 Hypotheses cite triggers.** A lead or hypothesis without at least one resolvable trigger cannot be written (pilot, systematic: lead required for a hypothesis). All modes.
- **R-121 Computed outcome.** The outcome of a registered hypothesis is computed from recorded results by its registered decision rule; no actor sets it. All modes.
- **R-122 Reproduce before confirm.** Confirmatory runs need every declared baseline resolved; a non-reproduced baseline accepted by a human flags every dependent outcome. P, S.
- **R-123 Recorded order.** Confirmatory results carry the unlock nonce issued after registration and freeze; results without it are refused. P, S.
- **R-124 Failure conditions.** Every registry row states the conditions of failure (design, data, budget, model, code); a registry row is never removed. All modes.
- **R-125 Own results apart.** Own and reproduced results are never merged with reported results in groups, frontiers or counts. All modes.

## In scope
Property vocabulary; method cards and problem descriptions with verified assertions; cross-project card import; matching with transfer flags; contradiction and gap finders; leads with prior-failure lookup; hypothesis registry with critic review, gate policies and R-53; experiment designs, runs and result ingestion; budget, access and deviation accounting; baseline reproduction; decision-rule evaluation, multiverse and ablation summaries, controls; ledger view; failed-directions registry; check, trace, methods text; skills.

## Out of scope
Executing experiments, sandboxes and GPU runners (slice 5 deployment); integration with an external experiment tracker beyond storing its run id (decision 21 stays open); embeddings or learned similarity (decision 9); automatic hypothesis generation by the platform; meta-analysis and pooled effect sizes (line 6); dataset discovery (line 10, first half); paper-level cross-project alerts (IDEA-04 proper, slices 3d/4); writing results up (slice 7); many-analysts re-implementation (tier 3, later).

## Acceptance criteria
1. **Vocabulary.** An assertion on an unapproved property is refused; a merge and its reversal restore card views exactly; `V@` is unchanged by a prose edit.
2. **Assertion verification.** A `quote` assertion with a non-verbatim quote, a number absent from its quote, or an enum value absent from the quote (and aliases) is rejected; valid assertions of the same call are written; no document text appears in errors.
3. **Stated rule.** `row` and verified `quote` assertions are stated; `inferred` ones are excluded from default views and matches until a human confirms; an agent cannot confirm.
4. **Import.** An imported assertion whose document version is in the target library re-verifies to stated; otherwise it is `imported-unverified`; the import names its source events.
5. **Matching.** On a constructed vocabulary and five cards, `match_query` returns the expected satisfied, conflicting and unknown sets and order; the transfer flag follows ruling 7; a property change alters `match_key`; the query reads only cards asserting a required property (query-count test).
6. **Contradictions.** A constructed group with two works reporting different values for one method yields a conflict listing both rows and the differing regime keys; a copied row or a difference within tolerance does not.
7. **Gaps.** Empty cells are reported with the corpus definition; a grid above 10,000 cells is refused with a structured error.
8. **Leads.** A lead without a resolvable trigger is refused; `prior` lists a failed direction sharing a card with the lead; a discard needs a reason; the author cannot decide its own lead.
9. **Hypothesis hash.** Changing the statement leaves `H@` unchanged; changing margin, rule or conditions changes it; a revision after an evaluation exists is refused.
10. **Critic independence.** The drafter's session, the lead author's session and (systematic) the drafter's model are refused as critic; the review task's `input_blob` contains no lead text and no drafter note.
11. **Gate policy.** Under pilot, an agent cannot register, freeze, unlock or ingest; under exploratory, a non-drafter agent may register and the hypothesis carries `autonomy: agent` in every view and in methods.
12. **R-53.** A literature hypothesis whose drafter model's declared cut-off is after the window start is flagged `contaminated`; an undeclared cut-off gives `cutoff-unknown`, an error in systematic.
13. **Design validation.** A design with > 256 universes, an ablation differing in two keys, or a baseline row outside the hypothesis conditions is rejected; `E@` changes with any decision-relevant field.
14. **Order.** Confirmatory registration or results before unlock are refused; results without the nonce are refused; a second confirmatory access to a cell is a deviation and flags `test-reused`.
15. **Pairing.** Runs differing in a non-factor key are not paired and are counted as confounded; a run whose commit or environment differs is excluded and listed.
16. **Budget.** Registration beyond the maximum run count is refused; reported hours above the budget produce a deviation and a check finding.
17. **Reproduction.** A reproduced value within tolerance gives `reproduced`; outside, `not-reproduced`; unlock is refused until each baseline is resolved; acceptance of a non-reproduced baseline flags dependent outcomes.
18. **Evaluation.** On constructed runs, the paired-t CI and the outcome match hand-computed values for superiority and non-inferiority; `literature-direction` with n < n_min gives `insufficient-evidence`; an outcome cannot be set by any actor; a rebuild recomputes the same outcome or `check` reports `evaluation-stale`.
19. **Multiverse.** A constructed specification curve gives `only-non-primary` and `fragile` as defined.
20. **Ledger separation.** With own results and reproductions present, `evidence_report` output is byte-identical to the state without them; the ledger shows reported and reproduced values in separate columns.
21. **Registry.** A refuted hypothesis, a discarded lead, a not-reproduced baseline and a closed direction each appear with reason and conditions; `registry_query` finds them by card, idea, property and work.
22. **Trace.** `trace` from an outcome returns the evaluation, runs, metrics blobs, design, hypothesis, review, lead, triggers and, through a trigger row, the slice-2 chain to the question.
23. **Methods.** `report_methods` states the counts of leads by decision, hypotheses by outcome (including refuted and inconclusive), deviations, test reuse, non-reproduced baselines and autonomy labels, all computed.
24. **Rebuild and quality.** Deleting the index and rebuilding gives identical tables and state hash; `mypy --strict`, ruff; coverage ≥ 90% for `services/` and `model/`; TDD; hypotheses, evaluation and experiments by subagent-driven development.
25. **Pilot.** The pilot flow of the Goal runs end to end with real runs supplied by the researcher; the reported numbers (matches, conflicts, leads, outcome, flags) are computed.

## Dependencies
| Slice / plan | Needed for |
| --- | --- |
| Plan 2E (evidence report) | `evidence_report`, `EvidenceRow`, `GroupReport.method_conflicts`, `group_id`, `regime`; baselines, contradictions, gaps, ledger |
| Plan 2D (extraction) | `final_rows`, `live_claims`, verifiers (`quote_in_element`, number checks) |
| Slice 3b (G2) | Confirmed `ida_` ideas as card subjects, contribution items as triggers |
| Slice 3c (G3) | Interpretation class and review conventions; `int_` and `cpt_` as triggers |
| Slice 3d (regions, parallel draft) | Region-scoped vocabularies, region-based transfer flag; before it, project = region |
| Slice M (modules, parallel draft) | Stage-module and gate-policy contract; this slice's gates map onto it unchanged |
| Slice 5 (teams, deployment) | Several humans for review independence; GPU runners as `system` actors |

## Proposed sub-plans
| Plan | Content | Tier |
| --- | --- | --- |
| [hypotheses-a-cards](../plans/2026-11-05-hypotheses-a-cards.md) | Vocabulary, cards, assertions, verification, import, tools, skill `rf-cards` | critical |
| [hypotheses-b-matching-finders](../plans/2026-11-05-hypotheses-b-matching-finders.md) | Match rules and builder, contradiction finder and proposals, gap finder | standard |
| [hypotheses-c-leads-registry](../plans/2026-11-05-hypotheses-c-leads-registry.md) | Leads, prior failures, hypothesis spec and `H@`, critic review, gate policy, R-53, skills `rf-ideate`, `rf-critic` | critical |
| [experiments-a-design-runs](../plans/2026-11-05-experiments-a-design-runs.md) | Designs and `E@`, amendments, freeze, unlock and nonce, runs, result ingestion, budget, access, baselines, skill `rf-experiment` | critical |
| [experiments-b-evaluation-registry](../plans/2026-11-05-experiments-b-evaluation-registry.md) | Statistics, pairing, decision rules, evaluation, reproduction, multiverse, ledger, registry, check, trace, methods, acceptance | critical |
Order: A → B → C → XP-A → XP-B; B and C may run in parallel after A. Each plan ends with every earlier test passing unchanged except the projection-version pin.

## Decisions (recorded 2026-11-04)
- **67 Slice-6 scope.** The platform records, but never executes, experiments; results enter only from machine-written metrics files through the CLI; outcomes are computed by pre-registered rules from a fixed menu (rulings 1, 16, 17, 19).
- **68 Slice-6 rulings.** Rulings 2–15 and 18–27 as recommended, ruling 14 through slice-M gates (reconciliation item 1); answers decision 17 (property vocabulary: agent-proposed, human-approved).

## Open questions
1. **Single-researcher independence.** With one human, the human gate holder is also often the lead's promoter; recommendation: allow it with the `self-reviewed` flag as slice-3c ruling 8, since the critic is a separate agent session.
2. **Statistics beyond the menu.** Some hypotheses need other tests (rank-based, multiple metrics). Recommendation: add rules to the menu by decision, each with a hand-checked test; never free scripts for the registered outcome; free analyses are recorded as exploratory.
3. **Multiple metrics.** A hypothesis with several primary metrics needs a multiplicity rule. Recommendation: one primary metric per hypothesis in this slice; secondary metrics reported descriptively.
4. **External tracker.** Recommendation: keep decision 21 open; a later adapter converts a tracker export into the metrics file schema.
5. **Cost of cards.** Cards for every lineage idea may be costly; recommendation: cards on demand for ideas that appear in matches or leads, plus the problem descriptions of each project.
6. **Literature hypotheses at scale.** Evaluating against later literature needs a living corpus (slice 4) for the window; until then the window is filled by a declared search run after registration.
