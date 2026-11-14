# Wrap-up, lane A: the step miner `m-stage-steps` v1 (2026-11-14)

Exploratory: no calibration (see `STEPS-EXPLORATORY.md`). Everything below is computed from the pilot's events unless it says "my reading".

## What was done
- Spec `make_stage_steps_spec.py` -> `m-stage-steps-v1-spec.json`; registered on the first try (`a0b08aea4fe72586`); listed in the protocol for layer core, on demand (amendment `amend-stage-steps-2026-11-14.json`, protocol P@4566cae4). No refusals.
- Stage axis: the 9 stages of `m-stages` v1, as an enum field. Row key: stage + step order (enum "1" to "12", each with a quote).
- Deviation from the brief: the selector is the whole text of the core works (95), not "works with an `m-stages` row of mode automated/human-assisted". A mining session cannot read `m-stages` rows (only the mine tools are allowed), so the session decides which stages the paper's system carries out. Not done: restricting to the paper's cited `m-stages` passages.
- Dry run: 3 works, 51 rows, rows checked by me (quotes verbatim and anchored, no duplicate keys). No wording change was needed.
- Pass A (Haiku): 95 units closed (3 in the dry run, 92 in the production pass: 4 sessions in parallel, 23:42 to 00:58, no failures, no usage-limit stop). 1,352 rows over 95 works.
- Pass B (Sonnet): the platform's own sample drew 12 works (more than 10% because of its draw rule); all closed, 115 rows. Cost was not measured here.
- A2 (our own process documents) is NOT done yet: see the end.

## Rows by stage (pass A)
| Stage | Rows | Works with at least one step |
|---|---|---|
| ideation-hypothesis | 274 | 87 |
| implementation-execution | 255 | 71 |
| review-verification | 251 | 81 |
| literature-review | 163 | 61 |
| paper-writing | 130 | 47 |
| data-analysis | 119 | 49 |
| experiment-design | 100 | 49 |
| other | 53 | 24 |
| lab-automation | 7 | 4 |

Per work and stage: mean 2.9 steps, at most 12. Per work: median 13 rows, at most 39.

## Optional fields (filled, of 1,352 rows)
method 267 (20%), outputs 164 (12%), inputs 102 (8%), check 102 (8%), limits 58 (4%). Actor: automated 1,288, human-assisted 18, human 17, not-stated 29.

## Agreement of pass A and pass B (as the platform computes it)
0.580 over all rows, 0.978 over aligned rows. Read this with care: step numbers within a stage are not stable between two readings of the same paper (the key is stage plus step order), so rows often fail to align (IDEA-52, 53, 69). The figure that matters for quality will come from the researcher's gold sub-steps, not from this.

## Quality observations (my reading, a sample of 17 rows, not a measurement)
- Quotes are verbatim and anchored (the platform checks it).
- A few rows look placed in the wrong stage: "A TaskMemory module recursively traverses this tree, executing each node in dependency order" is filed under paper-writing; "SGHA then inserts the validated paper objects ... into a typed evidence multigraph" under literature-review; one step with a method but actor `not-stated`. About 3 of 17 sampled rows look doubtful. A calibration against gold labels would say how many.
- Some `step` quotes are only a stage heading ("paper drafting"), which says nothing about how it is done.

## My reading of how the stages are done (not a finding)
- Ideation and hypothesis generation, review and verification, and implementation and execution are the stages most papers describe in steps (87, 81 and 71 of 95 works). Lab automation is almost absent (4 works).
- Nearly all steps are automated (95%); papers rarely say how a step is checked (8%) or where it fails (4%). A comparison of how systems validate each step, which the improvement analysis needs most, will therefore rest on few papers per stage until `check` and `limits` are read more completely or the papers are read at full text by a stronger pass.
- Literature review has steps in 61 works; the steps that recur in the sample are retrieval of papers, summarising, and a novelty check against the literature; to be confirmed by grouping, which is the next step.

## Next steps (the researcher's or later lanes)
1. Gold sub-steps for a calibration sample and the calibration (the researcher's act); then tune and re-run if needed.
2. Group the steps of one stage into step types (the agent proposal in part 3 of the plan), starting with literature review, and register them if accepted.
3. Compare with our process: lane E's draft `docs/process/our-process-v0.*`, once it is checked.
4. The hub page for the miner exists (`miners/m-stage-steps.html`); a stage page is part 5 of the plan.
