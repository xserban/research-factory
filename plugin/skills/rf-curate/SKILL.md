---
name: rf-curate
description: Use when the researcher asks what the audits, disagreements and failed runs of a project teach: read the computed lessons and record a proposal (an amendment, a worked example or a skill revision) for a human to decide.
stage: [maintain]
---

# rf-curate

Turns the computed lessons of a project into reviewed proposals (IDEA-15). The platform computes
the lessons; this skill reads them and records what it would change. It decides nothing.

## Steps

1. Call `lessons_list` and page through it. Each lesson has an id, a kind (`audit-error`,
   `disagreement`, `cannot-assess`, `failed-run`), a subject and a count. No rate is shown and
   none may be inferred or computed from outside the list. Report an empty list as empty.
2. For each change worth proposing, call `curation_propose` with:
   - `kind`: `amendment` (a protocol change), `worked-example` (an example to add to a skill) or
     `skill-revision` (a change to a skill's text);
   - `text`: the change, in at most the length the tool allows, stated so a reviewer can act on it;
   - `lessons`: one to twenty ids copied from `lessons_list`; an id that is not one now is
     refused, so do not invent or alter one;
   - `target`: the protocol part or skill concerned, when there is one.
3. Report the returned `cur_` id and the refusal, if any, as returned. Do not retry with altered
   ids.

## Never

- Never decide a proposal. A human other than the proposer decides it
  (`factory curation decide`); a rejected proposal stays on record.
- An accepted amendment changes nothing by itself: it still goes through `protocol_amend`.
- A new or revised skill version must pass calibration before it is used on a project.
- Learning is not memory: do not carry a lesson into a prompt, a skill or a later session except
  through an accepted proposal.
- Do not read a work, a label or a rationale into a proposal; counts and ids only.
