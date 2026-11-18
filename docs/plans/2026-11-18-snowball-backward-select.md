# Plan: selected backward snowball rounds, taken offline from stored records

Date: 2026-11-18 · Branch: `snowball-backward-select` · Decision: 135 (proposed) · Amends: slice 3a ruling 7 (backward rounds take every candidate) for protocols that opt in

## Goal
On the pilot, a backward round would take all 6,372 candidates through 320 OpenAlex queries. The
researcher chose (2026-11-18) to take only candidates that (a) are published inside the protocol's
window, (b) are cited by at least 2 included works and (c) score at least 0.92 by SPECTER2 against
the development positive seeds (decision 116): 168 works in a read-only trial
(`~/.cache/rf-snowball/score.py`). They also ruled not to rely on OpenAlex (decision 130): the
candidates' records are already stored from the Crossref/arXiv lookup, so the round takes them from
the store, offline.

## Design
1. **Protocol options** (`model/protocol.py`, `SnowballPlan`), all optional and omitted from the
   dump at their defaults, so existing protocol hashes are unchanged (same pattern as the forward
   options):
   - `backward_min_cited_by: int | None` (ge 1)
   - `backward_min_similarity: float | None` (0 < x ≤ 1; needs the `ranker` extra and weights)
   - `backward_published_from: date | None` (a candidate without a known publication date is not
     taken; it is counted)
   A backward round with none of them set behaves exactly as today (ruling 7).
2. **Selection** (`services/snowball.py`): when any option is set, the plan's candidates are
   filtered in this order: published-from, min-cited-by, then similarity (embedding only the
   survivors; `services.ranking.max_cosine_scores`, references = `reference_works`, development
   seeds only, R-20). Embedding runs outside `project.writing()` like `_pick_forward`; a missing
   extra or weights refuses the round with the remedy, writing nothing.
3. **Record** (`model/references.py`): `BackwardSelection` on `SnowballRoundStarted.selection`
   (a union with `ForwardSelection`, discriminated, or a separate optional field — pick the one
   that keeps old events valid and projections unchanged for old rounds): the thresholds, model id,
   weights hash, software, the counts considered / dropped per step / taken, and the taken work
   keys with their score and cited-by count. Counts not taken are derived, never stored, as for
   `CoreSelection.not_taken` (R-05). A change of seeds or weights between plan and record refuses
   the round, as for the forward cap.
4. **Offline route** (`sources/stored.py`, new, offline like `reflist`): a source that returns the
   stored `Work` records for a list of work ids (`QueryKind.ID_LIST`), bound to the project in
   `round_sources` as `reflist` is. `_route` prefers it for a candidate whose work is stored (every
   resolved link's work is), before `openalex`/`arxiv`/`doi`. The run's archived page holds the
   records as returned, so provenance and dedup work as for any run. A protocol flag is not needed:
   stored records are always preferred (no network call can do better than the record the link
   was resolved to); if the reviewer finds a reason to keep OpenAlex as default, gate it with
   `backward_offline: bool` instead and say so in the decision.
5. **Plan view and CLI/MCP**: `snowball plan backward` and `snowball_round` show the selection
   (thresholds, counts per step, top taken by score) in the dry run. No new CLI options: the
   options live in the protocol (amended by the researcher), like the forward cap.
6. **Docs**: decision 135 (Proposed): selected backward rounds and the stored-record route;
   `docs/specs/slice-3a-references.md` gets a note under ruling 7 pointing to decision 135; backlog
   pointer. Do not regenerate MAP (after merge).

## Tasks (TDD)
- T1 `SnowballPlan` options + hash stability test (a plan without them dumps as before).
- T2 `sources/stored.py` + registry binding + `_route` preference; test: a candidate with a stored
  work routes to `stored`, a `no-source-record` one still to `reflist`; a run records the page.
- T3 selection in plan and round with a fake embedder (tests use a deterministic embedder as the
  forward-cap tests do): order of filters, counts, refusal without ranker, refusal on changed seeds,
  dry run writes nothing, recorded round's `selection` round-trips, projection of old rounds
  unchanged.
- T4 render lines for the plan; MCP/CLI output.
- T5 docs.

## Testing
Only touched modules' tests (`test_snowball*`, `test_protocol*` hash tests, `test_sources_reflist*`
or the new source test, ranking tests) with `--basetemp=$HOME/.cache/rf-test-tmp/<name>`; never the
full suite; mypy --strict and ruff on changed files.

## After merge (with the researcher)
1. Screen the 8 pending works (the round is refused while any corpus work can be acted on).
2. Amend the pilot protocol: `backward_published_from 2025-01-01`, `backward_min_cited_by 2`,
   `backward_min_similarity 0.92` (researcher's amendment).
3. `snowball plan backward` (dry run), compare with the trial's 168, then record the round.
4. Screen the new records (SPECTER2 orders the queue).
