# Software architecture (draft)

Principle: **a deterministic platform, with the intelligence outside it.** The platform stores, validates, schedules and logs; it never calls a model. All reasoning comes from Claude (subscriptions) calling the platform's tools. Consequences: no API keys, testable, model-provider independent.

## Overview

```
 Humans
    │
 ┌──▼───────────────────────────────────────────────────────────┐
 │ AGENT LAYER (Claude subscriptions)                           │
 │ Claude Code sessions (PC/server) · claude.ai chats           │
 │ Shared "factory plugin": skills, subagents, hooks, commands  │
 └──┬───────────────────────────────────────────────────────────┘
    │ MCP (tools)            CLI (humans, scripts, scheduler)
 ┌──▼───────────────────────────────────────────────────────────┐
 │ INTERFACE LAYER: MCP server · CLI · (later) dashboard        │
 ├──────────────────────────────────────────────────────────────┤
 │ DOMAIN SERVICES (Python, deterministic)                      │
 │ Ingestion · Graph · Claims & evidence · Projects & protocols │
 │ Quality · Experiments · Watch & alerts · Views & exports     │
 │ Work queue & policy (ownership, gates, autonomy, budgets)    │
 ├──────────────────────────────────────────────────────────────┤
 │ STORAGE                                                      │
 │ Event log (source of truth) → graph tables (projection)      │
 │ Blob store (PDFs, parsed text, artifacts) · Search index     │
 └──────────────────────────────────────────────────────────────┘
```

## 1. Storage
- **Event log (append-only) as source of truth.** Each event: actor (human/agent), session, model, timestamp, change, evidence. Graph = projection of events. Gives provenance, versioning/snapshots, per-person branches, replay, credit.
- **Graph tables:** nodes, edges, labels, properties (relational property graph; recursive SQL for neighbourhoods and paths). SQLite (via SQLAlchemy) first; Postgres for teams. No graph database needed at this scale.
- **Blob store:** PDFs, parsed full text, datasets, experiment outputs; content-addressed (hash).
- **Search index:** full text; embeddings optional (open decision #9 — if used, a local model chosen and evaluated for scientific text, no API).

## 2. Domain services
| Service | Responsibility |
| --- | --- |
| Ingestion | Adapters: OpenAlex, Semantic Scholar, arXiv, PubMed, Europe PMC, Zotero, local PDFs; parsing; de-duplication |
| Graph | Nodes, edges, free labels; synonym/entity merging; label promotion |
| Claims & evidence | Span verification, contradiction detection, certainty ratings |
| Projects & protocols | Focus, scope policy, registered protocols, deviations |
| Quality | Checks, gold-set regression suites, positive/negative controls, audit sampling |
| Experiments | Pre-registration, runs, seeds, outputs → graph (reuse an existing experiment tracker) |
| Watch & alerts | New papers, retractions, corrections; region subscriptions; digests |
| Views & exports | Onion, evidence/benchmark maps, digests; RO-Crate, nanopublication exports |
| Work queue & policy | Tasks (owner, priority, budget); region ownership; review gates; autonomy per task type |

## 3. Interfaces
- **MCP server (agents' API):** strict tools for the core (protocols, claims, screening decisions — each validates input) + generic graph tools (propose node / edge / label). Every call authenticated → actor recorded.
- **CLI:** humans, scripts, scheduled jobs.
- **Dashboard:** later; meanwhile views as generated pages/docs.

## 4. Agent layer
- **Shared Claude Code plugin** installed by every team member: skills (screening protocol, extraction codebook, method cards), subagents (screener, extractor, critic, method-card writer, experiment runner), hooks (log tool calls, run quality checks), commands.
- **claude.ai + connector:** interactive gates, review, planning.

## 5. Orchestration: agents pull work
- The platform keeps a **work queue**; agents call e.g. `next_task(project, role)`.
- Sessions (manual, scheduled, or on a server) process tasks until budget or usage limit; queue tracks progress so any later session resumes.
- Priority rules: joint work before solo; focus before outer regions; active before dormant projects.

## 6. Cross-cutting
- Identity and ownership from day one (users, roles, region owners).
- Personal workspaces → change sets → owner review → merge to shared graph. High-accuracy task types may auto-merge (earned autonomy).
- Releases: tagged point in the event log per project (for papers, theses).

## 7. Repository layout (monorepo)
- `platform/` — Python package: storage, services, MCP server, CLI
- `plugin/` — Claude Code plugin
- `domain-packs/` — vocabularies, extraction schemas, gold sets
- `projects/` — project configuration (focus, scope policy, protocols)
- Experiment code lives in each project's own repo, tracked by the platform.

## 8. Deployment stages
| Stage | Setup | When |
| --- | --- | --- |
| 0. Single machine | PC: SQLite + files; MCP server started locally by Claude Code (stdio). No Docker, no DB server | Pilot, one person |
| 1. Team | Server: MCP over HTTPS (connector), Postgres, shared blob store, PDF parser, scheduled sessions | ≥ 2 people |
| 2. Compute | GPU runners attached to the experiment service | Automated experiments |

## Key decisions (see decisions.md)
| Decision | Recommendation |
| --- | --- |
| Event log vs. editable tables | Simple event log + projected tables |
| Graph DB vs. relational | Relational first |
| Specific vs. generic tools | Strict for core, generic for graph |
| Platform launches agents vs. agents pull | Agents pull |
| Embeddings | Open (see decisions.md #9) |
| Build vs. reuse | Reuse APIs, parsers, reference manager, experiment tracker; build graph, provenance, quality system, queue, plugin |

## Next design step
Data model: event types, core node/edge types, first set of MCP tools.
