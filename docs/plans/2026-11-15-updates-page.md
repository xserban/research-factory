# Updates page: additions since v1, corpus growth, weekly watch settings

Status: built and merged (2026-11-15; one Sonnet review, fixes e23092f; tests written, not run); approved layout (researcher, 2026-11-15) · Branch: `updates-page` · Parent: `docs/plans/2026-11-15-living-loop.md` steps 2, 4 (route only), 6, 7
Testing is paused (researcher's ruling 2026-11-05): tests are written, not run; mypy --strict and ruff must pass.

## Goal

One hub page per project, `/p/<slug>/updates/`, that answers: what entered the corpus since the
frozen review (v1) and how far each work got; how the corpus grows from snapshot to snapshot; and
what the weekly watch does, with the researcher's two acts (save watch settings, close the week).

## Rulings

1. Layout as approved: four blocks (header, additions, growth, weekly watch) on one page.
2. A week closes automatically after each watch cycle (`watch_plan.snapshot_every = 1`); a
   "Close week now" button takes a human snapshot early.
3. No full re-run of the search, and never an automatic one (researcher, 2026-11-15; decision
   128): sources run in `window` mode with `full_replay_every` None; the first window is anchored
   on the earliest of each search query's latest complete run outside the watch; a full re-run
   is only `watch run --full-replay`, shown on the page, with no button.
4. Every number is computed from events; the page writes nothing; each button is a recorded act
   of the local human through `site_server`, refused to any other actor.

## Tasks

### T1 — Watch configuration service and the two acts (critical: protocol amendment)
- `services/watch_config.py`: `configure_watch(project, actor, *, sources, interval_days, until,
  reason) -> str` (the new protocol id). Human actor only (else `FactoryValidationError`, nothing
  written). `sources` non-empty, each an included source of the current protocol
  (`spec.sources[].name` with `included`); `interval_days >= 1`; `until` a `date` or None, not in
  the past. Builds `WatchPlan(sources=[WatchSource(source=s, interval_days=..., mode="window",
  overlap_days=7, full_replay_every=52)], snapshot_every=1, until=until)`, keeping the current
  plan's other fields (notices, budgets) when one exists, and calls
  `protocol.amend_protocol(project, actor, spec_with_plan, reason=..., semantic=True, effects={})`.
  No change (same plan) is refused with `watch_plan: unchanged`.
- `site_server.py`: `POST /api/watch/configure` (`sources`, `interval_days`, `until` ISO date or
  null, optional `reason`; default reason "Weekly watch settings saved from the Updates page") and
  `POST /api/living/snapshot` (no body; `snapshots.snapshot(project, human, trigger="human")`),
  following `feed_configure` exactly (project token, `authorize_command`, 400 on validation, 403
  on permission). Register both in the project-scoped route table.
- Tests (written, not run): `tests/test_watch_config.py` — refuses agent; refuses unknown or
  excluded source; refuses past `until`; records an amendment whose spec has the plan; unchanged
  refused; keeps notices of an existing plan.

### T2 — Updates view service (read-only)
- `services/updates.py`: `updates_view(project) -> UpdatesView` (pydantic `StrictModel`s).
  - `baseline`: the first snapshot (`snapshots.snapshots(project)[0]`): id, cut-off event,
    recorded time, included count (`len(blob.included_ids)`); None when no snapshot exists.
  - `open_period`: since the last snapshot: `update_work_ids(project, last_cutoff, None)` count
    and how many of those are included at title/abstract.
  - `additions`: every work in `update_work_ids(project, baseline_cutoff, None)`, one row each:
    `work_id`, `title`, `year`, `added_at` (time of its first non-probe provenance event),
    `route` (one of `inbox`, `feed`, `watch`, `chase`, `search`, `other`, derived from that
    provenance: a `supplied` query whose inbox item came from the feed is `feed`, otherwise
    `inbox`; a query run inside a watch cycle is `watch`; `citation-chase` is `chase`), `note`
    (the inbox note, if any), `ta_outcome`, `ft_state`, `ft_outcome` (as `flow_works` computes
    them; reuse its service function), `layer` (the latest layer scheme assignment, as
    `site_layers` reads it; None when none), `mined` (miner names with a final unit for the
    work). Sorted newest first.
  - `growth`: one point per snapshot in order: snapshot id, recorded time, included count, and
    the pinned update flow's identified / screened / included totals and identified-by-route
    counts when the blob has `update` (None for the baseline).
  - `watch`: from `watch.watch_status(project)` and the current protocol's `watch_plan`: sources
    with interval and mode, `until`, last cycle, next due, open cycle; `has_plan`.
- Tests (written, not run): `tests/test_updates_view.py` on the living fixtures
  (`tests/watch_helpers.py`, `tests/notice_helpers.py`): no snapshot gives `baseline None` and
  empty additions; a supplied work after a snapshot appears with route `inbox`; a work before the
  snapshot does not; growth has one point per snapshot.

### T3 — The page (depends on T1 and T2)
- `services/site_updates.py`: `render_updates(view, slug) -> str` and `build_updates(project,
  out)`, in the style of `site_settings.py` (escaped, no external resources, buttons disabled
  until the server injects its token, `with_bar` chrome). Blocks:
  1. Header: "Since v1 (<snapshot id>, <date>): N included"; open period line.
  2. Additions table with a client-side route filter (all, inbox, feed, watch, chase, other) and
     the add-link form posting to the existing `POST /api/inbox/add` (`project`, `value`,
     `note`).
  3. Growth: an inline SVG line of included count per snapshot (no library) and the update-flow
     table.
  4. Weekly watch: current settings or "not configured"; the form (source checkboxes from the
     protocol's included sources, interval days default 7, end date optional) posting to
     `/api/watch/configure`; "Close week now" posting to `/api/living/snapshot`; a line stating
     that sources run in window mode with a full replay every 52 cycles.
- Register the product in `site.py` `products()` (group Corpus, label "Updates") and in the
  server's page routes as `settings` is.
- Tests (written, not run): `tests/test_site_updates.py`: renders with no snapshot; escapes a
  title with `<`; buttons disabled in the static page.

## Done when

mypy --strict and ruff pass on every touched file; the page builds against a copy-free read of
the pilot (`build_updates` on `data/`, read-only) and shows v1 = 365 and the Zubeldia row; one
Sonnet review, fixes in; the researcher approves the merge.
