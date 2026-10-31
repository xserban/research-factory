# Research Factory — instructions for Claude

## What this project is
A deterministic platform that lets Claude run rigorous, traceable research (literature search, screening, extraction, hypothesis testing). Read `README.md` for the document index.

**Status:** planning complete for slice 1; sub-plan 1 (platform core) implemented — see docs/plans/2026-10-31-platform-core.md.

## Binding documents (read before planning or coding)
1. `docs/specs/00-system.md` — system contracts (layout, IDs, events, index, MCP conventions, quality bars).
2. `docs/specs/01-rigour.md` — rigour requirements R-xx. Every slice must satisfy the ones in its scope.
3. `docs/specs/slice-N.md` — the slice being built (currently `slice-1.md`).
4. `docs/decisions.md` — decision log. Do not contradict a *Decided* entry; propose a new entry instead.

Background only (not binding): `docs/00-…09-*.md`, `docs/reference/research-factory-old-spec/`.

## Non-negotiable rules
- **The platform never calls a model.** No API keys, no model SDKs in `platform/`. All judgement comes from Claude through MCP tools.
- **Events are the source of truth.** Append-only JSONL under `projects/<slug>/events/`; never edit or delete an event; corrections supersede. The SQLite index is a rebuildable projection and is never written except by the projector.
- **Business logic lives in `platform/src/factory/services/`.** `mcp/` and `cli/` only parse input, call a service, and format output.
- **Validate at the boundary.** Invalid input writes nothing and returns structured errors.
- **Provenance everywhere:** every agent-written event carries model, skill version and `input_blob`.
- **Scripts never judge; agents never do bookkeeping.** Counts, hashes, PRISMA numbers are computed, never typed.

## Pilot hold-out
Never open `docs/pilot/heldout-seeds.md` unless the task is the post-search seed check; record any opening in `docs/pilot/log.md`.

## Reuse
Port from `~/Projects/research-factory-old/src/rf/` only what `docs/09-existing-assets.md` lists under "Reuse — code", **with its tests**, adapting it to the event model. Do not copy `cli.py`, `claims.py`, `entities.py`, the file-based store, or vendored skills.

## Development process (obra/superpowers)
- Specs live in `docs/specs/`; **plans go in `docs/plans/YYYY-MM-DD-<name>.md`** (not `docs/superpowers/plans/`).
- Brainstorming must start from the existing specs; do not create parallel spec documents.
- TDD is mandatory for `platform/`. Experiment and prototype code outside `platform/` is exempt.
- Use subagent-driven development for critical modules (events, index, protocol, screening, provenance); inline execution is fine for small tasks.
- Commit small and often; one branch/worktree per plan.

## Tooling
Python ≥ 3.11 · `uv` · `ruff` · `mypy --strict` (must pass) · `pytest` (offline by default; mark network tests `network`). Coverage ≥ 90% for `services/` and `model/`.

## Style
Documentation: concise, academic, no marketing language. Code: small focused modules, type hints everywhere, docstrings that state invariants.
