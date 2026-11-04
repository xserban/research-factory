# Slice 4b — Living corpus: watches, updates, notices and digests

Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted). Decisions 62 and 63; requirements R-102–R-106.

## Cross-spec reconciliation 2026-11-04

1. **Inbox ownership (ruling 6, open question 5) settled with slice 4a.** Records enter the corpus as pending works when the run that retrieves them finishes (watch search runs here, `supplied` lookups in 4a). The candidate inbox is the 4a `inbox_items` table for links plus a computed view of pending works by discovery route; watches write no inbox items. Slice 4a is built first (build order), so living-B Task 1 takes its 4a branch.
2. **PRISMA precedence (ruling 8 corrected).** "Counts once, under the earlier route" contradicted decision 38 item 6 (a work found by a database search and by other methods counts under databases only). The rule is now: within any flow, a work counts once, under `database` if any of its provenance up to the flow's cut-off is `database` (watch runs included), else under the first applicable of `citation-chase`, `seed-admission`, `hand-search`, `supplied`, `library-import`. The update flow counts a work in the update in which its first non-probe provenance lies; its box is decided by this precedence over provenance up to that update's cut-off. Update flows are pinned in snapshot blobs; the cumulative flow is recomputed.
3. **Priority hints (ruling 10).** `inbox.prioritised` is not built in v1: ordering the screening queue by a human hint departs from R-34 (records screened in randomised order). It is Later and needs a decision that reconciles it with R-34. Ruling 10's prohibition of a verdict path from the digest stands.
4. **Module kinds.** The watch cycle and notice/version tracking (the "status module") are `retrieval` modules; conclusions, snapshots and the digest are a `builder` that owns its system output events and the human `conclusion.registered` input event (slice-M reconciliation items 2, 3). Gates: `living.notice_assess`, `living.document_prefer`, `living.conclusion_register`, floor `human`. Slice M is built before this slice, so these are declared when built.
5. **Per-region digests** (ruling 18 (b)) consume slice 3d's reviewed `R@` snapshots; Later.
6. **Query purposes.** `STATUS` (here), `SUPPLIED` (4a) and `IMPORT` (3d) are distinct; status runs never create corpus works.
7. **Requirements** R-L1–R-L5 are R-102–R-106 in [01-rigour.md](01-rigour.md).
8. **Projection version.** Each plan that adds a table bumps `PROJECTION_VERSION` by one from the value it finds.

## v1 scope

- **v1:** `watch_plan`, cycles (full and window), due computation, `factory watch run` for an external scheduler, incremental dedup (living-A without its scale task); watch route in the candidate view, sample extension, audit top-up, snapshots, update flow, PRISMA-S cycle rows, living findings (living-B without priority hints); notices, versions, aliases, assessments, preferred document, read-time effects (living-C); conclusions, diffs, digest, `rf-living`, automated acceptance on fixtures (living-D).
- **Later:** the scale tests (acceptance 15), the two-cycle pilot (acceptance 16 except its `network` adapter tests, which stay in v1), priority hints, per-region digests, `factory notices check --all`.

Date 2026-11-05 · Builds on [00-system.md](00-system.md), slices 1, 2, 3a and (optionally) 3b; must satisfy [01-rigour.md](01-rigour.md) R-01–R-05, R-14, R-15, R-21–R-27, R-33–R-37, R-43, R-47, R-60, plus the proposed requirements below. Implements the "Keep current" production line of [docs/02-production-lines.md](../02-production-lines.md) and backlog IDEA-02 (per-project literature watch) and IDEA-03 (digest). Slice 4a (link inbox, discovery provenance; IDEA-34, IDEA-35) is a parallel draft; this spec uses its candidate inbox and adds the route `watch`.

**Depends on:** slice 4a (candidate inbox and discovery record; fallback below); slice M (module and miner contract, `slice-M-modules.md`): the watch cycle is a retrieval module and notice tracking a status module. Both are implemented first as hand-written services in the slice-1 style and move behind the module contract when slice M lands; no event defined here changes when they move.

## Goal
Keep each project's corpus current without redoing the review. On a schedule set outside the platform, the platform re-runs the project's recorded searches, deduplicates what is new against the corpus and routes it into the project's screening protocol; it tracks preprints that are published, newer versions, corrections and retractions of the works the project depends on; it marks as doubtful only the rows, claims and edges those changes touch; and it reports, as computed facts, when a recorded conclusion has changed. A digest summarises all of this per project. The platform never calls a model and never runs as a daemon: one CLI command does one due cycle and exits; an agent run that reads the digest and acts on it is outside the platform.

Pilot for acceptance: **best linear attention mechanism for vision models**, declared as a `living-review` profile in `pilot` mode, with a weekly watch of its arXiv and OpenAlex queries.

