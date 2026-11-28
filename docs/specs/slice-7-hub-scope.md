# Slice 7 addendum: hub-wide scope (IDEA-141)

Status: proposed, 2026-11-28. Requirement: `docs/backlog.md` IDEA-141 and the researcher's rulings of
2026-11-28. Binding context: `docs/hub-guide.md`, `docs/specs/00-system.md`, decisions 140 to 148 (chat
basket), IDEA-97 (hub v2). Plan: `docs/plans/2026-11-28-hub-scope.md`.

## 1. Scope

A **scope** is a publication-date range (month granularity) and an optional **paper set**. It is a
projection over works that already exist: no scope writes an event, mines or judges anything. Phase 1
builds the bar and the date range; phase 2 builds paper sets.

## 2. Requirements

Scope bar
- HS-01 Every hub page that lists or counts works shows one scope bar (published from, to, paper set).
  Pages with no work lists (kit, platform, costs, learn, protocol, levels, method) show no bar.
- HS-02 The scope is in the address hash: `scope.from=YYYY-MM`, `scope.to=YYYY-MM`, `scope.set=<set_id>`,
  and `scope.undated=1` (the "include undated" tick, HS-11; absent means off).
  A link reproduces the view; the scope persists when moving between pages (the nav carries it).
- HS-03 Every scoped page states "n of N papers in scope", with N the page's own unscoped denominator
  (for example included works for miner pages) and n computed, never typed (hub-guide: n of N).
- HS-04 No bar state is silent: an empty scope shows the empty state with the active scope and a reset.

Dates
- HS-10 The date is `dates.published` of the work as indexed (the same value as `ctx.publication`). It
  is a publication date, never a listing or record date. A preprint with a later journal version keeps
  the date the work record holds; the platform does not choose between versions (open question 1).
- HS-11 A work with no usable date is "no date", is not dropped, and is counted in the line "k papers
  have no date". A range filter excludes them by default and offers one tick "include undated"; the
  denominator line always names how many are held out for that reason.
- HS-12 Partial dates (`YYYY`, `YYYY-MM`) compare at month granularity: `YYYY` is in range when the whole
  year lies in range, otherwise shown as "year only" and excluded from partial overlaps (counted, shown).

Rigour
- HS-20 Every count, table, chart and ranking on a scoped page is recomputed over works in scope; the
  denominator is shown beside it. A figure that cannot be recomputed from per-work rows is labelled
  "whole corpus" and is not changed by the scope (never a silently scoped or unscoped mix on one panel).
- HS-21 Agreement figures (exact, fairer, platform; kappa) stay those of the whole pass. When a scope
  is active they carry "whole pass, not scoped"; no scoped agreement is computed or shown.
- HS-22 (ruled 2026-11-28: hide and count, no toggle) Leaderboard and results rows: a row is in scope when its source paper (the work that reports
  the value) is in scope. A baseline row whose source paper is out of scope is hidden, and the table
  says "k baseline rows hidden (source paper out of scope)"; it is never kept as a reference line
  without that note, and never re-attributed to an in-scope paper.
- HS-23 A scope never changes layer assignment, final rows, or protocol-state; it is read-only.
- HS-24 Counts of a category in an empty scope read 0 of n, not a missing row.

Paper sets (phase 2)
- HS-30 Papers are ticked in any list (corpus, data tables, miner tables, leaderboard rows) and added to
  the working set. The working set is the same list as the chat basket (`only` basket of
  `hub_chat.parse_spec`); "Send to Spar/Ask" opens the Chat page with it.
- HS-31 A working set is saved as a named set by a human act. Two kinds: `picked` (an explicit work id
  list) and `filter` (a rule, for example layer chest-ct-vlm, from 2026-01, field value 3D encoder).
- HS-32 A saved `filter` set stores its rule AND the work ids it resolved to when recorded. The set
  means exactly those ids afterwards; the rule is documentation. A page may offer "re-resolve", which
  records a new set superseding the old one and shows how many ids were added and removed.
- HS-33 Sets are recorded as events (section 3), persist, and are shared with everyone who opens the
  project hub. A set may be selected as scope (`scope.set`); with a date range the scope is the
  intersection, and the bar shows both sizes.
- HS-34 A set id that is unknown or superseded in an address shows the refusal state with the newest
  successor offered, never an empty page.

## 3. Event

`paper_set.recorded`, version 1 (catalog in `events/catalog.py`, model in `model/`, fold into a
`paper_sets` table in `index/`).

| field | type | rule |
|---|---|---|
| `set_id` | `PS-<8 lowercase hex>` | new per set; a revision reuses the name, not the id |
| `name` | text 1..80 | shown as typed, unique among live sets (case-folded) |
| `kind` | `picked` or `filter` | |
| `works` | tuple of work ids, min 1, max 5000 | canonical ids, corpus works only, resolved at record time |
| `rule` | object or null | set exactly when `kind` is `filter`: `{layers, from, to, miner_filters, text}`; documentation only |
| `supersedes` | set_id or null | the live set this replaces; null for a new set |
| `reason` | text or null | |

Invariants: human actor only (a non-human actor is refused with nothing written, as `work.layer_set`);
the project owns the event, the researcher authors it (the hub is one project per slug, so there is no
cross-project scope). Never edited or deleted: a rename, a change of members or a re-resolve is a new event with `supersedes` set to the live set; only the newest in a chain is live. Retiring a set without a successor is out of scope for v1 (open question 4). A set whose work ids leave the corpus (merge, exclusion) keeps them; the page shows "k no
longer in the corpus". Refusals: unknown work id (`works`), empty set, duplicate live name, `supersedes`
not live. Provenance fields as the other human acts (actor, ts); no model fields apply.

