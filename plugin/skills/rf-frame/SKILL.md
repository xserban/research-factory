---
name: rf-frame
description: Use when a researcher starts a review or states a goal, and the factory needs a recorded, versioned research question with its framing and non-goals.
---

# rf-frame

Turns a stated goal into a recorded question. Source: research-factory-old `stages/00-frame.md`.

## Procedure

1. Record the goal verbatim. Pass the researcher's own words unedited as `raw_goal`, with the
   spec, to `question_record`. Never paraphrase or tidy the wording. Each later restatement is a
   new `raw_goal` call and is appended, never replaced.
2. Quote it back. Show the recorded `raw_goal` to the researcher, quoted, and ask whether it is
   what they meant. Nothing else proceeds until they confirm or correct it.
3. Choose a scheme provisionally: `PICO` (clinical), `PECO` (observational), `SPIDER` (qualitative
   or mixed), or `TDMBM` (method and ML reviews). Re-select if the slots resist filling, and
   record the reason in `scheme_rationale`.
4. Interview with at most five questions. Never ask what `raw_goal` already answers. Anything
   still unknown after five becomes an open slot.
5. Fill slots. Use `open:` with a `resolve_in` naming the stage that will resolve it, for example
   `resolve_in: "rf-probe"`. Never write `TBD`. If more than half the slots are open, say the
   question is absent and keep interviewing rather than recording it.
6. Write non-goals with stable ids (`NG01`, `NG02`, ...). Apply the plausible-paper test: each
   non-goal must describe a paper a good query would return and that the researcher does not
   want. Reject vacuous non-goals ("not about cats"). Minimum: one for `exploratory`, three for
   `pilot` or `systematic`.
   Research questions under the primary one (`RQ1`, ...) go in `sub_questions` with ids `SQ1`,
   `SQ2`, ... (`id`, `text`, optional `serves`), never in `slots`: slots are scope elements. A
   criterion may name a sub-question as its `parent`.
7. Write the rationale and objectives in two or three sentences each (PRISMA-P items 1 to 4).
8. Propose a rigor mode with its reasoning: `exploratory` (landscape scan, single pass),
   `pilot` (dual screening on a sample, advisory kappa) or `systematic` (full PRISMA, dual
   screening, enforced kappa). Read the project's current mode with `project_status`. The rigor
   mode is a project setting, not a field of the question spec, so the human sets it. Put your
   reasoning in `rationale` or `scheme_rationale`, and say the choice is reversible by promotion.
9. Every mutating tool also takes `project` (the project slug), `role`, and `model` (your own model id), alongside `skill`, which is the bare skill name. The platform computes the skill hash; do not send one. Pass the bare skill name `rf-frame` as `skill`.

## Done when

The question is recorded with its `raw_goal`, the researcher has confirmed the quoted goal, and
the proposed rigor mode and its reasoning are stated, and the human has confirmed the project's mode. Hand over to `rf-probe`.
