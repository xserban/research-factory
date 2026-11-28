# Hub scope, phase 1: payload audit (P1-02)

Spec: `docs/specs/slice-7-hub-scope.md` (HS-03, HS-10, HS-20, HS-22). Plan task P1-02. Shapes were read
from the pilot build (`chest-ct-vlm`, 248 included works) and from the builders; the page ids are those of
`hub_ui.PAGES`. "Published" is `dates.published` of the work as indexed (`ctx.publication`), `""` when
undated (HS-10, HS-11).

## Change made

A `published` string was added to every work-bearing row that lacked it, and to nothing else:

| Payload | Rows that gained `published` |
|---|---|
| `shell` | `works[]` (the join table every id-only list below resolves against) |
| `explore` | `works[]` |
| `overview` | `most_cited[]` |
| `corpus` | `citation.rows[]` (`works[]` already had it) |
| `lenses` | `influence.items[]` |
| `mining` | `miners[].examples[]`, `holes.works[]`, `data_grid` rows |
| `grid-<miner>` | `rows[]` |
| `findings` | `cards[].evidence[]` |
| `landscape` | `works[]` (kept `date`, which is `null` when undated) |
| `landscape_uses` | `approaches[].uses[]` |

Growth on the pilot: about 25 bytes per row; shell 248 rows (about 6 KB of 275 KB), explore 248, grids at
most 248 rows each over 9 grids (about 55 KB of 1.2 MB). `tests/test_hub_scope_payloads.py` asserts a
`published` key sits only on rows holding `id` or `work`, and holds at most 32 characters.

## Audit table

Per-work rows: Y = carries id and `published`; "ids" = lists of work ids only, resolved against
`shell.works` (which now carries `published`), so the browser can recompute from them.

| Page | Payload | Per-work rows with dates? | Pre-aggregated panels (no per-work rows; P1-08) | Notes |
|---|---|---|---|---|
| overview | `overview` | `most_cited` Y (top 50 only); `cited_here` map work -> [count, self] (ids, no date) | `lead` (PRISMA, screened, identified), `pipeline`, `line`, `composition` (layer, human counts), `papers_per_month` (month counts), `next_actions`, `level_statement` | `composition` and `papers_per_month` can be recomputed from `shell.works` (layer, human, published). `most_cited` is cut to 50 by whole-corpus rank: a scoped top list needs all works from `cited_here` + shell. PRISMA and queue panels are whole corpus. |
| corpus | `corpus` | `works` Y (248); `citation.rows` Y (top 50 by rate only) | `results` (design results grid: `cells[].works` ids but `bars` and `rows/own/left_out` counts only); `citation` head counts (extractions, entries, resolved_links, unknown); `refs_done`; `sets` ids | `cites` pairs have slug ids, no dates (resolve via `works`). `citation.rows` is a top-50 cut, so a scoped ranking cannot be recomputed from it: P1-08. `results` is empty on the pilot. |
| explore | `explore` | `works` Y (248, with `dna`, `similar`) | none | `similar[]` (top 8 neighbours per work) is computed over the whole corpus: a neighbour may be out of scope. Label "whole corpus" or recompute from `dna` plus shell cites (P1-08). |
| findings | `findings` | `cards[].evidence` Y (quotes); `cards[].ids`, `claims.rows[].cells[].ids`, `cycle.stages[].ids`, `openness.groups[].*.segments[].ids` are ids only | per card: `numerator`, `denominator`, `distribution`, `share`, `say` (typed from counts); `cycle.stages[]` `automated/core/other/not_stated/of/share`, `techniques_*`, `quotes`; `openness` `n` and `segments[].n`; `claims.rows[].n`; `population` | Counts have an `ids` list beside them in every case except `cards[].distribution`, `cycle.stages[].techniques` and the `say`/`share` sentences, which are derived text: P1-08. The card ranking uses whole-corpus cited-here. |
| landscape | `landscape` | `works` Y (the compact `rows` index into it) | `matrix`, `stages`, `edges` (co-used, derives-from), `earliest.by_approach`, `candidates` (ranked lists with component scores), `sets` (`works`, `rows`, `by_layer`) | The page's counts come from the technique service per lens; edges, candidates and earliest rows are server-computed. `rows` are per work and could feed a browser recompute, but candidates and edges are not derivable from them without the service rules: label "whole corpus" or P1-08. |
| landscape | `landscape_uses` | `approaches[].uses` Y (cut to 300 per approach) | `rows_total` vs `rows_shown` | The cap hides rows; a scoped use list is only a subset of the shown rows. |
| lenses | `lenses` | `influence.items` Y (248) | `matrix`, `matrices` (observed, expected, residuals, totals), `chains.columns`, `icicle`, `trends` (counts by year/half), `association` (n, v), `adoption` (cells, first_seen, periods, `works_with_records`), `n` | `chains.links` carry work ids (ids only). Matrices, icicle, trends, association and adoption hold counts only: P1-08 (recompute from `shell.works` dims, `explore.works[].dna`, `year`/`month`/`published`; adoption needs per-record rows, which are not in the payload). |
| miners | `mining` | `miners[].examples` Y (4 per miner); `holes.works` Y (top 25); `coverage.works` ids with `a`/`b` index lists (per-work, no dates) | `miners[].pass_a/pass_b` (rows, works), `distributions[field][value]` ({rows, works, ids}: ids present), `fields[].values`, `rows_per_work`, `scope`, `status`; `holes.fields` (counts and shares); `columns[].filled`; `by_model_pair`; agreement blocks (`exact`, `fairer`, `platform`, `by_model`) | Agreement figures are whole pass by rule (HS-21): label "whole pass, not scoped". `distributions` can be recomputed from ids. `holes.fields` and `holes.works` (top 25) are counts only: P1-08. |
| data | `mining` + `grid-<miner>` | grid `rows` Y (one row per work read, first value per field) | grid `columns[].empty/gap` (count per field), `not_read`, `works_read`, `disagreements` (whole pass) | Per-field tables can be recomputed in the browser from grid rows. `gap`/`empty` counts are derived from the rows and should be recomputed, not read. |

