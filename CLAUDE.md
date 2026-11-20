# Research Factory — instructions for Claude

## What this project is
A deterministic platform that lets Claude run rigorous, traceable research (literature search, screening, extraction, hypothesis testing). Read `README.md` for the document index.

**Status:** slice 1: sub-plans 1–5 (platform core; works and acquisition; question, seeds, probe, protocol; screening, calibration, audit; supplementary search; reports, trace, check) implemented — see docs/plans/. Slice 2: plan A (acquisition) and plan B1/B2 (canonical Markdown and conversion) implemented, converters chosen (decision 49: PDF docling, HTML latexml-html, LaTeX pandoc); plan 2C (full-text screening and full PRISMA) implemented; plans 2D (schema, extraction, agreement, audit) and 2E (evidence report) implemented, MCP and CLI included; decisions 50–53 adopted; G1 (slice 3a: references and snowballing) implemented, MCP, CLI and skill `rf-references` included; its pilot run is set aside (decision 74); slice 4a (link inbox and discovery record, decision 61) implemented (v1). Slice 3b (lineage: contribution items, relations, ideas and the graph; plans G2-A to G2-E, check, trace and acceptance included, decision 82 proposed) implemented; its pilot run is set aside (decision 74). Slice 3c (intuition layer: interpretations, background concepts, the `layer` filter, labelled export, check, trace and CLI review; plans G3-A to G3-C, decision 83 proposed) implemented; its pilot run is set aside (decision 74). Later slices, all built (see `docs/build-status.md` and the backlog statuses for review and merge state): 4b and 4c (watch cycles, discovery feed), 5 (teams, hosting, deploy), 6 (hypotheses, experiments), 7 (views, writing), M (miners: extraction as miners plus builders, taxonomies, technique and lifecycle miners), 8 (suggest and select, screening ranker, core works, forward snowballing), the papers chat and spar (decisions 140-148), the hypothesis engine v1 (IDEA-103: lead candidates, queue, statistics, derived cache) and its follow-ups, and the hub v2 (IDEA-97: one design system, out-of-process builds, per-payload fingerprints, click tests). Tests and static checks run on GitHub Actions (`docs/runbook-ci.md`); locally run only mypy, ruff and the touched test files.

New to the code: read `docs/ARCHITECTURE.md` (how the parts fit), then `docs/MAP.md` (where each module, event, table, tool, command and skill lives; generated — after a plan merges, regenerate with `uv run --project platform python scripts/gen_map.py`, never edit by hand).

Build state: `docs/build-status.md`. `docs/handoff-2026-11-05.md` is superseded (kept for history).

## Binding documents (read before planning or coding)
1. `docs/specs/00-system.md` — system contracts (layout, IDs, events, index, MCP conventions, quality bars).
2. `docs/specs/01-rigour.md` — rigour requirements R-xx. Every slice must satisfy the ones in its scope.
3. `docs/specs/slice-N.md` — the slice being built (currently `slice-2.md`; `slice-1.md` is implemented and still binding for what it built).
4. `docs/decisions.md` — decision log. Do not contradict a *Decided* entry; propose a new entry instead.

Background only (not binding): `docs/00-…09-*.md`, `docs/reference/research-factory-old-spec/`.

## Non-negotiable rules
- **The platform never calls a model.** No API keys, no model SDKs in `platform/`. All judgement comes from Claude through MCP tools.
- **Events are the source of truth.** Append-only JSONL under `projects/<slug>/events/`; never edit or delete an event; corrections supersede. The SQLite index is a rebuildable projection and is never written except by the projector.
- **Business logic lives in `platform/src/factory/services/`.** `mcp/` and `cli/` only parse input, call a service, and format output.
- **Validate at the boundary.** Invalid input writes nothing and returns structured errors.
- **Provenance everywhere:** every agent-written event carries model, skill version and `input_blob`.
- **Scripts never judge; agents never do bookkeeping.** Counts, hashes, PRISMA numbers are computed, never typed.

## Backlog
New ideas go to `docs/backlog.md` using its template. Do not implement a backlog item unless a slice spec includes it.

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
