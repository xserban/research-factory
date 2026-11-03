# Specifications

Two levels:
- **System contracts** ([00-system.md](00-system.md)) and **rigour requirements** ([01-rigour.md](01-rigour.md)) — fixed before any code; cross-cutting and binding on every slice.
- **Slice specs** — one per vertical slice, written in detail just before the slice is built. Each slice must produce working, tested software on its own. Implementation plans (superpowers `writing-plans`) are written per slice into `docs/plans/`.

## Slices

| Slice | Goal | Status |
| --- | --- | --- |
| 1 | **Literature review tracer bullet:** question → seeds → scope probe → versioned protocol → search (OpenAlex, arXiv) → dedup → dual title/abstract screening → PRISMA, trace, check | [Spec drafted](slice-1.md) |
| 2 | **Full text, extraction and evidence:** legal full-text acquisition, canonical documents with stable anchors, full-text screening, schema-driven extraction with verified quotes and numbers, dual extraction and audit, evidence/benchmark report with comparability groups; local literature library | [Spec approved](slice-2.md) |
| 3 | **Graph and regions:** generic nodes, edges and free labels; regions and project foci; consolidation (synonym merging, label promotion); importing an existing corpus (Zotero/PDF folders) | Outline |
| 4 | **Living corpus:** scheduled re-runs, incremental updates, retraction/correction tracking, alerts and digests per region | Outline |
| 5 | **Teams and deployment:** users, ownership, per-person workspaces and review, remote MCP connector on a server, budgets | Outline |
| 6 | **Hypotheses and testing:** method cards and problem descriptions, cross-region matching, hypothesis registry, pre-registered tests, benchmark ledger, experiment tracking | Outline |
| 7 | **Views and writing:** onion and evidence/benchmark views, related-work drafting from verified claims, exports (BibTeX, RO-Crate, nanopublications) | Outline |

Order after slice 1 is provisional and is revisited after the slice-1 retrospective and the manual pilot.

**Outlines** (future, not binding): [grey literature](outlines/grey-literature.md).