## Leaderboard and results tables (spec open question 2)

- There is no leaderboard or results table in the hub. Nothing in `platform/src` refers to `m-results`,
  `model_role` or a leaderboard; the `m-results` miner appears only through the generic paths of every
  miner: the Miners page entry (`mining.miners[]`, with one example row), and the Data page grid
  `grid-m-results` (pilot: 181 work rows, 303 KB, columns `task`, `result_quote`, `model_name`,
  `model_role` (own/baseline), `dataset`, `data_access`, `setting`, `metric`, `value`, `averaging`).
- `corpus.results` is the design-approach results grid (stage x approach heat map; roles `own-system`),
  a different thing; it is empty on the pilot.
- Source work id: every `grid-m-results` row is keyed by `id`, the work whose pass-A record holds the
  values. That is the source work, so HS-22's source-paper test is possible at work level. After this task
  each row also carries `published`.
- Gap for P1-07: the grid is one row per work with the first value of each field, and a work with several
  result rows (`multi_row` is true for `m-results`) puts the other values only in the cell's distinct-value
  list (`[v, quote, anchor, n, [values]]`). Model, dataset, metric and value of one result row are therefore
  not reconstructable as a tuple, and the baseline/own role of a given value cannot be paired with its
  number. A leaderboard needs a per-result-row payload (one entry per `MRow`: source work id, `published`,
  the cells of that row). `hub_mining` holds the rows (`MiningData.rows`, `MRow.eid`, `cells`) so the
  builder change is small, but it is a payload change that P1-07 must plan; the audit does not add it.

## Tests

`platform/tests/test_hub_scope_payloads.py`: one test per payload (shell, explore, overview, corpus,
corpus citation rows, lenses, mining, grids, data grid page, findings evidence, landscape and uses). The
pilot's `landscape` and `findings` panels are empty or sparse, so those two use the unit fixtures of
`test_hub_landscape.py` and `test_hub_findings.py`. Existing exact-key tests were updated for the new key.
