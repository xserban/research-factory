---
name: rf-critic
description: Use when a hypothesis draft must be reviewed against the checklist as an artefact, in a Claude Code session that neither drafted it nor wrote its lead, and, where the protocol asks, runs on another model than the drafter.
stage: [develop]
---

# rf-critic

Reviews hypothesis drafts. You judge the artefact the platform serves, against a fixed
checklist, and recommend `register`, `revise` or `reject`. Whether a hypothesis is registered
is not yours to decide.

## Independence

- Review only through `hypothesis_review_next`. Use a Claude Code session that did not draft
  the hypothesis or write its lead, and that has not run a screening or extraction pass. The
  platform refuses an ineligible session (the drafter's, the lead author's, a subagent of
  either, and, where the protocol asks for it, the drafter's model) before it serves anything;
  do not work around the refusal.
- Do not read the proposer's notes, the lead's text or the drafter's rationale; do not ask for
  them and do not open the lead. If you find yourself holding them, say so and stop; the review would no
  longer be independent.
- Do not read or ask for the held-out seeds, the audit samples or the answer key.

## Procedure

1. Call `hypothesis_review_next`. The task holds the spec without prose, the statement, the
   lead's triggers (references, builder rows and verified quotes) and the prior failures. When
   none waits, report that and stop.
2. Judge each checklist item from the task alone, as `pass`, `fail` or `n/a`:
   - `falsifiable`: the rule and margin can refute it, and the falsifier is not vacuous;
   - `measurable`: the metric, its direction and unit are defined and obtainable;
   - `single-factor`: treatment and baseline differ in one factor only;
   - `baselines-named`: the baseline is a named method or card, not "the usual";
   - `rule-complete`: the margin, rule and test are stated and fit each other;
   - `prior-addressed`: the prior failures listed are answered by the spec;
   - `conditions-in-evidence`: each condition is a key the evidence schema has.
   Add a note of at most 300 characters to any item you fail.
3. Call `hypothesis_review` with the task id, `items`, `notes` and `recommend`. A failing item
   means `revise` or `reject`; `register` is refused with one. Recommend `register` only when
   you would stake the item list on it.

## Stopping and human steps

Registration, abandonment and conclusion belong to the researcher on the command line. If a call
is refused, report the reason verbatim and stop.

## Tool arguments

Every tool call also takes `project` (the project slug), `role`, and `model` (your own model
id), alongside `skill`, which is the bare skill name. The platform computes the skill hash; do
not send one. Pass `rf-critic` as `skill`.

## Done when

Every task the platform served you has a review recorded, or you have reported that none waited.
