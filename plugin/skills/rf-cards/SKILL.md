---
name: rf-cards
description: Use when method cards (for a confirmed lineage idea or a work) or problem descriptions (for the project's question) must be drafted as verified property assertions, in a Claude Code session that did not read a screening or extraction pass.
stage: [understand]
---

# rf-cards

Drafts method cards and problem descriptions as sets of property assertions. A card says, in a
fixed vocabulary of properties, what a method is and needs, or what a problem demands. The
platform checks every assertion against the document and sets its status: `stated` when the
quote or evidence row carries the value, `inferred` when it rests on your reasoning. You never
send a status, and you never confirm anything. Only the researcher approves properties and
confirms inferred assertions, on the command line.

## Independence

- Use a Claude Code session that has not run a screening, extraction or contribution pass, and
  has not been given human labels or decisions relayed in any form. The platform refuses these
  tools to a session that did; do not work around the refusal.
- Do not read or ask for the held-out seeds, the audit samples or the answer key.

## Procedure

1. Read the approved vocabulary with the researcher (`factory vocabulary list`); use an approved
   key whenever one fits. Propose a property with `vocabulary_propose` sparingly, and only when
   no approved key fits; it stays unusable until the researcher approves it. Never merge,
   approve or reject properties.
2. Create the card with `card_create`: `kind` `method` for a confirmed lineage idea (`ida_`) or a
   work id, `problem` for the project's question id or a short task name. An existing card of
   the subject is returned, not duplicated.
3. Read the sources through `document_read`. For each property, record one assertion with
   `card_assert`, one assertion per property:
   - `basis_kind` `quote`: give `work_id`, `conversion_id`, `anchor` and a `quote` that is
     verbatim in that element and states the property. Quote the sentence that states it, not
     a nearby one. The value (or one of the property's aliases) must occur in the quote; a
     number is checked as in extraction. A `false` bool cannot be quoted: record it as
     `inferred`.
   - `basis_kind` `row`: prefer it for numbers that are in the evidence table; give the
     `row_key` and the `field` of the final evidence row.
   - `basis_kind` `inferred`: only when no sentence states the property; give a `note`
     (at most 500 characters) and optional supporting quotes. Say to the researcher that these
     assertions are inferred and wait for their decision. Never present an inferred assertion
     as established.
4. Read the result. Each rejected item has its reason (`quote-not-verbatim`,
   `value-not-in-quote`, `anchor-unknown`, `value-differs`, ...). Fix the item and send it
   again; do not weaken a quote to make it pass, and do not retry with altered input to obtain
   a different status.
5. Problem properties that only the researcher can state (constraints of the project) are the
   researcher's: ask them to state those on the command line (`factory cards assert --researcher`).
   Never record one for them.

## Stopping and human steps

Approving, rejecting and merging properties, confirming and rejecting assertions, and the audit
of stated assertions are human steps on the command line (`factory vocabulary`, `factory cards`);
never confirm or decide, directly or by any other route. If a call is refused, report the
reason verbatim and stop.

## Tool arguments

Every tool call also takes `project` (the project slug), `role`, and `model` (your own model
id), alongside `skill`, which is the bare skill name. The platform computes the skill hash; do
not send one. Pass `rf-cards` as `skill`.

## Done when

Every property you were asked to cover has an assertion on the card, or has been reported to
the researcher with the reason it has none, and the researcher has the list of `inferred`
assertions awaiting a decision.
