# Hub v2 — port of every old-hub page (IDEA-97, second part)

Date: 2026-11-19. Parent plan: `docs/plans/2026-11-18-hub-ui.md`. Acceptance list: `docs/plans/2026-11-18-hub-ui-parity.md` (347 elements, IDs such as `LC-3`).

## Goal

Every element of the old hub has a place in v2 or an explicit drop ruled by the researcher. The old pages are rebuilt in the v2 design, with new visualisations where they help. Nothing is lost silently.

## Rulings (researcher, 2026-11-18/19)

| # | Ruling |
|---|---|
| P1 | Seven new pages: **Protocol**, **Pipeline**, **Sources**, **Method**, **Costs & runs**, **Write & export**, **Platform**. Updates and every feed act go into **Living**. |
| P2 | Dropped: DB-29 (old Extraction tab), HM-7 (planned modules), DB-37 (static snapshot), FD-1 (feed pointer), HM-12 ("New hub" link, at cut-over), HM-18 (portal admin note). SE-12 (merge revert) stays read-only. |
| P3 | Protocol, decisions, PRESS, probes and deviations get their own page, first in the rail. |
| P4 | Overall stage sequences (LC-10) group m-lifecycle stage names onto the nine m-stages stages by a deterministic, visible name map; unmapped names show as "other". |
| P5 | Coordinator default (researcher accepts recommendations): the portal, project creation and project tabs (HM-14/15, FD-4, SV-7, SV-16) become a **project switcher in the shell**; the layer-moves replay (LY-3) joins **Flow › Replay** as a second track. |

## Pages and sources

| Page | Old pages | Service (new or extended) |
|---|---|---|
| Protocol | dashboard Protocol, Decisions, PRESS, Probes tabs; deviations | `hub_protocol.py` |
| Pipeline | Control room, Work queue (Process all, run stage, Preview, Resume, Interrupted), Activity (live) | `hub_pipeline.py` |
| Sources | Search and dedup, Acquisition, Conversion + inspector item pages, Documents | `hub_sources.py` |
| Method | Lifecycle (overall sequences + per paper), Steps, Taxonomy + registered versions and diffs | `hub_method.py` |
| Costs & runs | Costs, Runs | `hub_costs.py` |
| Write & export | Synthesis pages, Bibliography + BibTeX, Wiki vault, PRISMA SVG | `hub_write.py` |
| Platform | Capabilities, Backlog (hub level) | `hub_platform.py` |
| Living (+) | Updates, feed status, react, add, configure, run, refetch, watch configure, snapshot, inbox add | `hub_living.py` |
| Existing pages | 47 gap rows (parity section 33): Flow 16, Miners 15, Corpus 5, Overview 3, Living 3, Lenses 3, Explore 1, Graph 1 | `hub_screening`, `hub_mining`, `hub_payloads`, `hub_lenses` |

## Rules (binding, as in the parent plan)

- Numbers are computed by services and never typed (R-05). Every view's ⓘ text comes from the payload's `methods`.
- Payload services wrap existing services. They never re-derive a count that a service already computes.
- Acts go through the existing auth seam (`_ROUTES`, `_allowed`, `_layer_act` or the existing route), are allow-listed, and use inline confirmation. Invalid input writes nothing. No new event type.
- TDD for services. The page port brief applies to pages: `docs/plans/2026-11-18-hub-ui-port-brief.md`.
- Each task closes its parity rows. The reviewer checks the rows, not the summary.

## Steps

| Step | Content | Who / review |
|---|---|---|
| 0 | Shell: rail and palette entries for the seven pages, stub payloads registered in `BUILDERS`, `PAGES` and the rail; project switcher (P5); `HUB.act` wiring for routed acts | builder-critical; light review |
| 1 | Protocol page | builder; light review |
| 2 | Pipeline page with its acts | builder-critical; review with guard mutation |
| 3 | Sources page | builder; light review |
| 4 | Method page (LC-10 name map) | builder-critical; light review |
| 5 | Costs & runs page | builder; light review |
| 6 | Write & export page (downloads through routes) | builder-critical; light review |
| 7 | Platform page | builder; light review |
| 8 | Living additions with its acts | builder-critical; review with guard mutation |
| 9 | Gap fixes: Flow and Overview | builder |
| 10 | Gap fixes: Miners, Corpus, Lenses, Explore, Graph, Living | builder |
| 11 | Parity audit (every row checked against the code), gate, merge on the researcher's go | coordinator |

Two agents run at a time, each in its own worktree. Shared files (`shell.js`, `hub_ui.py`, `hub_build.BUILDERS`, `hub_serve`) are touched in step 0 only. Later steps fill in their own service and page files.

## Out of scope

- The switch-over, which needs the researcher's go.
- Removing old routes; they stay until the switch-over.
