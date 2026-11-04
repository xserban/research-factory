# Build Order of the Remaining Plans (MVP v1)

Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted). Decisions 74 and 75.

This plan orders every plan still to build: the remaining tasks of G1, G2 and G3, the two clean-up plans, and the plans of slices M, 3d, 4a, 4b, 5, 6, 7a and 7b. It adds no task of its own. Each listed plan keeps its own tasks, tiers and review rules; "v1 tasks" counts the tasks above each plan's `## Later (not v1)` section.

## Rules that hold for every plan below

1. **Projection version.** The built value is `PROJECTION_VERSION = "22"` (G2-A Task 3). A plan marked "bumps" raises `PROJECTION_VERSION` by one from the value it finds on its base when the bumping task starts, and updates the pin test. Values named in a plan (G2-C 23, G2-D 24, G3-A 25, G3-B 26, …) are the values expected when nothing else lands in between; when a parallel branch merged a bump first, the later branch rebases and bumps again from the new value. No other rule numbers the projection.
2. **Module declarations.** Plans merged before M-A are declared by M-A Task 6, which declares every module present on its base. Every plan merged after M-A declares its event types, task kinds, protocol sections, check codes and decision gates in `services/modules/<name>.py` in the same task that adds them; slice M's ownership test fails otherwise. Gate ids, floors and presets are those of the slice-M reconciliation table.
3. **Shared names fixed by the reconciliation (decision 75).** Other-methods precedence `citation-chase`, `seed-admission`, `hand-search`, `supplied`, `library-import` after `database`; epistemic classes `evidence`, `interpretation`, `organisation`, `test`; ids `mim_` (mining import) and `lbl_` (label application); `benchmark_ledger` (slice 6) beside `ledger` (slice 5); experiment plans XP-A and XP-B beside export plans X-A and X-B; mining store root `<root>/.mining/`.
4. **Later work.** Pilot runs, manual or real-server steps, client tests, scale-only tasks and cross-project reuse are in each plan's Later section (decision 74). They are built after every v1 row below, in the order of the last table. `network`-marked fact tests stay in v1.
5. **Constraints from the researcher.** Slice M's first plan (M-A, the deduplication of quality code) starts only after G2 and G3 are merged. Slice 5 is built last.

## v1 order

Rows are in dependency order; a row may start once every plan in its "depends on" cell is merged. "Parallel with" names rows that may run at the same time in separate worktrees.

