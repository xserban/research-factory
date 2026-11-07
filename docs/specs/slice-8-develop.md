# Slice 8: suggest and select (the develop stage and every decision after it)

**Status:** draft accepted by the researcher as the basis for the build, 2026-11-07; built after the pilot's protocol level. Supersedes the draft of 2026-11-06. Takes in IDEA-39 and the agentic-science pilot (goal, research questions, plan, seeds, probe rounds 1 to 3, criteria), recorded in `~/Documents/research-factory-pilot/demo-log.md`. Binding documents: `00-system.md`, `01-rigour.md`.

## Problem

In the pilot, the factory recorded what the agent sent. The goal was taken as typed, the plan was drafted without the scientist, probe rounds were the agent's alone, and the criteria were drafted whole. When the work was instead done as a loop (the agent suggests a grounded set, the scientist ticks, removes or adds, and the choice is recorded), the result changed at every level: a Key Result was added, one replaced, one cut back and one moved to a later cycle; the main question lost "human-directed"; the review method was overruled; the exclusions were cut from six to three. None of this is in the event log. It lives in a chat transcript and hand-made PDFs.

## Goal

One general mechanism, **suggest and select**, used at every decision the scientist owns, from the overarching goal to the extraction fields. The platform records suggestions and selections, keeps rejected items, and renders each level as a formal document. All judgement still comes from agents and the scientist; the platform never calls a model.

## The loop

1. **Suggest.** An agent records a suggestion set for one decision: a short list of items, each with its text, its grounds and, for technical decisions only, whether it is recommended.
2. **Select.** The scientist ticks the items to keep and may add items of their own, with an optional note. This is a human event, written through the CLI or an MCP elicitation, never by an agent.
3. **Act.** The record the decision feeds (a question version, a protocol, a probe, a seed) cites the selection it implements.
4. **Render.** Each level is rendered as a formal document from its events.

Rules learned in the pilot:

- **One level at a time, top-down:** goal, research questions, plan, seeds, probe, protocol. A level is drafted only after the level above is validated.
- **Items, not wholes.** Suggestions are lists to tick, not documents to approve whole. Each item is Proposed until selected; then Validated or Rejected.
- **Grounded suggestions.** Each item names its grounds: a probe, sample titles, a seed, a document, a previous selection. Suggestions drawn from templates were wrong in the pilot (exclusions for papers no source returns). An item with no grounds is allowed and flagged.
- **Neutral on research decisions, recommend on technical ones.** A recommended label anchors choice. Research decisions (goal, questions, method, criteria) carry no recommendation; technical decisions (tooling, ordering, fixes) may.
- **Explain before acting.** The suggestion set carries a short statement of the step and why, so the process itself can be criticised.
- **Scope, do not copy.** Input is analysed for vague terms and hidden assumptions; documents are formal deliverables, not transcripts.
- **Reviews follow evidence, not a calendar.**

## Levels and their decisions

| Level | Decisions (each a suggestion set) | Feeds |
|---|---|---|
| Goal | scoping dimensions; Objective; Key Results (minimum outcomes); later cycles | goal document |
| Questions | main question; one or more questions per Key Result; scope (field, dates) | `question.recorded` |
| Plan | study frame; review method; shortcuts; phases; evidence scale; bias controls; limits | plan document |
| Seeds | positive seeds; negative seeds; scope rulings (benchmarks, surveys) | `seed.added` |
| Probe | term blocks and terms; variants per round; next change after each round; close (proceed, amend, reframe) | `probe.run` |
| Protocol | inclusions; exclusions; sources; snowballing; screening plan; extraction fields | `protocol.recorded` |

## Expected outcomes, not KPIs

Kept from the 2026-11-06 draft. A Key Result states what an objective should yield **at the minimum**; real values are assessed afterwards. A missed minimum is reported as a finding. Each outcome is `computed` (counted from events) or `judged` (needs a reading). The factory computes what it can and suggests a status; an agent proposes judged outcomes with evidence; the scientist validates each (R-05). Activity counts belong to Initiatives.

## Events (sketch)

- `decision.suggested` (agent): `decision_id`, `level`, `subject`, `explanation`, `items[]` (`item_id`, `text`, `grounds[]`, `recommended`), with the usual provenance and `input_blob`.
- `decision.selected` (human): `decision_id`, `selected[]` (item ids), `added[]` (text), `note`. Fold guard: the actor must be human; an agent-written selection changes nothing on rebuild.
- `decision.superseded` (agent or human): a new suggestion set for the same subject, with a reason. Earlier sets and selections stay on record.
- `document.rendered` (system): level, version, source events, blob.

## Binding

- In `pilot` and `systematic`, `question_record`, `seed_add`, `probe_run` and `protocol_record` require a `decision_id` whose selection covers what they record. `exploratory` may skip it (see IDEA-41).
- New `check` rules: a record with no selection; a selection never acted on; a suggestion set with ungrounded items; an act that departs from its selection.
- `trace` runs from a claim through its field, criterion, question, Key Result and Objective, and shows each selection on the way.
- `factory status` shows open suggestion sets awaiting the scientist.

## Probe changes found in the pilot

1. **Sample titles.** Each probe query also archives a small random sample of titles (metadata only), so the scientist can judge noise. The sample stays outside the corpus and PRISMA counts.
2. **Unique-count estimate** across sources, since the counts per source double-count shared records.
3. **Term suggestions** that exclude generic words; the current ones ("introduce", "driven") were unusable.
4. **Untestable is not missed.** Per-source recall counts seeds a source cannot test as misses; it should report recall over testable seeds, with the untestable listed.
5. **Consistent date limits.** The probe refuses arXiv filters, so the date went into the query text; the watch accepts `listed_since`.

Already fixed during the pilot (commit 8c6da39, tests not run): the arXiv count no longer sends `max_results=0`; OpenAlex matches seeds by DOI when they have no OpenAlex id.

## Rigour

- Selections are fixed before results. A changed selection is a new suggestion set with a reason, and is reported.
- Rejected items stay on record and appear in the methods report.
- Whether the scientist followed a recommendation is computed, so anchoring can be measured.
- Suggestion sets never show held-out seeds (R-20).
- Rigor modes set what is required: `exploratory` may skip selections; `pilot` and `systematic` require them.

## Rulings (researcher)

From 2026-11-06, kept: a validated plan is required before the probe in `pilot` and `systematic`; one project holds the phases; the stage is prototyped by hand, the spec corrected from it, then built.

2026-11-07: every decision is bounced back to the scientist; what the pilot did by hand is implemented in the factory; this spec is written now, built after the protocol level, and the pilot's decisions are then backfilled from the demo log.

## Rulings on the open questions (researcher, 2026-11-07)

1. `QuestionSpec` gains a sub-questions field; the `RQn` slots of the pilot move to it.
2. Selections are recorded through the CLI and, where the client supports it, MCP elicitation.
3. Backfill: the agent prepares each past selection from the demo log; the scientist records them as human events through the CLI, marked as reconstructed.
4. Rendering format stays open; Markdown at least.

## Not in this slice

The local screening ranker (IDEA-42), the quick factory (IDEA-41) and self-review of factory choices (IDEA-40), though all will use this loop.
