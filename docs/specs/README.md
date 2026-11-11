# Specifications

Two levels:
- **System contracts** ([00-system.md](00-system.md)) and **rigour requirements** ([01-rigour.md](01-rigour.md)) — fixed before any code; cross-cutting and binding on every slice.
- **Slice specs** — one per vertical slice, written in detail just before the slice is built. Each slice must produce working, tested software on its own. Implementation plans (superpowers `writing-plans`) are written per slice into `docs/plans/`.

## Slices

| Slice | Goal | Status |
| --- | --- | --- |
| 1 | **Literature review tracer bullet:** question → seeds → scope probe → versioned protocol → search (OpenAlex, arXiv) → dedup → dual title/abstract screening → PRISMA, trace, check | [Spec drafted](slice-1.md) |
| 2 | **Full text, extraction and evidence:** legal full-text acquisition, canonical documents with stable anchors, full-text screening, schema-driven extraction with verified quotes and numbers, dual extraction and audit, evidence/benchmark report with comparability groups; local literature library | [Spec approved](slice-2.md) |
| 3 | **Graph and regions:** references and snowballing ([3a](slice-3a-references.md)), contributions and lineage graph ([3b](slice-3b-lineage.md)), interpretation and concept layer ([3c](slice-3c-intuition.md)), regions, labels, consolidation and corpus import ([3d](slice-3d-regions-import.md)) | 3a–3c rulings adopted (G1 and G2-A partly built); [3d accepted 2026-11-04](slice-3d-regions-import.md) |
| 4 | **Living corpus:** link inbox and discovery provenance ([4a](slice-4a-inbox-discovery.md)); watches, updates, notices, conclusions and digests ([4b](slice-4b-living-corpus.md)); discovery feed ([4c](slice-4c-feed.md)) | [4a](slice-4a-inbox-discovery.md) and [4b](slice-4b-living-corpus.md) accepted 2026-11-04; [4c](slice-4c-feed.md) accepted 2026-11-11 |
| 5 | **Teams and deployment:** users, ownership, per-person workspaces and review, remote MCP connector on a server, budgets | [Accepted 2026-11-04](slice-5-teams-deployment.md) (built last) |
| 6 | **Hypotheses and testing:** method cards and problem descriptions, matching, leads, hypothesis registry, pre-registered experiments, benchmark ledger, failed-directions registry | [Accepted 2026-11-04](slice-6-hypotheses.md) |
| 7 | **Views and writing:** portfolio ([7a](slice-7a-portfolio.md)); onion and evidence views, writing from verified claims, exports, briefings ([7b](slice-7b-views-writing.md)) | [7a](slice-7a-portfolio.md) and [7b](slice-7b-views-writing.md) accepted 2026-11-04 |
| M | **Stage modules, gate policies and miners** (cross-cutting) | [Accepted 2026-11-04](slice-M-modules.md) |

All slices above were accepted on 2026-11-04 with their recommended rulings and cut to a v1 scope (decisions 55–75; the pilot is deferred, decision 74). Build order: [../plans/2026-11-05-build-order.md](../plans/2026-11-05-build-order.md). Each accepted spec opens with its cross-spec reconciliation and v1 scope.

**Outlines** (future, not binding): [grey literature](outlines/grey-literature.md).