## User flow
1. **Declare the watch (R-13, R-60).** The protocol gains a `watch_plan` section: cadence per source, retrieval mode, notice sources, version tracking, conclusion snapshot cadence and an end date. It is an amendable, hashed section, omitted from every hash while absent, and outside `S@`, so a PRESS confirmation carries over.
2. **Schedule.** The researcher registers one external job (launchd, cron, a Claude Code scheduled routine) that calls `factory watch run --due --all` (all projects under the projects root). The command finds the projects whose watch is due from the event log, runs one **watch cycle** per due project and exits with a status code.
3. **A watch cycle** re-runs every planned query of the due sources as ordinary recorded search runs (full replay, or a declared window), deduplicates the new records incrementally, observes notices and versions for the project's dependent works, and closes with computed counts. New works enter the corpus as pending works; the candidate inbox shows them with route `watch`.
4. **Screening.** New works are screened by the project's existing passes under the current protocol. Pass B's sample is extended by the recorded seed (decision 38 item 3), calibration carries until an amendment, and the audit is topped up per update.
5. **Notices and versions.** A retraction, withdrawal, expression of concern or correction is recorded as a notice with its date and source. Its effects are computed at read time: only the dependents of the affected work are marked. A human assesses each notice; nothing is deleted and no screening outcome changes on its own.
6. **Conclusions.** The researcher registers conclusions (a statement and the computed facts it rests on). A snapshot records the computed facts at a cut-off; after each cycle the platform diffs the current facts against the last snapshot and reports every change.
7. **Digest.** `factory digest` (or the MCP `digest_get`) returns a computed summary since the last digest: new candidates and why they matched, pending human decisions, notices, versions, conclusion changes, failed runs and overdue watches. A scheduled agent may read it and deliver it; the platform does not send it.

## Rulings

Every ruling is recommended, not adopted; each is marked **[confirm]** with its recommended option first.

