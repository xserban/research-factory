# A common lifecycle of AI scientists, from the papers (plan, 2026-11-13)

Status: plan; nothing registered or run. Research question: SQ1 (a reference process) of the rapid review of AI research systems. Builds on: miners (IDEA-37), taxonomies as versioned objects (IDEA-50, decision 120), layers (`m-layer` v1), `m-stages` v1 (which of 9 fixed stages a system automates).

## 1. What exists and what is missing

`m-stages` v1 (364 works, 1,237 rows, agreement 0.981) records, per system, which of 9 fixed stages it automates and in what mode (automated 1,137, human-assisted 63, mentioned-only 37). It has no order, no links between stages, and no account of how a stage is done; the 9 stages were chosen before reading the papers.

## 2. Rulings (researcher, 2026-11-13)

| Choice | Ruling |
|---|---|
| Scope | Core works first (98 by the layer pass A; the layers are not yet calibrated), then decide on others |
| Derivation | Bottom-up: the papers' own stage names are grouped into a common lifecycle that the researcher accepts as a registered taxonomy version; the 9 `m-stages` categories are a cross-check, not the start |
| Per-stage fields | Name (the paper's own), order, how it is done (quote), techniques or tools named, who does it (automated, human-assisted, human), the stage(s) it feeds or loops back to |
| Passes | Whole text; pass A Haiku on all, pass B Sonnet on 10% |

## 3. Parts

1. **`m-lifecycle` (per-paper miner).** One row per stage the paper describes, in the paper's order. Fields: `stage_order` (integer), `stage_name` (the paper's words, quote), `how` (quote), `techniques` (quote or list of short quotes), `actor` (enum: automated, human-assisted, human, not-stated), `feeds` (stage orders it passes its output to), `loops_to` (stage orders it can send work back to). Whole-text selector, every field with a verbatim quote and anchor (as `m-release`). Absence: `not-stated` with no quote; a paper that describes no staged process gets one row `no-lifecycle`.
2. **Common lifecycle (taxonomy).** An agent proposal groups the stage names of the core papers into candidate common stages with definitions and include cues (`taxonomy_propose`; counts and clusters computed, never typed). The researcher edits and accepts; the accepted set is registered as `t-ai-scientist-lifecycle` version 1 (dimension `lifecycle-stage`, multi). A derived miner maps each paper's stage rows to common stages.
3. **Per-stage synthesis.** For each common stage: how many papers have it, the order it occurs in (median position, typical predecessors and successors), the loops, the actor split, the techniques grouped (from the quotes, by an agent proposal the researcher checks), and 3 to 5 representative quotes with work and anchor. Computed counts come from events; the prose is an agent draft that goes through claim verification like any written text.
4. **Hub page.** A lifecycle page (stages as a flow with order and loops, a click-through to the quotes per paper and per stage), built from events like the other products.

## 4. Order of work (calibration first)

The layer pass showed that a miner mined before its calibration can never be calibrated on the platform. So:

1. Write and register `m-lifecycle` v1, list it in the protocol with `layers: [core]`; run a dry run on 3 works.
2. Draw the calibration sample (10 works, seed recorded) before any production pass. The researcher gives the gold stages for those 10 papers (about 6 to 8 rows each, a heavy human act: I draft, the researcher checks each, as for `m-release`). Score; tune the wording on a sample and test on a fresh one (the `m-release` lesson).
3. Production: pass A on the 98 core works (about 4 dollars, about 1 hour with 4 sessions), pass B on 10 percent (about 3 dollars).
4. Taxonomy proposal, researcher's edits, registration, mapping miner, calibration of the mapping on a sample.
5. Synthesis and the hub page.

## 5. Dependencies and risks

- **Row alignment.** A multi-row miner whose key is free text does not align across passes (IDEA-52, 53, 69). Recommendation: the row key is `stage_order`, which is stable only when both passes split the process alike; the quality figure is the agreement with the researcher's gold stages, not pass against pass. After agent A's work on agreement lands (branch `idea-69-agreement`), recompute.
- **Layers are uncalibrated.** The core set (98) comes from `m-layer` v1 pass A; the 6 disagreements and the 20-work validation sheet decide whether it stands. A work moved into core later is mined on demand.
- **Whole text for 98 works** is about 4 to 8 pages of 30,000 characters per paper; expect 2 to 4 minutes per session for the longest.
- **Not a lifecycle.** Some systems are not staged (single-model prompting); the `no-lifecycle` row keeps them visible instead of forcing stages.

## 6. Open questions for the researcher

1. Whether `loops_to` is wanted at the first version or only `feeds` (loops are the harder judgement).
2. The name of the lifecycle's top level: one lifecycle for all core systems, or one per family (end-to-end, tree-search, multi-agent debate) if the core papers fall into groups.
3. Whether adjacent and applied works are mapped onto the accepted lifecycle later (on demand) to show specialisation.
