---
name: rf-lineage
description: Use when recorded contribution items of the included works must be turned into lineage relations (builds-on, improves-on) between works, or into named ideas, as proposals for the researcher to confirm, in a Claude Code session that did not read a contribution or screening pass.
---

# rf-lineage

Proposes lineage relations and ideas from contribution items that have been recorded and
agreed. A proposal is a claim for a human to check, not a fact. The platform sets the status of
every relation: `stated` when the item's cited reference entry resolves, in the reference
extraction, to exactly the work you propose; otherwise `inferred`. The platform sets the status;
you never send one, and you never claim a relation is confirmed. Only the researcher confirms
or rejects, on the command line.

## Independence

- Use a Claude Code session that has not run a contribution, extraction or screening pass, and
  has not been given human labels or decisions relayed in any form. The platform refuses these
  tools to a session that did; do not work around the refusal.
- Do not read or ask for the agreement, the audit sample, the held-out seeds or the answer key.

## Procedure

1. Pick a `base-idea` or `addition` item of an included work (its id is the `basis_item`). Only
   such an item may be a basis. An item that is superseded, stale, still disputed between the
   passes, or of kind `result` or `limitation` is refused.
2. One target per item. If the item names several predecessors, it has been split into one item
   per named predecessor; propose one relation per item. Prefer the work that the item's
   `cited_entry` resolves to: then the relation is `stated` and needs no further check. A
   `base-idea` gives `builds-on`; an `addition` that names what it improves gives
   `improves-on`.
3. Call `relation_propose` with `source_work` (the work the item belongs to), `target` (a work
   id, or an idea id), `edge_type`, and `basis_item`. When you propose a target other than the
   one the cited entry resolves to, say why in `note` (at most 500 characters). The note is
   your own words, not evidence; it is shown to the researcher labelled `agent-note` and is never
   counted. Without a `basis_item` a `note` is required and the relation is `inferred`.
4. A relation to an idea always needs a `basis_item` and is always `inferred`.
5. Propose an idea with `idea_propose` only with a `name_item`: a recorded item of the origin
   work whose `name` quote contains the idea's name verbatim. List the member works, including
   the origin. An idea is a proposal until the researcher confirms it. Never merge ideas, and
   never propose the same grouping twice under another name; naming variants are merged by the
   researcher.
6. Read the result: `status` and `status_reason` are the platform's. Report the number of
   `inferred` relations you proposed, with their reasons, to the researcher for confirmation.
   Do not describe an `inferred` relation as established, and never confirm a relation or an
   idea, directly or by any other route.

## Stopping and human steps

Confirmation, rejection, merging and unmerging of relations and ideas are human steps on the
command line (`factory relations`, `factory ideas`); do not attempt them. If a call is
refused, report the reason verbatim and stop; do not retry with altered input to obtain a
different status.

## Tool arguments

Every tool call also takes `project` (the project slug), `role`, and `model` (your own model
id), alongside `skill`, which is the bare skill name. The platform computes the skill hash; do
not send one. Pass `rf-lineage` as `skill`.

## Done when

Every base-idea and addition item you were asked to cover has a proposal, or has been reported
to the researcher with the reason it has none, and the researcher has the list of `inferred`
proposals awaiting a decision.