1. **What a watch run is [confirm].** (a) *Recommended:* a watch run is an ordinary search run (`search.run_started` … `search.run_finished`, purpose `search`) of a planned query, grouped under a **watch cycle** (`watch.cycle_started` / `watch.cycle_finished`, id `wcy_<ULID>`) that names its runs. All PRISMA-S fields, raw archiving, reported-versus-retrieved and shortfall handling (R-22, R-23) apply unchanged, and the protocol gate (`search_authorization`) is re-checked per run. (b) A new `QueryPurpose.WATCH` with its own counting rules. (b) would fork identification accounting for no gain; a cycle is a grouping, not a new kind of retrieval.
2. **Retrieval mode [confirm].** (c) *Recommended:* both modes, declared per source in `watch_plan`. `full` re-executes the planned query verbatim (R-27 replay) and diffs the result against the recorded corpus. `window` runs a platform-built variant of the planned query restricted to records first listed since the previous complete cycle minus a declared overlap; it is allowed only on a source field that records when the source first listed a record (arXiv submission date; for OpenAlex the creation-date filter, whose availability without an API key is verified in plan living-A, task 5), never on publication date, which is not monotone in listing time (R-21: partitioning must be provably exhaustive). A window source must declare `full_replay_every` (cycles); each full replay reports, as a computed count, the works the windows missed. (a) full only: exhaustive but costly at 10^4–10^5 records per query; (b) window only: cheap, unmeasured misses.
3. **Window queries are authorised by the cycle [confirm].** A window query is registered naming its cycle (`query.registered` refs end with the `wcy_` id), and `search_authorization` waives the planned-text match for a query whose text and filters equal a planned query plus the cycle's window filter, as it waives snowball texts for a query naming its round (slice-3a ruling 20). No agent chooses a watch query.
4. **Watch plan in the protocol [confirm].** (a) *Recommended:* a new section `ProtocolSpec.watch_plan: WatchPlan | None = None`, amendable, hashed, omitted from every hash while `None` (existing `P@` ids unchanged), not part of `S@`. It is required for `method_profile = living-review` in `pilot` and `systematic` (a promotion gap in `exploratory`) and permitted for every other profile. (b) A project setting outside the protocol: rejected, because cadence and mode change what is identified and so belong to the declared method (R-13).
5. **Schedule mechanism [confirm].** (a) *Recommended:* the platform exposes `factory watch run [--project SLUG | --all] [--due] [--dry-run]`. `--due` runs only projects whose next due time (computed from the last finished cycle per source and `interval_days`) has passed; a cycle already open is resumed, never doubled (per-project exclusive index lock, as `run_query`). Exit status: 0 nothing due or all complete, 1 some cycle partial or failed, 2 invalid input. No daemon, no timer, no network listener in `platform/`. The external scheduler and any agent routine that reads the digest are documented, not built. (b) An MCP-only trigger: rejected as primary, because a schedule must work without an open Claude session; `watch_run` also exists over MCP for a session that wants to run a due cycle (recorded with the agent actor).
6. **Where watch records go [confirm].** (a) *Recommended:* watch records enter the corpus as pending works at once, exactly as database records do, and the candidate inbox is a computed view of pending works by discovery route (slice 4a). "Enters the corpus only through screening" (IDEA-02) is read as "enters the included set only through screening". (b) Hold them outside the corpus until a human admits them: rejected, because a human pre-selection before screening is an undeclared filter that PRISMA could not count. *If 4a is not built first,* plan living-B provides `inbox_entries(project, route="watch")` as a minimal computed view that 4a later absorbs; the event log is the same either way.
7. **Incremental deduplication [confirm].** A cycle deduplicates only its new records, against the corpus, through indexed key lookups (strong identifiers, then year-blocked normalised-title buckets within `YEAR_WINDOW`), applying the same cascade rules and writing the same `dedup.merged` events as `dedup_run`. A property test asserts that incremental runs followed by `dedup_run` write nothing further. `dedup_run` stays the full reconciler, run on demand. Nothing loads the whole corpus into memory.
8. **PRISMA for living reviews [confirm].** (a) *Recommended:* two computed flows. The cumulative flow is today's `prisma_flow`. The **update flow** follows the PRISMA 2020 template for updated reviews: "studies included in the previous version" (from the last snapshot), then the identification, screening and inclusion boxes counted only over records whose first provenance lies between the previous snapshot and the current one (or now). Watch records are database identification attributed to their cycle; a work found by a watch and by a snowball counts once, under databases (decision 38 item 6; corrected by the 2026-11-04 reconciliation, item 2). The PRISMA-S report lists each cycle's runs with their dates. (b) Only the cumulative flow: rejected; a living review must report what each update added.
9. **Screening of updates [confirm].** New works join the existing passes; a new session may join a pass under decision 37's rules. Pass B's sample is extended for watch works as for chase works (`screening.sample_extended`, decision 38 item 3). Calibration holds across cycles until an amendment (decision 37 item 5, decision 50). The audit is topped up per update: the decision-37 size rule is recomputed over all agreed decisions, and the shortfall is drawn from decisions agreed since the last audit draw only, with a recorded seed and the 3:1 weighting. No earlier draw is redrawn.
10. **Digest triage [confirm].** (a) *Recommended:* the digest carries no verdict and offers no verdict path. A researcher reacting to it may record a **priority hint** (`inbox.prioritised`, defined by slice 4a, or by plan living-B if 4a is absent) that orders the screening queue and changes no outcome. A human screening decision is possible only through the existing human acts (calibration labels, disagreement resolution, audit labels). (b) Let a human triage from the digest as a screening decision: rejected for `pilot` and `systematic`, because it bypasses the declared passes (R-33); in `exploratory`, a human-only single pass is already possible under the protocol's screening plan.
11. **Notice sources and scope [confirm].** Notices come from OpenAlex (`is_retracted`, already parsed into `Work.retracted`) and from Crossref update metadata (records that declare themselves a retraction, correction, withdrawal or expression of concern of a DOI; the Retraction Watch data are distributed through Crossref). A notice check runs over the project's **dependent works**: works whose final outcome is `INCLUDED` at any stage, plus works with a live extraction row, claim or contribution item. It runs in batches of identifier lookups with a per-cycle budget and a recorded cursor, so the whole set is covered in a bounded number of cycles at any corpus size. The raw response is archived (R-03). Works without a DOI are checked through OpenAlex only and listed as `notice-unchecked-crossref`.
12. **Notice effects [confirm].** Effects are computed at read time from `notice.observed` and `notice.assessed` events by one pure function (`model/notices.py`); nothing is stored as a derived status. *Recommended table:*

    | Notice kind | Before assessment | Assessment options (human) |
    | --- | --- | --- |
    | `retraction`, `withdrawal` | work flagged `retracted`; its rows, claims and contribution items are `notice-affected`; the evidence report excludes them by default and lists them under `Excluded` reason `retracted`; edges whose basis is an affected item are labelled `retracted-basis` and leave default lineage views | `exclude` (stays out, finding closed) · `keep-flagged` (rows return, labelled) |
    | `correction` | the work's rows and claims are `correction-pending`: shown, labelled, excluded from frontiers and conclusion facts | `no-effect` · `affects` (named fields: those rows become stale; a corrected document is fetched and re-extracted) |
    | `expression-of-concern` | labelled; nothing excluded | `exclude` · `keep-flagged` |
    | `reinstatement` | supersedes an earlier retraction notice for the same work; effects revert to the state before it | none needed |

    Screening outcomes never change because of a notice. `check` raises `included-retracted` (error in `systematic`, warning in `pilot`) until assessment, as R-27 requires. A protocol that wants retracted works excluded by criterion declares that criterion; the platform does not invent one.
