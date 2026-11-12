---
name: rf-intuition
description: Use when a confirmed idea or a corpus paper needs a short, source-bound interpretation of why it works, to be reviewed by the researcher, in a Claude Code session that did not read a screening, extraction or contribution pass.
stage: [understand]
---

# rf-intuition

Writes interpretations: a short reading of why an idea or a paper works, bound to the sources
that support it. An interpretation is not evidence. It is a reading for the researcher to check;
it is never counted, never cited as a result, and never enters an evidence table. The platform
verifies the length, the target and every source; it does not judge whether your reading is
right. The researcher reviews each one on the command line.

## Independence

- Use a Claude Code session that has not run a screening, extraction or contribution pass, and
  has not been given human labels or decisions relayed in any form. The platform refuses these
  tools to a session that did; do not work around the refusal.
- Do not read or ask for the agreement, the audit sample, the held-out seeds or the answer key.
- Never review an interpretation, yours or another's. Never mark one reviewed, wrong or
  superseded by any route, and never ask a human to relay your own judgement as a review.

## Procedure

1. Call `intuition_next`. Without `targets` it serves the next confirmed idea; name `targets`
   (idea or paper ids) to interpret specific nodes. Papers are served only when named. When
   `batch` is null there is nothing left: stop.
2. Read the served items: each is a recorded contribution item of a member work, with its
   verified quote, anchor and conversion. Open the paper with `document_read` when you need a
   quote beyond the items.
3. Write the interpretation in at most 600 characters: why the idea works, in your own words,
   from what the sources say. One target, one reading. A longer thought is several
   interpretations, each with its own sources.
4. Give 1 to 5 sources. A quote source names `work_id`, `conversion_id`, `anchor` and `quote`;
   the quote must be verbatim in that one anchor of that conversion, within one paragraph or
   table cell. A citation source names a reference entry (`rex_...:n`) or a corpus `work_id`.
   Mark a source `supports` when the text rests on it and `background` when it is only context.
5. Call `interpretation_record` with the batch's `task_id` and `target`. If the call is
   refused, every problem is reported together; correct the input and send a new call. A
   rejected quote is resubmitted verbatim from the document, never edited to fit.
6. Use `interpretation_list` to see what exists for a target, with its label and review state.
   Replace your own unreviewed or wrong interpretation by naming it in `supersedes`. Never
   supersede a reviewed one or one a human wrote: that is a human step.
7. Write nothing you cannot ground in a source. A speculation without a source is not recorded;
   keep it in the session, or tell the researcher so it can go to the backlog.

## Concepts

A background concept is an outside idea a paper relies on (a technique, a theorem, a method the
paper takes as known). Propose one with `concept_propose` only for such an idea, never for a
claim of the paper itself.

- Give the source the paper itself cites when possible: `source` is a textbook, a survey, a
  corpus paper or other, with its citation text and, for a corpus paper, its `work_id`.
  The concept stays hidden until the researcher approves that source: an approved source is a
  human act, never yours. The `batch` lists the visible concepts (`concepts`); link to those
  instead of proposing a duplicate (a name or alias already taken is refused with the existing id).
- Draft the text (at most 600 characters) from the approved source, with `quotes` that are
  verbatim in that source's own document. Never quote a source without a document: a textbook
  or any source with no `work_id` takes no quotes and is shown as unverifiable.
- Propose `uses` links with `concept_link`: a `quote` of the citing paper that names the concept
  (or one of its aliases), or the citing paper's `reference` entry for the concept's approved
  source. The platform decides `stated` or `inferred`; an `inferred` link waits for a human.
  With neither basis give a `note`; it is shown as an agent note and never counted.
- A drafted definition is shown `unreviewed` until the researcher reviews it. To replace your own
  definition name `concept_id` and `supersedes`; a redefinition with a different source is hidden
  again.
- Never approve a source, review a definition, confirm or reject a link, merge or unmerge
  concepts, or ask a human to relay your own judgement as any of these.

## Stopping and human steps

Review, rejection and replacement of a reviewed or human-written interpretation are human steps
on the command line (`factory interpretations`); do not attempt them. If a call is refused,
report the reason verbatim and stop; do not retry with altered input to obtain a different
outcome.

## Tool arguments

Every tool call also takes `project` (the project slug), `role`, and `model` (your own model
id), alongside `skill`, which is the bare skill name. The platform computes the skill hash; do
not send one. Pass `rf-intuition` as `skill`. `interpretation_list` takes only `project` and its
filters.

## Done when

Every target you were asked to cover has an interpretation, or has been reported to the
researcher with the reason it has none, and the researcher knows how many are waiting for
review.
