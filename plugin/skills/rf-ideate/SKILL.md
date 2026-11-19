---
name: rf-ideate
description: Use when research ideas must be captured as leads tied to triggers in the corpus and turned into pre-registrable hypothesis drafts, in a Claude Code session that did not read a screening or extraction pass and is not the session that will review or register them.
stage: [develop]
---

# rf-ideate

Captures research ideas as leads, each tied to what in the project suggested it, and drafts
falsifiable hypotheses from the leads the researcher promoted. You propose; you never decide,
review or register. The platform computes every version, state and flag, and prints the
falsifier sentence from the rule you choose.

## Independence

- Use a Claude Code session that has not run a screening, extraction or contribution pass. The
  platform refuses these tools to a session that did; do not work around the refusal.
- You cannot review a hypothesis you drafted or a lead you wrote, and you cannot register it:
  the critic is another session (`rf-critic`) and the registration belongs to the researcher
  (or, in exploratory mode only, to a session other than yours). Never register.
- Do not read or ask for the held-out seeds, the audit samples or the answer key.

## Procedure

1. Start from the project's own evidence, not from memory: `match_query` for method cards that
   fit a problem description, `finder_contradictions` and `finder_gaps` for numeric conflicts
   and empty cells, the lineage and interpretation views for ideas. Note which output you are
   reading; it will be a trigger.
   For technique challenges, combinations and gaps and for limitation rows of m-claims, the
   read-only tools `lead_candidates`, `lead_queue` (ordered by computed measures, balanced across
   sources) and `lead_stats` give candidates with the exact triggers to cite; `rf-hypothesis-engine`
   describes the procedure. A lead is still yours to word and the researcher's to decide.
   Where two live claims or contribution items of different works contradict each other, propose
   the pair with `contradiction_propose` and a note of at most 500 characters. It stays inferred
   until the researcher confirms it.
2. Record a lead with `lead_record`: at most 600 characters and at least one trigger. A trigger
   is `{kind, ref}`: `work`, `row`, `claim`, `item`, `idea`, `interpretation`, `concept`,
   `card`, `contradiction`, `lead` or `hypothesis`, or a builder row (`match`, `conflict`,
   `gap`) given with its key as `ref` and the row exactly as the builder returned it. A lead
   without a trigger is refused; do not invent one. Name the ideation framework you used in
   `framework`.
3. Read `prior` in the answer. It lists the parked and discarded leads and the earlier
   hypotheses that share a trigger, card, idea or property. Open each with `hypothesis_view`
   where it is a hypothesis, and tell the researcher how this lead differs from every one of
   them, or withdraw it.
4. The researcher promotes, parks or discards the lead. Do not decide it yourself.
5. From a promoted lead, draft a hypothesis with `hypothesis_draft`:
   - one factor changes (treatment against a named baseline), one primary metric, and
     conditions that exist as comparability keys of the evidence schema;
   - a prediction with a margin you state before any result;
   - a decision rule from the menu: `superiority`, `non-inferiority` or, for a hypothesis tested
     on later literature, `literature-direction` with its `n_min` and `q`;
   - the `lead` id, and `supersedes` only when you replace a draft of your own.
   Read the falsifier sentence in the answer. If it does not say what you meant to risk,
   supersede the draft; do not argue it away.
6. A hypothesis with evidence cannot be revised; report that and stop.

## Stopping and human steps

Promoting, parking and discarding leads, registering, abandoning and concluding hypotheses and
declaring model cut-offs are the researcher's steps on the command line (`factory leads`,
`factory hypotheses`, `factory models`). If a call is refused, report the reason verbatim and
stop; do not retry with altered input to obtain a different answer.

## Tool arguments

Every tool call also takes `project` (the project slug), `role`, and `model` (your own model
id), alongside `skill`, which is the bare skill name. The platform computes the skill hash; do
not send one. Pass `rf-ideate` as `skill`.

## Done when

Each idea you were asked about is a lead with its triggers, its prior has been read and
answered, and each lead the researcher promoted has a hypothesis draft whose falsifier sentence
the researcher has seen, or has been reported with the reason it has none.
