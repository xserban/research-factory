# factory platform

The deterministic platform of the research factory. The document index is in the repository
`README.md`; the contracts are in `docs/specs/`.

## Running tests

From `platform/`:

- During development: `uv run pytest -m "not network and not slow"`. The `slow` marker covers
  the acceptance suites (`tests/test_acceptance_*.py`) and other long files.
- At a milestone (a plan finished, before merging to `main`): `uv run pytest -m "not network"`,
  which runs everything offline, `slow` included.
- Optionally in parallel: `uv run pytest -n 4 …` (pytest-xdist, a dev dependency; not the
  default). Tests are isolated by `tmp_path`, so any worker count is safe.

Expensive test worlds are built once per process and restored by copying files
(`tests/world_cache.py`); `FACTORY_TEST_NO_WORLD_CACHE=1` disables this, and
`FACTORY_TEST_WORLD_CACHE_STATS=1` reports how often snapshots were reused.
