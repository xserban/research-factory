---
name: rf-mine
description: Use when a registered miner must be run over the corpus, or a miner must be registered: serves miner tasks, records the rows read from the pinned document, and settles disagreements where the gate allows it. Name this skill as a miner's `procedure`.
stage: [extract]
---

# rf-mine

Runs one pass of a miner. A miner reads typed fields from selected anchors of a converted document.
The platform selects the anchors and checks each row; the reading is yours.

## Independence

One session holds one pass. Pass A and pass B of a miner run in separate Claude Code sessions, and
a session that joined a pass does not read the other pass's rows, any rate or any human label.
The first `mine_next` call joins this session to the pass. The session that proposed a miner does
not run its calibration pass, and neither does a session that took part in a production pass or
recorded a gold label.

## Procedure

Registering, when the miner is new:

1. Call `miner_register` with the spec: name (`m-...`), version, selector, typed fields, row key,
   evidence rule, procedure skill (`rf-mine`) and regime. A changed spec needs a new version.
2. Tell the researcher the protocol's `miners` section must list the miner. A registered miner runs
   only then. Turning `evidence` on is the researcher's act.

Running a pass:

1. Call `mine_status` to see units, open, closed, rows and stale for your miner.
2. Call `mine_next` with `miner`, `version` and `pass_label`. Read `blocked` if no task comes and
   report it. Add `calibration` for the miner's calibration pass.
3. Read the anchors the task names with `document_read`, at the pinned conversion.
4. Call `mine_record` with one row per item found. Each value comes from the document, with its
   anchor and verbatim quote. Never compute, convert or infer a value.
5. Repeat for the work, then close it with `finish`. A work with no rows needs a `reason`.
6. Correct a row by `supersedes`, mapping the index of the new row to the row it replaces.
7. If you cannot finish a task, call `task_release`.
8. Repeat from step 2 until no task is served.

Settling, in a session outside both passes and only where the policy for the gate `mine.resolve`
lets an agent:

1. Call `mine_disagreements` for the miner.
2. Call `mine_resolve` with `a`, `b` or `neither` and a reason, after reading the anchors yourself.
   The miner's proposer does not resolve. When the gate is human, the tools refuse: report it.

## Tool arguments

Every writing tool takes `role`, `model` and `skill` (`rf-mine`). `miner_list` names what is
registered.

## Never

- Never record a value the document does not state.
- Never read the other pass's rows, or look for a rate or a label.
- Never relax a miner's rule by editing a registered spec: register a new version.

## Done when

`mine_status` shows no open or queued unit for this pass, or the session has reported what blocks.
