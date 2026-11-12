---
name: rf-reference-layers
description: Assign relevance layers (earth rings) to the cited items of a project's reference lists, from titles, under the researcher's recorded scheme. Use when asked to run the title or abstract stage of reference layers, or the calibration pass.
stage: [gather]
version: 1
---

# Reference layers: title and abstract stages

You place cited items (references of the included works, grouped by normalised title) into the
rings of the project's **layer scheme**. You judge relevance; the platform does everything else
(grouping, clean-up, counts, order, precursor marking). Plan: `docs/plans/2026-11-11-reference-layers.md`.

## Procedure

1. Call `reference_layer_next(project, stage, limit)` (stage `title`, or `abstract` when asked).
   It returns a batch, its `input_blob`, the scheme (layers inner to outer, with criteria and
   examples) and whether the calibration still gates the queue.
2. For each item, read the title (and the abstract at stage `abstract`), then choose the **one
   layer** whose criteria fit best. Use the year only as context; precursor status (published
   before the scheme's cutoff) is computed by the platform and is never your judgement.
3. Write a rationale of one short sentence naming the criterion that decided it.
4. Call `reference_layer_record(project, scheme_version, stage, assignments, input_blob, role,
   model, skill="rf-reference-layers")` with every item of the batch. Repeat until `remaining` is 0.

## How to judge from a title

- Go ring by ring from the **outside in**. Most references are not relevant (about three in four
  in the agentic-science pilot); say so plainly when the criteria place an item outside.
- A title that names an AI research system, AI scientist or autonomous discovery system is core
  (general purpose) or applied (one science). Do not count research stages; that is checked later
  at full text.
- A title about one science with no AI at its core is **not relevant**, however good the science.
- A title about LLMs or LLM agents in general (how they work, behave, fail, are evaluated) is
  **background**; one that builds a technique agents use is **adjacent**; attacks on LLMs are not
  relevant. Follow the scheme's own wording when it is more specific than this list.
- When a title is too vague to place, choose the outermost layer its words support and say
  "vague title" in the rationale. Never guess inward.
- Never use knowledge of the researcher's calibration labels; you are not shown them and must not
  ask for them.

## Rules

- You judge; you never count, sort or compute. One layer per item, no ties.
- Record through the tool only; never write files or events by other means.
- If a call is refused, read the structured error, fix the batch and retry; do not drop items.
