# Research Factory

Status: **in development**. The platform is implemented through the evidence, miner, lineage, living-corpus and hub layers (see [docs/build-status.md](docs/build-status.md) and the generated module map [docs/MAP.md](docs/MAP.md)); a pilot on agentic-science literature is under way, and a second, biomedical pilot is being prepared. Licence: MIT.

A research factory is a platform in which teams of researchers and AI agents run research projects end to end — literature search, corpus building, knowledge extraction, hypothesis generation and testing, keeping knowledge current — with full transparency, provenance and a built-in quality system. The intelligence comes from Claude (through Claude subscriptions); the platform itself is deterministic.

## How it works

- **The platform never calls a model.** Every judgement (screening, extraction, interpretation, hypotheses) comes from an AI agent or a
  researcher through MCP tools or the command line, and is recorded with its provenance (model, skill version, input blob). Scripts
  compute counts, hashes and statistics; agents never do bookkeeping.
- **Events are the source of truth.** Append-only JSONL files under `projects/<slug>/events/`; nothing is edited or deleted, and
  corrections supersede. The SQLite index is a projection that can be rebuilt from the events and is written only by the projector.
- **Business logic lives in `platform/src/factory/services/`.** `mcp/` and `cli/` parse input, call a service and format output.
- **Sources:** arXiv, OpenAlex, Crossref, PubMed with PMC and Europe PMC full text. The contact address configured for polite API
  use is never sent to any outside host.
- **Interpretation layers are labelled.** Miner rows from uncalibrated miners, taxonomies and the technique landscape are exploratory:
  they never enter counts that a report uses.

## Getting started

```
cd platform
uv sync
uv run factory --help          # the command line (MCP server: `factory serve`)
uv run pytest tests/test_<file>.py        # run test files one at a time
uv run ruff check src tests && uv run mypy --strict src
```

The project hub is a local web server over `<repo>/data` (or `$FACTORY_DATA`): `scripts/hub.sh` serves the portal at
`http://127.0.0.1:8766/`, and the new hub UI at `/p/<slug>/ui/`. Products build when opened. Pilot data are not part of the repository.

New to the code: read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (how the parts fit), then [docs/MAP.md](docs/MAP.md) (where each
module, event, table, tool, command and skill lives; generated, never edited by hand: `uv run --project platform python scripts/gen_map.py`).
Plans are in [docs/plans/](docs/plans/), the decision log in [docs/decisions.md](docs/decisions.md), ideas not yet in a spec in
[docs/backlog.md](docs/backlog.md).

## Contents

| File | Content |
| --- | --- |
| [docs/00-vision.md](docs/00-vision.md) | Goal, what "automating a lab" means, properties of the ideal factory |
| [docs/01-concepts.md](docs/01-concepts.md) | Knowledge graph, regions, focus, onion view, typing, processing depth, projects |
| [docs/02-production-lines.md](docs/02-production-lines.md) | The repeatable pipelines the factory runs, and their priority |
| [docs/03-methods-catalogue.md](docs/03-methods-catalogue.md) | Concepts borrowed from software factories and from research methodology |
| [docs/04-architecture.md](docs/04-architecture.md) | Software architecture: layers, storage, services, interfaces, orchestration, deployment |
| [docs/05-tooling-and-workflow.md](docs/05-tooling-and-workflow.md) | Claude subscription, Claude Code, sessions, subagents, cloud, costs |
| [docs/06-teams.md](docs/06-teams.md) | Ownership, interfaces between researchers, coordination, credit |
| [docs/07-research-programme.md](docs/07-research-programme.md) | Our research projects and their graphs (TAVI, linear attention, angiography, ND thesis) |
| [docs/08-roadmap.md](docs/08-roadmap.md) | Build tiers, phases, next steps |
| [docs/09-existing-assets.md](docs/09-existing-assets.md) | Review of existing projects (arxiv-miner): what to extract, what not |
| [docs/10-abstractions.md](docs/10-abstractions.md) | Abstractions across all specs (artifacts, stage modules, gates, miners, builders) for brainstorming; background, not binding |
| [docs/specs/](docs/specs/README.md) | System contracts, slice specs and slice roadmap |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the parts fit: layers, events, index, services, interfaces |
| [docs/MAP.md](docs/MAP.md) | Generated map of modules, events, tables, tools, commands and skills |
| [docs/plans/](docs/plans/) | Implementation plans, one per slice or feature |
| [docs/backlog.md](docs/backlog.md) | Idea backlog: not yet in any spec |
| [docs/pilot/](docs/pilot/seeds.md) | Manual pilot (linear attention for vision): seeds, split, log |
| [docs/decisions.md](docs/decisions.md) | Decision log: decided, proposed, open |
| [docs/references.md](docs/references.md) | Literature and documentation |
| [docs/thesis-proposal.pdf](docs/thesis-proposal.pdf) | Draft MSc thesis proposal (first instance of the factory) |

