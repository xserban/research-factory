# Decision sheet for the researcher (2026-11-21): tiers and autonomy levels (slice 9)

Scope: every proposed decision row and open ruling raised by the lanes of the plan `docs/plans/2026-11-20-tiers-and-autonomy.md` (branch `tiers-base`, not on main). Rows 163 to 168 (D1 to D6) are in `docs/specs/slice-9-decision-rows.md`; D7 and D8 are in `docs/plans/2026-11-20-tiers-and-autonomy/on-the-fly-miners.md` section 7; the other rows below (labels `D-V*`, `D-C*`, `D-E*`, `D-G*`, `D-X*`, `D-ATTR`) were raised by the lane prompts, the code and the follow-ups of the lanes. `docs/decisions.md` is not changed; a ruling is written there after you answer. This sheet follows the format of `docs/decision-sheet-2026-11-20.md`.

How to read it. "Built on it" cites the module or test on `tiers-base` that already depends on the row (path under `platform/src/factory/` or `platform/tests/`). Nothing here says the tests pass; the integrated branch had one CI run (982ca9cc, three failures fixed). The lane reports themselves are not in the repository; where a row is reconstructed from the lane prompt and the code rather than from a report, the status table says "reconstructed". D7 and D8 carry the provisional numbers 169 and 170 (next free after 168; `main` may have moved: fix at merge). Recommendations: DECIDE as written; AMEND (say what).

Conflicts with *Decided* entries: none contradicts one. D3 (165) amends 84 item 6, and the spec section 11 amendments to 84 items 4 and 5 (agent audit label) and to 24 (a tier is a second setting above the mode) are in the confirmation list. D1, D2, D4 and D6 rely on 158 (Decided), 160, 161 and 162 (Proposed at the time of writing; not re-checked here), so rule those first.

## 1. Status table

