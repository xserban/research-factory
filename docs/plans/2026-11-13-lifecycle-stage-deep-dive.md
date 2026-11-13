# Inside each lifecycle stage: how it is done, and how our process compares (plan, 2026-11-13)

Status: plan; nothing built. Research question: SQ1 (a reference process), second level. Builds on `2026-11-13-ai-scientist-lifecycle.md` (the common lifecycle, `m-lifecycle`, per-stage synthesis), miners (IDEA-37), taxonomies (IDEA-50) and the factory's own protocol and specs.

## 1. The idea (researcher, 2026-11-13)

For each step of the lifecycle, show how it is done (for the literature review: how do the systems do it?), what can be learned from that, and, set against our own process, what we can improve.

## 2. What the lifecycle plan already gives, and what is new

`m-lifecycle` records per paper and per stage one quote on how it is done and the techniques named. That is one line per stage. Part 3 of that plan aggregates it per common stage (counts, order, actor split, techniques, quotes). Not covered there: the steps inside a stage, what a stage takes in and gives out, how a stage checks its own result, and any comparison with the factory's own process.

## 3. Parts

1. **Our process as data.** The factory's own steps, written as rows against the same common stages: question and protocol, probe, search, screening (two passes, calibration, audit), full text, extraction, snowballing, layers, reports and checks. Fields as for the papers (step, how, tools, actor, check). Drafted by an agent from the specs and the protocol, each row citing its spec section; the researcher accepts. It is a registered document, not a free text, so the comparison never depends on memory.
2. **`m-stage-steps` (per work and stage miner).** For each (work, common stage) pair where the paper describes the stage, one row per sub-step in the paper's order: `step` (the paper's words, quote), `inputs`, `outputs`, `method` (quote), `actor`, `check` (how the paper validates the step's result, quote or `not-stated`), `limits` (what the paper says goes wrong, quote or `not-stated`). Selector: only the passages the lifecycle row cites, widened to the whole text when the pass finds none. Every field carries a verbatim quote and anchor (as `m-release`); absence is `not-stated`, never a guess.
3. **Step patterns (taxonomy and synthesis).** An agent proposal groups the sub-steps of one stage into candidate step types; the researcher edits and registers them as `t-<stage>-steps` v1. Computed per stage: how many systems use each step type, typical order, which come with a check, actor split, and the systems that do something nobody else does. Counts come from events; prose drafts pass claim verification.
4. **Comparison with our process.** Computed, not argued: each of our steps against the step types of its stage (how many of N systems do it) and each step type used by at least k systems and absent from our process. Output: a coverage table per stage and a list of candidates. An agent drafts, for each candidate, a short improvement idea with its evidence; the researcher decides, and accepted ideas go to the backlog as ideas with citations, not into the platform.
5. **Hub page.** A stage page (steps as a flow, step types with counts and quotes, our process beside them, gaps marked), built from events like the other products.

## 4. Order of work

1. Wait for the `m-lifecycle` calibration (the 10 gold labels are the researcher's pending act); the deep dive is only as good as the stage assignment.
2. Part 1 for one stage only: **literature review**, the stage the factory knows best. Dry run of part 2 on 3 papers, calibrate on 10 (gold sub-steps: agent draft, researcher checks), then the whole core set for that stage.
3. Parts 3 and 4 for that stage; judge the usefulness of the comparison with the researcher before opening the other stages.
4. The remaining stages, one at a time; hub page last.

## 5. Risks

- **Stage assignment errors** carry into every row; mitigated by the order above.
- **Granularity.** "Step" is a loose unit; two passes split a stage differently, so rows do not align by key (IDEA-52, 53, 69). The quality figure is agreement with gold sub-steps, as for `m-lifecycle`.
- **Thin descriptions.** Many papers describe a stage in one sentence; the absence policy keeps them visible instead of inventing steps, and the coverage counts say how many systems had anything to compare.
- **Selection bias.** The core papers are systems that describe themselves; a comparison with them shows what systems claim, not what works. Stated on the page.

## 6. Rulings (researcher, 2026-11-13)

| Choice | Ruling |
|---|---|
| Scope of the first run | ~~Literature review only~~ Superseded the same evening: every stage, run overnight as an **exploratory** pass (see below) |
| Comparators | Two columns beside our process: the core AI-scientist papers, and the methods literature on how people do a review (PRISMA, Cochrane, rapid-review guidance). The methods sources are chosen and listed by the researcher before part 2 for that column |
| Our process | An agent drafts the rows from specs and protocol, each citing its section; the researcher checks |
| Step granularity | Free text, grouped afterwards into step types the researcher registers |
| Fields and passes | All fields (step, inputs, outputs, method, actor, check, limits; `check` and `limits` are `not-stated` when absent); pass A Haiku on all, pass B Sonnet on 10 percent |

## 7. Still open

1. The list of methods sources for the human-methods column (researcher).
2. The `m-lifecycle` calibration (gold stages for 10 papers), which gates part 2.

## 8. Change of ruling: all stages, overnight, exploratory (researcher, 2026-11-13)

The researcher asked to run the step miner for each lifecycle step overnight "to understand how it is done". Consequences, taken as the recommendation:

- **Axis.** The stages are the 9 of `m-stages` v1 (listed, agreement 0.981, the stages of the hub's lifecycle page), not the bottom-up common lifecycle: that taxonomy needs the `m-lifecycle` production pass and the researcher's acceptance, neither of which can happen unattended. The common lifecycle replaces the axis later and the step rows are re-mapped, not re-mined.
- **Exploratory.** The step miner has no calibration. Its rows are for reading, not evidence: recorded as exploratory in the wrap-up and on every page that shows them; no count from them goes into a report until the miner is calibrated against gold sub-steps. The platform does not yet refuse a production pass without calibration (IDEA-69 (3)); the guard is built the same night, and the run is labelled exploratory by the run, not by the platform.
- **Selection.** Works of the core layer with an `m-stages` row for the stage in mode automated or human-assisted.
- **Not changed.** Our process rows (part 1) and the human-methods column still need the researcher's check and source list.
