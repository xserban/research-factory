---
name: rf-extract
description: Use when the included works of a ready protocol must be extracted into schema rows (and, in pass A, claims) from their pinned converted full text, as pass A or pass B of the dual extraction, in a Claude Code session dedicated to that pass.
stage: [extract]
---

# rf-extract

Extracts schema-driven result rows from the converted full text of each included work, one
task at a time. Every value is recorded as printed, with the element and the verbatim quote
that show it, so that the platform can verify it.

## Independence

- Run exactly one pass per Claude Code session, and say which pass it is (`A` or `B`).
- Never start pass B in a session, or a subagent, that ran pass A or that was given human
  labels (agreement resolutions or audit labels, relayed in any form). Start a fresh session.
- Use a different model for pass B than for pass A.
- Do not read the other pass's rows, the agreement, the audit sample or its labels, the
  reports, `check` or `trace`, and do not ask for them. The platform refuses them to a pass
  session; do not work around a refusal.

## Procedure

1. Call `extract_next` with the pass label. It serves a batch (the declared fields with
   `name`, `group`, `kind`, `unit_family`, `units` and `check`; which are `required`; whether
   `claims` are on; and one record with `work_id`, `title`, `document_id`, `conversion_id`), or
   says why none is served.
2. Read the document only with `document_read(work_id=..., conversion_id=...)`, paging with
   `after` set to the page's `next_after`, until you have read the results sections, tables
   and captions that the fields need. Use the pinned `conversion_id` of the record. Read only
   the works of your own batch. Do not use outside knowledge of the paper or its results.
3. Record one row per reported result (one method on one dataset and metric), each separately.
   A row is `{"fields": {...}}`, where `fields` maps field name to `{value, unit, anchor, cell, quote, reported_in, cited_work}`;
   omit what does not apply. Give only declared fields.
4. Values and units:
   - `value` is the number exactly as printed, never a converted form.
   - `unit` matches exactly one of the field's declared `units`. A printed suffix or sign
     (`25M`, `4.6 GFLOPs`, `82.4 %`) requires the matching unit (`M`, `G`, `%`). A bare number
     in a column headed, for example, "Params (M)" takes the header's unit.
   - The rule is never compute: do not convert, round, average, rescale or combine values; a
     fraction is not rewritten as a percentage. If the text does not print a number, omit the field.
5. Anchors and quotes:
   - `anchor` is the element id served by `document_read` (for example `s3.2.p4`, `t2`).
   - For a table value also give `cell` (for example `t2.r3.c4`) and quote the cell text
     alone. A quote that spans two cells, paragraphs or anchors is rejected.
   - For a value in prose give the paragraph anchor and a verbatim quote that contains the
     number. Copy it character for character; never paraphrase a quote.
   - Text fields (method, task, dataset, metric) carry a quote that contains the value.
6. Values attributed to other papers (a baseline row copied from a cited work, a number
   quoted from earlier work): set `reported_in = "cited"` and, where the work is in the
   corpus, `cited_work`. Use `own` only for results that the paper itself produced. The
   platform also detects copy markers (`[41]`, `(Wang et al., 2021)`) in the table row; a
   marker overrides an `own` claim for the independence counts.
7. Claims (pass A only, and only when the batch says claims are on): a short paraphrase
   (at most 600 characters) with `claim_type`, `evidence_type`, `strength` (your judgement)
   and an `anchor` with a verbatim `quote` supporting it. Do not record claims in pass B or
   when claims are off.
8. Call `extract_record` with the `task_id`, the `rows`, any `claims`, and `role`, `model`,
   `skill`. Read the reply: each row is accepted or rejected with reasons; accepted rows are
   written.
9. A rejected row is fixed and resubmitted. Re-read the cited anchor or cell, correct the
   unit, cell or anchor, or cite the element that does contain the number. Never edit a quote
   to make it pass; if the document does not support the value, drop the field or the row.
10. A correction of an accepted row is a new row passed with `supersedes`, an object
    whose keys are row indices (the position of the new row in this call's `rows`, written as a
    string such as `"0"`) and whose values are the ids of the rows they replace. A claim is
    corrected likewise with `claim_supersedes`, keyed by claim index. Never resubmit an
    accepted row as new.
11. When the work is fully extracted, call `extract_record` with `finish=True` (with the final
    rows, or none). A work with no extractable results is closed with `finish=True` and a
    `reason` stating why; a close with no rows and no reason is refused. A close is not
    applied while any item of the call is rejected: fix it, then finish.
12. Repeat from step 1. Stop when `batch` is null.

## Stopping and human steps

If `batch` is null and `blocked` is non-empty, report the reasons verbatim to the
researcher. If `batch` is null, `blocked` is empty and `remaining` > 0, other sessions hold
the work; report and stop. Agreement, resolution and audit labelling are human steps; do not
attempt them. A pass whose extraction fails the audit needs a schema or skill amendment by
the researcher; do not retry it.

## Tool arguments

Every tool call also takes `project` (the project slug), `role`, and `model` (your own model
id), alongside `skill`, which is the bare skill name. The platform computes the skill hash; do
not send one. Pass `rf-extract` as `skill`. `project_status` shows the current state if
needed.

## Done when

`batch` is null: `remaining` is 0 for this pass, or the block or the held work has been
reported to the researcher.