| # or label | Title | Built on it (evidence) | Rec. | Reason |
|---|---|---|---|---|
| 163 (D1) | Tiers and their rigour modes | `model/levels.py` `RIGOR_OF_TIER`; `tiers/plans.py`; `services/project.py`; `tests/test_tiers.py`, `tests/test_levels_model.py` | DECIDE (Q1) | No new mode, no hashed change; exploratory already relaxes what a brief needs. |
| 164 (D2) | Autonomy levels | `modules/autonomy.py` `profile`; `services/level_statement.py`; `tests/test_autonomy_levels.py`, `tests/test_level_statement.py` | DECIDE (Q2) | Controls grow with what each level removes; `attended` unchanged. |
| 165 (D3) | Gates that may go below `human` under `autonomous` | `modules/autonomy.py` (`AUTONOMOUS_FLOOR` ships empty, supervised gates filled); `index/hypotheses.py` fold; `tests/test_fold_autonomy_level.py` | DECIDE (Q3) | No floor lowered; until ruled nothing moves. Amends 84.6. |
| 166 (D4) | An agent's selection of a decision | Not built (`index/decisions.py:126` still drops non-human selections) | DECIDE (Q4) | Needed only for `pilot` and `systematic` at `autonomous`. |
| 167 (D5) | Trust thresholds and stop rule | `services/gate_trust.py` (0.05 watch, 0.10 pause, 20 audited); `tests/test_autonomy.py` | DECIDE (Q5) | 5% equals the existing gate-audit ceiling. |
| 168 (D6) | Promotion between tiers is by import | Nothing built; `tiers/` has no promotion; builds on 161 | DECIDE (Q6) | Keeps mode fixed at init. |
| 169 (D7) | Relax "categories are the researcher's" for miner proposals (decision 120) | `services/miner_proposal.py`, skill `rf-miner-suggest`; design only, no admission change | DECIDE (Q7) | Label on every row; taxonomies stay the researcher's. |
| 170 (D8) | Independent review of a miner schema | `services/miner_proposal.py` (check only); review not enforced in code | DECIDE (Q8) | Admission stays human; revisit after a benchmark. |
| D-V1 | Validation profile per tier and level (reconstructed) | `tiers/validation.py`, `services/validation_profile.py`, `enforcement_for` in five consumers; `tests/test_validation_profile.py` | DECIDE (list) | Pilot, systematic and legacy projects keep today's `ENFORCEMENT`. |
| D-V2 | Independent judge under `supervised` and `autonomous` (reconstructed) | `tiers/validation.py` (`independent_judge`, `calibration_required`) | DECIDE (list) | Same rule as D8 and R-154; label says `unvalidated` without human gold. |
| D-V3 | Miner admission stays human at every level (reconstructed) | `tiers/validation.py` (`admission = "human"`); `services/miners.py` `admit_miner` | DECIDE (Q9) | No autonomous admission until ruled. |
| D-V4 | What "claims-only" means for brief miners | `tiers/validation.py` (`miners_allowed="claims-only"`), `services/validation_profile.py` | DECIDE (Q10) | Operational definition exists only as "a use admitted as evidence". Backlog IDEA-128. |
| D-C1 | Conductor state is five new system event types, derived, no table (reconstructed) | `events/catalog.py` (conductor.*), `model/conductor.py`, `services/conductor.py` | DECIDE (Q11) | No table, so no state hash moves. |
| D-C2 | Conductor stop rules; never skips a stage; waits at a human-only gate (reconstructed) | `services/conductor.py` module docstring; `tests/test_conductor.py` | DECIDE (list) | Computed rules; no gate lowered. |
| D-C3 | Verifier and auditor as separate runs under `supervised` and `autonomous`; no human-only act in a stage allow-list in v1 (reconstructed) | `services/conductor.py`, `services/runner.py` stage specs (lane L10 prompt) | DECIDE (list) | Same pattern as `spar_v2`. |
| D-E1 | PRESS review needs a session other than the protocol author's | `services/protocol.py`; `tests/test_press_session.py` | DECIDE (Q12) | Closes the L6 finding; scope is a choice. |
| D-E2 | Tier caps enforced by the platform for brief and deep | `services/tier_caps.py`, `services/screening.py`, `services/fulltext.py`; `tests/test_tier_caps.py` | DECIDE (list) | Legacy, pilot, systematic never capped. |
| D-E3 | The gate-policy fold reads the level from `project.created` | `index/hypotheses.py`, `index/levels.py`; `tests/test_fold_autonomy_level.py` | DECIDE (list) | No table or column, no hash change. |
| D-G1 | Agent audit label is `gate.audit_labelled` with an agent actor, counted apart from human labels | `services/gates.py` `gate_audit_record_agent`; `services/gate_trust.py` | DECIDE (Q13) | No new event type; also amends 84 items 4 and 5. |
| D-G2 | Deferred review uses the existing audit label event, human only; items exist only below `attended` | `services/deferred_review.py`, `cli/review.py` | DECIDE (list) | No `gate.review_recorded` event was needed. |
| D-X1 | Brief extraction: single pass and the pass-B requirement | `services/extraction_agreement.py` (about :628); L15 prompt (not built) | AMEND (Q14) | Plan says one pass; code needs pass B opened. IDEA-122. |
| D-X2 | Screening cap may be overshot by up to one batch | `services/screening.py` `_require_under_tier_cap` (`SCREEN_BATCH = 10`, brief cap 40) | DECIDE (Q15) | State or trim. IDEA-124. |
| D-ATTR | Attribution of mechanical document acts | `services/document_convert.py` lines 695 and 725 (`project.human_actor()`) | AMEND (Q16) | A mechanical act inside an agent run is logged as human. IDEA-121. |
| L-R1 to L-R3 | Lane rulings recorded in `slice-9-decision-rows.md`: lifecycle stage ids `gather` and `write`; `effective_policy` stays in `services/gates.py` with a re-export; agent audit label gap | `services/site_catalog.py`; `services/gates.py:136` | DECIDE (list) | Record only; code follows them. |
| R-150 to R-158 | Requirements of spec section 12, to enter `01-rigour.md` section Q | `docs/specs/slice-9-tiers-autonomy.md` section 12; guards in `tests/test_level_statement.py`, `tests/test_tier_caps.py`, `tests/test_press_session.py` | DECIDE (list) | Marked proposed until D1 to D6 are ruled. |
| Spec section 11 amendments | 84.6 (baseline is the level's profile), 84 items 4 and 5 (agent audit), 24 (tier above mode) | `modules/autonomy.py`, `services/gates.py` | DECIDE (list) | 84.6 is also in Q3. |

## 2. Summary

Rows: 8 numbered (163 to 170), 15 labelled rows and 3 labelled groups (L-R, R-150 to R-158, the spec amendments). 16 questions in 4 batches (they are numbered in the order of the table, so batches 3 and 4 are not in numeric order); the other 10 items are in one confirmation list. AMEND: D-X1, D-ATTR (both change what a lane built or planned). Not verified: the content of the lane reports (D-V*, D-C*, D-G*, L-R*); whether any test depends on the attribution in D-ATTR; whether R-150 to R-158 each have a guard test (the three named exist).

## 3. Batches

Four batches, 16 questions. Option text can be pasted into a questionnaire.

### Batch 1: the core settings (4 questions)

**Q1 (163, D1: tier names and the mapping).**
- A (recommended). Four tiers: `brief` and `deep` in `exploratory`, `pilot` in `pilot`, `systematic` in `systematic`. No new mode; decision 24 unchanged; a project with no tier is legacy.
- B. Three tiers (`brief` with options instead of `deep`). Fewer names; the disclosure statement cannot name the tier of protocol-lite and PRESS-lite.
- C. A new rigour mode `rapid`. Changes decision 24 and every preset and enforcement table; old projects cannot use it.
- Other.

**Q2 (164, D2: autonomy levels).**
- A (recommended). `attended` (default), `supervised` (independent agent session plus sampled third-session audit), `autonomous` (orchestrated run, verifier and auditor, trust ledger, deferred review, "not human-confirmed" labels).
- B. Two levels only (`attended`, `autonomous`). Loses the pilot case of a second agent seconding link confirmations under audit.
- C. Per-gate protocol setting only, no project-level level. No level statement, no ledger stop; weakening is a readiness gap in pilot.
- Other.

**Q3 (165, D3: which gates may go below `human` under `autonomous`; amends 84.6).** Today `AUTONOMOUS_FLOOR` is empty, so `autonomous` changes no policy.
- A (recommended). Move only gates whose declared floor is already below `human`: `hypotheses.lead_decide`, `hypotheses.register`, `experiments.freeze_unlock`, `mine.resolve`, `reference.link_confirm`, `import.resolution_confirm`, `writing.release`, each with an independent verifier and a platform-drawn sample. Keep human: PRESS confirmation, hold-out split draw, `manuscript.citation_confirm`, every other floor-`human` gate, protocol amendments that weaken a gate. Fill the floor table in a follow-up (IDEA-125).
- B. As A, and let an independent critic session confirm PRESS in `brief` and `deep`. Needs a floor change in the gate declaration (`services/human_queue.py:40`), a human-reviewed code change.
- C. Nothing moves; `autonomous` only orchestrates and leaves every gate to the deferred queue.
- Other.

**Q4 (166, D4: an agent's selection of a decision).**
- A (recommended). A labelled selection under `autonomous`, proposing session excluded, shown "agent-selected, not human-confirmed", never satisfying a rule that names a human (158). Representation in the design note of the lane that builds it (IDEA-125).
- B. No agent selection; `autonomous` only at `brief` and `deep`; `pilot` and `systematic` are `attended` or `supervised`.
- C. Agent selections count as human-equivalent once a deferred-review item is confirmed. Mixes the audit trail.
- Other.

### Batch 2: trust, promotion and miners (4 questions)

**Q5 (167, D5: trust thresholds).**
- A (recommended). `watch` above 5% overturned with at least 20 audited; `pause` above 10%; named constants (`services/gate_trust.py`); the run stops when any gate is at `pause`.
- B. As A, with the state computed from human labels only; agent labels never move a state to `ok`.
- C. Stricter: `pause` above 5% with at least 20 audited, no `watch` band.
- Other (give numbers).

**Q6 (168, D6: promotion).**
- A (recommended). By import into a new project at the deeper tier; records are re-verified; the brief stays immutable (builds on 161).
- B. In-place promotion by a new event type; contradicts 161 and the state-hash rule for old logs.
- C. No promotion; start the deeper study from scratch.
- Other.

**Q7 (169, D7: the researcher's categories and agent-proposed miner schemas).**
- A (recommended). Relax decision 120 for miner schemas under `brief`, `deep` and `autonomous`, with the label `agent-proposed schema` on the level statement and every row view; taxonomies stay the researcher's.
- B. No relaxation; a researcher ticks every proposed schema first.
- C. Relax for `brief` only.
- Other.

**Q8 (170, D8: independent review of a miner schema).**
- A (recommended). Under `supervised`, `autonomous` and `deep` a session and model other than the proposer's reviews the schema before the first run and judges its gold sample; admission stays human.
- B. As A, and allow audited admission by an independent judge after a measured overturn rate.
- C. No review below `supervised`.
- Other.

### Batch 3: validation and extraction (4 questions)

**Q9 (D-V3, who admits a miner).**
- A (recommended). Admission to the evidence layer stays a human act (`factory miner admit`) at every level; unadmitted rows are exploratory (R-87).
- B. Allow admission by an independent judge session at `autonomous` after a ruling on an overturn rate (the profile field `audited-judge-after-ruling` exists and is unused).
- C. Allow it now at `autonomous`, audited.

**Q10 (D-V4, "claims-only" miners in a brief).**
- A (recommended). Define it as miners whose use is admitted as evidence and whose fields are quote-bearing claim records; no free-text field; name the kinds in the spec and test it.
- B. Keep the present operational meaning only ("a use admitted as evidence") and do not extend it.
- C. Drop the restriction; a brief may run any miner within its caps.
- Other.

**Q14 (D-X1, one-pass extraction in `brief` and `deep`).** A work is final for extraction only after pass B has been opened (`services/extraction_agreement.py`), while the plan says "extract: 1 pass".
- A (recommended, as lane L15 was briefed). The plan carries the pass-B open as data (`StagePlan` second-pass flag, with the 1% sample) and the conductor starts it as a separate run in a separate session; no fold change; output labelled single-pass, no agreement figure.
- B. An explicit single-pass mode for exploratory tiers, so pass B is never opened. Changes extraction finality in the fold and needs a protocol field.
- C. Leave as is; the researcher opens pass B by hand in a brief.

**Q15 (D-X2, the last screening batch at the tier cap).** The cap is checked before a batch is claimed and batches are served whole (`SCREEN_BATCH = 10`), so brief's 40 may become up to 49.
- A (recommended). State the overshoot bound in the level statement; no change to batching.
- B. Trim the last batch so the cap is exact.
- C. Leave silent (not recommended; R-82 shortcuts must be disclosed).

### Batch 4: conductor, attribution and agent audit (4 questions)

**Q11 (D-C1, conductor events).**
- A (recommended). Five new system event types (`conductor.started`, `step_started`, `step_finished`, `paused`, `finished`), state derived from the log, no table; a hand-written event by a non-system actor is ignored.
- B. Keep the conductor state in a file outside the log; no new event types. Not traceable.
- C. Store state in a projection table; changes state hashes.

**Q12 (D-E1, PRESS review session).** The reviewer must differ from the protocol author's session.
- A (recommended). Required for `pilot`, `systematic` and any non-`attended` project; exploratory attended unchanged (as built).
- B. Required in every project, exploratory attended included.
- C. Not required; rely on the skill text.

**Q13 (D-G1, agent audit label).**
- A (recommended). Record it as `gate.audit_labelled` with an agent actor (the closing session is refused), counted apart from human labels in the ledger; amends 84 items 4 and 5.
- B. A new event type `gate.agent_audit_labelled`; cleaner to read, a new type and fold.
- C. No agent audit; only human labels count. Then `supervised` has no third-session audit.

**Q16 (D-ATTR, mechanical document acts).** `document.converted` and `document.conversion_failed` are written as `project.human_actor()` (`services/document_convert.py:695`, `:725`), so a conversion in an agent run counts as a human act.
- A (recommended). Record them under the `system` actor, after listing the callers and tests that rely on the present attribution (list not yet made, not verified).
- B. Record them under the calling agent's actor.
- C. Leave as is and exclude both event types from the human-confirmed count in the level statement.

### Confirmation list (one answer)

Recommended DECIDE as written, no real choice; one "approve" answer covers all 10 items: D-V1, D-V2, D-C2, D-C3, D-E2, D-E3, D-G2, L-R1 to L-R3, R-150 to R-158 (as proposed, in `01-rigour.md` section Q), and the spec section 11 amendments to 84 items 4 and 5 and to 24.

Notes for the apply step: D1 to D6 take numbers 163 to 168 only if no other row has used them (the numbers are provisional); D7 and D8 take the next free numbers; Q3 and Q13 amend decision 84 together; Q6 needs 161 decided first; Q4 needs 158 and 160 read together; the label rows `D-*` receive numbers when applied.
