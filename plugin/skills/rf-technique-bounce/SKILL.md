---
name: rf-technique-bounce
description: Use when an idea or a question about the techniques of AI research systems must be set against the technique landscape (what is used, how widely, with what evidence, what is untried), and hypotheses may be proposed from its gaps, combinations and challenges, in a Claude Code session that did not read a screening, extraction or mining pass.
stage: [develop]
---

# rf-technique-bounce

Sets an idea against the landscape of approaches (techniques) that the technique miners read
from the corpus, and proposes hypotheses from what the landscape shows is common, untried or
contested. Everything the landscape shows is exploratory: it comes from uncalibrated miners
(pass A; quote the agreement between passes from the tool's own stage figures, never from memory), it is an interpretation, never evidence, and no
figure from it enters a report. "Not found in this corpus" is not "absent from the field".
You propose; the researcher accepts or discards. You never confirm, review, promote or register.

## Independence

- Use a Claude Code session that has not run a screening, extraction or mining pass. The
  platform refuses these tools to a session that did; do not work around the refusal.
- Do not read or ask for the held-out seeds, the audit samples or the answer key.

## Labelling rule

Every sentence of yours that carries a count, a ranking, a gap or a combination says where it
comes from: "exploratory, pass A of m-tech-<stage>, core layer, n works". Name the lens
(`layer`, `stage`, `evidence`, `status`) the tool printed. Call the nodes "approaches" to the
researcher. Never call a `derives-from` candidate or `earliest-in-corpus` an origin: the first is
a candidate, the second a date rule.

## Procedure

1. Call `technique_landscape` (read-only) for the stages the idea touches. List the candidate
   approaches as a tick list with their number of works and evidence buckets, and the stage's
   agreement figure; the researcher ticks the ones that matter. Keep `layer` core unless asked.
2. For each ticked approach call `technique_view`: its uses, the miner's `described_as` per use,
   status, evidence level and the quote with its anchor. Call `technique_neighbors` for what it
   is used with, the stages its users reach and the `derives-from` candidates.
3. Read each quote you will rely on with `document_read` (the quote must be verbatim in that
   anchor of that conversion); a row whose quote you cannot find is dropped from your argument
   and reported to the researcher. A row with no `evidence` attribute is "not stated", not weak.
4. Place the idea, in your own words, labelled as your reading: what is already done and by how
   many works at which evidence level; the nearest variant; what is only asserted
   (`asserted-only`); what has a `reported-failure` row (see `technique_challenges`).
5. To find what may be new, call `technique_gaps` (approaches well used at one stage whose users
   show none at another; `from_stage`, `to_stage`, `min_works`), `technique_combinations`
   (well-used pairs no work uses together) and `technique_challenges` (reported as failing in one
   work and supported in another, settings possibly different). Each result is a list of
   hypotheses to check, not findings. Choose at most a few that fit the idea, and for each say
   why it may be empty (a stage a paper does not describe, a pair that does not combine) before
   proposing it.
6. Check each hypothesis you keep against the verified quotes of both sides: the work ids and
   rows the tool returned, opened with `document_read`. A candidate whose quotes do not show what
   the statement says is discarded.
7. Record only what the researcher says to record, with the existing tools, labelled in the
   text as derived from exploratory miner rows:
   - `interpretation_record` for a reading of one work (at most 600 characters, 1 to 5 sources,
     each a verified quote). An agent records it against a task: first call
     `intuition_next` with `targets` set to that work id (a paper is served only when named),
     then record with the returned `task_id` and the same target. There is no task-free route
     for an agent; do not look for one.
   - `lead_record` (at most 600 characters) for an idea to follow up, with triggers: the works
     (`work`), and an `interpretation` you recorded. Name the framework. Read `prior` in the
     answer and say how the lead differs.
   - `hypothesis_draft` only after the researcher has promoted that lead (`lead_decide` is a
     human act): the draft needs the promoted lead, a treatment and baseline, one metric,
     conditions from the evidence schema, a prediction and a decision rule. A literature-kind
     hypothesis fits a gap or combination that is to be checked in the corpus; an experiment kind
     needs a metric the evidence schema has. Technique counts are never the evidence of a
     hypothesis.
8. Do not call `idea_propose` or `relation_propose` for approaches: they need a recorded
   contribution item and a confirming human, and are not used for techniques.

## Stopping

If a call is refused, report the reason verbatim and stop. Report to the researcher: the lens
and tools used, the approaches ticked, the candidates kept and discarded with the reason, and
what you recorded (ids). State that the figures are exploratory and not for a report.

## Tool arguments

Every write call also takes `project` (the slug), `role`, `model` (your own model id) and
`skill`, the bare skill name: pass `rf-technique-bounce`. The platform computes the skill hash.

## Done when

The researcher has the placement of the idea, the kept and discarded candidates with their
quotes, and any interpretation, lead or draft you were told to record.