13. **Propagation is bounded to dependents [confirm].** The affected set of a notice is enumerated by indexed queries keyed by work id: the work's live extraction rows and claims (both scopes), relations whose basis item is one of them, evidence groups containing those rows, and conclusions whose basis references any of them. No other row, decision, document or report section is recomputed or re-queued. Re-extraction is queued only for units with rows made stale by an `affects` assessment (plan-D staleness, unit by unit).
14. **Newer versions on the same route [confirm].** The cycle's version check looks up the arXiv versions of dependent works held through arXiv routes and records `version.observed` when a newer `vN` exists than the work's current document. It fetches nothing. The finding `newer-version-available` lists the works; `factory fulltext fetch --refresh --work ID` fetches it, the newer document supersedes on the same route (decision 46 item 3), and plan-D staleness marks that work's rows only.
15. **Preprint to version of record [confirm].** (a) *Recommended:* the version check also records `version.linked` when OpenAlex or arXiv (`doi`, `journal_ref`) names a published version of a preprint work. The link adds the published identifiers as **aliases** of the existing work (used by incremental dedup, so a later database record of the published version merges by identifier; R-26: linked, not merged away). It changes no screening decision (decision 50 spirit: the published version is the same work) and no document pin. The finding `version-of-record-available` lists linked works with a pinned preprint document. A human moves the extraction basis with `document.preferred` (CLI), naming a fetched document of the same work; `default_conversion` then serves it, and plan-D staleness marks that work's rows only. (b) Switch automatically to the version of record: rejected, it would contradict decision 46 item 3 (different routes never supersede) and silently restale rows. (c) Never switch: rejected; corrections often appear only in the published version.
16. **Conclusions are computed facts [confirm].** (a) *Recommended:* two layers. **Conclusion facts** are computed from the evidence report and the lineage graph, never typed: per comparability group, the frontier members per declared axis and the best row per declared metric and direction (within the group only, decision 41), the number of independent rows, and the included-set size. A **registered conclusion** (`conclusion.registered`, human, `ccl_<ULID>`) is a statement written by the researcher with a non-empty list of basis references (trace ids: cell, row key, group id, relation id, work id) and optionally one fact predicate from a fixed menu (`frontier-member`, `best-in-group`, `group-row-count-at-least`, `path-exists`). A conclusion **changes** when a basis reference becomes stale, notice-affected or superseded, or when its predicate's computed value differs from the value at the last snapshot. (b) Facts only, no registration: rejected, a changed frontier in a group nobody cites would raise alerts without meaning. (c) Agent-judged conclusion change: rejected (platform never judges; proposer ≠ evaluator).
17. **Snapshots and review versions [confirm].** A snapshot (`living.snapshot_recorded`, `snp_<ULID>`, system actor, triggered by the human or by the plan's `snapshot_every` cycles) records the cut-off event id, the protocol id, and the hash of a blob holding the computed PRISMA flow, the conclusion facts and each registered conclusion's predicate value and basis state. A snapshot is the boundary of an update (ruling 8) and the reference of conclusion diffs. The blob is a generated report (00-system §4.3, committed); it is not recomputed at check time, because as-of computation would require a replay to the cut-off. The projection version and the platform version are recorded in the payload.
18. **Digest [confirm].** (a) *Recommended:* the digest is a builder. `digest_build(project, since)` returns a structured object rendered as Markdown and JSON; `factory digest [--project | --all] [--since EVENT|last] [--out DIR] [--record]` prints it or writes it, and with `--record` stores the rendered blob and writes `digest.generated` (cut-off, blob hash, counts), so "since last" is computed from events. The digest lists, per project: new candidates by route with the query ids that returned them (why they matched; no similarity score, decision 9 open); open human decisions (screening disagreements, calibration and audit labels outstanding, notice assessments, inferred relations); notices and versions observed; conclusion changes with the fact diff; failed or partial runs; overdue watches. It is bounded (counts always; listings capped at a declared number with a "more" count). It never carries a verdict, document text or held-out information: the MCP `digest_get` returns the agent view (decision 43; no seed marks, no label-derived rates, refused to pass sessions). Delivery (mail, chat, an artifact page) is done by whatever the scheduler runs after the command, never by the platform. (b) Per-region digests (slice 3 regions): deferred until regions exist; the builder takes a project list, so a region-to-project mapping can feed it later.
19. **Seed checks in a living review [confirm].** The seed check (R-24) and held-out recall belong to the initial search and are not repeated per cycle; held-out recall is reported per protocol version as today. A cycle's report contains no seed information. Seeds published after the first search are not added to the held-out set (that would leak the cycle's outcome into the honest figure).
20. **End of a living review [confirm].** `watch_plan.until` (a date) or an amendment that removes `watch_plan` ends the watch; `watch run` then refuses for the project with a reason, and the digest marks it `retired`. Elliott et al. (M11) require that a living review state when it stops being living.
21. **Failure handling [confirm].** A failed or partial run leaves its cycle `partial`; the cycle records which queries completed. The window boundary of a source advances only past cycles in which all of that source's runs completed; the next due cycle retries the rest. A source that fails `max_consecutive_failures` cycles (declared, default 3) raises `watch-source-failing` in `check` and the digest.
22. **Model drift across cycles [confirm].** (a) *Recommended:* a session joining a pass after the first cycle with a `model` that no calibration of that pass under the current protocol lineage recorded raises `calibration-model-drift`: a `check` warning in `pilot`, a join refusal in `systematic` until the pass is recalibrated. (b) Ignore drift: rejected; long living reviews outlive model versions, and calibration measured one model.