| # | Plan | Depends on | v1 tasks | Bumps projection | Can run in parallel with |
|---|---|---|---|---|---|
| 1 | `2026-11-05-cleanups.md`, remaining Tasks 1–2 (test helpers; Tasks 3–9 merged) | plan D | 2 | n | 2, 3, 4, 5 |
| 2 | `2026-11-04-references-snowballing.md` (G1), remaining Tasks 7–10 (Task 7 in progress); Task 10's pilot part is Later | G1 Tasks 1–6 (built) | 4 | n | 1, 3, 4, 5 |
| 3 | `2026-11-05-cleanups-2.md` | base `4c20a14`; Tasks 4–5 after G2-A Task 3 (built) | 8 | y (per task that adds a table) | 1, 2, 4, 5 |
| 4 | `2026-11-05-exports-a-bibliography-prisma.md` (X-A) | slices 1–2 | 5 | n | 1–3, 5–14 |
| 5 | `2026-11-05-portfolio.md` (7a) | plans 2C–2E | 5 | n | 1–4, 6–14 |
| 6 | `2026-11-05-lineage-a-contribution-pack.md` (G2-A), remaining Tasks 4–5 | G1 merged (row 2) | 2 | n | 3, 4, 5, 13 |
| 7 | `2026-11-05-lineage-b-contributions.md` (G2-B) | 6 | 5 | n | 4, 5, 13 |
| 8 | `2026-11-05-lineage-c-relations-ideas.md` (G2-C) | 7 | 6 | y (expected 23) | 4, 5, 13 |
| 9 | `2026-11-05-lineage-d-graph.md` (G2-D) | 8 | 5 | y (expected 24) | 4, 5, 13 |
| 10 | `2026-11-05-lineage-e-check-acceptance.md` (G2-E); Task 4 (pilot run) is Later | 9 | 4 | n | 11, 4, 5, 13 |
| 11 | `2026-11-05-intuition-a-interpretations.md` (G3-A) | G1, G2-A–G2-D (rows 2, 6–9) | 7 | y (expected 25) | 10, 4, 5, 13 |
| 12 | `2026-11-05-intuition-b-concepts.md` (G3-B), then `2026-11-05-intuition-c-layer-acceptance.md` (G3-C; its pilot part is Later) | 11; G3-C also 10 | 6 + 6 | G3-B y (expected 26); G3-C n | 4, 5, 13 |
| 13 | `2026-11-05-inbox-discovery.md` (4a) | cleanups-2 Tasks 1–2 (row 3); G1 Tasks 1–6 | 10 | y | 4–12 |
| 14 | `2026-11-05-modules-a-contract-quality.md` (M-A) | G2 and G3 merged (rows 6–12); clean-ups (rows 1, 3) | 7 | n | 4, 5 |
| 15 | `2026-11-05-modules-b-gate-policies.md` (M-B) | 14; G1 | 6 | y | 4, 5 |
| 16 | `2026-11-05-modules-c-miner-spec.md` (M-C) | 15; G2-A | 7 | y if Task 6 adds a table | 17, 20, 23, 27 |
| 17 | `2026-11-05-modules-d-authored-miners.md` (M-D) | 16 | 7 | y | 20–30 |
| 18 | `2026-11-05-import-a-parse-archive.md` (3d Import-A) | 15; slice 1, plan 2A | 6 | y | 16, 17, 20, 23, 27 |
| 19 | `2026-11-05-import-b-resolve-admit.md` (Import-B), then `2026-11-05-import-c-coverage.md` (Import-C) | 18; G1; 4a (row 13) | 6 + 5 | Import-B y; Import-C n | 20–30 |
| 20 | `2026-11-05-regions-a-rules-snapshots.md` (Regions-A) | 15; 18 (for the `import` rule); G2-D, G3-B | 6 | y | 16, 17, 19, 23–30 |
| 21 | `2026-11-05-regions-b-members-links-adoption.md` (Regions-B) | 20 | 4 | y | 19, 22, 23–30 |
| 22 | `2026-11-05-regions-c-labels-consolidation.md` (Regions-C) | 20 (21 first for its acceptance); G2-C, G3-B; Import-B optional | 6 | y | 19, 21, 23–30 |
| 23 | `2026-11-05-living-a-watch-cycles.md` (4b living-A) | 15; G1; slice 2 | 6 | y | 16–22, 27–30 |
| 24 | `2026-11-05-living-b-updates-prisma.md` (living-B) | 23; 4a (row 13) | 6 | y | 25, 19–22, 27–30 |
| 25 | `2026-11-05-living-c-notices-versions.md` (living-C) | 23; plans 2A–2E; G2 | 6 | y | 24, 19–22, 27–30 |
| 26 | `2026-11-05-living-d-conclusions-digest.md` (living-D) | 24, 25; plan 2E | 6 | y | 19–22, 27–30 |
| 27 | `2026-11-05-hypotheses-a-cards.md` (6 H-A) | 15; plans 2D, 2E; G2-A–G2-C | 5 | y | 16–26 |
| 28 | `2026-11-05-hypotheses-b-matching-finders.md` (H-B) and `2026-11-05-hypotheses-c-leads-registry.md` (H-C) | 27; H-C also G2, G3, M-B | 6 + 7 | y, y | each other; 19–26, 30 |
| 29 | `2026-11-05-experiments-a-design-runs.md` (XP-A), then `2026-11-05-experiments-b-evaluation-registry.md` (XP-B) | 28 (H-C; XP-B also H-B); plan 2E | 7 + 8 | y, y | 19–26, 30 |
| 30 | `2026-11-05-views-a-contract-onion.md` (V-A) | G2-D, G3-C; Regions-B (row 21, `regions_of`) | 5 | n | 19, 22–29 |
| 31 | `2026-11-05-views-b-coverage-horizon.md` (V-B) | 30; plan 2E; G2-C/D; living-A (row 23) | 5 | n | 24–29 |
| 32 | `2026-11-05-writing-a-outline-drafts.md` (W-A) | 31; G1, G2, G3 | 6 | y | 24–29 |
| 33 | `2026-11-05-writing-b-verification-release.md` (W-B) | 32; X-A (row 4); M-B | 7 | y | 24–29 |
| 34 | `2026-11-05-deploy-a-hosting-sequencer.md` (5 deploy-A) | every row above merged (slice 5 last) | 5 | y | — |
| 35 | `2026-11-05-teams-a-identity-access.md` (teams-A) | 34 | 6 | y (project index; the lab index has its own version) | — |
| 36 | `2026-11-05-deploy-b-remote-mcp.md` (deploy-B) | 35 | 6 | n | 37, 38, 39 |
| 37 | `2026-11-05-teams-b-review-workspaces.md` (teams-B) | 35; M-B | 4 | y | 36, 38, 39 |
| 38 | `2026-11-05-teams-c-screening-teams.md` (teams-C) | 35; 37 for `full_view_allowed` (else its own) | 5 | y | 36, 39 |
| 39 | `2026-11-05-teams-d-ledger-budgets.md` (teams-D) | 35 | 4 | y | 36, 37, 38 |
| 40 | `2026-11-05-deploy-c-lab-library.md` (deploy-C) | 34–39 | 5 | y | — |

