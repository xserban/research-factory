---
name: rf-taxonomy
description: Use when classifying works with a miner derived from a taxonomy (mine_next, mine_record), or when writing a change proposal for the next taxonomy version (taxonomy_propose). Name this skill as a derived miner's `procedure`.
stage: [extract]
version: 1
---

# rf-taxonomy

A taxonomy is a versioned set of dimensions, each with categories. A miner derived from it assigns
categories to works. You read and judge; the platform checks each row and computes counts,
coverage and digests. Plan: `docs/plans/2026-11-12-taxonomies-as-versioned-objects.md`.

## Classifying a work

Run the pass as in `rf-mine` (independence, `mine_next`, `document_read`, `mine_record`, `finish`).
The task serves, per dimension: its question, cardinality, read scope, and each category's
definition, include cues, exclude cues and examples. Only dimensions that apply to the work's layer
are served; do not classify the others.

1. Read the anchors the task names. Answer each dimension's question from the text.
2. Apply each category's **definition** and its include and exclude cues to what the paper
   states. Never match on keywords: a term that appears is not evidence that the category applies.
3. Write one row per assigned category. Field `category` is a full id `dimension/category`, for
   example `technique/multi-agent`. Every such row quotes verbatim evidence with its anchor.
4. Cardinality: a `single` dimension gets exactly one row; a `multi` dimension gets one row for
   each category that applies (not more than the dimension's `max_labels`, if set).
5. `<dim>/other`: the paper states something about the dimension that fits no category. Quote it,
   and give `described_as` in the paper's own words. `described_as` is allowed only on `other`.
6. `<dim>/not-stated`: the text you read says nothing about the dimension. No quote. Never quote
   "the nearest sentence" to avoid it. `not-applicable` is used only where the task offers it.
7. Never invent a category or an id. If nothing fits, use `other`; the proposal route below is how
   categories change.
8. Rows are keyed on `category`; do not rely on a quote to match another pass's row.

When a work is borderline between two categories, choose the one whose definition the quoted text
satisfies, and record the other only if its definition is also satisfied (`multi`). Do not
average, hedge or write both into a `single` dimension.

## Writing a change proposal

Proposals are written when asked, from the cluster and disagreement views (`mine_disagreements`,
the coverage and `other` listings of the taxonomy). Call `taxonomy_propose(project, taxonomy,
base_version, kind, targets, drafts, works, rows, cluster_id, rationale)`; it records a proposal
against version N, for the researcher to settle into version N+1.

Choose the kind from the evidence:

- `add`: `other` rows cluster around one unnamed idea. Cite the works and rows.
- `split`: one category is too broad: its rows fall into distinct groups. Name it in `targets`.
- `merge`: two categories are confused in disagreements and the difference does not hold up.
- `redefine`: the category is right but its definition or cues misfit the rows cited.
- `rename`: the idea is right and the name misleads.
- `retire`: the category is empty or fully covered by another.

Every kind except `add` names its targets as full ids `dimension/category` of the base version.

A draft gives, for each new or changed category: id, name, definition, include cues, exclude cues
and examples. Examples are verbatim quotes with work id and anchor, and never come from a
calibration sample. Cite only works of the project corpus and rows you have read. The rationale
states what you saw and why the change follows from it.

## Rules

- A proposal is a suggestion; the researcher decides, and only a registered version changes the
  taxonomy. Do not register, and do not treat a proposal as in force.
- Counts, rates and coverage are computed by the platform; never type them into a rationale as
  findings. Cite the cluster or row ids and let the platform's numbers speak.
- Record through the tools only; if a call is refused, read the structured errors and fix it.
- Never use calibration labels you were not shown, and never ask for them.