## Design

### Watch plan (protocol section)
```
WatchPlan:
  sources: tuple[WatchSource, ...]          # each names a protocol source with included=True
  notices: tuple[Literal["openalex","crossref"], ...] = ("openalex", "crossref")
  notice_budget: int = 200                   # identifier lookups per cycle
  track_versions: bool = True
  snapshot_every: int | None = None          # cycles; None = human-triggered only
  max_consecutive_failures: int = 3
  digest_listing_cap: int = 50
  until: date | None = None
WatchSource:
  source: str
  interval_days: int (>= 1)
  mode: Literal["full","window"] = "full"
  overlap_days: int = 7                      # window only
  full_replay_every: int | None              # required for window
```
Validation (boundary): every `WatchSource.source` names an included `SourcePlan`; `window` requires a source adapter that declares a listing-date filter (`Source.window_filter`), `overlap_days >= 1` and `full_replay_every`; `until` after the protocol's recording date. Readiness rules: `living-review` profile without `watch_plan` is a readiness error in `pilot`/`systematic` and a gap otherwise.

### Watch cycle (retrieval module)
One cycle per project and due moment. The service `services/watch.py`:
1. Under the exclusive index lock: refuse when the project has no ready protocol with a `watch_plan`, when `until` has passed, or when the protocol gate fails; resume an open cycle if one exists; otherwise write `watch.cycle_started` (cycle id, due sources, mode per source, window start per window source, `full_replay` flag, protocol id).
2. For each due source and each planned query of that source: register the query (unchanged text for `full`; planned text plus window filter for `window`, naming the cycle) and `run_query` it. A failed run does not stop the others.
3. Incremental dedup of the cycle's new records (ruling 7).
4. Pass B sample extension for new works (ruling 9) through the existing `_extend_sample` path.
5. Notice and version checks (plan living-C) within `notice_budget`.
6. `watch.cycle_finished`: status (`complete|partial|failed`), run ids, and computed counts: records retrieved, new works after dedup, duplicates, for a full replay of a window source the `window_missed` count (new works the replay found whose listing date lay inside an earlier window), works no longer returned by the source (`disappeared`, reported, never deleted).
7. When `snapshot_every` is reached, a snapshot (ruling 17).

Every count is computed by the service from events of the cycle; none is supplied. The system actor writes all cycle events; the triggering actor (human via CLI, agent via MCP, `system` for the scheduler) is recorded on `watch.cycle_started`.

### Due computation
`next_due(project, source) = last finished cycle covering source + interval_days`, or now when none exists. Computed from `watch.cycle_finished` events, using `project.clock`, so tests run on a fixed clock. A cycle covers all sources that are due at its start; sources not due are skipped and named in the event.

### Notices and versions (status module)
A status lookup is an identifier lookup run with `QueryPurpose.STATUS` (new purpose): its records are archived but never become corpus works and never count in PRISMA identification (as probe runs). From each response the service derives observations:
- `notice.observed` (`ntc_<ULID>`): work, kind, notice date, notice identifier (DOI of the notice when given), source, run id, raw blob. Idempotent per (work, kind, notice identifier).
- `version.observed`: work, route, newer `source_version`, run id.
- `version.linked`: work, published identifiers (DOI, venue), source, run id.
Human acts (CLI only; over MCP only as relayed answers with the configured human as actor, decision 37 item 6): `notice.assessed` (notice id, decision `exclude|keep-flagged|no-effect|affects`, `fields` for `affects`, rationale) and `document.preferred` (work, document id, rationale). Each supersedes the previous act on the same target.

### Effects (pure, read time)
`model/notices.py`: `notice_state(observed, assessed) -> dict[work_id, WorkNoticeState]` with `flag` (`retracted|correction-pending|concern|none`), `synthesis` (`excluded|labelled|normal`) and `stale_fields` (for `affects`). Consumers apply it:
- `services/evidence_report.py`: rows of works with `synthesis = excluded` leave groups and frontiers and appear in `Excluded` (new reasons `retracted`, `correction-pending`); labelled rows carry the flag. A flag `include_notice_affected` widens the view (CLI only).
- Extraction staleness: `stale_fields` joins plan-D row staleness through a new `RowRef`-level rule `notice_stale_rows(states, rows)` in `model/staleness.py`, beside `stale_rows`.
- Lineage (if slice 3b is built): `services/lineage.py` effective status gains `retracted-basis`, hidden by default like `stale`.
- `check`, `trace` and the digest read the same function.

### Conclusions and snapshots (builder)
`services/conclusions.py` computes `ConclusionFacts` from `evidence_report(...)` (the default, agent-independent view) and, if built, the lineage queries; `register_conclusion` validates that every basis reference resolves through `trace` and that the predicate's arguments exist. `snapshot(project, actor)` writes the blob and event. `conclusion_diff(project)` compares current facts and predicate values to the last snapshot and returns per-conclusion `unchanged|changed|basis-affected` with the fact-level difference (added and removed frontier members, a changed best row, a changed count). Diffs are computed, never stored; the digest and `check` (`conclusion-changed`, advisory) read them.

