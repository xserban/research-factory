# Technique comprehension and the graph of ideas (plan, 2026-11-14)

Status: plan; nothing built, nothing run. Research question: SQ1 (a reference process), deepened from "what systems do" to "how, why and from where". Builds on the step miner `m-stage-steps` v1 (`ops/screeners/steps-wrapup-2026-11-14.md`), `m-stages` v1, the lifecycle plans (`2026-11-13-ai-scientist-lifecycle.md`, `2026-11-13-lifecycle-stage-deep-dive.md`), slice 3b (contribution pack, ideas, relations) and 3c (concepts, interpretations), taxonomies as versioned objects (IDEA-50), miners (IDEA-37) and the hypotheses-engine plan (`2026-11-14-hypotheses-engine.md`, gap G1). Backlog: IDEA-78. Part A is the pilot's process; part B is what the factory should take from it.

## 1. Why: what the step miner did and did not give

`m-stage-steps` v1 recorded, per paper and stage, one row per step: the paper's sentence for the step, with optional inputs, outputs, method, check and limits (95 core works; pass A Haiku, 1,352 rows; pass B Sonnet, 12 works; uncalibrated, exploratory). Computed over pass A: 267 rows (20%) say how a step is done; 38 rows (3%) carry any citation marker, the only place an origin appears; no row links one paper's technique to another's, although such links exist (OmniScientist's ideation steps repeat Deep Ideation's; Chain of Ideas reuses Idea Arena). Keyword counts (exploratory) show the same mechanisms in many stages: retrieval and LLM critics in 8 stages, evolutionary operators in 7, tree search and pairwise ranking in 5, novelty checks in 4.

The miner answered "which sentence describes step N of stage X": an index of each pipeline, not an understanding of its techniques. Calibrating it would not change what it asks.

## 2. Goal

For each stage of the reference pipeline, a list of techniques and the relations between them (lineage, variants), each technique understood: what it is and how it works, why it should work, where it comes from, what evidence supports it, what problems it addresses or shows. The graph of ideas is built from these and feeds the hypotheses engine.

## 3. The difficulty the process must solve

A paper is deep on the stage where it innovates and shallow on the others, which it still carries out, each slightly differently from other papers. One general reader per paper (v1) spreads thin and flattens the shallow stages. A small difference is visible only against a reference: describing every implementation in absolute terms gives descriptions that cannot be compared.

## Part A. The pilot process

### A1. Comprehension levels (ruling 1)

An entry reaches **explain** (mechanism in own words, the design choices that matter), **justify** (why it should work, what it assumes), **situate** (origin, what it builds on or replaces; citations followed outside the corpus when needed), **abstract** (variants across papers recognised as one technique), **evaluate** (evidence level, A6) and **use** (what could be changed, combined or transferred).

### A2. Unit and granularity

