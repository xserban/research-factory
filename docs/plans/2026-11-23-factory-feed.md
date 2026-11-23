# Factory feed: a general like/dislike ranker and per-project scores in the main hub (plan, 2026-11-23)

Status: built on branch factory-feed, reviewed (fixes in), not merged. Extends IDEA-58 (port of arXiv Miner) and slice 4c (`docs/specs/slice-4c-feed.md`, rulings 4 and 8). Decision 169 proposed.

## 1. Goal

The main hub (`factory site serve --all`) gets a paper-feed page that works like the researcher's arXiv Miner. A Today list is ordered by one general classifier, trained on the researcher's likes and dislikes. Each card carries badges for the factory projects whose core works it resembles. Each project has its own page, ordered by similarity to that project's core works. In arXiv Miner a topic is a folder of reference PDFs; here it is a factory project.

## 2. Rulings (researcher, 2026-11-23)

1. **Storage.** General reactions and the general ranker live in a new factory-level event log, not in a project. This extends `00-system` §4.1, which keeps events per project only (decision 169, proposed).
2. **Layout.** arXiv Miner's layout:
   - Today, ordered by the general classifier, with project badges;
   - one page per project, ordered by that project's score;
   - Liked and Reading list in the sidebar.
3. **Project scores.** Core works only. A project's score is similarity to its core works, as the feed computes today. It does not learn from reactions, as in arXiv Miner's topics. Only the general classifier learns.
4. **Training.** Training happens only when the researcher presses Train, never automatically.

Assumptions taken from arXiv Miner. The researcher may overrule them at review.
- A1. Only dislikes are negatives. Papers that were shown and skipped are not negatives.
- A2. Training needs at least 5 reactions, of which at least 3 are likes (slice 4c ruling 8).
- A3. Before the first training, Today is ordered newest first.
- A4. The badge line is a weak-match slider, default 0.5, kept in the browser. It hides nothing; it only decides which badges show.

## 3. What exists (survey, 2026-11-23)

- Feed engine (slice 4c, decision 118): `services/feed.py`. It provides:
  - a per-project `feed.configured` with categories and a reference set (core, or core plus included);
  - `feed_run` and `feed_run_all`, with an arXiv category listing shared across projects (`feed.py:305`);
  - a ranking by maximum SPECTER2 cosine to the reference set, with a seeded exploration share;
  - `feed.reacted` (like, dislike, save, dismiss; rank and score shown; `beyond_shown`);
  - `feed.sent` to the link inbox, and the one-click add.
- Main hub: a `/feed/` page (`services/site_hub_feed.py`) with one tab per project. Reactions are POSTed to `/p/<slug>/api/feed/react` with the project token (`site_server.py:57-61`). It uses the old site chrome, not the IDEA-97 design system.
- Not built:
  - any consumer of reactions in scoring;
  - `feed.ranker_trained` (planned in slice 4c ruling 8);
  - an event log at factory level;
  - a cross-project list;
  - a reading list or Liked view.

## 4. Design

### 4.1 Factory scope (decision 169)
- Layout: `<factory root>/factory/` mirrors a project directory:
  - `events/<actor>/<session-ULID>.jsonl`
  - `blobs/sha256/…`
  - `.index/factory.sqlite`
- Envelope: unchanged. `project` is the reserved value `_factory`. The slug is reserved, and `factory init` refuses it.
- Allow-list: the factory scope accepts only the `feed.*` area: `feed.reacted`, `feed.ranked`, `feed.ranker_trained`. Any other type is refused at the boundary.
- Projection: the factory index has its own projector and its own `FACTORY_PROJECTION_VERSION`. Project projection bumps therefore never rebuild it, and the reverse.
- Reader and writer: they take a scope root instead of a slug. A project is one scope; the factory is another. No service gains a second code path for writing.

### 4.2 Pool
- Today's pool is the union of the arXiv entries fetched for all projects, from the shared fetch cache. Entries are deduplicated by arXiv id and keep the union of their categories.
- An entry that a project already holds keeps that project's badge with the note "in <project>". It is not hidden.

### 4.3 General ranker (`services/feed_ranker.py`)
- Port of arXiv Miner's `Ranker` (`src/core/ranker.py`) with its tests, adapted to SPECTER2 vectors (one encoder per factory, slice 4c ruling 5). The model:
  - the profile is the mean of the liked vectors;
  - the features are the cosine to the profile, the vector norm and the first 10 dimensions;
  - then `StandardScaler` and `LogisticRegression(class_weight="balanced", random_state=0)`;
  - dislikes are weighted 0.5;
  - with no dislikes it falls back to profile cosine.
- Training set: the latest reaction per arXiv id. It reads like and dislike from the factory log and also from every project's `feed.reacted`, because a like is about the researcher (slice 4c open question 3). Save and dismiss are not labels.
- Training writes `feed.ranker_trained` (actor `system`; refs the human command):
  - the training-set hash and its ids;
  - the counts;
  - the feature list;
  - the library versions;
  - a state blob (JSON, no pickle).
- Scoring: each `feed.ranked` in the factory scope names the ranker version it used, or `none` (newest first).
- Dependency: `scikit-learn` joins the optional `ranker` extra next to `torch` and `transformers`.

### 4.4 Project scores
- The existing max-cosine score against each project's core works (`feed.py:516`), computed for every pool entry and every project.
- Kept in the factory ranking's order blob as `{project: score, closest_core_work}`. Projects never learn (ruling 3).

### 4.5 Hub page (main hub `/feed/`, IDEA-97 design system)
- Sidebar:
  - Today (count);
  - Liked (count);
  - Reading list (count);
  - Projects (one link per project with a feed configuration);
  - category chips for the loaded page.