### Deterministic versus agent
| Platform (deterministic, tested, offline by default) | Agent or human |
| --- | --- |
| Due times, cycles, query construction, runs, archiving, dedup, sample extension, counts | — |
| Notice and version observation from source metadata; effect computation; staleness | Human assesses notices, prefers a document |
| Conclusion facts, predicates, snapshots, diffs; digest assembly | Human registers conclusions (statement and basis) |
| — | Agents screen and extract new works through the existing passes; a scheduled agent may read and deliver the digest |
No agent writes a notice, a version link, a count or a conclusion state. Agent-written events in this slice are limited to `watch.cycle_started` triggered over MCP (with provenance, R-04).

## Events (schema 1)
| Event | Payload (summary) | Actor |
| --- | --- | --- |
| `watch.cycle_started` | `cycle_id`, `protocol_id`, `sources` (source, mode, window start, full replay), `skipped` sources, `trigger` | system (trigger recorded) |
| `watch.cycle_finished` | `cycle_id`, `status`, `run_ids`, `status_run_ids`, computed counts per source | system |
| `notice.observed` | `notice_id`, `work_id`, `kind`, `notice_date`, `notice_doi`, `source`, `run_id`, `raw_blob` | system |
| `notice.assessed` | `notice_id`, `decision`, `fields`, `rationale` | human |
| `version.observed` | `work_id`, `route`, `source_version`, `run_id` | system |
| `version.linked` | `work_id`, `identifiers`, `venue`, `source`, `run_id` | system |
| `document.preferred` | `work_id`, `document_id`, `rationale` | human |
| `conclusion.registered` / `conclusion.retired` | `conclusion_id`, `statement`, `basis`, `predicate`; `retired`: reason | human |
| `living.snapshot_recorded` | `snapshot_id`, `cutoff_event`, `protocol_id`, `blob`, `projection_version` | system |
| `digest.generated` | `digest_id`, `projects`, `since_event`, `cutoff_event`, `blob`, counts | system |
`query.registered` gains no field: a window or status query names its cycle by its last ref (the snowball pattern). `QueryPurpose` gains `STATUS`. No existing event changes; a log without these events projects to an identical state hash except the projection version.

## Index tables (projections, written only by the projector)
`watch_cycles`, `watch_cycle_runs`, `notices`, `notice_assessments`, `version_observations`, `work_aliases` (identifier → work id, from `version.linked`), `document_preferences`, `conclusions`, `snapshots`, `digests`. Effects, due times and diffs are computed on read. Indexed columns: `work_id` on notices, versions, aliases; `(project, finished_at)` on cycles. Rebuild determinism holds (slice-1 AC 1).

## MCP tools and CLI
| Tool | Purpose | Actor |
| --- | --- | --- |
| `watch_status` | Per source: last cycle, next due, mode, window start, failures; open cycle | read |
| `watch_run` | Run the due cycle of this project (refused when nothing is due unless `force`) | agent (recorded) |
| `notice_list` | Notices with computed state and affected counts (no assessment tool over MCP except relayed human answers) | read |
| `conclusion_status` | Registered conclusions with computed state and the fact diff since the last snapshot | read |
| `digest_get` | Agent view of the digest since a cut-off | read |
Pass sessions are refused `watch_*`, `notice_list`, `conclusion_status` and `digest_get` (decisions 43, 48). CLI: `factory watch run|status|plan`, `factory notices list|assess`, `factory versions list|prefer`, `factory conclusions register|retire|status|diff`, `factory living snapshot|prisma-update`, `factory digest`. Services: `services/watch.py`, `services/dedup_incremental.py`, `services/notices.py`, `services/versions.py`, `services/conclusions.py`, `services/digest.py`; pure helpers `model/watch.py`, `model/notices.py`, `factory/living/` (`due.py`, `window.py`, `facts.py`, `digest_render.py`). Source adapters gain `window_filter` (arXiv, OpenAlex) and a new `sources/crossref.py` (notice lookups only). Skill: `rf-living` (how a scheduled agent reads a digest, what it may and may not do), versioned by hash.

## Check findings
`watch-plan-missing` (living-review without a plan; gap or error by mode) · `calibration-model-drift` (ruling 22) · `watch-overdue` (a due source not run for more than two intervals) · `watch-source-failing` · `watch-cycle-open` (an unfinished cycle older than a day) · `window-misses` (a full replay found works the windows missed; advisory, with the count) · `included-retracted` · `notice-unassessed` · `notice-unchecked-crossref` (advisory) · `newer-version-available` · `version-of-record-available` · `conclusion-changed` · `conclusion-basis-affected` · `update-audit-outstanding`. Messages carry ids and counts, never document text.