## 4. Decision: where filtering happens

Client-side, over the payloads the page already loads, with a shared scope module in `shell.js`.
Reasons from the code:
1. The payloads are already per work and large: corpus 6.7 MB, mining 1.4 MB, grids to 1.5 MB, explore
   0.97 MB (pilot build). Per-scope payloads multiply that by every date range and set.
2. The cache key of a payload is the fingerprint of the event types it reads (`hub_serve.fingerprint`,
   `PAYLOAD_INPUTS`). A scope is not an event; server-side scoping would need the scope in the key,
   giving unbounded keys, and a new set event would re-stale every payload. The hub's measured slowness
   is exactly version ping-pong rebuilds (hub-slowness diagnosis 2026-11-20); scope must not add any.
3. Scope changes while browsing; a client filter is instant and the address hash needs no server round trip.
Cost and guard: counts that are pre-aggregated on the server (category tallies in `mining`) cannot be
recomputed in the browser. Plan task P1-02 audits them and, where needed, adds per-work rows (not scoped
variants) to the payload. A panel without per-work rows is labelled "whole corpus" (HS-20). Paper sets
are the only server write: the existing hub write route (`site_server` act table, taken under
`slot.write_lock`, allow-listed like `_CHAT_ACTS`) gets one act, `POST /api/sets/record`. Set contents
are served in a small `paper_sets` payload (fingerprint reads `paper_set.` only), so a set event
restales that payload alone.

## 5. Pages

Phase 1, by page id (`hub_ui.PAGES`): `miners`, `data` (per-field tables of a miner such as m-arch;
leaderboard and results tables are in `data`, to be confirmed in P1-02), `corpus`, `explore` (layers
and the explorer), `findings`, `landscape`, `lenses`, `overview`. Layers also appear in `corpus` and
`explore`.
Phase 2 adds ticks and set actions to `corpus`, `data`, `miners`, `explore`, and the basket link to
`chat`. Out of phase 1: `flow`, `screening` and `pipeline` (PRISMA numbers are whole-pass by definition,
bar hidden with the sentence "whole corpus"), `graph`, `journeys`, `hypotheses`, `ideas`, `write`.

## 5a. Leaderboard page (HS-50 to HS-55)

Page id `leaderboard` (section Extract, after Data), payload `leaderboard` (`services/hub_leaderboard.py`).
Rulings of 2026-11-24 and 2026-11-28; the reference is `ops/results/build_v3.py` of the pilot.

- HS-50 Source. One payload entry per final row of the project's results miner: the registered miner
  whose fields include `model_role`, `metric` and `value` (the pilot's `m-results`, fields task,
  model_name, model_role own/baseline, dataset, data_access, setting, metric, value, averaging,
  result_quote), listed miners first. Rows are the final rows of pass A (agreed, resolved or single):
  with no pass B every live pass-A row, once pass B exists the extraction service's final rows, never a
  row with an unresolved disagreement. Each entry carries its source work id, `published`, cells, and
  the quote and anchor of its value.
- HS-51 Normalisation is not hard-coded. Spellings of dataset, metric and setting merge only through
  the approved vocabulary: the `value_aliases` of the approved properties `pr:leaderboard-dataset`,
  `pr:leaderboard-metric` and `pr:leaderboard-setting` (compared without case, spaces, hyphens and
  punctuation). An unapproved proposal does nothing; without an approved property values are grouped as
  extracted. The payload keeps both spellings per row; the page shows "as extracted, as merged" on hover.
- HS-52 Own-model names. A generic own-model name (ours, our model, our method, our approach, proposed
  method or model) is replaced by the paper's own model name from a model-card miner field
  (`model_name`, else `model_name_quote`, of the first miner by name that has it, at most 60
  characters), otherwise by the paper's short id; a size-only remainder (7B) is joined to it. The rule is
  shown on hover. Baseline names are never changed.
- HS-53 Part A (own models): per table (task, dataset, setting, metric), the best value per
  (model, paper); public rows only (`data_access` public, or not stated on a dataset whose stated rows
  are all public); a table needs at least 3 models; ranked, top 15; every value opens its quote.
  Part B (baselines): per baseline, task, dataset, setting and metric, how many papers re-reported it
  (best value per paper, at least 4 papers), with median, minimum and maximum.
- HS-54 Scope (HS-22 applied). A row is in scope when its source work is in scope. A baseline row whose
  source paper is out of scope is hidden and the page says "k baseline rows hidden (source paper out of
  scope)"; rows are never re-attributed. The n of N line counts works with result rows.
- HS-55 Numbers. Values are read as numbers (a percent sign is dropped, a value above 1 is divided by
  100, anything else is left out and counted). `rank` in the service is the one definition of both
  parts; the page repeats its steps over the rows in scope and a test compares the two.

Not reproduced from leaderboard-v3: its hand-curated `model-names.json`, its fixed list of
(task, metric) tables, its public-dataset list (replaced by the `data_access` rule of HS-53), and its
restriction of Part B to two datasets.

## 6. Proposed decision row (not entered in `docs/decisions.md`)

Decision proposed: the hub scope (publication-date range plus a paper set) is a client-side projection
carried in the address; paper sets are the only recorded part (`paper_set.recorded`, human actor,
superseding), a filter set stores its resolved ids, and agreement figures are never scoped.

## 7. Open questions

1. Preprint versus journal date: keep the work record's `dates.published` (HS-10) or add a researcher
   choice per work. Default proposed: keep.
2. (Answered: the leaderboard is its own page, section 5a.)
3. Whether the baseline hidden-row rule (HS-22) should offer a "show as reference" toggle.
4. Whether a set can be retired without a successor (a `paper_set.retired` event); v1 omits it.
