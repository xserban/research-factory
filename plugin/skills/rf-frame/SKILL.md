---
name: rf-frame
description: Use when a researcher starts a review or states a goal, and the factory needs a recorded, versioned research question with its framing, non-goals and rigor mode.
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
7. Write the rationale and objectives in two or three sentences each (PRISMA-P items 1 to 4).
8. Propose a rigor mode with its reasoning: `exploratory` (landscape scan, single pass),
   `pilot` (dual screening on a sample, advisory kappa) or `systematic` (full PRISMA, dual
   screening, enforced kappa). State that the choice is reversible by promotion and offer the
   override. Record it in the question spec.
9. Pass the bare skill name `rf-frame` as `skill` on every mutating call. The platform computes
   the skill hash; do not compute or send one.

## Done when

The question is recorded with its `raw_goal`, the researcher has confirmed the quoted goal, and
the rigor mode is recorded with its rationale. Hand over to `rf-probe`.