## Rigour requirements
Existing, in scope:
- **R-01, R-02:** each watch-found work carries provenance with the cycle's run and query; `trace` from a work names its cycle.
- **R-03, R-22, R-23:** watch and status runs archive raw responses and record PRISMA-S fields, reported and retrieved counts.
- **R-05:** every cycle count, PRISMA number (cumulative and update), notice count, conclusion state and digest number is computed from events.
- **R-14, R-15, decision 50:** `watch_plan` changes are amendments; adding works stales no decision; notices stale rows only through assessments.
- **R-21:** window retrieval only on a provably exhaustive listing-date partition, measured by periodic full replays.
- **R-25, R-26:** routes counted once; preprint and published versions linked by alias, never silently merged away.
- **R-27:** replay diffs are first-class; retracted records are flagged with notice date, never deleted, and raised as findings if included.
- **R-33–R-37:** updates use the declared passes, the extended sample, carried calibration and a topped-up audit.
- **R-43, R-47:** version changes produce new documents; no literature text in events or digests.

Added on acceptance (numbers in [01-rigour.md](01-rigour.md)):
- **R-102 Watch runs are search runs.** A living update identifies records only through recorded search runs of planned queries, grouped in cycles; window partitions are declared and their misses measured. P, S.
- **R-103 Update flow.** A living review reports, per update, a PRISMA flow over the records first identified in it, besides the cumulative flow; both computed. P, S.
- **R-104 Notice propagation.** Retractions, withdrawals, corrections and expressions of concern of dependent works are recorded with source and date; their effects reach only the affected work's dependents, are computed, and require a human assessment; nothing is deleted. All modes.
- **R-105 Conclusion change is computed.** A conclusion's change is a difference in computed facts or in its basis state since a recorded snapshot; no agent judges it. All modes.
- **R-106 Declared cadence and end.** A living review declares its cadence per source and when it stops being living. P, S.

## In scope
`watch_plan` section and readiness rules · watch cycles (full and window), due computation, `factory watch run` for external schedulers · incremental dedup · watch route in the candidate inbox · screening of updates (sample extension, audit top-up) · PRISMA update flow and cycle rows in the PRISMA-S report · notice observation (OpenAlex, Crossref), assessment and read-time effects · newer-version and version-of-record observation, aliases, preferred document · registered conclusions, conclusion facts, snapshots, diffs · digest builder, CLI and MCP agent view · check findings, trace extension · skill `rf-living`.

## Out of scope
Delivery channels (mail, chat, push) and any scheduler inside the platform; per-region digests (after slice 3 regions); cross-project suggestions (IDEA-04); idea capture from the stream (IDEA-05); arxiv-miner's daily scan as an adapter mode (IDEA-02 open question; revisit after acceptance 15); grey-source monitoring (outline grey literature, question 4); embeddings or similarity ranking (decision 9 open); automatic exclusion of retracted works by a criterion; automatic re-extraction without a human assessment or an explicit refresh; prose synthesis (slice 7); teams and routing digests to people (slice 5, IDEA-14); any model call by the platform.

## Acceptance criteria
1. **Hash stability.** A log without `watch_plan` replays to identical `P@` and `S@` ids; adding `watch_plan` changes `P@`, not `S@`, and keeps the PRESS confirmation.
2. **Readiness.** A `living-review` protocol without `watch_plan` is not ready in `pilot`; it is a gap in `exploratory`. A window source without `full_replay_every` or on an adapter without a listing-date filter is rejected, nothing written.
3. **Cycle is search runs.** A cycle on fixture sources writes `watch.cycle_started`, one complete search run per planned query of each due source, and `watch.cycle_finished` whose counts equal those recomputed from the run events.
4. **Due and idempotence.** On a fixed clock, `watch run --due` runs nothing before the interval and one cycle after it; a second call at the same time runs nothing; an open cycle is resumed, not doubled; two concurrent calls write one cycle.
5. **Window.** A window query equals the planned query plus the window filter, is authorised only when naming its cycle, and is refused for a foreign cycle; the window start advances only past complete cycles; a full replay reports the constructed missed works as `window_missed`.
6. **Incremental dedup equivalence.** Over randomised fixture corpora, incremental dedup after each cycle followed by `dedup_run` writes no event; the merges equal those of a single full run.
7. **Screening of updates.** New works are pending, appear in the inbox with route `watch`, enter pass B's sample by the recorded seed, are served to existing passes; calibration is not re-required; the audit top-up draws only from newly agreed decisions and meets the recomputed size.
8. **PRISMA update flow.** With two snapshots and a cycle between them, the update flow's boxes count only the cycle's records; the cumulative flow equals `prisma_flow`; both satisfy the PRISMA identities.
9. **Notices.** A fixture OpenAlex record with `is_retracted` and a fixture Crossref retraction each produce one `notice.observed` (idempotent on repeat); an included retracted work raises `included-retracted`; its rows leave the evidence report with reason `retracted`; no screening outcome changes.
10. **Bounded propagation.** A correction assessed `affects` on one field stales exactly the rows of that work carrying that field and re-queues only their units; every other row, unit and decision is unchanged (row-set equality test).
11. **Versions.** A newer arXiv version produces `newer-version-available` and no fetch; a version-of-record link adds aliases, merges a later database record of the published version by identifier, and changes no decision; `document.preferred` makes `default_conversion` serve the named document and stales that work's rows only.
12. **Conclusions.** A registered conclusion with a `best-in-group` predicate is `unchanged` after a cycle that adds no row to its group, `changed` after one that adds a better row, and `basis-affected` after a retraction of its basis work; registration with an unresolvable basis is refused.
13. **Digest.** The digest since the last recorded digest lists exactly the cycle's new works with their query ids, the open human decisions by kind, notices, versions and conclusion changes; it contains no document text, no verdict, no seed mark in the agent view; it is byte-identical across rebuilds for the same events and clock.
14. **Rebuild.** Deleting the index and rebuilding yields identical living tables and state hash.
15. **Scale.** On a synthetic project with 2·10^5 works and a cycle of 10^4 new records, a cycle with incremental dedup completes with peak memory bounded by the batch size (not the corpus), and `notice` coverage of 10^4 dependent works completes within the budgeted number of cycles (`slow`).
16. **Pilot.** The linear-attention pilot runs two weekly cycles (arXiv window, OpenAlex full); the digest, the update flow and the conclusion diff of one registered conclusion are reported; one `network` test checks each adapter's window filter and Crossref notice lookup against the live APIs.
17. **Quality.** `mypy --strict` and ruff pass; coverage ≥ 90% for `services/` and `model/`; TDD; the cycle service, incremental dedup and notice effects by subagent-driven development.