The unit is a **technique use**: system S uses technique T in stage St, with a variant. A technique is a **swappable component**, a part another system could adopt without the rest (tournament ranking, novelty check against a search API, tree search over hypotheses). Prompt wording, model and parameters are attributes of a use. The pipeline shape (line, loop, tree, agent pool with orchestrator) is a technique at the level above. Each use carries a status: core contribution, secondary contribution, reused with a citation, standard without a citation, unclaimed variant (the miner's reading, flagged). Contributions that are not techniques (benchmark, dataset, finding) are recorded as such; they feed evidence and problem nodes.

### A3. Miners (ruling 8)

1. **Map miner** (per work, whole text, light). Which stages the system carries out (axis: the 9 stages of `m-stages` v1, ruling 9), where each is described (section anchors), the pipeline shape, and which stages the paper claims to innovate in. Reuses `m-stages` where its rows suffice.
2. **Contribution miner** (per claimed innovation, deep). Reads the sections the map located and, when needed, the cited sources. Records the problem observed, the mechanism in its own words, what it builds on and what it changes, the evidence (ablations), the stated limits. Extends slice 3b's `contribution` pack (base-idea, addition, result, limitation) with the problem and the stage.
3. **Stage codebooks.** For each stage, a catalogue of known techniques and the usual practice, seeded from the contribution miner's output: papers that innovate at a stage describe it best and name their predecessors, so innovations become entries already linked to origins. Codebooks for the 7 substantive stages; `lab-automation` (4 works) and `other` (a catch-all) are recorded without a codebook until material suffices (ruling 9). A technique used in several stages (tree search, critics, retrieval) is one entry referenced by several codebooks, never split.
4. **Stage miners** (per stage, all works, reading only that stage's passages from the map). With the stage's codebook: which entries the paper uses, how its variant differs from the entry, and anything not in the codebook, proposed as a new entry. A stage described only in passing is recorded as "uses X, details not stated", never dropped and never filled in (ruling 10).
5. **Versioned growth.** Proposed entries are reviewed in batches and added as a new codebook version; works mined against an older version are re-checked only for the new or changed entries.

Relations: **lineage** (builds on, changes) from the contribution miner; **variant-of** from the stage miners.

### A4. Descriptions, not excerpts

Mechanism, rationale and variant fields are descriptions in the miner's own words; quotes are footnotes that let a reader find where a statement comes from. These fields are interpretations, never evidence.

### A5. Graph (ruling 3)

Nodes: technique, system, origin, problem, evidence. Edges: uses (with stage and variant), derives-from (stated by citation, or convergent without one), variant-of, addresses, reports, supported-by (with evidence level). Lenses hide node types: techniques and lineage; problems; one system; evidence overlay; a stage filter (where technique T is used across the pipeline). Every node carries its first-version date: the corpus moves in weeks and the feed keeps adding papers.

### A6. Evaluation in a heterogeneous corpus

Effects are not compared across papers (different benchmarks, models, budgets). Each use carries an evidence level: **independent test** (other authors test it, mainly evaluation and benchmark papers), **own ablation**, **asserted only**, **reported failure**. A technique's evaluation is the computed count of uses at each level, with settings named.

### A7. Problems (ruling 5)

The weakest layer: motivation problems are shaped to fit the paper's answer and observed failures are rare (4% of v1 rows had a limit). Each problem is **claimed** or **observed**, with the evidence levels of A6; observed problems come mainly from evaluation papers; a problem is a node with supporting and contradicting sources; the problems lens shows observed problems by default.

### A8. Checking understanding (ruling 6)

Automatic teach-back with separated roles: the **writer** reads the papers and writes the entry; the **questioner** reads the papers and writes questions with answers; the **answerer** sees only the entry; the **grader** compares answers with the papers and flags parts for rewriting, never overwriting. Writer and grader use different models where possible. The researcher calibrates the checker once, on about 10 entries. Subagents at most Sonnet.

### A9. Order of work

1. Trial on one stage (ideation) to design the miners: map miner and contribution miner on about 6 works whose contributions are at ideation, a first ideation codebook, the stage miner on about 6 further works, one teach-back round. The researcher judges the shape.
2. Fix fields and wording; record the decision entry (section 5).
3. Map miner on all core works; contribution miner on all claimed innovations.
4. Codebooks for the 7 stages (the researcher accepts version 1 of each, one act per codebook).
5. Stage miners; codebook versions as entries are proposed.
6. Problems; teach-back and checker calibration.
7. Graph and hub lenses.
8. Hypotheses-engine connection: empty cells of the facet space and cross-stage transfer candidates as builder rows for leads (hypotheses-engine plan, part 1), labelled interpretation.

## Part B. What the factory takes from this

What is pilot-specific: the 9 stages, the codebook contents, field wording about AI research systems, the trial papers. What generalises is the **core and the shape of the process**. The core is universal (ruling 11): every paper proposes or uses techniques and builds on earlier ones, so technique, use, origin and lineage, evidence and problem are the graph in every project. The axis on which a technique sits is a **slot axis declared by the project**, a versioned taxonomy and a lens, not the backbone: stages for agentic-science (a corpus of pipelines); model components for a review of chest CT report-generation models (image encoder, 3D handling, language decoder, vision-language alignment, pretraining data, training objective, retrieval or knowledge, evaluation metric); none for some projects. Where a project has shared benchmarks (chest CT: CT-RATE and similar), numeric comparison within comparability groups uses the existing evidence machinery, on top of the evidence levels of A6. The miners in part A are then instances of generic templates: map miner, contribution miner, slot codebooks, slot miners. Templates are never run as they are; each project adapts them (ruling 12, B8). The shape applies to any review of methods any review of methods (care pathways and interventions, lab protocols, software pipelines) has an axis of stages, papers that innovate at one point and use ordinary practice elsewhere, and a need to compare variants against a reference. Candidate platform capabilities, each needing its own backlog entry and tests before it is built; built only where the pilot needs it:

| # | Capability | Exists today | Missing |
|---|---|---|---|
| B1 | **Chained miners**: a selector that reads another miner's rows (works or anchors where miner X recorded field = value) | `Selector` takes population, element kinds, heading patterns (`mining/spec.py`); a mining session cannot read other miners' rows (lane A wrap-up) | selector by upstream miner rows; staleness when upstream rows change |
| B2 | **Codebook-guided miners**: a miner whose enum is a registered, versioned codebook, with open-set proposals recorded during mining | taxonomies as versioned objects and classification miners derived from them (IDEA-50); `taxonomy_propose`, `taxonomy_diff` | proposals from inside a mining pass; re-check limited to works affected by new or changed entries (as stale rules do for criteria) |
| B3 | **Description fields**: a field kind for the miner's own words with supporting quotes as footnotes, labelled interpretation | field kinds number, integer, enum, quote, citation; interpretations of slice 3c (600 characters, separate layer) | the field kind, its class in the index, its exclusion from evidence counts |
| B4 | **Teach-back regime**: a quality regime for description fields with questioner, answerer and grader roles, independence enforced by session, scores computed, checker calibrated by a human sample | `MinerRegime` (passes, calibration, recall and agreement thresholds); calibration draws and labels | roles, task kinds, computed teach-back score, checker calibration |
| B5 | **Shared vocabularies for methods reviews**: use status (core, secondary, reused, standard, unclaimed variant), evidence levels (independent, own ablation, asserted, failure), problems claimed versus observed | contribution pack item kinds (slice 3b) | as reusable enums any miner can use |
| B6 | **Miner templates and an adaptation process** (ruling 12): generic templates (map, contribution, slot codebook, slot miner) that are never run as they are; each project adapts them before use (B8) | miners and taxonomies importable across projects (`mine_import`, taxonomy reuse); one-command miner registration proposed (IDEA-51) | templates as registered objects; a project miner records `derived_from` template and version, with its diff |
| B8 | **Adaptation procedure** (a skill and a gate): (1) the slot axis is proposed from a probe sample, the researcher selects (suggest-and-select); (2) the templates are instantiated with domain fields, wording, examples and absence rules (agentic-science: actor, autonomy, pipeline shape; chest CT: 2D or 3D input, dataset, benchmark metrics); (3) dry run on about 3 works, reviewed by the researcher; (4) codebooks seeded from the project's own innovators; (5) the teach-back checker calibrated per project, since domains differ; (6) registration as a project miner version with its diff from the template; (7) lessons proposed back to the template as a new template version, never applied silently | miner registration, calibration draws, protocol amendment of the `miners` section | the procedure as a skill; the gate "adaptation reviewed" before a production pass; template versions and back-proposals |
| B7 | **Graph lenses** by node type and stage over interpretation-layer nodes | graph export (slice 3b), layer filter (slice 3c), lifecycle page filters | lenses over the new node types |

A second reading of "the factory's processes": the factory is itself an AI research system with the same stages. The stage codebooks are the reference against which the factory's own process (`docs/process/our-process-v0.json`) can be compared, as part 4 of the deep-dive plan intended. That comparison follows the codebooks; it is not part of this plan.

## 4. Risks

- **Fluent but wrong explanations**, most likely two techniques merged because they sound alike: teach-back, a different grader model, checker calibration.
- **Codebook bias**: entries seeded from innovators may frame ordinary practice in their terms; stage miners propose entries, and usual practice is described from the stage miners' material too.
- **Selection bias**: core papers describe themselves; evidence levels and claimed versus observed problems keep it visible.
- **Unstable codebooks** as papers arrive: versions, explicit re-checks.
- **Cost**: deep reads only for claimed innovations, stage miners only on located passages; measured in the trial.
- **Conversion defects**: the SOVEREIGN rows of v1 are garbled characters; that conversion must be fixed before its work is mined.
- **Platform before pilot**: part B is built only where part A needs it, tests first; until then the pilot runs with scripts and existing miner kinds, labelled exploratory.

## 5. Status in the platform and the decision needed

The layer is an **interpretation** layer: labelled, agent-checked, never evidence, never in a report's counts (as R-87 for slice 3c). It departs from decision 82 ruling 1 (ideas are human-confirmed, named from a verified quote, never clustered automatically) and from the human floors of `lineage.idea_confirm` and `lineage.relation_confirm`. Decision 82 is Proposed; this plan proposes a new entry rather than changing it: technique entries, codebook groupings and variant and convergent links form a separate interpretation layer, checked by teach-back, with the researcher accepting each codebook version; slice 3b's evidence-layer ideas and relations keep their human floor. Reuse of slice 3c storage versus new events is **to check** before step 3 of A9.

## 6. Rulings (researcher, 2026-11-14)

| # | Choice | Ruling |
|---|---|---|
| 1 | Comprehension levels | explain and justify, situate, abstract, evaluate and use |
| 2 | How techniques are found | bottom-up from descriptive reading, then grouping |
| 3 | Graph node types | techniques and systems, origins and lineage, problems, evidence; lenses hide node types |
| 4 | Pipeline | techniques grouped across stages; stage on the use; pipeline shape as a second technique level |
| 5 | Problems | claimed versus observed, each with an evidence level; observed by default |
| 6 | Check | automatic teach-back with separated roles; the researcher calibrates the checker once |
| 7 | Order | plan, then a trial |
| 8 | Mining process | map miner, contribution miner, stage codebooks seeded from contributions, stage miners against the codebooks, versioned growth |
| 9 | Stage axis | the 9 stages of `m-stages` v1; codebooks for 7; `lab-automation` and `other` without a codebook for now |
| 10 | Thin descriptions | recorded as "uses X, details not stated", never dropped or filled in |
| 11 | Core versus axis | technique, use, origin and lineage, evidence, problem are universal; the slot axis (stages here, model components for chest CT) is declared per project |
| 12 | Generic miners | factory-wide templates, but every new project adapts them through a recorded adaptation process before use; lessons go back to the templates as proposals |

## 7. Open

1. Trial works for A9 step 1.
2. Reuse of slice 3c storage or new events (section 5).
3. Grader model under the Sonnet cap.
4. Which part B capabilities the trial needs first (likely B1 and B3). The agentic-science miners are written as the first adaptation, so the templates are extracted from them afterwards, not designed in the abstract.
5. Whether chest CT report generation is an illustration only or a candidate for pilot 2 (a second adaptation would test the templates).

## Part C. Recording the technique layer (amendment 2026-11-15; backlog IDEA-83)

State before this part: steps A9.1 to A9.4 were run as exploratory files instead of recorded miners (researcher's rulings of 2026-11-15): 93 technique notes (template v3, teach-back 98.7% on 20 papers), 8 stage codebooks (343 entries; `lab-automation` skipped, `other` holds 24 full entries and 23 cross-references), two CSVs (`techniques.csv`, `technique_papers.csv`, 1,609 technique x paper rows), a cross-stage synthesis and a lineage-versus-citations check, all under `ops/technique-trial-2026-11-14/v3/`. None of it is recorded. Part C records it with the existing machinery of decision 120 (taxonomies as versioned objects) and the miner regime. The researcher asked for as much as possible to be planned and built without intervention; the rulings below were taken by the agent on the recommended option and are listed for review (C7).

### C1. Taxonomies (no code)

- One taxonomy per stage, `t-tech-<stage>` (8), each with one multi-cardinality dimension `technique` whose categories are the codebook's full entries (`other`: its 24 full entries; cross-references are left out, the core entry is the category). Separate from `t-agentic-layer` and from the loose `taxonomy.json` (the 12 coarse technique families of `m-classification`); never mixed with their labels.
- Category: id from the codebook id (`ie-01`), name, definition (the mechanism, shortened to the swappable component), include cues (variants), exclude cues (the neighbouring entries it is confused with). No examples in v1: the codebooks carry no anchored quotes; examples come from calibration.
- Residuals `other` (described, quoted) and `not-stated`.
- Read scope: whole text (a stage is not reliably located by headings).
- Specs are generated by `ops/.../v3/taxonomy/build_specs.py` from the codebook JSON; registering them is the researcher's act (`factory taxonomy register`, human only).

### C2. Prior (no code)

The notes, codebooks and CSVs are registered once as files (`factory files register --kind input`, human, decision 125); each taxonomy's rationale names the codebook's sha256. The miner does **not** see the prior: it reads the paper against the taxonomy alone, so the notes cannot anchor its reading. The comparison is computed afterwards (C5).

### C3. Miner (one platform change)

`m-tech-<stage>` derived from `t-tech-<stage>@1` (`derive_miner`), rows keyed on the category, plus attribute fields:
- `status`: enum `core`, `secondary`, `reused-cited`, `standard`, `unclaimed-variant` (A2);
- `evidence`: enum `independent-test`, `own-ablation`, `own-comparison`, `asserted-only`, `reported-failure` (A6);
- `parameters`: quote, optional.
Each enum attribute needs its own anchored quote (registered-miner rule). Change: `derive_miner(..., attributes=())` appends attribute fields after the derived ones; registration re-derives with the attributes the spec declares (fields beyond `category`, `quote`, `described_as`), so a spec without attributes derives byte-identical to today. Attributes are never key fields, never named like a derived field, kinds enum, quote, number or integer only, never required. CLI: `factory taxonomy derive --attributes <json>`.
Selector: included-ft, protocol use `layers: [core]`, exploratory until calibrated; two passes (B on the protocol sample); procedure `rf-taxonomy`.

### C4. Hub (small change)

The taxonomy product lists registered taxonomies (versions, digest, dimensions, categories with definitions, proposals, coverage from the derived miner's rows) beside the loose `taxonomy.json` view. Miner pages come for free. Technique pages, the four-level placement (system > stage > step > technique) and naming are deferred: the researcher doubts "technique" as the UI name.

### C5. Comparison with the prior (exploratory script first)

`ops/.../v3/prior-check/compare.py` reads the index read-only: per (work, stage, category) the prior row (CSV) against the mined row: **confirmed** (same category; status and evidence equal), **changed** (same category, status or evidence differs), **not found** (prior row, no mined row or `not-stated`), **new** (mined row absent from the prior). Counts per stage and evidence level measure how reliable step 1 was. A platform service follows only if the hub needs it.

### C6. Later phase (not in this build)

Relation types `reuses`, `corrects`, `re-invents` and a basis that is a miner row (lineage schema change: projection bump, critical module, its own decision); graph lenses (B7); codebook growth from `taxonomy_propose` during mining (B2); chained selection (B1).

### C7. Rulings taken without the researcher (2026-11-15), for review

1. One taxonomy per stage, not one taxonomy with 8 dimensions (task size: 343 definitions per task otherwise).
2. The miner is blind to the prior; the comparison is computed (avoids anchoring; keeps the reliability measure honest).
3. Attribute fields on derived miners instead of a hand-written miner (keeps "the miner is the taxonomy's projection").
4. `other` cross-references dropped as categories (one entry, one category).
5. No examples in taxonomy v1.
6. Relations and graph deferred to a later phase.
7. Techniques that the codebooks list in two stages (about 8 pairs, e.g. PW-07 and RV-20, DA-16 and RV-32, PW-22 and RV-22) stay two categories in version 1, separated by when in the pipeline the step runs and what it acts on (mutual exclude cues). This departs from A3.3 (one entry, several codebooks); version 2 merges them once calibration shows how often both fire.
8. Category definitions are generic rewrites of each codebook entry (definition, include and exclude cues), written by agents from the full entry; the first drafts, written from truncated entries, were discarded.

### C8. Build order and gates

| Step | Who | What |
|---|---|---|
| 1 | agent (branch `technique-miner`) | `derive_miner` attributes + registration + CLI; tests written (testing paused: mypy, ruff only) |
| 2 | agent (same branch) | hub taxonomy product reads registered taxonomies |
| 3 | agent (ops) | taxonomy spec generator; miner specs derived; comparison script |
| 4 | researcher | review, merge (tests first when the pause lifts) |
| 5 | researcher | `files register` the prior; `taxonomy register` x 8; `miner add` x 8; protocol amendment listing taxonomies and miners (exploratory) |
| 6 | agent | pass A on the core works, Sonnet/Haiku subagents, per stage |
| 7 | researcher | calibration labels (about 10 rows per stage) |
| 8 | agent | pass B sample, agreement, comparison with the prior, report |
