---
name: rf-screen
description: Use when records of a ready protocol must be screened, on title and abstract or (full-text mode) on the converted full text, as pass A or pass B of the two-pass screen, in a Claude Code session dedicated to that pass.
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
   says why none is served. Calibration batches arrive with the gate reason in `blocked`;
   screen them like any batch.
2. Judge each record only from its title and abstract, against the protocol criteria as served.
   Do not use outside knowledge of the paper, its full text, or its citations.
   At full text the worked examples show title-and-abstract text; use them for style only.
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
7. Repeat from step 1. Stop when `batch` is null. Screen every served batch even if `blocked`
   is non-empty (calibration batches arrive with the gate reason).
8. If `batch` is null and `blocked` is non-empty, report the reasons verbatim to the
   researcher. If `batch` is null, `blocked` is empty and `remaining` > 0, other sessions hold
   the work; report and stop. Calibration, agreement and audit are human steps; do not
   attempt them and do not work around the block. A pass that fails calibration needs a
   protocol amendment by the researcher; do not retry it.

## Full-text mode

Run this mode only when the researcher asks for the full-text pass; call `screen_next` with
`stage="full-text"` (the default, `title-abstract`, is the procedure above). A full-text
pass needs a fresh Claude Code session, as the Independence section requires: the platform
permits reuse of a session across stages, but this skill does not recommend it, and the
independence rules apply as stated. `screen_record` takes the stage from the batch.

1. A full-text batch lists records that each name a work (`work_id`), its `document_id` and a
   pinned `conversion_id`. Judge the work only from that conversion; a later conversion of the
   document never replaces it.
2. Read the document with the MCP tool `document_read(work_id=..., conversion_id=...)`, paging
   with `after` set to the page's `next_after`, until you have read the sections that the
   criteria need. The abstract is
   not a substitute for the text. Read only the works of your own batch; the platform refuses
   any other work, document or conversion.
3. Cite exactly ONE `anchor` per record: the id of the segment you rely on, as served by
   `document_read` (for example `s3.2.p4`, or a table cell such as `t2.r5.c3`).
4. Give `quote`: a span copied character for character from that anchor's text. The quote must
   lie inside the single paragraph or table cell of the cited anchor; it may not run across two
   paragraphs, cells or anchors. Pick the one anchor whose text supports the verdict.
5. Never rely on outside knowledge of the authors, venue, reputation or results of the paper;
   judge only the text of the pinned conversion.
6. The verdict rules are those of title and abstract: when in doubt include; `exclude` names an
   `EX` criterion and a `rationale`; `cannot-assess` names the criterion that the text cannot
   settle; `unsure` needs a `rationale`.
7. Call `screen_record` with items `{work_id, verdict, criterion, quote, rationale, anchor}`.
   For a rejected item, re-read the cited anchor and resubmit with a span that occurs in it, or
   cite the anchor that does contain the support; never edit a quote to pass the check. If no
   anchor supports the verdict, change it to `cannot-assess` or `unsure`.
8. Do not call `screen_agreement` or the audit and calibration tools; they are human steps.

## Tool arguments

Every tool call also takes `project` (the project slug), `role`, and `model` (your own model
id), alongside `skill`, which is the bare skill name. The platform computes the skill hash; do
not send one. Pass `rf-screen` as `skill`. `project_status` shows the current state if needed.

## Done when

`batch` is null: `remaining` is 0 for this pass, or the block or the held work has been reported to the researcher.
