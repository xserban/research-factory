---
name: rf-screen
description: Use when records of a ready protocol must be screened on title and abstract, as pass A or pass B of the two-pass screen, in a Claude Code session dedicated to that pass.
---

# rf-screen

Screens the records of a ready protocol on title and abstract against its eligibility criteria,
one batch at a time. Each judgement is recorded with a verbatim quote so that it can be checked.

## Independence

- Run exactly one pass per Claude Code session, and say which pass it is (`A` or `B`).
- Never start pass B in a session, or a subagent, that ran pass A or that was given human labels
  (calibration or audit labels, relayed in any form). Start a fresh session.
- Use a different model for pass B than for pass A.
- Do not read other passes' decisions, the calibration set or the audit sample, and do not ask
  for them.

## Procedure

1. Call `screen_next` with the pass label. It serves a batch of records and the criteria, or
   says why none is served.
2. Judge each record only from its title and abstract, against the protocol criteria as served.
   Do not use outside knowledge of the paper, its full text, or its citations.
3. Choose one verdict per record:
   - `include`: the text meets every inclusion criterion and no exclusion criterion applies.
   - `exclude`: the text shows that an exclusion criterion applies. Give `criterion` (the bare
     id of an `EX` criterion, e.g. `EX03`) and a `rationale`.
   - `cannot-assess`: the text lacks the information that a criterion needs (for example, no
     abstract). Give the `criterion` that cannot be assessed. Use it whenever the missing
     information is the reason, rather than guessing.
   - `unsure`: the text is genuinely borderline on the criteria. Give a `rationale`. Do not use
     it to avoid a decision that the text supports.
4. For every verdict, give `quote`: a span copied character for character from the title or the
   abstract that supports the verdict. The platform verifies it against the stored text.
5. Call `screen_record` with the `task_id` and the items, each
   `{work_id, verdict, criterion, quote, rationale}`. `criterion` and `rationale` are required
   as stated above and may be omitted otherwise.
6. Read the reply. Invalid items are reported by index and the valid ones are written. For a
   rejected item, re-read the title and abstract, find the span that supports the verdict and
   resubmit the item. Never retry by paraphrasing or editing the quote to pass the check; if no
   span supports the verdict, change the verdict (`cannot-assess` or `unsure`).
7. Repeat from step 1. Stop when `remaining` is 0 or `blocked` is non-empty.
8. If `blocked` is non-empty, report its reasons to the researcher verbatim. Calibration,
   agreement and audit are human steps; do not attempt them and do not work around the block.

## Tool arguments

Every tool call also takes `project` (the project slug), `role`, and `model` (your own model
id), alongside `skill`, which is the bare skill name. The platform computes the skill hash; do
not send one. Pass `rf-screen` as `skill`. `project_status` shows the current state if needed.

## Done when

`remaining` is 0 for this pass, or a block has been reported to the researcher.
