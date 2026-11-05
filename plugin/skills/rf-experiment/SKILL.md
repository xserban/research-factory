---
name: rf-experiment
description: Use when a registered or drafted experiment hypothesis needs a pre-registered experiment design, or planned runs must be registered against a frozen design, in a Claude Code session that did not read a screening or extraction pass.
---

# rf-experiment

Writes the experiment design that tests a hypothesis, and registers the planned runs of a design
the researcher has frozen. The design is fixed by hash before any result exists, so everything that
decides the outcome goes into it now. You propose; you never freeze, unlock, run, accept or record.
The platform computes the design version `E@`, every run configuration and every count.

## Independence

- Use a Claude Code session that has not run a screening, extraction or contribution pass. The
  platform refuses these tools to a session that did; do not work around the refusal.
- You do not freeze or unlock a design, accept a baseline, record a deviation or submit a result.
  Those are the researcher's steps on the command line (`factory experiments`, `factory runs`).
  The tools you have cannot do them; if one is refused, report the reason and stop.
- Do not read or ask for the held-out seeds, the audit samples or the answer key.

## Procedure

1. Read the hypothesis with `hypothesis_view`. Do not design for a hypothesis whose state is
   evaluated, abandoned or superseded, nor for a literature hypothesis.
2. Draft the design with `experiment_design`:
   - one factor: the key that changes between baseline and treatment, with both values; the
     baseline value must equal the base configuration's value for that key;
   - the fixed configuration (`base_config`), as scalars (write a decimal as a string);
   - the plan's minimum number of seeds, unique, and a primary universe inside the multiverse
     axes you declare (at most 256 universes);
   - ablations that each change exactly one existing key of the full configuration;
   - a positive and a negative control, each with its expected result, and none touching the factor;
   - baselines as final evidence rows (`row_key`) whose comparability values match the
     hypothesis conditions, each with a tolerance and its kind;
   - datasets with split roles (`dev`, `confirmatory`; one confirmatory dataset per name at
     most), with content hashes;
   - metrics with exactly one primary, the hypothesis metric;
   - the budget (GPU-hours, per-run cap, maximum runs) and the code and environment references.
   Do not state an id, a version or a configuration; the answer returns `E@`.
3. Amend an unfrozen design with `amend_of` and a `reason`, saying whether the change is
   `semantic`. After the researcher freezes it nothing can change: report what you would change
   and stop.
4. Read the design back with `experiment_view`. It shows the state, the budget used, the
   baselines and any deviation; it shows no result values and no nonce.
5. For a frozen design, register planned runs with `xrun_register`, one per cell: the primary
   cells (treatment and baseline on the confirmatory split, every seed), the baseline
   reproductions (`reproduction:<row_key>`), the ablations and the controls. The confirmatory
   cells wait for the researcher's unlock. A run outside the planned cells is accepted on the
   `dev` split only and is recorded as exploratory.
6. Never type a result. Results come from the runner through the researcher's `factory runs
   record`. Check progress with `xrun_list`.
7. State any analysis you did after seeing results as exploratory, and never as the test.

## Stopping and human steps

Freezing, unlocking, accepting a baseline that did not reproduce, recording a deviation and
ingesting results are for the researcher. Ask for them by name and wait. If a call is refused,
report the reason verbatim and stop; do not retry with altered input to obtain a different answer.

## Tool arguments

Every tool call also takes `project` (the project slug), `role`, and `model` (your own model
id), alongside `skill`, which is the bare skill name. The platform computes the skill hash; do
not send one. Pass `rf-experiment` as `skill`.

## Done when

The hypothesis has a design that passes validation, the researcher has seen its `E@`, and every
run the researcher asked for is registered against a planned cell, or the reason it is not has
been reported.
