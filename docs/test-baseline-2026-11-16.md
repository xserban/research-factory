# Test baseline, 2026-11-16

Source: a sweep of every test file on `main` (4775a7e2), one file per process, default markers (`ops/night-2026-11-15/sweep.txt`). Each failing file was rerun once, alone, with `-x -q --tb=short` in the worktree `status-refresh` (same tree as main); the cause lines below are from that rerun. `-x` stops at the first failure, so the test named is the first failing one; the count of failing tests is the sweep's. The rerun shell exported `FACTORY_ROOT` and `FACTORY_PLUGIN_DIR`. Nothing was bisected; "likely introducing merge" is read from `git log --since=2026-11-14` on the module under test and is a lead, not a finding. IDEA-65 is in `docs/backlog.md`; the earlier per-file baseline is `docs/test-baseline-2026-11.md` (2026-11-12), which lists most of these files as "feature not finished" or "open".

## Summary

- 542 test files: 515 do not fail (477 pass, 38 are fully deselected by the default markers); 27 files fail with 44 tests in all.
- Classes of the 27 failing files: feature not finished, open since 2026-11-12 (14 files: acceptance_regions, cli_evidence, evidence_check_methods, forged_events, hypotheses, hypothesis_review, miner_kinds, portfolio, progress, ranking, region_evaluate, slice6_surfaces, import_admit, passes); regression listed in IDEA-65 (commit); regression of a fix (hosting, old_log_replay); new since 2026-11-14 (http, pubmed, mcp_work_params_guard, site_main_hub_pages, views_b_merges, watch_config, window_baseline); environment (config); stale test or skill text (plugin); flaky (mcp_decisions).
- Listed in IDEA-65 or its 2026-11-12 document: 20 files. New: 7 (http, pubmed, mcp_work_params_guard, site_main_hub_pages, views_b_merges, watch_config, window_baseline). Two listed files fail for a new cause: `test_plugin` (was environment) and `test_hosting`/`test_old_log_replay` (fixed on 2026-11-12, broken again).

## Table

"Listed" is IDEA-65 or `docs/test-baseline-2026-11.md`. Size: S under an hour, M a few hours, L a feature owner's decision.