v1 total: 2 + 4 + 8 + 5 + 5 + 2 + 5 + 6 + 5 + 4 + 7 + 12 + 10 + 7 + 6 + 7 + 7 + 6 + 11 + 6 + 4 + 6 + 6 + 6 + 6 + 6 + 5 + 13 + 15 + 5 + 5 + 6 + 7 + 5 + 6 + 6 + 4 + 5 + 4 + 5 = 250 tasks.

Parallelism in practice: rows 1–5 and 13 run beside the G-series; once M-B (row 15) is merged, four tracks run side by side (import 18–19, regions 20–22, living 23–26, hypotheses 27–29), and the views-and-writing track (30–33) starts when Regions-B and living-A are in. Slice 5 (34–40) starts only when all of these are merged.

## Later (not v1)

Built after row 40, in this order. Each entry is the Later section of the named plan (or the whole plan where it has no v1 task).

| # | Plan | Later work | Depends on |
|---|---|---|---|
| L1 | `2026-11-05-modules-e-shared-store.md` (M-E, whole plan, 6 tasks) | shared mining store, `mine import`, `source-superseded`, scale | M-D |
| L2 | `2026-11-05-regions-b-members-links-adoption.md` L1 | region adoption across projects | Regions-B |
| L3 | `2026-11-05-hypotheses-a-cards.md` L1 | cross-project card import | H-A |
| L4 | `2026-11-05-exports-b-crate-nanopub.md` (X-B, whole plan, 4 tasks) | RO-Crate, nanopublications | X-A, W-B |
| L5 | `2026-11-05-views-c-briefings.md` (V-C, whole plan, 4 tasks) | briefings, context packs | V-B, W-B |
| L6 | `2026-11-05-writing-c-manuscript-check.md` (W-C, whole plan, 5 tasks) | external manuscript verification | W-B, G1 |
| L7 | `2026-11-05-living-a-watch-cycles.md` L1; `2026-11-05-living-d-conclusions-digest.md` L1 | scale tests | living-D |
| L8 | `2026-11-05-living-b-updates-prisma.md` L1 | priority hints, after a decision reconciling them with R-34 | living-B |
| L9 | `2026-11-05-deploy-b-remote-mcp.md` L1 | OAuth resource server; recorded client-session test (spec open question 1) | deploy-B |
| L10 | Pilot and manual steps: G1 Task 10, G2-E Task 4, G3-C Task 6 pilot parts; `2026-11-05-regions-c-labels-consolidation.md` L1; `2026-11-05-living-d-conclusions-digest.md` L2; `2026-11-05-deploy-c-lab-library.md` L1; slice-6 and slice-7b pilots (spec v1 scopes) | real-data pilots on the linear-attention question and the lab-server pilot | everything above; the pilot hold-out rules of CLAUDE.md apply |
