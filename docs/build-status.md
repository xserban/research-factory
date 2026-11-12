# Build status

Updated 2026-11-12 (restart and costs merged into `plan-feed-hub`; targeted tests run). Each line of work, and where it stands: **built** (code committed, mypy and ruff pass), **reviewed** (one model review of the branch, fixes committed), **tested** (the test suite has run and passed), **merged** (on `main`). Testing was paused by the researcher from 2026-11-05; on 2026-11-12 targeted runs of this line's test files were allowed (one file per process), so "partly" below means those files pass but the full suite has not run. No feature of this line has been tried live yet. The untested-work list kept by the controller names what to run first when testing resumes.

Update this file in the landing commit of every plan, together with the backlog statuses.

## The current line (each branch builds on the one above)

| Branch | Content | Built | Reviewed | Tested | Merged |
|---|---|---|---|---|---|
| `plan-8-suggest-select` | Slice 8: suggest and select, screening ranker (decision 116), core works and forward snowballing, the site hub (plan 2026-11-10-site-hub); backlog ideas 45–59 (aec35cf) | yes | per plan | no | no (359 commits ahead of `main`) |
| `plan-reference-layers` | Reference layers (IDEA-57 first part, plan 2026-11-11-reference-layers): T1–T5, scheme v2 earth rings, T8 cited-item rules v4, T9 inner calibration stratum, `seed_version`, `re-resolve --only-identifiers`. Not built: T6, T7, T10, P2, P4, P5, citations product. Pilot: scheme v3 current, 41 of 50 v3 labels pending (see IDEA-57) | yes | T1–T5 yes (one Sonnet review); T8, T9, `seed_version` no | no (no test file exists for `reference_layers` or `reference_items`; mypy and ruff only) | yes (in `main` ae5f5b5, 2026-11-12) |
| `plan-feed` | Slice 4c discovery feed v1, F1–F10 (decision 118) | yes | yes (Sonnet review, fixes cec877c) | no | no |
| `plan-feed-hub` (now includes `plan-restart-costs`) | Feed in the hub (decision 119): Daily updates page, write path, one-click add, work queue, Process now (H1–H7); full ingestion pipeline Process all, the hard MCP unit cap and a per-run time limit (H8); dashboard feed and queue panel | yes | H1–H7 yes (fixes to 62d5c7b); H8 yes (fixes a4d2bb8); dashboard panel (91fc18a) not reviewed | partly (2026-11-12: feed, inbox, hub, dashboard files pass one by one; not tried live) | yes (`main` ae5f5b5, unification 2026-11-12) |
| `plan-restart-costs` | Restartable LLM steps (IDEA-59: interruption finder, `factory resume`, hub Resume, `runs adopt`) and the run cost model (IDEA-45: cost reader, unit counter file, `factory costs`, hub Run costs page, pilot baseline); also the light theme (on `plan-feed-hub`, 7746eeb, 78e67b8) | yes | yes (Sonnet review, fixes fc2c23e, 73a1ef3) | partly (2026-11-12: resume, runner, pipeline, costs, adopt, usage-limit files pass one by one, and the trace, decisions, check and MCP files fixed on the branch; full suite not run; not tried live) | yes (via `plan-feed-hub`, `main` ae5f5b5, 2026-11-12). Wrap-up: no index change (no `PROJECTION_VERSION` bump), no new event type; what is left is in IDEA-59, IDEA-45 and IDEA-63 |
| `plan-catalog` | Capability catalog (IDEA-60): hub product `catalog`, MCP tools and skills by lifecycle stage, count check, mechanical instruction flags; `stage:` in every SKILL.md. Follow-ups IDEA-61 | yes | yes (Sonnet review, fixes 714d31b) | partly (the 11 catalog tests pass on the unified line, run 2026-11-12; one build on a pilot copy) | yes, in `main` at ae5f5b5 (2026-11-12) |

## Before merging this line

State at the restart-and-costs wrap-up (2026-11-12, after the unification on `main` ae5f5b5): items 2, 3 and 4 were done at the unification (backlog reconciled, decisions 118 and 119, `MAP.md` regenerated); item 1 is open (IDEA-65: about 400 test files not run on the unified line); item 5 is open.

1. Run every test file in small batches (never the full suite in one process). The targeted runs of 2026-11-12 fixed 4 product bugs (deadlock in the test harness 6935a07, feed arXiv version e5d7423, false `broken-link` on decision suggestions 6858d22, trace kind order 383aa8e) and about 50 stale tests; files outside this line have not run.
2. Reconcile `docs/backlog.md`: `plan-8-suggest-select` holds ideas 45–59 (aec35cf); this line holds only IDEA-58 among them.
3. Fix decision numbers at merge (117 and 118 are provisional; the reference-layers decision is unnumbered; next free is 120).
4. Regenerate `docs/MAP.md` (`scripts/gen_map.py` is on the `docs-onboarding` line, not on this one).
5. One live trial with the researcher (every feature of this line is untested live: Process now and Process all, the unit cap and time limit, resume, run costs, usage-limit detection): configure the feed on `agentic-science`, add two or three papers from the hub, Process now for screening once, to see the real `claude -p` flags work.

## Other unmerged branches

`git branch --no-merged main` lists 43 branches (2026-11-11), most from the build of 2026-11-05 to 2026-11-07, landed into the slice 8 line through the `land-*` branches. See `docs/handoff-2026-11-05.md` for that build.
