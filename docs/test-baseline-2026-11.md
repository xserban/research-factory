# Test baseline, 2026-11

Every file of `platform/tests/` (482) run one at a time, two in parallel, 360 s timeout, `-m 'not network'` (the `slow` suites included), with the shared venv. Two runs: **main** at 5bc9879, and **branch** `test-baseline` at 1cb71eb after the fixes. The main run had `FACTORY_ROOT` and `FACTORY_PLUGIN_DIR` exported by the shell; its failing files were rerun without them, and the branch run was made without them. Logs are in the worktree's `scratchpad/` (not in git). IDEA-65 in `docs/backlog.md` holds the follow-ups.

## Totals

| Run | Files | Files failing | Tests passed | Tests failed | Skipped |
|---|---|---|---|---|---|
| main 5bc9879 | 482 | 78 | 6456 | 183 | 4 |
| branch 1cb71eb | 482 | 22 | 6601 | 38 | 4 |

Two files (`test_living_network`, `test_watch_network`) hold only network tests; with network tests skipped they collect nothing (exit 5) and are not counted as failing.

Classes of the failing files on main: stale 46; feature not finished 19; product bug 4; stale (judgement) 3; environment 2; open (regression) 1; open question 1; flaky 1; product (rule) 1. *Stale*: the product changed on purpose and the test was not updated. *Feature not finished*: the researcher's ruling (2026-11-12) that ranking, hypotheses, regions and the other remaining features are not finished; recorded, not fixed.

## Files that failed on main

Tests, passed and failed are per file; main / branch.

