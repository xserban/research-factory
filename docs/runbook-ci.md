# Runbook: tests in CI and the pull-request flow

Status: required. `static` and the four `tests` shards are required checks on main (branch
protection); report-only until the first fully green run on 2026-11-20. SonarCloud stays advisory.

## What runs where
| When | What | Where |
|---|---|---|
| Every pull request and every push to main | `static` (ruff check and format, mypy --strict, import contracts) and `tests` limited to the files the change touches (`scripts/affected_tests.py`: coverage map, import fallback); a push to main is selected against the previous commit | GitHub, `.github/workflows/tests.yml` |
| Nightly 03:00 UTC and manual dispatch | the whole suite including the `slow` suites (acceptance and scale files); records the coverage map and durations; opens or updates the issue `Nightly full run failed` on a failure | GitHub |
| Weekly | quality report (radon, vulture, pip-audit, scc) | GitHub, `weekly-quality.yml` |
| Every pull request | `map-fresh` (advisory, `continue-on-error`): `scripts/check_map_fresh.py` regenerates `docs/MAP.md` in memory and compares it, ignoring the commit line; stale is expected before the post-merge regeneration | GitHub, `tests.yml` |
| Pull request touching `platform/pyproject.toml`, `platform/uv.lock` or workflows; Mondays 05:00 UTC; manual | dependency audit (pip-audit of the exported lock), report-only: summary and artifact `pip-audit`, never fails the run | GitHub, `security.yml` |
| Weekly (Dependabot) | grouped update pull requests for uv (`/platform`) and GitHub Actions, at most 3 and 2 open; reviewed like any change, never auto-merged | `.github/dependabot.yml` |
| Locally, before a branch is opened as a pull request | the touched files one at a time (`pt.sh`), mypy and ruff | the machine |

## How a change is selected
Pull requests and pushes to main run only the tests a change touches; the nightly full run is the
backstop for what the selection leaves out. `scripts/affected_tests.py` prints the plan (mode,
source of the selection, depth, selected files of the total) in the "which tests" job log.

1. A suite-wide file (pyproject, lock, `conftest.py`, the workflow, the script) selects everything,
   as does the label `full-tests` on a pull request. A manual dispatch also runs everything.
2. Coverage map (preferred). The nightly run records which source files each test file executed
   (`pytest --cov=factory --cov-context=test`, config `platform/.coveragerc-map`) and keeps only
   that relation, no line data, with the per-file durations (`scripts/make_coverage_map.py`). The
   merged `map.json` is uploaded as the artifact `selection-map` (14 days retention). A pull request
   downloads the latest one from a run on main. A changed source file the map knows selects every
   test whose recorded files include it. A map that is missing, unreadable or older than 7 days
   (`--max-age-days`) is ignored, and the log says so.
3. Import rules (the fallback, and for a changed file the map does not know, such as a new module
   or a non-Python file). Depth 1: the test files that import the changed module directly
   (`import factory.x`, `from factory.x import y`; a name a package `__init__` re-exports from a
   submodule counts as an import of that submodule). Depth 2 for the kernel
   (`platform/src/factory/{events,model,index}/`), whose blast radius is wider. `--closure N` sets
   the depth (`--closure 99` is the old unbounded transitive closure). A non-Python file under
   `platform/src` (hub JS, CSS) selects the tests named after its package and the tests importing
   the package's modules.
4. Name match, always: `test_<stem>*.py` and `test_<package>_<stem>*.py` for a changed module.
5. A changed test file selects itself; a changed test helper selects the tests that import it.
6. A changed file outside the Python tree selects the tests that name its top directory; four
   files that import nothing by name (plugin, MCP server, site catalogue, registry ownership)
   always run.

Known gaps: a test file added after the last nightly run is not in the map, so it is selected as
a changed file only; behaviour reached only through paths the map never saw (dynamic imports,
data-driven dispatch) is caught by the nightly run, whose failure opens the issue. A module that
nearly every test executes (`events/catalog.py`, `services/context.py`, many `model/` files)
selects most of the suite by overlap or by depth-2 imports: a pull request touching it is slow by
design; finer, line-level contexts would be the next step.

### Sharding
The four required shards are filled longest file first onto the lightest shard, using the
durations in the map (or the committed `platform/tests/.durations.json`). The headless-browser
files (`BROWSER` in the script) run in their own non-required job `tests (browser)` in parallel,
only when selected. A shard with no selected file still runs and passes, so the required names
`tests (shard 0..3 of 4)` and `ruff + mypy --strict` report on every run. A new push to a pull
request cancels the superseded run; runs on main are never cancelled.

### Refresh and force
- The map and durations refresh at every nightly run; refresh by hand with the workflow dispatch
  of `Tests` (Actions tab, "Run workflow"), which also runs the whole suite.
- Force all tests on a pull request: add the label `full-tests` (the run restarts).
- Refresh the committed durations: download the junit artifacts of a green full run
  (`gh run download <id> -p 'junit-*' -D /tmp/j`), then
  `python3 scripts/make_coverage_map.py --out /tmp/m.json --junit /tmp/j/*/*.xml --durations-out platform/tests/.durations.json`.

### Local gate
Before pushing, run `ruff`, `mypy --strict` and the new and touched test files (the same files
`python3 scripts/affected_tests.py --files <changed paths>` prints); never the full suite. CI and
the nightly run cover the rest.

## Pull-request flow
1. One branch per plan or fix, as now (worktree).
2. Local gate: mypy, ruff, the touched test files.
3. Push the branch, open a pull request to main. The Tests workflow runs; read the run summary
   (the plan, the failures, the 25 slowest tests of every shard).
4. Merge when the checks are green (once required: branch protection on main, checks `static`
   and `tests`). Until then a red check is information, not a block.
5. Never push to main directly after the switch; the local `main` is updated by fetching.

## Known failures
None. The three tests that failed on main on 2026-11-20 were fixed (a missing registry owner and
two stale tests), together with the failures the first full runs found.

## If a check is red
Read the run summary (the failing tests and the 25 slowest), then `gh run view <id> --log`. Fix on
the branch and push; the run restarts. A flaky test is a bug in the test: fix the cause, do not
re-run until green.

## Quality trend file
`scripts/quality_trend.py` appends one JSON line to `docs/quality-trend.jsonl`: date, commit, tests
collected, ruff findings, mypy errors, Python file, module and test-file counts (null where a tool
was skipped; `--fast` skips test collection and mypy). Run it by hand from the repository root
(`uv run --project platform python scripts/quality_trend.py`) when a trend point is wanted, for
example at a plan's merge; it only counts. The file holds one seed line; further lines are added
deliberately, not by CI. Where the history lives long term (repository, data branch, hub page) is
still open (IDEA-94).
