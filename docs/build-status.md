# Build status

Updated 2026-11-12 (restart and costs merged into `plan-feed-hub`; targeted tests run). Each line of work, and where it stands: **built** (code committed, mypy and ruff pass), **reviewed** (one model review of the branch, fixes committed), **tested** (the test suite has run and passed), **merged** (on `main`). Testing was paused by the researcher from 2026-11-05; on 2026-11-12 targeted runs of this line's test files were allowed (one file per process), so "partly" below means those files pass but the full suite has not run. No feature of this line has been tried live yet. The untested-work list kept by the controller names what to run first when testing resumes.

Update this file in the landing commit of every plan, together with the backlog statuses.

## The current line (each branch builds on the one above)

| Branch | Content | Built | Reviewed | Tested | Merged |
|---|---|---|---|---|---|
| `plan-8-suggest-select` | Slice 8: suggest and select, screening ranker (decision 116), core works and forward snowballing, the site hub (plan 2026-11-10-site-hub); backlog ideas 45–59 (aec35cf) | yes | per plan | no | no (359 commits ahead of `main`) |
| `plan-reference-layers` | Reference layers T1–T5 (plan 2026-11-11-reference-layers); branched from `plan-8-suggest-select` at a67690b, so it lacks aec35cf | yes | yes (one Sonnet review) | no | no |
| `plan-feed` | Slice 4c discovery feed v1, F1–F10 (decision 117) | yes | yes (Sonnet review, fixes cec877c) | no | no |
| `plan-feed-hub` (now includes `plan-restart-costs`) | Feed in the hub (decision 118): Daily updates page, write path, one-click add, work queue, Process now (H1–H7); full ingestion pipeline Process all, the hard MCP unit cap and a per-run time limit (H8); dashboard feed and queue panel | yes | H1–H7 yes (fixes to 62d5c7b); H8 yes (fixes a4d2bb8); dashboard panel (91fc18a) not reviewed | partly (2026-11-12: feed, inbox, hub, dashboard files pass one by one; not tried live) | no |
| `plan-restart-costs` | Restartable LLM steps (IDEA-59: interruption finder, `factory resume`, hub Resume, `runs adopt`) and the run cost model (IDEA-45: cost reader, unit counter file, `factory costs`, hub Run costs page, pilot baseline); also the light theme (on `plan-feed-hub`, 7746eeb, 78e67b8) | yes | yes (Sonnet review, fixes fc2c23e, 73a1ef3) | partly (2026-11-12: resume, runner, pipeline, costs, adopt, usage-limit files pass; not tried live); merged into `plan-feed-hub` 2026-11-12 | no |

## Before merging this line

1. Run every test file in small batches (never the full suite in one process). The targeted runs of 2026-11-12 fixed 4 product bugs (deadlock in the test harness 6935a07, feed arXiv version e5d7423, false `broken-link` on decision suggestions 6858d22, trace kind order 383aa8e) and about 50 stale tests; files outside this line have not run.
2. Reconcile `docs/backlog.md`: `plan-8-suggest-select` holds ideas 45–59 (aec35cf); this line holds only IDEA-58 among them.
3. Fix decision numbers at merge (117 and 118 are provisional; the reference-layers decision is unnumbered).
4. Regenerate `docs/MAP.md` (`scripts/gen_map.py` is on the `docs-onboarding` line, not on this one).
5. One live trial with the researcher (every feature of this line is untested live: Process now and Process all, the unit cap and time limit, resume, run costs, usage-limit detection): configure the feed on `agentic-science`, add two or three papers from the hub, Process now for screening once, to see the real `claude -p` flags work.

## Other unmerged branches

`git branch --no-merged main` lists 43 branches (2026-11-11), most from the build of 2026-11-05 to 2026-11-07, landed into the slice 8 line through the `land-*` branches. See `docs/handoff-2026-11-05.md` for that build.
