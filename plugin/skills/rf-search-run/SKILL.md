---
name: rf-search-run
description: Use when the question, seeds and protocol exist and the primary database search must be run: search_run per planned query, search_slice for a capped PubMed query, the search report, then dedup.
stage: [gather]
---

# rf-search-run

Runs the primary search of a ready protocol: the planned queries, one per source, then the report
and the merge of duplicates. It records nothing of its own and calls no model; the platform runs
the sources, archives every page and computes every count. Citation chasing after screening is
`rf-search`.

## Preconditions

Call `project_status` and read `stage`, `protocol`, `question`, `seeds` and `blocking`.

- The question is recorded (`question_view`; scoping with `rf-develop`, `rf-frame`).
- Seeds are added (`seed_list`; `seed_add` takes the researcher's list, not one you invent) and
  the probe has run (`rf-probe`, `probe_run`).
- The protocol is recorded and ready, with its search plan (`protocol_view`; `rf-protocol`). In
  `pilot` and `systematic` the PRESS review is confirmed by the researcher; that confirmation is
  theirs (`factory protocol confirm-press`). Read any `blocking` line of `project_status` aloud,
  for example a protocol with no full-text screening plan.
- In `exploratory` mode no protocol gate binds and a search reply carries a notice saying so.
  Report that notice as it is; such a search is not part of a registered protocol.

## Procedure

1. Read the planned queries from `protocol_view`: source, query text, kind and filters.
2. For each planned query call `search_run` with `source`, `query`, `kind`, `filters` exactly as
   planned, and your `role`, `model` and `skill`. Keep `purpose` as `search`. Run one source at a
   time and read each reply: `run_id`, `status`, `reported_count`, `retrieved_count`, `new_works`,
   `note`.
3. A run that is `partial` or `failed` is reported as it is, with its note. To continue it call
   `search_run` again with `resume_run` set to that run and the same `source`, `query`, `kind`.
4. A PubMed run with note `esearch-cap` is split by date: call `search_slice` with `query_id`
   and without `run` to read the plan (the slices and PubMed's counts), then with `run` set to
   register and run each slice. In `pilot` and `systematic` the slices are not planned queries:
   pass a `deviation_id` recorded with `protocol_deviation`, which is the researcher's decision.
5. A query the protocol does not plan is refused in `pilot` and `systematic`. Report the refusal;
   do not reword the query to pass the gate. A change of plan is `protocol_amend` after the
   researcher agrees, or a deviation.
6. Call `report_search` and report the registered queries and what each retrieved, any shortfall
   and any `notice`, as returned.
7. Call `dedup_run` so that works found by several sources are merged before screening.
   `dedup_merges` lists the merges with their rule; `merge_revert` undoes a wrong one, stating
   why. Version pairs the platform cannot settle wait for the researcher
   (`factory dedup pairs`, `factory dedup pair`); do not decide them.
8. Return to `rf-run` for the next step. Screening needs the calibration set drawn by the
   researcher (`factory calibrate draw`); it is listed in `human` of `project_status`.

## Never

- Never type a count, a hash or a PRISMA figure: read them from the reply or the report.
- Never name a held-out seed or look for one; withheld identifiers stay withheld.
- Never change a planned query, a filter or a limit to obtain more or fewer works.
- Never decide a human gate: PRESS confirmation, a deviation, a version pair, the calibration
  draw.

## Done when

Every planned query has a complete run (or a reported shortfall), `report_search` and `dedup_run`
have been called, and the researcher has the replies, notices and open `human` items.
