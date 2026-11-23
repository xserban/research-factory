# Slice 4c: discovery feed (a ranked daily suggestion list per project)

**Status:** Accepted 2026-11-11 by the researcher with the recommended option of every ruling (the **[confirm]** marks are kept as a record); decision 118 (provisional number, fixed at merge); plan `docs/plans/2026-11-11-feed.md`. Takes in backlog IDEA-58 (port of arXiv Miner; recorded in the main checkout's `docs/backlog.md`, not yet committed) and the parts of IDEA-03 (digest delivery) that concern suggestions. Builds on [00-system.md](00-system.md), slices 4a (link inbox, discovery record) and 4b (watch cycles, digest), slice 8 (screening ranker, decision 116; core works), and must satisfy [01-rigour.md](01-rigour.md) R-01–R-05, R-13, R-20, R-22, R-26, R-34, R-100, R-101, plus the proposed requirements below. Decision: one new entry, numbered at acceptance.

## Problem

A project's corpus is fixed by its protocol searches, snowball rounds and supplied links. Slice 4b keeps it current by re-running the recorded queries. Nothing yet surfaces papers that the recorded queries do not reach but that sit close to what the project already holds: new arXiv listings in the project's categories, phrased in terms the queries did not foresee. The researcher's own tool, arXiv Miner (`~/Documents/Projects/arxiv-miner`), does this for one person and one interest profile: it fetches the daily arXiv listing of chosen categories, embeds titles and abstracts locally, ranks them by similarity to liked papers or to folders of reference PDFs, and learns from likes and dislikes. Its picks never reach a review.

## Goal

One feed engine, configured per project, that ranks new arXiv listings against the project's own core works. It records every fetch, ranking and reaction as an event, and lets the researcher send a chosen paper into the project. From there the paper takes the existing path: inbox, `supplied` lookup, screening, full text, extraction. The feed suggests and the researcher selects; the feed never includes, excludes or extracts. The platform calls no model: fetching and ranking are deterministic and run offline from supplied weights. Agent work starts only after a paper is sent.

## Two intake channels (context)

| | Protocol channel (built, slice 4b) | Discovery channel (this slice) |
|---|---|---|
| What runs | the protocol's planned queries, re-run per `watch_plan` | the daily listing of declared arXiv categories |
| Enters the corpus | every retrieved record, as a pending work | only papers the researcher sends, via the inbox (`supplied`) |
| PRISMA | identification, `database` | other methods, `supplied` |
| Reproducible from the protocol | yes (R-27 replay) | no; disclosed as discovery (R-100, R-101) |

A paper that both channels surface counts once, under `database` (4a reconciliation item 2).

## User flow

1. **Configure.** The researcher records a feed configuration for the project: arXiv categories, the reference set, the number of items shown per day, the exploration share and the cadence (`factory feed configure`; human event).
2. **Fetch and rank.** An external timer calls `factory feed run --due --all`. For each due project, the platform fetches the new listings of the categories since the last complete fetch, removes papers the project already holds (by identifier, then by normalised title), embeds the remainder with the ranker model of decision 116, scores each against the reference set, and records the ranked list. There is no model call and no agent.
3. **Review the feed.** `factory feed show [--project]` and the MCP `feed_list` show the top items with their score, the nearest reference work (why the paper matched) and an `explore` label on exploration picks. The 4b digest gains a feed section (top items per project).
4. **React.** The researcher records `like`, `dislike`, `save` or `dismiss` (`factory feed react ID …`). Reactions are human events and record the rank and score that were shown.
5. **Send.** `factory feed send ID [--note]` adds the paper to the project's link inbox (channel `feed`). `inbox_resolve` looks it up as a `supplied` query under the protocol's `supplied_links` gate, and the paper enters the corpus as a pending work.
6. **Downstream (unchanged).** Title/abstract screening (blind to route and note, 4a ruling 8), full text, extraction, miners and lineage. These run in an agent session the researcher starts, or in a scheduled agent routine outside the platform.
7. **Grow the references.** A sent paper that is included and marked core (a human act, `core_works`) joins the reference set, and the next ranking uses the new version.

## Rulings

1. **Feed entries are not corpus records [confirm].** (a) *Recommended:* fetched listings are kept in a feed store (`feed_entries`, a projection of `feed.fetched` events, with raw responses archived as blobs per R-03). They are outside the corpus, outside PRISMA and outside dedup, as probe sample titles are (slice 8). A paper enters the corpus only when it is sent, through the `supplied` lookup. (b) Treat a feed fetch as a watch search run, so that every listing becomes a pending work. Rejected: a category listing returns hundreds of papers a day, most outside scope, and would flood screening and identification counts with records no protocol query selected.
2. **Sources in v1 [confirm].** v1 supports the arXiv category listing only, windowed by submission date with a declared overlap (as 4b ruling 2), through the existing arXiv client and throttle. Free-text feed queries and other sources (OpenAlex concepts, bioRxiv) come Later. A feed query is never a protocol query and never authorises one.
3. **Reference set [confirm].** (a) *Recommended:* the reference set is the project's core works (`forward_core_sources`: the researcher's included core marks plus development positive seeds), and optionally its included works when the configuration says `references: core+included`. Its membership is hashed and recorded on every ranking. Held-out seeds are never references (R-20). A held-out seed's work that is already in the corpus is filtered out of the feed as held, like any corpus work, so the feed reveals nothing about it. (b) Folders of PDFs as in arXiv Miner. Rejected for v1, because a folder outside the project gives no provenance. The same need is met by importing the PDFs (plan PI) and marking them core.
4. **Topics [confirm].** A topic is a named subset of the reference set (for example, the core works of one region (slice 3d) or one reference layer). Each feed item records its best-scoring topic. v1 supports a single topic, the whole set. Named topics come Later.
5. **Scoring [confirm].** v1 uses the scorer of decision 116 unchanged: SPECTER2 from local weights, `title [SEP] abstract`, a score equal to the maximum cosine similarity to any reference, and ties broken by arXiv id. arXiv Miner's 384-dimension sentence model is not ported, so that the feed and the screening ranker share one embedding space and one cache. `feed.ranked` records the model, the weight tree hash, library versions, the parameters, the reference-set hash and the order blob. Fixed inputs give the same order.
6. **Exploration [confirm].** (a) *Recommended:* the configuration declares an exploration share (default 10 per cent of the items shown). Those slots are filled by a seeded random draw from the items ranked below the shown cut-off. The seed is recorded, and each pick is labelled `explore` wherever the feed is shown. This counters the narrowing of a ranker trained on its own picks. (b) No exploration. Rejected: once a learned ranker exists (ruling 8), a feed without exploration can only confirm the reference set.
7. **Reactions are human events [confirm].** `feed.reacted` carries the entry, the reaction (`like`, `dislike`, `save`, `dismiss`), the ranking id, and the rank and score shown. A non-human actor is refused, and the fold ignores an agent-written reaction (as `core_works`). Reactions are kept even when a later ranking supersedes the list. Whether the researcher took the top item, an exploration pick or a low-ranked one is computed, so that anchoring can be measured (slice 8 rigour).
8. **Learned preference ranker [confirm].** (a) *Recommended:* Later. Port it once a project has recorded at least 5 reactions with at least 3 likes (arXiv Miner's threshold), and only then. It is arXiv Miner's `Ranker` (running-average profile, then logistic regression on cosine, metadata and novelty features) with a fixed random state. Every training writes `feed.ranker_trained` (training-set hash, feature list, library versions, state blob). Ranking stays reproducible from events. The learned ranker only orders the feed. It never orders a screening queue and never touches seeds. (b) Build it in v1. Rejected, because without reactions it reduces to the similarity baseline.
9. **Like and send are separate acts [confirm].** (a) *Recommended:* a like teaches the ranker; a send names a project and starts the review path. A paper may be liked without being sent (interesting but out of scope) and sent without being liked. (b) A like implies a send. This is simpler, but it mixes "close to my interests" with "within this project's scope" and would push out-of-scope papers into screening, where they would be excluded at cost.
10. **Send goes through the inbox [confirm].** `feed_send` writes the inbox item (`inbox.item_added`, channel `feed`, carrying the feed entry and ranking ids) and nothing else. Resolution, the `supplied_links` gate, corpus entry, blind screening, the discovery record and PRISMA all follow slice 4a unchanged. The discovery report adds the channel `feed` under the route `supplied`, and the methods report states how many included works came only through the feed. In `systematic` mode, sending is possible only when the protocol's `supplied_links` permits supplied works.
11. **Schedule and cost [confirm].** `factory feed run [--project SLUG | --all] [--due] [--dry-run]` mirrors `watch run` (4b ruling 5): no daemon, a per-project lock, and exit codes 0, 1 and 2. One fetch per (category, day) is cached at the projects root and shared by all projects. The cache is not a source of truth: each project records its own `feed.fetched` with the raw blob hash. The MCP `feed_run` exists for an open session. No agent runs in the feed cycle. Screening and extraction of sent papers run only when an agent session (interactive or scheduled) picks up the pending work.
12. **Scope-drift signal [confirm].** The platform computes, per project, the share of sent papers excluded at title/abstract screening and the number of liked papers never sent. When the first exceeds a declared threshold over a declared minimum count, `check` and the digest raise `feed-scope-drift`. This is a count, not a judgement. The finding points to a protocol amendment through suggest and select (slice 8). The feed never widens or narrows the criteria on its own.
13. **Configuration is outside the protocol [confirm].** (a) *Recommended:* `feed.configured` is a project event (human), not a protocol section. The feed changes nothing the protocol identifies; what it adds enters through `supplied`, which the protocol already governs. (b) A protocol section, as `watch_plan`. Rejected: every change of categories or exploration share would then be a protocol amendment, without any gain in reproducibility.

## Events (sketch)

- `feed.configured` (human): `categories[]`, `references` (`core` | `core+included`), `shown_per_cycle`, `exploration_share`, `interval_days`, `overlap_days`, `drift_threshold`, `drift_min_count`.
- `feed.fetched` (system): `source`, `categories[]`, `window` (from, to), `raw_blob`, `count`, `held_count` (dropped as already in the corpus).
- `feed.ranked` (system): `fetch_ids[]`, `reference_hash`, `reference_count`, model, weight hash, library versions, parameters, `exploration_seed`, `order_blob`, `shown[]`.
- `feed.reacted` (human): `entry_id`, `reaction`, `ranking_id`, `rank_shown`, `score_shown`.
- `feed.sent` (human): `entry_id`, `ranking_id`, `inbox_item_id`, `note`. It is written together with `inbox.item_added`.
- Later: `feed.ranker_trained` (system).

Projection: `feed_entries`, `feed_rankings`, `feed_reactions`. `PROJECTION_VERSION` goes up by one.

## Surfaces

- CLI: `factory feed configure | run | show | react | send | status`.
- MCP: `feed_list` (agent view: no held-out information; refused to pass sessions as in decision 101), `feed_run`, `feed_status`. There is no MCP `feed_react` or `feed_send`, since both are human acts. Where the client supports MCP elicitation, they may be offered as in slice 8.
- Digest (4b): a feed section per project with the top items, exploration picks, open sends awaiting resolution and the drift finding.
- Site hub (IDEA-54, IDEA-55): the Daily updates page with react and one-click add, the work queue and Process now are built by plan `2026-11-11-feed-hub.md` under decision 119.

## Proposed requirements (numbered at acceptance)

- **R-F1.** A feed item never enters the corpus, PRISMA or screening except through a human send and the `supplied` lookup.
- **R-F2.** Every ranking shown to the researcher can be reproduced from events: model and weight hash, reference-set hash, parameters, exploration seed.
- **R-F3.** Reactions and sends are human events. An agent can neither write them nor have them take effect.
- **R-F4.** Held-out seeds never serve as references, and the feed reveals nothing about them.
- **R-F5.** The share of included works that came through the feed is reported in the methods statement and the discovery report.

## v1 scope

- **v1:** configuration, arXiv category fetch with shared cache, held filter, SPECTER2 ranking against core works, exploration picks, reactions, send to inbox, digest section, drift finding, CLI and MCP surfaces, acceptance on offline fixtures (network tests marked `network`).
- **Later:** learned preference ranker (ruling 8), named topics (ruling 4), other sources and free-text feed queries (ruling 2), hub page, metadata enrichment (h-index, citation counts; IDEA-57), cross-project view of one day's feed (IDEA-01).

## Acceptance (sketch)

On a fixture project with three core works and a recorded arXiv listing of about 200 papers, five of them already in the corpus:
1. `feed run` records one fetch and one ranking, and the five held papers do not appear.
2. A second run on the same inputs gives the same order and the same event payloads (except ids and times).
3. The shown list has the declared exploration share, labelled `explore`.
4. An agent-written reaction is refused and is ignored on rebuild.
5. A sent paper becomes an inbox item, resolves as `supplied`, enters screening blind to the route, and appears in PRISMA under other methods and in the discovery report under channel `feed`.
6. Excluding most sent papers raises `feed-scope-drift` once the threshold is met.

## Open questions

1. Retention: how long unreacted feed entries and their raw blobs are kept (arXiv Miner keeps everything; a lab with several projects may not want to).
2. Should a dislike become a suggested negative seed (through a slice 8 suggestion set), or stay a feed-only signal? Recommended: feed-only in v1.
3. Shared reactions across projects: a like is about the researcher's interest, not one project. Should the learned ranker (Later) train per researcher across projects or per project?
4. Port of arXiv Miner's tests: the ranker and topic-ranker tests come with the code when ruling 8 is built (CLAUDE.md, Reuse), adapted to events.

## Not in this slice

Changes to the protocol channel (slice 4b), screening order by feed score (R-34; the screening ranker of decision 116 is separate), any automatic send, and any agent step inside the feed cycle.

## Status notes (dated; rulings above are not rewritten)

- 2026-11-23, ruling 8 (learned preference ranker): built for the factory scope, reviewed, merged to main (PR #35). Scope as built: a general like/dislike ranker over the factory pool, training by button only (never automatic), dislikes only as negatives (plan assumption A1), project pages ordered by core-work similarity without learning. Decision 169 decided (2026-11-23). See `docs/plans/2026-11-23-factory-feed.md` (section 8, build notes). Per-project learned ranking is not built.
- 2026-11-23, "cross-project view of one day's feed" (IDEA-01, Later): built for the factory scope as the main-hub `/feed/` Today list, with project badges. See the same plan and IDEA-58 in `docs/backlog.md`.
