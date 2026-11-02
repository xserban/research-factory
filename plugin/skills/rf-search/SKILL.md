---
name: rf-search
description: Use when screening of the corpus has finished and agreement is recorded, and the included works must be chased backward and forward for further candidates.
---

# rf-search

Runs the citation-chasing step of a ready protocol. The platform builds every chase query from
the included works and records the round before any query runs; this skill only asks for the
round and routes the new works back into screening.

## Preconditions

- The corpus has been screened in both passes and `screen_agreement` has been read, and every
  disagreement has been resolved by the researcher. The tool refuses while any work still lacks
  a final outcome, and reports how many are pending.
- At least one included work carries an OpenAlex identifier. Included works without one are
  listed as `unchasable` in the reply; report them to the researcher and do not look them up.

## Procedure

1. Call `search_chase` with `directions` set to both `backward` and `forward`. Use a single
   direction only when the researcher asks for it.
2. Read the reply: `round_id`, `from_works`, `unchasable`, one run summary per query and
   `new_works`. A run that is `partial` or `failed` is reported as it is, with its note; do
   not hide a shortfall.
3. Call `dedup_run` so that a work the chase returned again, or that duplicates a corpus work
   under another identifier, is merged instead of screened twice.
4. Return to screening. The new works are served by `screen_next` to pass A, and to pass B
   when the platform draws them into the pass B sample. Screening, agreement and resolution
   follow the `rf-screen` procedure, in their own sessions.
5. After agreement and every resolution on the new works, repeat from step 1. Stop when a round
   adds no new works. Each repeat is a new round; the platform records them all.

## Never

- Never write, edit or reuse a chase query by hand, and never pass one to `search_run`. The
  protocol gate refuses a chase query that no recorded round contains.
- Never name a seed, a DOI or a citation in a request. Admission of a missed seed by
  identifier is a researcher step (`factory seeds admit`), not a tool.
- Never retry a refused round by changing what the platform computed. Report the refusal
  message to the researcher.

## Tool arguments

Every tool call also takes `project` (the project slug), `role`, and `model` (your own model
id), alongside `skill`, which is the bare skill name. The platform computes the skill hash; do
not send one. Pass `rf-search` as `skill`. `project_status` shows the number of chase rounds.

## Done when

A round adds no new works, or a refusal has been reported to the researcher.
