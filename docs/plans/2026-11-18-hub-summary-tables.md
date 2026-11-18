# Plan: summary tables kept by the projector, and a published index snapshot (IDEA-96, part 2)

Date: 2026-11-18 · Branch: `hub-summary-tables` (to be made) · Follows: IDEA-96, plan
2026-11-18-hub-on-demand · Status: parked by the researcher 2026-11-18 (complex; the hub is usable as merged). Revisit when testing resumes or when Hub UI v2 (IDEA-97) needs faster payloads

## Goal
Hub pages and the dashboard read small tables the projector keeps current, not derivations
recomputed from the whole index at build or request time; and a served hub reads a published
snapshot of the index, so it never waits on a writer.

## Findings (pilot copy, 2026-11-18)
- Dashboard snapshot: 435–830 s. Of 643 s profiled, 369 s is `resume.interrupted` and 176 s
  `work_queue.queue`; the rest of the dashboard is about 80 s. The same code makes the queue
  product time out (> 12 min) and slows the hub's resume act.
- The hot path recomputed whole-project answers per work: `corpus_work_ids` read 912 times
  (0.28 s each), 838,962 blob reads, `mining_needs` 4 times. A `call_memo` scope over each build
  (plan hub-on-demand) took the dashboard from 377 s to 86 s on an idle machine, same output.
  What remains is per-unit work: `extraction._ledger` (58 s of 115 s profiled, 313k blob reads),
  `mine_status` (36 s), `resume._last_activity` (33 s, 2,472 calls), `abandoned_task_ids` (20 s).
- Queue product: 712 s (profiled 2026-11-18, memo scope on): `index.sync()` 976 calls, 152 s
  (each walks every event file; a build cannot simply hold `snapshot()`, which would block
  writers for minutes; the published snapshot removes it); `extraction._ledger` 55 calls, 244 s
  (not memoised: a mutable ledger the write path also uses); `dedup_current` 2 calls, 177 s
  (memoised on hub-on-demand); `abandoned_task_ids` 114 s for one call (312k blob reads).
- Taxonomy: more than 30 min; it computed the full `mine_status` (with agreement) twice per
  taxonomy version only to read the listed miner names. Fixed on hub-on-demand
  (`mining.listed_miner_names`, same 18 names): 106 s.

## Scope (critical modules: projector and index; TDD; subagent-driven per CLAUDE.md)
1. **Summary tables** (one projection version bump, rebuildable from the log):
   - `work_mining_state` (work, miner, latest unit state, last task id): replaces the per-work
     ledger walk behind `mining_needs`, `pending_work`, `interrupted`.
   - `work_conversion` (work, default conversion id): replaces per-work `default_conversion`.
   - `event_type_counts` (type, count, last id): the fingerprints read it in one row per type.
   - `corpus_membership` (work, in corpus, outcome per stage): replaces `corpus_work_ids` and
     `final_outcomes` scans for the hub.
   Each table states its invariant and has a property test: table == the derivation it replaces,
   over generated logs.
2. **Readers switch** in `work_queue`, `resume`, `dashboard`, `site_*`: same outputs, compared on
   the pilot copy before and after (as the dashboard JSON was on 2026-11-18).
3. **Published snapshot**: the server copies the index with SQLite's backup API to
   `.index/published.sqlite` when events settle (at most every `--every` seconds) and opens hub
   reads on it read-only; pages say "as of <time>". Writers never wait on the hub.
4. **Taxonomy** profiled and fixed on the same pattern.

## Not in scope
The on-demand server, child builds, badges, lazy items and `--dev` (plan hub-on-demand).

## Checks
Testing is paused (2026-11-05); this plan needs the pause lifted for the projector work, or an
explicit ruling to build it untested. mypy, ruff, import contracts; equivalence runs on a copy of
the pilot.