| File | Failing | Cause (first failure on rerun) | Class | Listed | Likely introducing merge | Suggested fix, size |
|---|---|---|---|---|---|---|
| test_acceptance_regions | 2 (`acceptance_01_cites_rule` first) | `cites` rule returns `zhou2020-negative` where the test expects `outside-00000001`; scale case yields 0 | feature not finished (regions) | yes | not touched since 11-14; open since 11-12 | region owner decides rule or test, M |
| test_cli_evidence | 5 (`md_is_default_and_has_group_sections`) | evidence CLI exits 1 with empty stderr under a monkeypatched `evidence_report` (signature `expect=, include_notice_affected=`) | feature not finished / stale fixture | yes | not touched since 11-14 | read the CLI error, align the patched signature, S |
| test_commit | 1 (`a_deleted_event_file_refuses_the_job`) | `DID NOT RAISE FactoryValidationError` | real bug candidate | yes ((c) in IDEA-65) | none since 11-14; passed at e696e33, bisect unfinished | finish the bisect; hosting event removed with the only event file, M |
| test_config | 1 (`settings_precedence`) | `Settings` equality fails: the shell's `FACTORY_PLUGIN_DIR` leaks into `Settings.load` | environment | yes | n/a | run with a clean environment (or the test clears the variable), S |
| test_evidence_check_methods | 1 (`agent_view_hides_audit_rate_and_flag`) | rule `audit-reported-to-researcher` absent from the agent view's list (0 not 1) | feature not finished / stale | yes | not touched since 11-14 | evidence owner confirms the rule is meant to show, S |
| test_forged_events | 1 (`abandon_and_conclusion_by_an_agent_do_not_fold`) | `hypothesis.concluded` by a human does not fold | feature not finished (hypotheses) | yes | not touched since 11-14 | hypothesis owner, M |
| test_hosting | 1 (`unhosted_project_unchanged`) | state hash `e58aa6...` instead of `277c8d...` | real bug (regression) | yes (fixed 917e9eb, now broken again) | `registered_files` (b3258caf, hub-records, via `merge-hub` a0466515, 2026-11-14) is not in `OMITTED_WHEN_EMPTY` (`index/index.py`) | add `registered_files` to the set, S |
| test_http | 1 | rate-limit table has an extra host `eutils.ncbi.nlm.nih.gov: 0.34` | stale test | no | `pubmed` merge cb447f27 (eebe2d4f, `sources/http.py`) | add the host to the expected table, S |
| test_hypotheses | 1 (`conclusion_needs_an_evaluation_and_a_human`) | conclusion text is `None` | feature not finished | yes | not touched since 11-14 | hypothesis owner, M |
| test_hypothesis_review | 1 (`nothing_waiting_and_no_second_serving`) | a second serving is returned | feature not finished | yes | not touched since 11-14 | hypothesis owner, M |
| test_import_admit | 1 (`failed_admission_can_be_retried`) | `DID NOT RAISE FactoryValidationError` | feature not finished; also fails on the `pubmed-tests` base | yes | not touched since 11-14 | import owner, M |
| test_mcp_decisions | 1 (`suggest_scrubs_a_held_out_seed...`) | `10.1000/p2` appears in the output instead of `[withheld]` | flaky (two writers share a `FixedClock`); also fails on the `pubmed-tests` base | yes (flaky) | n/a | give the writers distinct clocks, S; check the assertion is not a real leak, S |
| test_mcp_work_params_guard | 1 | guard map lacks `flow_trail: {'work_id'}` | new tool not in the guard map, or an unguarded work id (IDEA-66) | no | `flow-transparency` (9ad08e1a added `flow_trail`, 11-14) | resolve the id through `work_ref` in `flow_trail` and add it to the map, S |
| test_miner_kinds | 1 (`title_kind_accepts_exact_and_rejects_unknown`) | an unknown work title is accepted (`work-not-found` not raised) | feature not finished / real bug | yes | not touched since 11-14 | miner owner, S to M |
| test_old_log_replay | 1 | same state hash change as `test_hosting` | real bug (regression) | yes (fixed 917e9eb) | same as `test_hosting` | same fix, S |
| test_passes | 1 (`no_duplicate_membership_queries`) | membership queries remain in `extraction.py` and `screening.py` outside `services/passes.py` | structural rule | yes ((d)) | `multi-miner-session` (d65e0dd8, 11-16) touched `extraction.py` again | move the queries to `passes.py`, M |
| test_plugin | 1 (`rf_write_names_its_tools...`) | `rf-write/SKILL.md` names `draft_release`, test says it must not | stale test or skill text | listed as environment, cause now different | skill unchanged since 11-12 (5aa4da2c, IDEA-61 catalog mentions) | decide whether the skill may name `draft_release`, then edit one, S |
| test_portfolio | 1 (`counts_equal_the_projects_own_reports`) | human queue `assignee` is `None`, test expects `obd` | feature not finished | yes | not touched since 11-14 | portfolio owner, S |
| test_progress | 1 (`dashboard_state_has_a_progress_panel`) | running op has `done` 0, test expects 4 | feature not finished | yes | not touched since 11-14 | progress owner, S |
| test_pubmed | 2 | wrong assertions (e.g. `'2' == '200'`) | stale test | no | `pubmed` merge cb447f27 | already fixed on branch `pubmed-tests` (673fb9b5), merge it, S |
| test_ranking | 7 | writer refuses fixture `ranking_id` (must be `rnk_` + ULID) and a count given as a string | stale fixture; one test also needs the tokenizer model (not installed) | yes | not touched since 11-14 | fix fixtures to valid ids, M |
| test_region_evaluate | 1 | same `cites` case as `test_acceptance_regions` | feature not finished (regions) | yes | not touched since 11-14 | with the regions owner, M |
| test_site_main_hub_pages | 1 (`project_sidebar_groups...`) | sidebar has a new group `updates` | stale test | no | `updates-page` (5015ff90, 11-15) | add `updates` to the expected list, S |
| test_slice6_surfaces | 1 (`hypothesis_view_carries_the_evaluation`) | `KeyError: 'outcome'` | feature not finished | yes | not touched since 11-14 | hypothesis owner, S |
| test_views_b_merges | 4 | row count 5, expected 6 (views vs report after a real merge) | unclear: stale test or real bug in absorbed-work handling | no (passed on 2026-11-12) | probably `flow-transparency` (b0a4a766, f20f2c08: absorbed works leave the canonical queue; 0a97e740) | read which row went missing, then decide, M |
| test_watch_config | 3 (`records_amendment_with_plan`) | `watch_plan.sources[0].mode: source has no window filter` for `openalex` with mode `window` | stale fixture or real bug (window sources not supplied) | no | watch work: 12ae9e7c (decision 127), 1fcbadf5, merged in `updates-page` 5015ff90 | check `window_sources` in the test's mock sources against `protocol_rules._watch_plan_errors`, S to M |
| test_window_baseline | 1 (`full_replay_request_refused_for_agent`) | same refusal as `test_watch_config` | same | no | same | same fix, S |

## Real bugs (likely product defects)

1. `registered_files` missing from `OMITTED_WHEN_EMPTY`: an old log's state hash changes (`test_hosting`, `test_old_log_replay`). Regression of the 917e9eb fix, from b3258caf. Fix is one line.
2. `test_commit::test_a_deleted_event_file_refuses_the_job`: IDEA-65 open question (c), unresolved.
3. `flow_trail` takes a work id without the NFC resolution (`test_mcp_work_params_guard`), unless the guard map is simply out of date.
4. `test_miner_kinds`: the title kind accepts an unknown work (open since 11-12; the test or the kind is wrong).
5. Open for the owner to classify as product or test: `watch_config` and `window_baseline` (window refusal for `openalex`), `views_b_merges` (row count after a merge).

## Stale tests

`test_http` (PubMed host in the rate table), `test_pubmed` (two assertions; fixed on `pubmed-tests`, 673fb9b5), `test_site_main_hub_pages` (`updates` group), `test_ranking` (fixture ids), `test_plugin` (skill text versus test), `test_passes` (structural rule; behaviour correct), `test_cli_evidence`, `test_evidence_check_methods`, `test_portfolio`, `test_progress` (fixtures behind the feature; owners decide).

## Environment and flaky

- Environment: `test_config` fails only when the shell exports `FACTORY_ROOT` or `FACTORY_PLUGIN_DIR` (as the rerun shell did). `test_ranking` has one test that needs the tokenizer model.
- Flaky: `test_mcp_decisions` (two writers share a `FixedClock`; the failing assertion on this rerun is the held-out DOI scrub, which fails on the `pubmed-tests` base too).
- Also failing on the `pubmed-tests` base: `test_import_admit::test_failed_admission_can_be_retried`.

## Not covered

Network-marked tests are deselected by default. No file was run twice, so flakiness beyond `test_mcp_decisions` is not excluded. The causes are the first failure of each file only.