- Today cards. Each card shows:
  - rank, title linking to arXiv, id, date;
  - authors (3, then "+N");
  - project badges at or above the weak line (each links to the project page);
  - categories, and an `explore` badge when relevant;
  - the abstract with a "Show more" expander;
  - "predicted NN% (ranker vK)" once a ranker exists.
- Card controls:
  - like and dislike: the card leaves Today and the reaction is recorded in the factory log;
  - save: toggles the reading list;
  - **Send to project…**: a project picker that uses the existing `feed.sent`, so the paper goes to that project's link inbox;
  - **Add to project…**: the existing one-click add.
- Today list controls: sort Ranked or Newest, a text filter, and pages of 100.
- Project page:
  - window of 24 h, 7 d, 30 d or all;
  - entries sorted by project score, with "similar to <closest core work>" and the score;
  - a divider "weak matches below x";
  - the same card controls.
- Liked: liked titles with dates, plus a collapsed "N disliked" list. Undo writes a new reaction `unset`, which supersedes the earlier one.
- Reading list: saved papers, each with a remove button (`unsave`).
- Settings panel:
  - the weak-line slider;
  - the ranker state (version, trained when, on how many likes and dislikes);
  - the **Train** button, disabled with a reason below the threshold;
  - the categories per project, read-only, with a link to `factory feed configure`.
- Writes:
  - new POST routes `/api/feed/react` and `/api/feed/train` on the main hub, using the hub token, the same guards (loopback, constant-time token, JSON, 16 KiB, same origin) and actor the local human;
  - Send and Add keep the per-project routes.
- CLI equivalents: `factory feed react --scope factory`, `factory feed train`, `factory feed today`.

### 4.6 Rigour
- Reactions are human events; an agent actor is refused (slice 4c R-F3). There are no MCP write tools for reactions or training.
- The general ranker orders the factory feed only. It never orders a screening queue, never reads seeds, and never touches held-out works (R-20).
- Every ranking names its ranker version and its training-set hash. Ranking is reproducible from events and the encoder weights.
- The exploration share stays (slice 4c ruling 6) and is labelled on the cards.

## 5. Tasks

| # | Task | Module class | Model |
|---|---|---|---|
| T1 | Factory scope: reserved slug, scope-root reader and writer, type allow-list, factory projector with its own version; `00-system` §2 and §4 text | critical (events, index) | Sonnet implement, Opus-tier review per SDD tiers |
| T2 | Payload models: `feed.reacted` gains reactions `unset` and `unsave` (additive, schema 1 stays valid); `feed.ranker_trained` registered | critical (events) | Sonnet |
| T3 | Pool and project scores: union of fetch caches, dedup, per-project max-cosine with closest core work; factory `feed.ranked` | services | Sonnet |
| T4 | Ranker port with arXiv Miner's tests (`tests/test_ranker*.py` adapted), state blob, threshold | services | Sonnet |
| T5 | Train and react: service, CLI, main-hub POST routes, guards | services, cli, site_server | Sonnet |
| T6 | Hub page in the IDEA-97 design system: Today, project pages, Liked, Reading list, settings; click tests | site | Sonnet |
| T7 | Docs: decision 169 text, slice 4c rulings 4 and 8 marked built, IDEA-58 status, MAP regenerated | docs | Haiku |

Order: T1 → T2 → (T3, T4 in parallel) → T5 → T6 → T7. There is one branch per plan (`factory-feed`), and the work lands by PR through CI (main is protected). Locally only mypy, ruff and the touched test files are run.

## 6. Further rulings (researcher, 2026-11-23)
5. A like or dislike made anywhere in the factory feed, project pages included, is recorded in the factory log only. Project logs receive only Send and Add, as now. Earlier project reactions still count toward training.
6. The new page replaces `/feed/` in the main hub. The tab-per-project page stays reachable at `/feed/classic/` until the researcher drops it.
7. Build now on branch `factory-feed`, then a PR through CI. No merge without the researcher's go.

## 7. Open question
- Q3. arXiv Miner's crude features (the first 10 dimensions of a 768-dimension vector) are ported as is for v1. A better feature set is a later version of the ranker, measured against v1 on held-out reactions.

## 8. Build notes (2026-11-23)

Branch `factory-feed`, commits in build order:
- `c35bfda6` general like/dislike ranker, pure module (IDEA-58).
- `9f1d01cd` factory event scope with feed allow-list, own projector and `ranker_trained` payload (decision 169 proposed).
- `e1136116` factory pool, per-project scores, general order and factory `feed.ranked`.
- `d91324e2` factory scope guards pinned (review); no `PROJECTION_VERSION` bump.
- `b007cfdf` factory react, train and ranker status; hub `POST /api/feed/react` and `/api/feed/train`; CLI `train`, `today`, `react --scope factory`.
- `ce3a3fa7` main-hub `/feed/` as the factory feed page; the tab-per-project page moves to `/feed/classic/`; per-project send route `POST /p/<slug>/api/feed/send`.
- `dc30150c` review fixes: train returns 500 and 409 correctly; ranking id minted under the scope lock; encoder match; pool by event time; send via the inbox; 30 s TTL cache.

Deviations from the plan, as recorded in the commit messages:
- Pool source: the projects' `feed.fetched` records, not a separate store.
- `feed.ranked` gains optional fields `ranker_version` and `project_references`.
- Send and Add fall back to the project link inbox (channel CLI) when the entry is not in that project's ranking. No `feed.sent` is written on that path. The Add fallback is untested.
- Project scores are cached for 30 s.
- Train runs inside the request; it returns 409 when a training is already running.

Testing: tests were run per file for the touched test files. The full suite was not run locally; CI is the gate (`docs/runbook-ci.md`).
