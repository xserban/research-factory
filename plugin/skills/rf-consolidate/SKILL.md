---
name: rf-consolidate
description: Use when free labels must be applied to works, ideas or concepts, or when candidate clusters of labels, ideas or concepts that may name the same thing must be read and a merge, keep or split proposed for the researcher to decide, in a Claude Code session that did not read a screening, extraction or contribution pass.
stage: [understand]
---

# rf-consolidate

Applies free labels and proposes consolidations. A label is organisation, not evidence: it names
a method, a topic or a family in the researcher's own words so that works can be found again, and
it selects nothing until the researcher promotes it to a term. A proposal is a claim for a human
to check, not a fact. The platform computes the status of every label and the candidate
clusters; you never send a status, and you never merge, keep, split or promote anything. Only
the researcher decides, on the command line.

## Independence

- Use a Claude Code session that has not run a screening, extraction or contribution pass, and
  has not been given human labels or decisions relayed in any form. The platform refuses these
  tools to a session that did; do not work around the refusal.
- Do not read or ask for the agreement, the audit sample, the held-out seeds or the answer key.

## Applying labels

1. Call `label_apply` with items `{target_type, target, text, quote?}`: a short label (at most 60
   characters) on a work, an idea or a concept that exists in the project.
2. A `quote` is a verbatim passage of the target work, given as `{work_id, conversion_id,
   anchor, quote}`. The platform checks it against the converted document. When the verified
   quote contains the label, the application is `stated`; with no quote, or a quote that does not
   contain the label, it is `inferred` and waits for a human to confirm it. Do not describe an
   `inferred` application as established.
3. Prefer one label per method or topic, in the words the paper uses. Reuse a label that already
   exists rather than coining a variant; naming variants are merged by the researcher.
4. Each item is written or rejected on its own. Read the rejected items and fix them; do not
   resend an item altered only to obtain a different status.

## Proposing consolidations

1. Call `consolidation_next`. It serves one cluster as a task: the members with their names and
   aliases, and for each pair of members the signals that linked them (similar names, an acronym,
   shared targets). The signals are hints. Two labels with no similar spelling may name one
   method because they sit on the same works; two similar names may name different things.
2. Decide what you would recommend and call `consolidation_propose` with `action`:
   `merge` (name `into`, the member that remains, and the `members` to merge), `keep` (the
   members are distinct) or `split` (the cluster mixes distinct things). Give a `reason` in your
   own words (at most 600 characters) and, where a paper supports it, verbatim `quotes`.
3. The task is completed by your proposal. Nothing is merged by it. Report the number of
   proposals you made, by action, to the researcher.

## Stopping and human steps

Confirming and rejecting applications, merging and unmerging, deciding clusters, completing a
pass and promoting or retiring terms are human steps on the command line (`factory labels`,
`factory terms`, `factory consolidation`); do not attempt them. If a call is refused, report the
reason verbatim and stop.

## Tool arguments

Every tool call also takes `project` (the project slug), `role`, and `model` (your own model
id), alongside `skill`, which is the bare skill name. The platform computes the skill hash; do
not send one. Pass `rf-consolidate` as `skill`.
