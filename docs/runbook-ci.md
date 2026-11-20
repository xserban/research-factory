# Runbook: tests in CI and the pull-request flow

Status: report-only until the known failures are cleaned up (decision pending; target two weeks
after the first green run).

## What runs where
| When | What | Where |
|---|---|---|
| Every pull request | `static` (ruff check and format, mypy --strict, import contracts) and `tests` limited to the files the change can reach (`scripts/affected_tests.py`) | GitHub, `.github/workflows/tests.yml` |
| Every push to main | `static` and the whole offline suite (`-m 'not network and not slow'`), four shards in parallel, pytest-xdist inside each | GitHub |
| Nightly 03:00 UTC | the whole suite including the `slow` suites (acceptance and scale files) | GitHub |
| Weekly | quality report (radon, vulture, pip-audit, scc) | GitHub, `weekly-quality.yml` |
| Locally, before a branch is opened as a pull request | the touched files one at a time (`pt.sh`), mypy and ruff | the machine |

## How a change is selected
`scripts/affected_tests.py` builds the import graph of `platform/src` and the test helper
modules, and selects every test file whose imports reach a changed module. It selects more, never
fewer, when unsure: a suite-wide file (pyproject, lock, `conftest.py`, the workflow, the script)
selects everything; a changed file outside the Python tree selects the tests that name its top
directory; four files that import nothing by name (plugin, MCP server, site catalogue, registry
ownership) always run. Core modules (`services/context.py`, `events/`) reach almost every test,
so a pull request that touches them runs nearly the whole suite, sharded. Dynamic imports are the
blind spot; the full run after the merge covers it. A coverage-based selection (pytest-testmon)
is the next step if the first timings show the import graph is too coarse.

## Pull-request flow
1. One branch per plan or fix, as now (worktree).
2. Local gate: mypy, ruff, the touched test files.
3. Push the branch, open a pull request to main. The Tests workflow runs; read the run summary
   (the plan, the failures, the 25 slowest tests of every shard).
4. Merge when the checks are green (once required: branch protection on main, checks `static`
   and `tests`). Until then a red check is information, not a block.
5. Never push to main directly after the switch; the local `main` is updated by fetching.

## Known failures (report-only list, 2026-11-20)
`test_hypothesis_review::test_nothing_waiting_and_no_second_serving`,
`test_hypotheses::test_conclusion_needs_an_evaluation_and_a_human`,
`test_registry_ownership::test_every_protocol_section_has_one_owner` (`pending_tolerance` has no
owner). Each fails identically on main.
