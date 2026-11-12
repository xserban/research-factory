---
name: rf-contributions
description: Use when the included works of a ready protocol must be read for what they build on, add, report and concede, as contribution items from their pinned converted full text, as pass A or pass B of the dual contribution reading, in a Claude Code session dedicated to that pass.
stage: [extract]
---

# rf-contributions

Reads each included work for four kinds of statement: the base idea it builds on, what it adds,
what it reports, and what it concedes. Every item is recorded with the anchor and the verbatim
quote that show it, so that the platform can verify it. The platform checks quotes, numbers and
cited reference entries; it does not classify. Whether a sentence states a base idea or an
addition is your reading of the paper's own words, and the quote must carry those words.

## Independence

- Run exactly one pass per Claude Code session, and say which pass it is (`A` or `B`).
- Never start pass B in a session, or a subagent, that ran pass A or that was given human
  labels (agreement resolutions or audit labels, relayed in any form). Start a fresh session.
- Use a different model for pass B than for pass A.
- Do not read the other pass's items, the agreement, the audit sample or its labels, the
  reports, `check` or `trace`, and do not ask for them. The platform refuses them to a pass
  session; do not work around a refusal.
- A session of this skill does not run evidence extraction (`rf-extract`), and the reverse.

## Procedure

1. Call `contribution_next` with the pass label. It serves a batch: the declared fields, one
   record (`work_id`, `title`, `document_id`, `conversion_id`), `item_rules`, and `references`.
   `references.status` is `current` (its `entries` are listed with `ordinal`, `anchor` as
   `b<n>`, `label`, `title`, `first_author`, `year`, `doi`, `arxiv`), or `none` or
   `other-conversion`: then `cited_entry` is unavailable for this work and you leave it out.
2. Read the document only with `document_read(work_id=..., conversion_id=...)`, using the
   pinned `conversion_id` of the record and paging with `after` set to the page's
   `next_after`. Read the abstract, introduction, related work, method, results and
   limitations or conclusion. To identify a cited entry read it through `document_read` at
   its `b<n>` anchor. Read only the works of your own batch. Do not use outside knowledge of
   the paper or of what it cites.
3. Record one item per statement, as `{"fields": {...}}` where `fields` maps a field name to
   `{value, unit, anchor, cell, quote}`; give only declared fields and omit what does not apply.
   `item_kind` is `base-idea`, `addition`, `result`, `limitation` or `not-stated`.
   - `base-idea`: a named method, paper or principle the paper says it builds on. One item per
     named predecessor: a sentence that names several is several items with the same quote.
     Give `name` (the predecessor's name as it occurs in the quote) and `statement`.
   - `addition`: what the paper says it adds over that base: `name`, `statement`, and
     `compared_to` when it names what it improves on.
   - `result`: a reported result: `statement`, `metric`, and `value` with `unit` (as printed;
     never compute, round or convert), optionally `result_row`, the row key of an evidence row
     of the same work.
   - `limitation`: a stated limitation or failure case: `name`, `statement`.
4. Discriminating wording. Put the words that justify the kind in the quote: "we build on",
   "following", "based on", "extends", "inherits" for a base idea; "unlike", "in contrast to",
   "improves", "instead of", "we propose" for an addition. If the quote does not carry such
   words, the kind is not established: do not record it. The platform does not classify, and
   the human audit checks your reading.
5. Quotes and anchors. `anchor` is the element id served by `document_read` (for example
   `s3.2.p4`). Give the paragraph anchor and a quote copied verbatim, character for character,
   from a single paragraph or table cell; never paraphrase a quote. Each text field (`name`,
   `statement`, `compared_to`, `metric`) must occur in the quote.
6. `cited_entry`. Set it to an ordinal from `references.entries` only when the quote's own
   citation marker, or the entry text read at its `b<n>` anchor, identifies the predecessor.
   A quote with no marker is stored and flagged; a marker that maps to another entry is
   stored and flagged as a mismatch. Never guess an ordinal. When no entry identifies it,
   leave `cited_entry` out.
7. `not-stated`. If the paper states no base idea, or no limitation, record one item with
   `item_kind = "not-stated"` and `absent_kind` set to `base-idea` or `limitation`, and no
   quote, anchor or other field. Never infer a base idea or a target the paper does not state;
   the absence of an addition or a result cannot be declared.
8. Two items of one kind with the same name and metric at one anchor are refused as a
   duplicate. For the second, quote a finer anchor (the sentence's paragraph or the table
   cell), or supersede the first.
9. Call `contribution_record` with the `task_id`, the `items`, and `role`, `model`, `skill`.
   Each item is accepted or rejected with reasons; accepted items are written. Fix a rejected
   item by re-reading its anchor; never edit a quote to make it pass. A rejection for
   `entry-unknown` or `result-row-unknown` means the value is not available: drop it.
10. Correct an accepted item with a new item passed with `supersedes`, an object whose keys
    are item indices of this call's `items` (strings such as `"0"`) and whose values are the
    ids of the items they replace. A `not-stated` item that turns out wrong is superseded by
    the item it denied. Never resubmit an accepted item as new.
11. Close the work with `finish=True` only when `base-idea` and `limitation` are each covered
    (by an item or by `not-stated`) and at least one `addition` is recorded. A work whose
    paper reports no result needs a `reason` stating that. A work with no items at all needs
    a `reason`. A close is refused while its coverage is incomplete and not applied while any
    item of the call is rejected: fix it, then finish.
12. Repeat from step 1. Stop when `batch` is null.

## Stopping and human steps

If `batch` is null and `blocked` is non-empty, report the reasons verbatim to the researcher.
If `batch` is null, `blocked` is empty and `remaining` > 0, other sessions hold the work;
report and stop. Agreement, resolution, audit labelling and the choice between the passes are
human steps; do not attempt them. A reading whose audit fails needs a schema or skill
amendment by the researcher; do not retry it.

## Tool arguments

Every tool call also takes `project` (the project slug), `role`, and `model` (your own model
id), alongside `skill`, which is the bare skill name. The platform computes the skill hash; do
not send one. Pass `rf-contributions` as `skill`. `project_status` shows the current state if
needed.

## Done when

`batch` is null: `remaining` is 0 for this pass, or the block or the held work has been
reported to the researcher.