| File | Tests | Passed | Failed | Class | Cause | Branch |
|---|---|---|---|---|---|---|
| `test_hosting.py` | 36 / 36 | 35 / 36 | 1 / 0 | product bug | same state-hash cause as `test_old_log_replay` | fixed (917e9eb) |
| `test_old_log_replay.py` | 1 / 1 | 0 / 1 | 1 / 0 | product bug | reference-layer tables (f06b64b) not in `OMITTED_WHEN_EMPTY`: an old log's state hash changed | fixed (917e9eb) |
| `test_sequencing.py` | 15 / 15 | 14 / 15 | 1 / 0 | product bug | runner and pipeline minted events outside the write lock (a hosted project refuses them with `OrderingError`) | fixed (bcd8dfc) |
| `test_snowball_forward.py` | 11 / 11 | 10 / 11 | 1 / 0 | product bug | `FORWARD_ROUND_RE` let an `openalex:` text carry a topic filter; its docstring and the only producer say it has none (b7bf7b0). Run after the fix in the main run; 1 failure confirmed against main's source | fixed (092254f) |
| `test_passes.py` | 11 / 11 | 10 / 10 | 1 / 1 | product (rule) | `screening._is_human_session` (f984579) is a membership query outside `services/passes.py`; behaviour correct | open: move to passes.py |
| `test_commit.py` | 31 / 31 | 30 / 30 | 1 / 1 | open (regression) | deleting the only event file also deletes the hosting event, so the job skips the project instead of refusing; passed at e696e33, bisect not finished | open |
| `test_acceptance_extraction.py` | 11 / 11 | 10 / 11 | 1 / 0 | stale | re-runs the earlier acceptance suites; failed through `test_acceptance_screening` | fixed (b9f5fbe) |
| `test_acceptance_inbox.py` | 14 / 14 | 13 / 14 | 1 / 0 | stale | dedup-gate fixture collision | fixed (ecc2662) |
| `test_acceptance_protocol.py` | 8 / 8 | 4 / 8 | 4 / 0 | stale | selected decision required in pilot (8290c90); `status_view` passes `agent` | fixed (b9f5fbe) |
| `test_acceptance_screening.py` | 1 / 1 | 0 / 1 | 1 / 0 | stale | 'Study NN' works merge under the dedup gate; distinct authors | fixed (b9f5fbe) |
| `test_acceptance_slice1.py` | 22 / 22 | 13 / 21 | 8 / 0 | stale | selected decision required (8290c90); dedup-gate collision | fixed (b9f5fbe, ecc2662) |
| `test_amendment_lineage.py` | 21 / 21 | 18 / 21 | 3 / 0 | stale | dedup-gate fixture collision | fixed (ecc2662) |
| `test_check_composition.py` | 10 / 10 | 7 / 10 | 3 / 0 | stale | reference rule order lacked later rules (appraisal) | fixed (b9f5fbe) |
| `test_check_drafts.py` | 15 / 15 | 12 / 15 | 3 / 0 | stale | verdict span minimum 12 characters (07033af, PF ruling 2) | fixed (1cb71eb) |
| `test_cli_gates.py` | 8 / 8 | 7 / 8 | 1 / 0 | stale | dedup-gate fixture collision (pass session never joined) | fixed (ecc2662) |
| `test_decision_trace.py` | 2 / 2 | 1 / 2 | 1 / 0 | stale | trace label is `<level> decision: <subject>` (36899d0) | fixed (b9f5fbe) |
| `test_draft_audit.py` | 23 / 23 | 21 / 23 | 2 / 0 | stale | span minimum; `DraftAuditReport.all_*` (18e0696, 900e815) | fixed (1cb71eb) |
| `test_draft_release.py` | 21 / 21 | 18 / 21 | 3 / 0 | stale | span minimum; live supported sentence (cc3a08f) | fixed (1cb71eb) |
| `test_draft_status.py` | 15 / 15 | 13 / 15 | 2 / 0 | stale | span minimum | fixed (1cb71eb) |
| `test_draft_systematic.py` | 13 / 13 | 4 / 13 | 9 / 0 | stale | selected decision required; release needs a live supported sentence (cc3a08f) | fixed (1cb71eb) |
| `test_draft_verify.py` | 34 / 34 | 31 / 34 | 3 / 0 | stale | span minimum; unit `flags` (921c057); writer refuses a missing blob (a67d972) | fixed (1cb71eb) |
| `test_drafts_b_cli_mcp.py` | 20 / 20 | 16 / 20 | 4 / 0 | stale | span minimum; verifier reads no status (70b3d98); `draft verify` asks for spans (bf5c7d0) | fixed (1cb71eb) |
| `test_fulltext_model.py` | 8 / 8 | 7 / 8 | 1 / 0 | stale | `LAB_LIBRARY` has no quality of its own (c52130a) | fixed (aea97fa) |
| `test_fulltext_screen_record.py` | 19 / 19 | 17 / 19 | 2 / 0 | stale | dedup-gate fixture collision | fixed (ecc2662) |
| `test_import_mcp.py` | 8 / 8 | 6 / 8 | 2 / 0 | stale | dedup-gate fixture collision (pass session never joined) | fixed (ecc2662) |
| `test_importlist_source.py` | 10 / 10 | 9 / 10 | 1 / 0 | stale | importlist entries keep the abstract (9d84d59, PD-4) | fixed (aea97fa) |
| `test_library_sources.py` | 10 / 10 | 9 / 10 | 1 / 0 | stale | grey methods after library-import (decision 75 item 2) | fixed (aea97fa) |
| `test_mcp_concepts.py` | 7 / 7 | 6 / 7 | 1 / 0 | stale | `concept_list` added (f6d6541, PROJECT_READ) | fixed (f026ea9) |
| `test_mcp_document.py` | 5 / 5 | 4 / 5 | 1 / 0 | stale | dedup-gate fixture collision (pass session never joined) | fixed (ecc2662) |
| `test_mcp_experiments.py` | 6 / 6 | 5 / 6 | 1 / 0 | stale | `experiment_list` added (b299847, PROJECT_READ) | fixed (f026ea9) |
| `test_mcp_fulltext.py` | 5 / 5 | 4 / 5 | 1 / 0 | stale | `by_route` counts the `lab-library` route (c52130a) | fixed (aea97fa) |
| `test_mcp_hypotheses.py` | 6 / 6 | 5 / 6 | 1 / 0 | stale | `lead_list`, `hypothesis_list` added (b299847, PROJECT_READ) | fixed (f026ea9) |
| `test_mcp_living.py` | 3 / 3 | 2 / 3 | 1 / 0 | stale | dedup-gate fixture collision (pass session never joined) | fixed (ecc2662) |
| `test_mcp_protocol.py` | 13 / 13 | 9 / 13 | 4 / 0 | stale | selected decision required (8290c90) | fixed (b9f5fbe) |
| `test_mcp_references.py` | 26 / 26 | 18 / 26 | 8 / 0 | stale | reference-layer tools registered inside the pinned block (1962194); prisma patch target moved to `agent_view` (a23f2eb); the 6 pass-session cases were the dedup collision | fixed (f026ea9, ecc2662) |
| `test_mcp_screening.py` | 13 / 13 | 7 / 13 | 6 / 0 | stale | dedup-gate fixture collision: the session never joins a pass, so nothing is refused | fixed (ecc2662) |
| `test_mcp_server.py` | 3 / 3 | 2 / 3 | 1 / 0 | stale | `page_*` tools added (site hub); `watch_run` moved | fixed (f026ea9) |
| `test_methods.py` | 9 / 9 | 8 / 9 | 1 / 0 | stale | methods names only screening models (889450b) | fixed (b9f5fbe) |
| `test_onion.py` | 24 / 24 | 22 / 24 | 2 / 0 | stale | fixture merge id `mrg_1` not a ULID; readers validate `DedupMerged` | fixed (48ef86e) |
| `test_onion_merges.py` | 3 / 3 | 1 / 3 | 2 / 0 | stale | fixture merge id `mrg_1` | fixed (48ef86e) |
| `test_prisma.py` | 20 / 20 | 19 / 20 | 1 / 0 | stale | grey methods after library-import (decision 75 item 2) | fixed (aea97fa) |
| `test_probe.py` | 33 / 33 | 32 / 33 | 1 / 0 | stale | an arXiv-only seed has an OpenAlex probe key (9bef7c0) | fixed (b9f5fbe) |
| `test_question.py` | 28 / 28 | 27 / 28 | 1 / 0 | stale | `bind_ids` called inside the counted window | fixed (b9f5fbe) |
| `test_region_snapshot.py` | 27 / 27 | 25 / 27 | 2 / 0 | stale | fixture merge id `mrg_1` | fixed (48ef86e) |
| `test_reports_surfaces.py` | 15 / 15 | 14 / 15 | 1 / 0 | stale | dedup-gate fixture collision (pass session never joined) | fixed (ecc2662) |
| `test_screening_next.py` | 25 / 25 | 10 / 25 | 15 / 0 | stale | fixture works 'Random 1' and 'Random 10' fuzzy-merge (score 94 > 92); screening waits for dedup since 69528b3 | fixed (ecc2662) |
| `test_screening_record.py` | 12 / 12 | 1 / 12 | 11 / 0 | stale | dedup-gate fixture collision (as `test_screening_next`) | fixed (ecc2662) |
| `test_source_base.py` | 29 / 29 | 28 / 29 | 1 / 0 | stale | query purpose `grey` (489e70d) | fixed (aea97fa) |
| `test_task_kinds.py` | 5 / 5 | 4 / 5 | 1 / 0 | stale | `appraise_a`/`appraise_b` kinds (5643492) | fixed (aea97fa) |
| `test_writing_acceptance.py` | 1 / 1 | 0 / 1 | 1 / 0 | stale | span minimum | fixed (1cb71eb) |
| `test_writing_render.py` | 20 / 20 | 18 / 20 | 2 / 0 | stale | span minimum | fixed (1cb71eb) |
| `test_writing_scale.py` | 1 / 1 | 0 / 1 | 1 / 0 | stale | scale row keys exceed the `rk_` pattern | fixed (1cb71eb) |
| `test_acceptance_intuition.py` | 15 / 15 | 14 / 15 | 1 / 0 | stale (judgement) | same separation rule | fixed (c78518d), owners to confirm |
| `test_drafts_cli_mcp.py` | 12 / 12 | 9 / 12 | 3 / 0 | stale (judgement) | briefing and trace import drafts (not evidence outputs); `draft_list`/`draft_repin`/`draft_reorder` added | fixed (c78518d), owners to confirm |
| `test_intuition_separation.py` | 9 / 9 | 7 / 9 | 2 / 0 | stale (judgement) | briefing/pipeline import the layer; five modules name layer tables as words only (no SQL); none is an evidence output | fixed (c78518d), owners to confirm |
| `test_config.py` | 6 / 6 | 5 / 6 | 1 / 0 | environment | the shell exports `FACTORY_ROOT`/`FACTORY_PLUGIN_DIR`; passes without them | passes with a clean environment |
| `test_plugin.py` | 34 / 34 | 31 / 34 | 3 / 0 | environment | `FACTORY_PLUGIN_DIR` points at the main checkout's (older) plugin | passes with a clean environment |
| `test_mcp_decisions.py` | 7 / 7 | 6 / 7 | 1 / 0 | flaky | two writers share a `FixedClock`: suggestion and selection get same-millisecond ids and the fold may order the selection first (about half of runs) | open: test design |
| `test_import_prisma.py` | 6 / 6 | 5 / 5 | 1 / 1 | open question | `version_pair_merges`, `identical_title_merges` (4c4e885, IDEA-56) are always dumped, unlike `stop_rule`/`not_screened_stop`, which are left out when unused; product convention or stale test? | open |
| `test_acceptance_regions.py` | 46 / 46 | 43 / 43 | 2 / 2 | feature not finished | cites rule returns a different work; scale yields 0 | open |
| `test_cli.py` | 23 / 23 | 20 / 21 | 3 / 2 | feature not finished | status line text; restore lists a `needs re-import` item | open |
| `test_cli_evidence.py` | 11 / 11 | 6 / 6 | 5 / 5 | feature not finished | evidence CLI output | open |
| `test_contribution_schema.py` | 10 / 10 | 9 / 9 | 1 / 1 | feature not finished | `_omit_absent_review` KeyError on an old amendment | open |
| `test_core_works.py` | 14 / 14 | 12 / 12 | 2 / 2 | feature not finished | agent event without `input_blob`; a forward-option case validates | open |
| `test_develop_render.py` | 10 / 10 | 8 / 8 | 2 / 2 | feature not finished | agent event without `input_blob`; `version` >= 1 | open |
| `test_evidence_check_methods.py` | 17 / 17 | 16 / 16 | 1 / 1 | feature not finished | agent view count | open |
| `test_forged_events.py` | 46 / 46 | 45 / 45 | 1 / 1 | feature not finished | `hypothesis.concluded` by a human does not fold | open |
| `test_hypotheses.py` | 15 / 15 | 14 / 14 | 1 / 1 | feature not finished | conclusion text not set | open |
| `test_hypothesis_review.py` | 9 / 9 | 8 / 8 | 1 / 1 | feature not finished | a second serving is returned | open |
| `test_import_admit.py` | 15 / 15 | 14 / 14 | 1 / 1 | feature not finished | failed admission retry not refused | open |
| `test_miner_kinds.py` | 11 / 11 | 10 / 10 | 1 / 1 | feature not finished | title kind accepts an unknown work | open |
| `test_portfolio.py` | 9 / 9 | 8 / 8 | 1 / 1 | feature not finished | human queue `assignee` | open |
| `test_progress.py` | 11 / 11 | 10 / 10 | 1 / 1 | feature not finished | progress panel state | open |
| `test_ranking.py` | 14 / 14 | 7 / 7 | 7 / 7 | feature not finished | 5: fixture `ranking_id` not `rnk_` + ULID; 1: environment (the ranking tokenizer model is not installed) | open |
| `test_region_evaluate.py` | 21 / 21 | 16 / 20 | 5 / 1 | feature not finished | `cites` min-k returns a different work (other 4 fixed by 48ef86e) | open |
| `test_region_scale.py` | 1 / 1 | 0 / 0 | 1 / 1 | feature not finished | scale yields 0 members | open |
| `test_screening_ranked.py` | 17 / 17 | 13 / 14 | 4 / 3 | feature not finished | amendment refused: `semantic` must be true | open |
| `test_slice6_surfaces.py` | 9 / 9 | 8 / 8 | 1 / 1 | feature not finished | hypothesis view lacks `outcome` | open |

