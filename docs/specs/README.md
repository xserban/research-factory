# Specifications

Two levels:
- **System contracts** ([00-system.md](00-system.md)) and **rigour requirements** ([01-rigour.md](01-rigour.md)) — fixed before any code; cross-cutting and binding on every slice.
- **Slice specs** — one per vertical slice, written in detail just before the slice is built. Each slice must produce working, tested software on its own. Implementation plans (superpowers `writing-plans`) are written per slice into `docs/plans/`.

## Slices

| Slice | Goal | Status |
| --- | --- | --- |
| 1 | **Literature review tracer bullet:** question → seeds → scope probe → versioned protocol → search (OpenAlex, arXiv) → dedup → dual title/abstract screening → PRISMA, trace, check | [Spec drafted](slice-1.md) |
| 2 | **Full text and claims:** legal full-text acquisition (arXiv source, PMC, OA PDFs, own PDFs), normalised Markdown with stable anchors, schema-driven claim extraction with verified source spans; PubMed source | Outline |
| 3 | **Graph and regions:** generic nodes, edges and free labels; regions and project foci; consolidation (synonym merging, label promotion); importing an existing corpus (Zotero/PDF folders) | Outline |
| 4 | **Living corpus:** scheduled re-runs, incremental updates, retraction/correction tracking, alerts and digests per region | Outline |
| 5 | **Teams and deployment:** users, ownership, per-person workspaces and review, remote MCP connector on a server, budgets | Outline |
| 6 | **Hypotheses and testing:** method cards and problem descriptions, cross-region matching, hypothesis registry, pre-registered tests, benchmark ledger, experiment tracking | Outline |
| 7 | **Views and writing:** onion and evidence/benchmark views, related-work drafting from verified claims, exports (BibTeX, RO-Crate, nanopublications) | Outline |

Order after slice 1 is provisional and is revisited after the slice-1 retrospective and the manual pilot.
