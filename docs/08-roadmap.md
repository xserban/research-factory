# Roadmap

## Guiding rule
**Do one project by hand before automating.** Run one idea (e.g. "best linear attention for vision") end to end with Claude (a Project in claude.ai + Claude Code), using the designed processes but no factory code. Record every step, decision and correction. Then automate what was done repeatedly and keep humans where intervention was needed ("automate what you've done three times"). The pilot's corpus, regions and benchmark ledger are reused.

## Build tiers
**Tier 1 — saves PhD-level time; moderate effort**
- Living corpus per project with alerts
- Graph store with provenance and free labels (event log)
- Screening and extraction with span verification
- Benchmark ledger
- Related-work drafting from the graph

**Tier 2 — postdoc-level leverage**
- Region linking and transfer hypotheses (method cards ↔ problem descriptions)
- Reproducing baselines
- Experiments under pre-registered protocols (seeds, multiverse)
- Scheduled consolidation pass

**Tier 3 — towards "senior" capability**
- Autonomous hypothesis → test loops
- Many-analysts checks; positive/negative controls measuring the factory's error rates
- Budget allocation across projects
- Claim verification of own drafts

**Not now:** own models/agent framework, polished UI, full ontology, lab automation, fully autonomous paper writing.

## Phases
| Phase | Content |
| --- | --- |
| 0 | Planning (this folder); decisions in decisions.md |
| 1 | Manual pilot on one idea; workflow log |
| 2 | Stage-0 platform on one machine: event log, graph, ingestion, screening/extraction tools, MCP server, plugin; tier 1 |
| 3 | Second project in parallel; shared regions; teams (ownership, workspaces); stage-1 server |
| 4 | Tiers 2–3; experiments; GPU runners |

## Failure modes to design against
- Knowledge debt (unverified agent edges accumulate) → provenance + audits.
- Review bottleneck → earned autonomy + sampled audits.
- No ground truth → gold sets + controls.
- Over-trust in fluent output → quality system built in from the start.

## Immediate next steps
1. Create a claude.ai Project "Research Factory" (instructions + this folder's docs as knowledge files).
2. Create a private GitHub repo; `git init` this folder and push.
3. Decide the open items in decisions.md (event log, agents pull, ND vs. own programme for the thesis, pilot idea).
4. Design the data model: event types, core node/edge types, first MCP tools.
5. Run the manual pilot.

## Update 2026-10-31
Specs started: [specs/00-system.md](specs/00-system.md) (contracts), [specs/slice-1.md](specs/slice-1.md) (literature review tracer bullet), slice outline in [specs/README.md](specs/README.md). Manual pilot runs in parallel on research-factory-old (stages 00–04 work there today).

