# Research Factory

Status: **in development**. The platform is implemented through the evidence, miner, lineage, living-corpus and hub layers (see [docs/build-status.md](docs/build-status.md) and the generated module map [docs/MAP.md](docs/MAP.md)); slice 9 (tiers and autonomy levels) is built on the integration branch `tiers-base`, not yet on main and not yet run live; a pilot on agentic-science literature is under way, and a second, biomedical pilot is being prepared. Licence: MIT.

A research factory is a platform in which teams of researchers and AI agents run research projects end to end — literature search, corpus building, knowledge extraction, hypothesis generation and testing, keeping knowledge current — with full transparency, provenance and a built-in quality system. The intelligence comes from Claude (through Claude subscriptions); the platform itself is deterministic.

## How it works

A project moves through nine stages: frame, gather, screen, acquire, extract, understand, develop, write, maintain. Claude reads and judges through MCP tools, led by one skill per stage. The platform never calls a model. It records every act as an append-only event, computes every count from the events, and holds the gates that only a person may pass. The database is a copy that can be rebuilt from the events.

Gates are attribution plus platform refusal of agent actors on the MCP path, not authentication. The command line always records a human actor and cannot tell a person from an agent with a shell; MCP relay tools record the human who confirmed the act in the client (decision 37.6). Which gates an agent may pass depends on the rigor mode (exploratory, pilot, systematic), and is pinned in `platform/tests/test_gates_by_preset.py`. Two controls rest on documentation only: the researcher's go-ahead before a real snowball round, and the rule that an agent-registered hypothesis is never reported as confirmatory.

Tiers and autonomy levels (slice 9, on the integration branch `tiers-base`, not on main): a project may declare at `factory init` a tier (`brief`, `deep`, `pilot`, `systematic`), which fixes the rigour mode, the stage plan, the caps and the templates, and an autonomy level (`attended`, `supervised`, `autonomous`), which fixes who may close the gates that allow an agent and with which controls (a platform-drawn audit sample, a trust ledger with a stop rule, a deferred human review queue). The default is `attended` with no tier, which behaves as before. Every report carries a level statement that lists the steps its tier skipped and says what no human confirmed. `factory brief` and `factory conductor` run a tier one step at a time through outside `claude -p` processes; the platform calls no model. The rows that govern this (decisions 163 to 168 and others) are proposed and not yet ruled; the floors for `autonomous` are not yet filled, so that level changes no gate policy. Nothing has run live; see `docs/specs/slice-9-tiers-autonomy.md` and `docs/plans/2026-11-20-tiers-and-autonomy.md`.

New here? Open the hub page **Start here** (`/p/<slug>/ui/learn.html`; the served hub opens on it for a project with no work past setup), or run `factory tour` for the stage list with your progress and `factory tour --stage N` for one stage card. The overview map of the stages and loops is on the Platform page, tab "How it works".

Business logic lives in `platform/src/factory/services/`; `mcp/` and `cli/` parse input, call a service and format output. Sources: arXiv, OpenAlex, Crossref, PubMed with PMC and Europe PMC full text. The contact address configured for polite API use is never sent to any outside host. Outputs of uncalibrated miners, taxonomies and the technique landscape are labelled exploratory and never enter counts that a report uses.

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
| [docs/hub-guide.md](docs/hub-guide.md) | Building a hub page or view: design and chart rules (UX books, Tufte), copy, steps, speed budget, review loop |
| [docs/plans/](docs/plans/) | Implementation plans, one per slice or feature |
| [docs/backlog.md](docs/backlog.md) | Idea backlog: not yet in any spec |
| [docs/pilot/](docs/pilot/seeds.md) | Manual pilot (linear attention for vision): seeds, split, log |
| [docs/decisions.md](docs/decisions.md) | Decision log: decided, proposed, open |
| [docs/references.md](docs/references.md) | Literature and documentation |
| [docs/thesis-proposal.pdf](docs/thesis-proposal.pdf) | Draft MSc thesis proposal (first instance of the factory) |