## Every file

Main and branch results per file (P passed, F failed, S skipped; `deselected` means the file holds only network tests).

| File | Main | Branch |
|---|---|---|
| `document/test_anchorise.py` | 25 P | 25 P |
| `document/test_anchors.py` | 52 P | 52 P |
| `document/test_anchors_bib.py` | 17 P | 17 P |
| `document/test_converter_contract.py` | 7 P | 7 P |
| `document/test_eprint.py` | 28 P | 28 P |
| `document/test_latexml_cites.py` | 11 P | 11 P |
| `document/test_latexml_escape.py` | 9 P | 9 P |
| `document/test_latexml_html.py` | 24 P | 24 P |
| `document/test_normalise.py` | 3 P | 3 P |
| `document/test_optional_converters.py` | 20 P, 2 S | 20 P, 2 S |
| `test_acceptance_acquisition.py` | 7 P | 7 P |
| `test_acceptance_document.py` | 5 P | 5 P |
| `test_acceptance_evidence.py` | 8 P | 8 P |
| `test_acceptance_extraction.py` | 10 P, 1 F | 11 P |
| `test_acceptance_fulltext.py` | 4 P | 4 P |
| `test_acceptance_fulltext_screening.py` | 6 P | 6 P |
| `test_acceptance_import.py` | 8 P | 8 P |
| `test_acceptance_inbox.py` | 13 P, 1 F | 14 P |
| `test_acceptance_intuition.py` | 14 P, 1 F | 15 P |
| `test_acceptance_lineage.py` | 20 P | 20 P |
| `test_acceptance_living.py` | 15 P | 15 P |
| `test_acceptance_miners.py` | 3 P | 3 P |
| `test_acceptance_protocol.py` | 4 P, 4 F | 8 P |
| `test_acceptance_rebuild.py` | 1 P | 1 P |
| `test_acceptance_references.py` | 4 P | 4 P |
| `test_acceptance_regions.py` | 43 P, 2 F, 1 S | 43 P, 2 F, 1 S |
| `test_acceptance_screening.py` | 0 P, 1 F | 1 P |
| `test_acceptance_slice1.py` | 13 P, 8 F, 1 S | 21 P, 1 S |
| `test_acceptance_supplementary.py` | 4 P | 4 P |
| `test_agreement.py` | 18 P | 18 P |
| `test_amendment_lineage.py` | 18 P, 3 F | 21 P |
| `test_amendments.py` | 16 P | 16 P |
| `test_arxiv.py` | 41 P | 41 P |
| `test_audit.py` | 19 P | 19 P |
| `test_audit_core.py` | 12 P | 12 P |
| `test_audit_top_up.py` | 9 P | 9 P |
| `test_autonomy.py` | 2 P | 2 P |
| `test_benchmark_ledger.py` | 7 P | 7 P |
| `test_blobs.py` | 10 P | 10 P |
| `test_calibration.py` | 11 P | 11 P |
| `test_canonical.py` | 5 P | 5 P |
| `test_card_values.py` | 24 P | 24 P |
| `test_cards.py` | 20 P | 20 P |
| `test_cards_index.py` | 9 P | 9 P |
| `test_cards_model.py` | 12 P | 12 P |
| `test_cards_rows.py` | 6 P | 6 P |
| `test_chase_model.py` | 13 P | 13 P |
| `test_chase_round_refs.py` | 4 P | 4 P |
| `test_chase_service.py` | 16 P | 16 P |
| `test_check.py` | 84 P | 84 P |
| `test_check_composition.py` | 7 P, 3 F | 10 P |
| `test_check_conversions.py` | 12 P | 12 P |
| `test_check_drafts.py` | 12 P, 3 F | 15 P |
| `test_check_living.py` | 9 P | 9 P |
| `test_check_notices.py` | 5 P | 5 P |
| `test_cli.py` | 20 P, 3 F | 21 P, 2 F |
| `test_cli_cards.py` | 5 P | 5 P |
| `test_cli_contributions.py` | 6 P | 6 P |
| `test_cli_decisions.py` | 4 P | 4 P |
| `test_cli_document.py` | 9 P | 9 P |
| `test_cli_evidence.py` | 6 P, 5 F | 6 P, 5 F |
| `test_cli_experiments.py` | 4 P | 4 P |
| `test_cli_extraction.py` | 4 P | 4 P |
| `test_cli_findings.py` | 4 P | 4 P |
| `test_cli_fulltext_screening.py` | 3 P | 3 P |
| `test_cli_gates.py` | 7 P, 1 F | 8 P |
| `test_cli_graph.py` | 4 P | 4 P |
| `test_cli_hypotheses.py` | 3 P | 3 P |
| `test_cli_import_admit.py` | 8 P | 8 P |
| `test_cli_imports.py` | 9 P | 9 P |
| `test_cli_inbox.py` | 2 P | 2 P |
| `test_cli_intuition.py` | 21 P | 21 P |
| `test_cli_lineage.py` | 4 P | 4 P |
| `test_cli_living.py` | 3 P | 3 P |
| `test_cli_miner.py` | 3 P | 3 P |
| `test_cli_modules.py` | 3 P | 3 P |
| `test_cli_organisation.py` | 5 P | 5 P |
| `test_cli_portfolio.py` | 7 P | 7 P |
| `test_cli_references.py` | 5 P | 5 P |
| `test_cli_regions.py` | 4 P | 4 P |
| `test_cli_watch.py` | 8 P | 8 P |
| `test_clock.py` | 2 P | 2 P |
| `test_commit.py` | 30 P, 1 F | 30 P, 1 F |
| `test_concepts_classify.py` | 14 P | 14 P |
| `test_concepts_define.py` | 23 P | 23 P |
| `test_concepts_index.py` | 23 P | 23 P |
| `test_concepts_links.py` | 19 P | 19 P |
| `test_concepts_merge.py` | 11 P | 11 P |
| `test_concepts_model.py` | 7 P | 7 P |
| `test_concepts_review.py` | 9 P | 9 P |
| `test_concepts_sessions.py` | 3 P | 3 P |
| `test_conclusion_diff.py` | 5 P | 5 P |
| `test_conclusions.py` | 12 P | 12 P |
| `test_conclusions_rows.py` | 1 P | 1 P |
| `test_config.py` | 5 P, 1 F | 6 P |
| `test_confirmatory_reproduction.py` | 6 P | 6 P |
| `test_consolidation_service.py` | 20 P | 20 P |
| `test_consolidation_signals.py` | 9 P | 9 P |
| `test_contradictions.py` | 10 P | 10 P |
| `test_contribution_agreement.py` | 10 P | 10 P |
| `test_contribution_checks.py` | 16 P | 16 P |
| `test_contribution_record.py` | 14 P | 14 P |
| `test_contribution_schema.py` | 9 P, 1 F | 9 P, 1 F |
| `test_core_works.py` | 12 P, 2 F | 12 P, 2 F |
| `test_cost_report.py` | 15 P | 15 P |
| `test_coverage_autonomy.py` | 2 P | 2 P |
| `test_coverage_autonomy_split.py` | 1 P | 1 P |
| `test_coverage_buckets.py` | 23 P | 23 P |
| `test_coverage_figures.py` | 13 P | 13 P |
| `test_coverage_render_autonomy.py` | 2 P | 2 P |
| `test_coverage_scale.py` | 1 P | 1 P |
| `test_crossref.py` | 10 P | 10 P |
| `test_dashboard.py` | 10 P | 10 P |
| `test_dashboard_feed.py` | 4 P | 4 P |
| `test_decision_binding.py` | 8 P | 8 P |
| `test_decision_check.py` | 6 P | 6 P |
| `test_decision_model.py` | 24 P | 24 P |
| `test_decision_trace.py` | 1 P, 1 F | 2 P |
| `test_decisions_fold.py` | 19 P | 19 P |
| `test_decisions_service.py` | 16 P | 16 P |
| `test_dedup_cascade.py` | 17 P | 17 P |
| `test_dedup_held_matches.py` | 6 P | 6 P |
| `test_dedup_incremental.py` | 68 P | 68 P |
| `test_dedup_service.py` | 13 P | 13 P |
| `test_depth.py` | 20 P | 20 P |
| `test_design_rules.py` | 17 P | 17 P |
| `test_develop_render.py` | 8 P, 2 F | 8 P, 2 F |
| `test_digest.py` | 10 P | 10 P |
| `test_directions.py` | 15 P | 15 P |
| `test_discovery.py` | 9 P | 9 P |
| `test_document_convert.py` | 21 P | 21 P |
| `test_document_index.py` | 5 P | 5 P |
| `test_document_model.py` | 7 P | 7 P |
| `test_document_preferred.py` | 5 P | 5 P |
| `test_document_quotes.py` | 24 P | 24 P |
| `test_document_read.py` | 23 P | 23 P |
| `test_document_read_gate.py` | 14 P | 14 P |
| `test_draft_audit.py` | 21 P, 2 F | 23 P |
| `test_draft_release.py` | 18 P, 3 F | 21 P |
| `test_draft_status.py` | 13 P, 2 F | 15 P |
| `test_draft_systematic.py` | 4 P, 9 F | 13 P |
| `test_draft_verify.py` | 31 P, 3 F | 34 P |
| `test_drafts_b_cli_mcp.py` | 16 P, 4 F | 20 P |
| `test_drafts_cli_mcp.py` | 9 P, 3 F | 12 P |
| `test_drafts_model.py` | 34 P | 34 P |
| `test_drafts_projection.py` | 34 P | 34 P |
| `test_drafts_service.py` | 30 P | 30 P |
| `test_envelope.py` | 13 P | 13 P |
| `test_evaluation.py` | 17 P | 17 P |
| `test_evaluation_literature.py` | 6 P | 6 P |
| `test_evaluation_pinned_plan.py` | 7 P | 7 P |
| `test_event_log.py` | 14 P | 14 P |
| `test_event_refs.py` | 5 P | 5 P |
| `test_event_validation.py` | 7 P | 7 P |
| `test_evidence_check_methods.py` | 16 P, 1 F | 16 P, 1 F |
| `test_evidence_frontier.py` | 20 P | 20 P |
| `test_evidence_groups.py` | 32 P | 32 P |
| `test_evidence_pareto.py` | 42 P | 42 P |
| `test_evidence_render.py` | 15 P | 15 P |
| `test_evidence_speed.py` | 22 P | 22 P |
| `test_evidence_trace.py` | 16 P | 16 P |
| `test_experiments.py` | 30 P | 30 P |
| `test_experiments_cross_design.py` | 7 P | 7 P |
| `test_experiments_forged.py` | 10 P | 10 P |
| `test_experiments_limits.py` | 6 P | 6 P |
| `test_experiments_model.py` | 4 P | 4 P |
| `test_export_bibtex.py` | 11 P | 11 P |
| `test_export_csl.py` | 5 P | 5 P |
| `test_export_keys.py` | 6 P | 6 P |
| `test_export_prisma_svg.py` | 12 P | 12 P |
| `test_exports_cli_mcp.py` | 6 P | 6 P |
| `test_exports_held_out.py` | 4 P | 4 P |
| `test_exports_scale.py` | 1 P | 1 P |
| `test_exports_service.py` | 9 P | 9 P |
| `test_extraction_agreement.py` | 43 P | 43 P |
| `test_extraction_audit.py` | 28 P | 28 P |
| `test_extraction_check_trace.py` | 25 P | 25 P |
| `test_extraction_index.py` | 11 P | 11 P |
| `test_extraction_model.py` | 14 P | 14 P |
| `test_extraction_next.py` | 26 P | 26 P |
| `test_extraction_numbers.py` | 52 P | 52 P |
| `test_extraction_record.py` | 24 P | 24 P |
| `test_extraction_schema.py` | 17 P | 17 P |
| `test_extraction_scope.py` | 22 P | 22 P |
| `test_extraction_scope_agreement.py` | 10 P | 10 P |
| `test_extraction_scope_index.py` | 11 P | 11 P |
| `test_extraction_stale.py` | 24 P | 24 P |
| `test_extraction_verify.py` | 33 P | 33 P |
| `test_feed_actions.py` | 12 P | 12 P |
| `test_feed_add.py` | 8 P | 8 P |
| `test_feed_cli.py` | 12 P | 12 P |
| `test_feed_index.py` | 9 P | 9 P |
| `test_feed_mcp.py` | 2 P | 2 P |
| `test_feed_model.py` | 14 P | 14 P |
| `test_feed_read.py` | 9 P | 9 P |
| `test_feed_report.py` | 14 P | 14 P |
| `test_feed_service.py` | 25 P | 25 P |
| `test_finder_conflicts.py` | 7 P | 7 P |
| `test_finder_gaps.py` | 7 P | 7 P |
| `test_forged_events.py` | 45 P, 1 F | 45 P, 1 F |
| `test_fulltext_eligibility.py` | 8 P | 8 P |
| `test_fulltext_import.py` | 15 P | 15 P |
| `test_fulltext_index.py` | 6 P | 6 P |
| `test_fulltext_model.py` | 7 P, 1 F | 8 P |
| `test_fulltext_restore.py` | 9 P | 9 P |
| `test_fulltext_routes_arxiv.py` | 28 P | 28 P |
| `test_fulltext_routes_oa.py` | 27 P | 27 P |
| `test_fulltext_screen_record.py` | 17 P, 2 F | 19 P |
| `test_fulltext_service.py` | 32 P | 32 P |
| `test_fulltext_status.py` | 4 P | 4 P |
| `test_gate_audit.py` | 15 P | 15 P |
| `test_gate_audit_coverage.py` | 3 P | 3 P |
| `test_gate_blast_radius.py` | 7 P | 7 P |
| `test_gate_check_agent.py` | 4 P | 4 P |
| `test_gate_policies_protocol.py` | 7 P | 7 P |
| `test_gate_policy_promotion.py` | 2 P | 2 P |
| `test_gate_presets.py` | 267 P | 267 P |
| `test_gates_live.py` | 2 P | 2 P |
| `test_gates_service.py` | 43 P | 43 P |
| `test_graph_index.py` | 12 P | 12 P |
| `test_group_accessors.py` | 7 P | 7 P |
| `test_horizon.py` | 12 P | 12 P |
| `test_hosting.py` | 35 P, 1 F | 36 P |
| `test_http.py` | 26 P | 26 P |
| `test_human_queue.py` | 8 P | 8 P |
| `test_human_queue_extraction.py` | 3 P | 3 P |
| `test_hypotheses.py` | 14 P, 1 F | 14 P, 1 F |
| `test_hypothesis_model.py` | 15 P | 15 P |
| `test_hypothesis_plan.py` | 30 P | 30 P |
| `test_hypothesis_review.py` | 8 P, 1 F | 8 P, 1 F |
| `test_ideas.py` | 14 P | 14 P |
| `test_identity.py` | 5 P | 5 P |
| `test_import_admit.py` | 14 P, 1 F | 14 P, 1 F |
| `test_import_attach.py` | 8 P | 8 P |
| `test_import_check_trace.py` | 13 P | 13 P |
| `test_import_confirm.py` | 12 P | 12 P |
| `test_import_mcp.py` | 6 P, 2 F | 8 P |
| `test_import_prisma.py` | 5 P, 1 F | 5 P, 1 F |
| `test_import_resolve.py` | 13 P | 13 P |
| `test_importlist_source.py` | 9 P, 1 F | 10 P |
| `test_imports_bibtex.py` | 18 P | 18 P |
| `test_imports_csl.py` | 5 P | 5 P |
| `test_imports_index.py` | 5 P | 5 P |
| `test_imports_pdfs.py` | 8 P | 8 P |
| `test_imports_service.py` | 11 P | 11 P |
| `test_imports_split.py` | 9 P | 9 P |
| `test_inbox_index.py` | 10 P | 10 P |
| `test_inbox_links.py` | 31 P | 31 P |
| `test_inbox_model.py` | 16 P | 16 P |
| `test_inbox_reports.py` | 9 P | 9 P |
| `test_inbox_screening.py` | 6 P | 6 P |
| `test_inbox_service.py` | 25 P | 25 P |
| `test_inbox_watch.py` | 5 P | 5 P |
| `test_index.py` | 11 P | 11 P |
| `test_index_concurrency.py` | 5 P | 5 P |
| `test_index_snapshot.py` | 3 P | 3 P |
| `test_interpretations_record.py` | 16 P | 16 P |
| `test_interpretations_review.py` | 14 P | 14 P |
| `test_intuition_check.py` | 27 P | 27 P |
| `test_intuition_export.py` | 12 P | 12 P |
| `test_intuition_index.py` | 14 P | 14 P |
| `test_intuition_layer.py` | 12 P | 12 P |
| `test_intuition_methods.py` | 3 P | 3 P |
| `test_intuition_model.py` | 13 P | 13 P |
| `test_intuition_separation.py` | 7 P, 2 F | 9 P |
| `test_intuition_sessions.py` | 4 P | 4 P |
| `test_intuition_sources.py` | 12 P | 12 P |
| `test_intuition_trace.py` | 14 P | 14 P |
| `test_labels.py` | 12 P | 12 P |
| `test_leads.py` | 16 P | 16 P |
| `test_library.py` | 2 P | 2 P |
| `test_library_sources.py` | 9 P, 1 F | 10 P |
| `test_lineage_check.py` | 20 P | 20 P |
| `test_lineage_cited.py` | 6 P | 6 P |
| `test_lineage_classify.py` | 13 P | 13 P |
| `test_lineage_export.py` | 10 P | 10 P |
| `test_lineage_fixes.py` | 6 P | 6 P |
| `test_lineage_index.py` | 12 P | 12 P |
| `test_lineage_model.py` | 15 P | 15 P |
| `test_lineage_paths.py` | 14 P | 14 P |
| `test_lineage_scale.py` | 1 P | 1 P |
| `test_lineage_service.py` | 17 P | 17 P |
| `test_lineage_trace.py` | 11 P | 11 P |
| `test_literature_forged.py` | 18 P | 18 P |
| `test_literature_real_path.py` | 6 P | 6 P |
| `test_living_c_fixes.py` | 6 P | 6 P |
| `test_living_due.py` | 11 P | 11 P |
| `test_living_facts.py` | 7 P | 7 P |
| `test_living_network.py` | deselected | deselected |
| `test_match_rules.py` | 19 P | 19 P |
| `test_matching.py` | 11 P | 11 P |
| `test_mcp_cards.py` | 5 P | 5 P |
| `test_mcp_concepts.py` | 6 P, 1 F | 7 P |
| `test_mcp_contributions.py` | 10 P | 10 P |
| `test_mcp_conventions.py` | 16 P | 16 P |
| `test_mcp_decisions.py` | 6 P, 1 F | 7 P |
| `test_mcp_document.py` | 4 P, 1 F | 5 P |
| `test_mcp_evidence.py` | 10 P | 10 P |
| `test_mcp_experiments.py` | 5 P, 1 F | 6 P |
| `test_mcp_extraction.py` | 21 P | 21 P |
| `test_mcp_findings.py` | 6 P | 6 P |
| `test_mcp_fulltext.py` | 4 P, 1 F | 5 P |
| `test_mcp_fulltext_screening.py` | 12 P | 12 P |
| `test_mcp_graph.py` | 6 P | 6 P |
| `test_mcp_hypotheses.py` | 5 P, 1 F | 6 P |
| `test_mcp_inbox.py` | 7 P | 7 P |
| `test_mcp_intuition.py` | 6 P | 6 P |
| `test_mcp_lineage.py` | 6 P | 6 P |
| `test_mcp_living.py` | 2 P, 1 F | 3 P |
| `test_mcp_mine.py` | 5 P | 5 P |
| `test_mcp_protocol.py` | 9 P, 4 F | 13 P |
| `test_mcp_references.py` | 18 P, 8 F | 26 P |
| `test_mcp_screening.py` | 7 P, 6 F | 13 P |
| `test_mcp_search.py` | 16 P | 16 P |
| `test_mcp_server.py` | 2 P, 1 F | 3 P |
| `test_mcp_watch.py` | 2 P | 2 P |
| `test_methods.py` | 8 P, 1 F | 9 P |
| `test_mine_path.py` | 11 P | 11 P |
| `test_mine_run.py` | 10 P | 10 P |
| `test_miner_admit.py` | 5 P | 5 P |
| `test_miner_calibration_draw.py` | 15 P | 15 P |
| `test_miner_calibration_pass.py` | 10 P | 10 P |
| `test_miner_compile.py` | 17 P | 17 P |
| `test_miner_evidence.py` | 17 P | 17 P |
| `test_miner_exploratory.py` | 1 P | 1 P |
| `test_miner_freeze.py` | 8 P | 8 P |
| `test_miner_gold.py` | 13 P | 13 P |
| `test_miner_kinds.py` | 10 P, 1 F | 10 P, 1 F |
| `test_miner_lifecycle.py` | 8 P | 8 P |
| `test_miner_registration.py` | 7 P | 7 P |
| `test_miner_review_fixes.py` | 10 P | 10 P |
| `test_miner_score.py` | 17 P | 17 P |
| `test_miner_select.py` | 11 P | 11 P |
| `test_miner_spec.py` | 19 P | 19 P |
| `test_miners_protocol.py` | 10 P | 10 P |
| `test_model_drift.py` | 4 P | 4 P |
| `test_module_contract.py` | 13 P | 13 P |
| `test_multiverse.py` | 8 P | 8 P |
| `test_notice_effects.py` | 5 P | 5 P |
| `test_notice_report.py` | 5 P | 5 P |
| `test_notice_state.py` | 8 P | 8 P |
| `test_notices.py` | 14 P | 14 P |
| `test_notices_surfaces.py` | 3 P | 3 P |
| `test_old_log_replay.py` | 0 P, 1 F | 1 P |
| `test_onion.py` | 22 P, 2 F | 24 P |
| `test_onion_empty.py` | 5 P | 5 P |
| `test_onion_merges.py` | 1 P, 2 F | 3 P |
| `test_onion_rebuild.py` | 1 P | 1 P |
| `test_onion_scale.py` | 1 P | 1 P |
| `test_onion_withholding.py` | 9 P | 9 P |
| `test_openalex.py` | 44 P | 44 P |
| `test_organisation_guards.py` | 8 P | 8 P |
| `test_organisation_separation.py` | 20 P | 20 P |
| `test_outline.py` | 16 P | 16 P |
| `test_pack_ai_research_system.py` | 8 P | 8 P |
| `test_packs.py` | 7 P | 7 P |
| `test_packs_contribution.py` | 25 P | 25 P |
| `test_pairing_rules.py` | 17 P | 17 P |
| `test_passes.py` | 10 P, 1 F | 10 P, 1 F |
| `test_passes_extraction.py` | 1 P | 1 P |
| `test_pipeline.py` | 43 P | 43 P |
| `test_plugin.py` | 31 P, 3 F | 34 P |
| `test_portfolio.py` | 8 P, 1 F | 8 P, 1 F |
| `test_portfolio_render.py` | 7 P | 7 P |
| `test_portfolio_stage.py` | 26 P | 26 P |
| `test_portfolio_stage_extraction.py` | 2 P | 2 P |
| `test_prisma.py` | 19 P, 1 F | 20 P |
| `test_prisma_full.py` | 9 P | 9 P |
| `test_prisma_update.py` | 13 P | 13 P |
| `test_probe.py` | 32 P, 1 F | 33 P |
| `test_progress.py` | 10 P, 1 F | 10 P, 1 F |
| `test_project_service.py` | 18 P | 18 P |
| `test_project_status.py` | 1 P | 1 P |
| `test_properties.py` | 11 P | 11 P |
| `test_protocol_model.py` | 9 P | 9 P |
| `test_protocol_rules.py` | 26 P | 26 P |
| `test_protocol_service.py` | 23 P | 23 P |
| `test_quality_stats.py` | 11 P | 11 P |
| `test_question.py` | 27 P, 1 F | 28 P |
| `test_queue_advance.py` | 13 P | 13 P |
| `test_ranking.py` | 7 P, 7 F | 7 P, 7 F |
| `test_read_rows_chunked.py` | 1 P | 1 P |
| `test_reference_view.py` | 6 P | 6 P |
| `test_references_bbl.py` | 11 P | 11 P |
| `test_references_extract.py` | 24 P | 24 P |
| `test_references_index.py` | 13 P | 13 P |
| `test_references_markers.py` | 24 P | 24 P |
| `test_references_match.py` | 13 P | 13 P |
| `test_references_model.py` | 19 P | 19 P |
| `test_references_parse.py` | 32 P | 32 P |
| `test_references_reports.py` | 25 P | 25 P |
| `test_references_resolve.py` | 28 P | 28 P |
| `test_reflist_source.py` | 7 P | 7 P |
| `test_region_check_trace.py` | 15 P | 15 P |
| `test_region_evaluate.py` | 16 P, 5 F | 20 P, 1 F |
| `test_region_focus.py` | 5 P | 5 P |
| `test_region_links.py` | 6 P | 6 P |
| `test_region_mcp.py` | 8 P | 8 P |
| `test_region_members.py` | 16 P | 16 P |
| `test_region_review.py` | 7 P | 7 P |
| `test_region_rules.py` | 8 P | 8 P |
| `test_region_scale.py` | 0 P, 1 F | 0 P, 1 F |
| `test_region_snapshot.py` | 25 P, 2 F | 27 P |
| `test_registration.py` | 13 P | 13 P |
| `test_registry_ownership.py` | 14 P | 14 P |
| `test_relation_staleness.py` | 14 P | 14 P |
| `test_relations.py` | 19 P | 19 P |
| `test_reports_surfaces.py` | 14 P, 1 F | 15 P |
| `test_reproduction.py` | 19 P | 19 P |
| `test_resume.py` | 19 P | 19 P |
| `test_resume_find.py` | 18 P | 18 P |
| `test_resume_surfaces.py` | 20 P | 20 P |
| `test_run_costs.py` | 19 P | 19 P |
| `test_runner.py` | 24 P | 24 P |
| `test_runner_skill_tools.py` | 7 P | 7 P |
| `test_runs_adopt.py` | 16 P | 16 P |
| `test_screening_check.py` | 8 P | 8 P |
| `test_screening_model.py` | 19 P | 19 P |
| `test_screening_next.py` | 10 P, 15 F | 25 P |
| `test_screening_ranked.py` | 13 P, 4 F | 14 P, 3 F |
| `test_screening_record.py` | 1 P, 11 F | 12 P |
| `test_screening_stats.py` | 15 P | 15 P |
| `test_search_service.py` | 38 P | 38 P |
| `test_seed_split.py` | 20 P | 20 P |
| `test_seeds.py` | 22 P | 22 P |
| `test_sequencing.py` | 14 P, 1 F | 15 P |
| `test_site_catalog.py` | 11 P | 11 P |
| `test_site_feed.py` | 8 P | 8 P |
| `test_site_server_writes.py` | 15 P | 15 P |
| `test_skills.py` | 14 P | 14 P |
| `test_slice6_acceptance.py` | 1 P | 1 P |
| `test_slice6_check_trace_methods.py` | 20 P | 20 P |
| `test_slice6_surfaces.py` | 8 P, 1 F | 8 P, 1 F |
| `test_snapshots.py` | 8 P | 8 P |
| `test_snowball_compare.py` | 6 P | 6 P |
| `test_snowball_forward.py` | 10 P, 1 F | 11 P |
| `test_snowball_plan.py` | 6 P | 6 P |
| `test_snowball_round.py` | 52 P | 52 P |
| `test_source_base.py` | 28 P, 1 F | 29 P |
| `test_sources_methods.py` | 3 P | 3 P |
| `test_stage_index.py` | 4 P | 4 P |
| `test_stage_model.py` | 32 P | 32 P |
| `test_stage_services.py` | 13 P | 13 P |
| `test_stats.py` | 6 P | 6 P |
| `test_status_purpose.py` | 7 P | 7 P |
| `test_supplied_links_protocol.py` | 13 P | 13 P |
| `test_supports.py` | 22 P | 22 P |
| `test_task_kinds.py` | 4 P, 1 F | 5 P |
| `test_tasks.py` | 18 P | 18 P |
| `test_terms.py` | 15 P | 15 P |
| `test_theme.py` | 11 P | 11 P |
| `test_timeline.py` | 16 P | 16 P |
| `test_tquantiles.py` | 13 P | 13 P |
| `test_trace.py` | 15 P | 15 P |
| `test_trace_drafts.py` | 14 P | 14 P |
| `test_unlock_access_budget.py` | 19 P | 19 P |
| `test_usage_limit.py` | 9 P | 9 P |
| `test_versions.py` | 10 P | 10 P |
| `test_view_coverage.py` | 10 P | 10 P |
| `test_views_b_cli_mcp.py` | 16 P | 16 P |
| `test_views_b_merges.py` | 5 P | 5 P |
| `test_views_b_render.py` | 8 P | 8 P |
| `test_views_cli_mcp.py` | 10 P | 10 P |
| `test_views_meta.py` | 7 P | 7 P |
| `test_views_render.py` | 8 P | 8 P |
| `test_vocabulary.py` | 9 P | 9 P |
| `test_watch_cycle.py` | 24 P | 24 P |
| `test_watch_network.py` | deselected | deselected |
| `test_watch_plan.py` | 12 P | 12 P |
| `test_watch_screening.py` | 6 P | 6 P |
| `test_watch_window.py` | 9 P | 9 P |
| `test_work.py` | 20 P | 20 P |
| `test_work_ids.py` | 39 P | 39 P |
| `test_work_queue.py` | 11 P | 11 P |
| `test_world_cache.py` | 7 P | 7 P |
| `test_writing_acceptance.py` | 0 P, 1 F | 1 P |
| `test_writing_checks.py` | 41 P | 41 P |
| `test_writing_render.py` | 18 P, 2 F | 20 P |
| `test_writing_scale.py` | 0 P, 1 F | 1 P |
| `test_writing_stats.py` | 15 P | 15 P |
| `test_xruns_ingest.py` | 9 P | 9 P |
| `test_xruns_register.py` | 9 P | 9 P |
