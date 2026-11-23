---
name: rf-deep
description: Use when a project is of tier deep (hours, up to 150 papers): the brief procedure plus a protocol-lite with an independent PRESS-lite review, one capped backward snowball round, a sampled audit, agreement on a sample and the contradiction finder, ending in a cited evidence note labelled as a deep review that says what it skipped.
stage: [frame, gather, screen, acquire, extract, develop, write]
---

# rf-deep

Runs the plan of tier `deep` end to end. It is the `rf-brief` procedure with the deep-only steps
below added; read `rf-brief` first and follow its steps for question, search, screening,
acquisition, extraction and the note. The plan, caps and limits are data in `factory.tiers`: run
`factory brief plan <project>` (it lists the deep stages with their skill names) and keep to it.
The platform does not enforce the caps in this session: you stop at them and say so. Limits: 150
papers, 360 minutes, 60 runs. Everything is exploratory: no protocol gate binds, and the output
is a deep review, not a systematic one.

## Before you start

1. Call `project_status`; `rigor_mode` must be `exploratory` and the project must have been made
   by the researcher with `factory brief new "<question>" --tier deep`. Stop if not.
2. Read `rf-run` for the rules every session follows. Pass `role`, `model` and the bare skill
   name `rf-deep` as `skill` to every mutating tool.

## Deep-only steps

### 1. Protocol-lite and an independent PRESS-lite review

- Record the protocol from the template of `factory brief plan` with `protocol_record`: at most
  3 sources, 2 queries per source, one screening pass with the stopping rule, a schema of at
  most 6 fields, one backward snowball round.
- The PRESS-lite review must come from a session other than the one that wrote the protocol.
  The platform does NOT enforce this: `protocol_press_review` only requires an agent actor and
  the current protocol id. So you do not call it from the authoring session. Tell the
  researcher to start a second session (a new run) that calls `protocol_press_review` with its
  own `role`, `model` and `skill`; say in your note that the distinct session is a procedure,
  not a platform check. The confirmation, `factory protocol confirm-press`, is the researcher's
  act (human gate).

### 2. One capped snowball round

- After `search_run`, `report_search` and `dedup_run` (see `rf-brief`), call `snowball_round`
  with `direction` `backward` and `dry_run` true (the default). Read its candidates and whether
  the protocol's snowball plan allows it. Then at most ONE real round with `dry_run` false. No
  forward round. Decision 158 (a real round needs the researcher's recorded go-ahead through
  `decision_ids`) binds `pilot` and `systematic` only; an exploratory project, which a deep
  project is, is exempt. Say that the exemption was used.

### 3. Screening and the sampled audit

- Screen as in `rf-brief` (`ranking_compute`, `screen_next`, `screen_record`), at most 300
  records, one pass.
- `audit_sample` draws the title-abstract audit sample; the platform draws it from a recorded
  seed, not you. The labels are the researcher's: `factory audit label` (human gate).
  `screen_agreement` reports agreement on the sample if two passes exist; report what it
  returns, never a number of your own.

### 4. Extraction audit and agreement on a sample

- Extract as in `rf-brief`. Then `extract_agreement` on the sample the protocol names and
  `extract_audit_sample` for the audit; labels are the researcher's (`factory extract audit-label`,
  human gate). `extract_audit_sample` and `finder_contradictions` are refused to a session that has joined a pass: call them from a session that has not.

### 5. Contradictions

- Call `finder_contradictions` and list the numeric conflicts it returns, with the regime
  fields that differ. Do not resolve them and do not call one a refutation; they are computed
  candidates. This is the whole of the `develop` stage in a deep review.

### 6. Autonomy

Under `supervised` or `autonomous` the gate profile of the project may let an independent agent
session close some gates (`project_status` shows the level). Today the audit labels above are
human acts and no agent label path is exposed to this skill; where it is not, the gate stays
the researcher's. Never close a gate from the session that proposed it.

## The note and its label

- Write the note as in `rf-brief` step 6: `report_evidence` numbers only, `chat_verify` before
  any quote, `claims_digest` for claims.
- Begin with the label from the plan, for deep `deep review, skipped: ...` followed by the
  lines under "skipped" in `factory brief plan <project>` (the label comes from
  `factory.tiers` `report_label`; copy it, do not retype it). Add a section on contradictions
  and one on the audit: how many records were sampled and labelled, as the platform reports.
- State: PRESS-lite review by a separate session, confirmed by the researcher or not yet;
  audit labels given or still pending; no human confirmed screening or extraction beyond those
  gates; the review is exploratory.

## Human gates

The question and goal confirmation, the PRESS confirmation, every audit label and any protocol
amendment are the researcher's acts. Say so and hand over the command; do not close a gate
yourself. Stop at the plan's caps and report which was reached. Promotion to `pilot` or
`systematic` is a new project that imports this one's works.

## Done when

The note is written and checked, carries the deep label, names what was skipped and what is
unconfirmed, and `project_status` and `factory brief status <project>` agree with it.