## Dependencies
| Slice / plan | Needed for |
| --- | --- |
| Slice 1 (search, dedup, screening, PRISMA) | Runs, gate, cascade, passes, sample extension, audit |
| Slice 2 plans A–E | Documents, routes, refresh, default conversion, extraction staleness, evidence report |
| Slice 3a | Snowball round pattern for authorised platform-built queries; route counting |
| Slice 3b (optional) | `retracted-basis` edge status and `path-exists` predicate; absent → those parts are skipped |
| Slice 4a | Candidate inbox and discovery record; `inbox.prioritised` (fallback in plan living-B) |
| Slice M | Module contract; this slice's services move behind it later |

## Decisions (recorded 2026-11-04)
- **62 Living corpus rulings.** Rulings 1–22 above, as one entry, with the recommended options, ruling 8 as corrected and ruling 10's priority hint deferred by the reconciliation above.
- **63 No scheduler in the platform.** Scheduling is external; the platform offers an idempotent, due-aware CLI command and computes everything from events (ruling 5). This extends decision 6 (platform never calls a model) to "the platform never acts on its own".

## Proposed sub-plans
| Plan | Content | Tier |
| --- | --- | --- |
| [living-A](../plans/2026-11-05-living-a-watch-cycles.md) | `watch_plan`, cycle events and projection, due computation, full and window modes, incremental dedup, `factory watch`, `watch_status`/`watch_run` | critical |
| [living-B](../plans/2026-11-05-living-b-updates-prisma.md) | Inbox route `watch` (or minimal fallback), sample extension and audit top-up for updates, snapshots, PRISMA update flow, PRISMA-S cycle rows, check findings for watches | critical |
| [living-C](../plans/2026-11-05-living-c-notices-versions.md) | `STATUS` purpose, Crossref adapter, notice and version observation, assessments, `document.preferred`, aliases, read-time effects in evidence report, extraction staleness and lineage | critical |
| [living-D](../plans/2026-11-05-living-d-conclusions-digest.md) | Registered conclusions, facts, predicates, diffs, digest builder and renderers, `factory digest`, `digest_get`, skill `rf-living`, acceptance and scale tests | standard |
Order: A → B → C → D; C depends only on A (status runs inside cycles) and may run in parallel with B.

## Open questions
1. **Cadence defaults.** Recommendation: arXiv weekly (daily only for `exploratory` watches), OpenAlex monthly, notices with every cycle; revisit after the pilot's two cycles.
2. **Notice scope beyond dependents.** Should notices be checked for every corpus work (e.g. to explain an excluded retracted work)? Recommendation: no; dependents only, with `factory notices check --all` as an explicit, budgeted command.
3. **Conclusions without an evidence report.** A scoping review has no frontiers. Recommendation: the predicate menu includes `group-row-count-at-least` and (with 3b) `path-exists`; counts by declared field values arrive with slice M builders.
4. **Shared watches across projects.** Two projects with the same query run it twice. Recommendation: accept the cost in this slice; a shared corpus layer (IDEA-37) may share raw pages by hash later, never decisions.
5. **Inbox ownership.** If slice 4a decides that inbox entries live outside the corpus until admitted, ruling 6 conflicts with it. Recommendation: settle ruling 6 and 4a's inbox ruling together; the watch events here are valid under either answer, only the PRISMA counting point moves.
