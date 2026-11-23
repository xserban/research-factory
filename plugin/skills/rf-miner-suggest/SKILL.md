---
name: rf-miner-suggest
description: Use when a study's question needs an extraction schema that no registered miner provides and you propose a miner on the fly: attended (the researcher ticks the fields) or brief (self-registered, one pass, labelled exploratory, unvalidated, agent-proposed). Never admits a miner.
stage: [extract]
---

# rf-miner-suggest

Proposes a miner for the question of the study, registers it and gets it listed in the protocol,
without admitting it. The design is `docs/plans/2026-11-20-tiers-and-autonomy/on-the-fly-miners.md`;
`rf-mine` runs the miner afterwards. Everything here is exploratory: rows of a miner nobody
admitted never enter evidence counts (R-87), and every statement about them says
`agent-proposed schema`.

## Before you start

1. Call `project_status`: read `tier`, `autonomy_level` and `rigor_mode`; call `question_view` for
   the question. Follow `rf-run` (pass `role`, `model` and the bare skill name `rf-miner-suggest`
   as `skill` to every mutating tool). Call `miner_list` and `mine_status`: do not propose a miner
   a registered one already covers.
2. Limits: tier `brief` at most 2 proposed miners, at most 6 fields each, one pass; tier `deep` at
   most 3. Stop at the limit and say so.

## Steps

### 1. Draft the schema

- One sentence: what this miner adds to answering the question. Fields typed (quote, enum, number,
  citation); at most 8 (6 in a brief); each with a definition (`description`); no free text.
- Every required quote field and every enum needs a 'not stated' outcome: put an enum value such as
  `claim/not-stated` in `evidence.absence_values`. A field must record what a work says, not
  restate the question ("does X improve Y" is the question, not a field).
- Cap the works read (`selector.max_units`), choose `population`, `heading_patterns` and `elements`,
  and the use: `on_demand` (works the researcher requests with `factory mine request`) or `layers`.
  Regime `passes` 1.
- Check the draft by hand against the list above (a pure check exists in `check_proposal` of
  `services/miner_proposal.py`; no tool calls it yet). The checks of `miner_register` are not a
  substitute: they refuse a wrong shape, not a vague or question-restating field.

### 2. Attended: the researcher ticks (human gate)

- Call `decision_suggest` with level `protocol`, subject `miner-<slug>`, an explanation of the step
  and why, and items (`I01`...: one per field and one for the miner), `grounds` naming the question
  or the papers read. No `recommended` flag (the schema is the researcher's). Then wait: the
  researcher selects (selection is the human's act: never call `decision_select`). Register
  only the selected items.

### 3. Brief: self-register, labelled

- Without waiting, call `miner_register` with the spec. State to the researcher, in your message
  and in the `rationale`, the label `exploratory, unvalidated, agent-proposed`.

### 4. List it in the protocol

- Add it to the protocol's `miners` section with its use: `protocol_record` in a brief, where the
  protocol is not yet ready, otherwise `protocol_amend` (the researcher's amendment: say so and
  hand over the command; do not close a gate yourself). `miner_list` shows whether it is listed.

### 5. Hand over

- Tell the researcher the miner is registered, unadmitted and which works it will read. Run it with
  `rf-mine` (`mine_next`, `mine_record`, one pass in a brief). Report any row as exploratory.

## Human gates

The ticking of fields and miners (attended), any protocol amendment, the calibration labels
(`miner_calibration_label`) and admission (`factory miner admit`) are the researcher's acts. In a
brief nobody validates the schema: say `unvalidated` every time rows are shown. Never admit a
miner, never read its rows as evidence, never type a count a report does not contain.

## Done when

The miner is registered and listed, the researcher has the label and the limits, and nothing was
admitted.
