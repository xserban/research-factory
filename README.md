# Research Factory

Status: **planning** (no implementation yet). Last updated: 2026-10-31.

A research factory is a platform in which teams of researchers and AI agents run research projects end to end — literature search, corpus building, knowledge extraction, hypothesis generation and testing, keeping knowledge current — with full transparency, provenance and a built-in quality system. The intelligence comes from Claude (through Claude subscriptions); the platform itself is deterministic.

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
| [docs/backlog.md](docs/backlog.md) | Idea backlog: not yet in any spec |
| [docs/pilot/](docs/pilot/seeds.md) | Manual pilot (linear attention for vision): seeds, split, log |
| [docs/decisions.md](docs/decisions.md) | Decision log: decided, proposed, open |
| [docs/references.md](docs/references.md) | Literature and documentation |
| [docs/thesis-proposal.pdf](docs/thesis-proposal.pdf) | Draft MSc thesis proposal (first instance of the factory) |

The editable version of the thesis proposal is the Claude doc: https://claude.ai/artifact/P8GEeyE8C4ZQJDnyjmyCWW
