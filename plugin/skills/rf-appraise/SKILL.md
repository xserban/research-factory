---
name: rf-appraise
description: Use when the included works of a ready protocol that declares an appraisal instrument must be read for the span items of that instrument (does the paper report its seeds, hyperparameters, variance, limitations), as pass A or pass B of the dual appraisal, in a Claude Code session dedicated to that pass.
---

# rf-appraise

Answers, for each included work, the span items of the project's appraisal instrument: `yes`,
`no` or `unclear`, each `yes` or `no` with the anchor and the verbatim quote that show it. You
report what the paper states; you do not rate how good the paper is. The platform checks that
the quote occurs in the anchor. It forms no total, score or grade, and neither do you.

Computed items (code link, dataset named, seeds, hardware) are found by the platform and
judgement items are a human's. Neither is ever served to you.

## Independence

- Run exactly one pass per Claude Code session, and say which pass it is (`A` or `B`).
- Never start pass B in a session, or a subagent, that ran pass A or that was given human
  labels (resolutions, judgements or audit labels, relayed in any form). Start a fresh session.
- Use a different model for pass B than for pass A.
- Do not read the other pass's answers, the sheet, the agreement, the audit sample or its
  labels, the reports, `check` or `trace`. The platform refuses them to a pass session; do not
  work around a refusal.
- A session of this skill does not extract, screen or read contributions, and the reverse.

## Procedure

1. Call `appraisal_next` with the pass label. It serves a batch: the instrument, one record
   (`work_id`, `document_id`, `conversion_id`) and the `items` to answer, each with its
   statement.
2. Read the document only with `document_read(work_id=..., conversion_id=...)`, using the
   pinned `conversion_id` of the record and paging with `after` set to the page's `next_after`.
   Read the whole paper including appendices; a statement may sit anywhere. Read only the work
   of your own batch. Do not use outside knowledge of the paper.
3. For each item give `{item, answer, anchor, quote}`.
   - `yes`: the paper states what the item asks. Give the paragraph or cell anchor and a quote
     copied verbatim, character for character, from that single anchor.
   - `no`: the paper states the opposite, or says it was not done. Quote that statement.
     Silence is not `no`: use `unclear`.
   - `unclear`: the paper does not say, says it ambiguously, or you cannot find it after
     reading the paper. No quote or anchor is needed.
4. Call `appraisal_record` with the `task_id`, the `answers`, and `role`, `model`, `skill`.
   Each answer is accepted or rejected with reasons; accepted answers are written. Fix a
   rejected answer by re-reading its anchor; never edit a quote to make it pass.
5. Close the work with `finish=True` once every item of the task has an answer. It is refused
   while an item has none, and not applied while any answer of the call is rejected.
6. Repeat from step 1. Stop when `batch` is null.

## Stopping and human steps

If `batch` is null and `blocked` is non-empty, report the reasons verbatim to the researcher.
If `batch` is null, `blocked` is empty and `remaining` > 0, other sessions hold the work;
report and stop. Resolving disagreements between the passes, judgement items and the audit are
human steps (`factory appraisal ...`); do not attempt them.

## Tool arguments

Every tool call also takes `project` (the project slug), `role`, and `model` (your own model
id), alongside `skill`, which is the bare skill name. The platform computes the skill hash; do
not send one. Pass `rf-appraise` as `skill`. `appraisal_status` shows counts only.
