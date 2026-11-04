# Conclusions, Diffs, Digest and Slice-4b Acceptance Implementation Plan (slice 4b, sub-plan living-D)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: draft — rulings recommended; awaiting the researcher's review before any build.**

> **Dependencies.** Plans living-A, living-B and living-C merged (cycles, snapshots and `SnapshotBlob`, `prisma_update`, `work_states`, version findings). Plan 2E (evidence report) merged. Slice 3b optional: the `path-exists` predicate is registered only when `services/lineage.py` exists.

**Goal:** The researcher can register conclusions with their basis; after each cycle the platform reports, as computed facts, which conclusions changed and why; and a bounded, verdict-free digest per project (or for all projects) is produced for an external scheduler or agent to deliver.

**Architecture:** `living/facts.py` derives `ConclusionFacts` from an `EvidenceReport` (frontier members per group and axis partition, the best independent row per group where the direction is known, independent row counts, included-set size). `services/conclusions.py` records `conclusion.registered` / `conclusion.retired` (human), evaluates predicates and basis state, and contributes a `SnapshotSection` so each snapshot stores facts and conclusion states. `conclusion_diff` compares now with the last snapshot. `services/digest.py` assembles a `Digest` from living-A–C services and existing status services; `living/digest_render.py` renders Markdown and JSON deterministically.

**Tech Stack:** as living-A; no new dependency.

**Spec:** `docs/specs/slice-4b-living-corpus.md` rulings 16, 17 (conclusion part), 18, 19; acceptance 12, 13, 15 (notice part), 16, 17.

## Rulings made in this plan

1. **Best row.** `best-in-group` is defined only for a group whose `direction_status` is known and only within one frontier partition's unit (or, without frontiers, among independent rows sharing one value unit); otherwise the fact is `undefined` with the reason, never a guess. Ties: all tied row keys, sorted. Copied rows are never candidates (decision 52). [confirm]
2. **Basis references.** Accepted kinds: `cell` (`rk_<12hex>/field`), `row` (`rk_<12hex>`), `group` (`grp_` id from `group_id`), `work` (`rf:` id), `relation` (`rel_`, only with slice 3b). Each must resolve through `trace` at registration; a basis that later stops resolving makes the conclusion `basis-affected` (never an error that blocks a cycle). [confirm]
3. **Basis state.** A basis is affected when its work has `synthesis != normal` (`work_states`), its row is stale (plan-D rule, including `notice_stale_rows`), superseded, or no longer in a final row, or its relation is stale, rejected or `retracted-basis`. [confirm]
4. **Digest cut-off.** `since` = the `cutoff_event` of the project's last `digest.generated`, or of the given event id, or the project's first event; `cutoff` = the last event at assembly. With several projects, one `digest.generated` per project is written (each project's log is separate), all sharing one `digest_id`. [confirm]
5. **Listing order and cap.** New candidates by query id then work id; notices by date (unknown last) then work id; each list capped at `watch_plan.digest_listing_cap` (50 without a plan) with `more: int`. Titles appear (bibliographic metadata, not literature text); abstracts never. [confirm]

## Global Constraints

- As living-A. The digest and diff are builders: they write nothing except `digest.generated` (with `--record`) and snapshot sections inside living-B's snapshot event.
- Agent views (MCP): no held-out information, no label-derived rates (audit error rate, calibration sensitivity), no seed marks; refused to pass sessions (decisions 43, 48, 52).
- A conclusion statement is researcher text; it is never shown in the agent view of the digest (only its id and computed state), so no agent reads a human judgement as evidence (R-51 spirit).
- `uv run pytest -m "not network and not slow"`, `mypy --strict`, ruff pass; coverage ≥ 90 %.

## Review Focus

1. A conclusion's state follows the three cases of acceptance 12 exactly (Task 3, `test_conclusion_states_across_cycles`).
2. The digest contains no abstract, quote or verdict, and its agent view no seed or rate (Task 4, `test_digest_has_no_text_or_verdict`, `test_digest_agent_view_withholds`).
3. Digest bytes are identical across rebuilds (Task 4, `test_digest_deterministic`).
4. End-to-end acceptance on fixtures covers acceptance criteria 1–14 of the spec (Task 6).

## File Structure

- Create `living/facts.py`, `model/conclusions.py`, `services/conclusions.py`, `index/conclusions.py`, `services/digest.py`, `living/digest_render.py`, `model/digest.py`.
- Modify `model/living.py` (type the `SnapshotBlob` slots as `ConclusionFacts | None` and `tuple[ConclusionSnapshot, ...] | None`), `services/living_hooks.py` (register `conclusion_section`), `services/check.py`, `cli/main.py`, `cli/render.py`, `mcp/server.py`, `events/catalog.py`, `index/default.py`.
- Create `plugin/skills/rf-living/SKILL.md`; modify `plugin/PROVENANCE.md`.
- Tests: `test_living_facts.py`, `test_conclusions.py`, `test_conclusion_diff.py`, `test_digest.py`, `test_cli_living.py`, `test_acceptance_living.py` (`slow` for the long part), `test_living_notice_scale.py` (`slow`).

---

### Task 1: Conclusion facts (pure)

*Tier: standard.*

**Files:** Create `living/facts.py`; Test `tests/test_living_facts.py`.

**Interfaces:**
- Consumes: `EvidenceReport`, `GroupReport`, `FrontierAxis`, `FrontierPartition`, `FrontierPoint`, `group_id`.
- Produces:
  - `class GroupFacts(StrictModel): group_id: str; independent_rows: int; frontier: dict[str, tuple[str, ...]]` (key `"<axis>|<unit>|<resolution>"` → sorted row keys on the frontier); `best: tuple[str, ...] | None; best_reason: str | None`.
  - `class ConclusionFacts(StrictModel): included: int; groups: tuple[GroupFacts, ...]` (sorted by `group_id`); `paths: tuple[tuple[str, str, bool], ...] = ()`.
  - `def conclusion_facts(report: EvidenceReport, *, included: int, paths: Sequence[tuple[str, str, bool]] = ()) -> ConclusionFacts`.
  - `def facts_diff(old: ConclusionFacts, new: ConclusionFacts) -> FactsDiff` (`groups_added`, `groups_removed`, per group `frontier_added`, `frontier_removed`, `best_changed: tuple[old, new] | None`, `rows_delta`; `included_delta`).

- [ ] **Step 1: Tests.** `test_frontier_members_by_partition`, `test_best_respects_direction`, `test_best_undefined_without_direction` (reason `direction-unknown`), `test_best_ties_listed`, `test_copied_rows_never_best`, `test_facts_sorted_and_stable` (same report → same JSON bytes), `test_diff_detects_new_frontier_member`.
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_living_facts.py -q`.
- [ ] **Step 5: Commit** `feat(living): conclusion facts from the evidence report`.

### Task 2: Registered conclusions

*Tier: critical (human statements, R-51).*

**Files:** Create `model/conclusions.py`, `services/conclusions.py`, `index/conclusions.py`; Modify `events/catalog.py`, `index/default.py`; Test `tests/test_conclusions.py`.

**Interfaces:**
- `class BasisRef(StrictModel): kind: Literal["cell", "row", "group", "work", "relation"]; ref: str`.
- `class Predicate(StrictModel): kind: Literal["frontier-member", "best-in-group", "group-row-count-at-least", "path-exists"]; group_id: str | None = None; axis_key: str | None = None; row_key: str | None = None; count: int | None = None; source: str | None = None; target: str | None = None` with per-kind required fields.
- `class ConclusionRegistered(StrictModel): conclusion_id: str (CCL_ID_RE); statement: str = Field(min_length=1, max_length=2000); basis: tuple[BasisRef, ...] = Field(min_length=1); predicate: Predicate | None = None`.
- `class ConclusionRetired(StrictModel): conclusion_id; reason: str`.
- `def register_conclusion(project: Project, actor: Actor, statement: str, basis: Sequence[BasisRef], predicate: Predicate | None) -> str` — human only; every basis resolves via `trace`; predicate arguments exist in the current facts (`path-exists` refused when lineage is absent); returns the id.
- `def retire_conclusion(project, actor, conclusion_id, reason) -> None` — human only.
- `def predicate_value(facts: ConclusionFacts, predicate: Predicate) -> bool | None` (pure; `None` = undefined).
- `def basis_state(project: Project, basis: Sequence[BasisRef]) -> tuple[str, ...]` (the affected references with reasons, ruling 3).

- [ ] **Step 1: Tests.** `test_agent_cannot_register`, `test_unresolvable_basis_refused` (nothing written), `test_predicate_fields_per_kind`, `test_path_exists_refused_without_lineage`, `test_retired_conclusion_not_evaluated`, `test_predicate_value_cases`, `test_basis_state_retracted_work`, `test_basis_state_stale_row`.
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_conclusions.py -q`.
- [ ] **Step 5: Commit** `feat(living): registered conclusions with verified basis`.

### Task 3: Snapshot section and conclusion diff

*Tier: critical (alerting rule).*

**Files:** Modify `model/living.py`, `services/conclusions.py`, `services/living_hooks.py`, `services/check.py`; Test `tests/test_conclusion_diff.py`.

**Interfaces:**
- `class ConclusionSnapshot(StrictModel): conclusion_id: str; predicate_value: bool | None; affected: tuple[str, ...]`.
- `def conclusion_section(project: Project) -> tuple[str, JsonValue]` — a living-B `SnapshotSection`; fills `conclusion_facts` and `conclusions` (facts from the default, non-agent evidence report with `include_notice_affected=False`).
- `class ConclusionDiff(StrictModel): conclusion_id: str; state: Literal["unchanged", "changed", "basis-affected", "new"]; predicate_before: bool | None; predicate_now: bool | None; affected: tuple[str, ...]; facts: FactsDiff | None`.
- `def conclusion_diff(project: Project, *, since: str | None = None) -> list[ConclusionDiff]` — against snapshot `since` (default: last); `new` for conclusions registered after it; no snapshot → every conclusion `new`.
- Findings `conclusion-changed` (advisory), `conclusion-basis-affected` (warning in pilot, error in systematic).

- [ ] **Step 1: Tests.** `test_conclusion_states_across_cycles` (fixture: snapshot; cycle adding no row to the group → `unchanged`; cycle adding a better row, screened and extracted → `changed` with `best_changed`; retraction notice on the basis work → `basis-affected`), `test_diff_against_named_snapshot`, `test_snapshot_blob_holds_conclusion_states`, `test_findings_by_mode`.
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_conclusion_diff.py tests/test_snapshots.py -q`.
- [ ] **Step 5: Commit** `feat(living): conclusion diffs against snapshots`.

### Task 4: Digest builder and renderers

*Tier: standard.*

**Files:** Create `model/digest.py`, `services/digest.py`, `living/digest_render.py`; Modify `events/catalog.py`, `index/living.py` (table `digests`); Test `tests/test_digest.py`.

**Interfaces:**
- `class DigestProject(StrictModel): slug: str; status: Literal["active", "retired", "no-watch"]; since_event: str | None; cutoff_event: str; cycles: tuple[CycleSummaryRow, ...]; new_candidates: Listing[CandidateRow]` (`work_id`, `title`, `query_ids`, `route`); `open_decisions: dict[str, int]` (keys `screening-disagreements`, `calibration-labels`, `audit-labels`, `notice-assessments`, `inferred-relations`, `fuzzy-reference-links`); `notices: Listing[NoticeRow]`; `versions: Listing[VersionRow]`; `conclusions: tuple[ConclusionDiff, ...]`; `failures: tuple[str, ...]`; `overdue: tuple[str, ...]`; `update_flow: UpdateFlow | None`.
- `class Listing(StrictModel, Generic[T]): items: tuple[T, ...]; more: int`.
- `class Digest(StrictModel): digest_id: str | None; generated_at: datetime; projects: tuple[DigestProject, ...]`.
- `def digest_build(projects: Sequence[Project], *, since: str | Literal["last"] | None = "last") -> Digest`.
- `def agent_digest(d: Digest) -> Digest` — removes `statement`-bearing fields (none are in `ConclusionDiff`), `update_flow` held-out fields, label-derived counts; keeps counts of open decisions.
- `def record_digest(projects: Sequence[Project], d: Digest) -> str` — renders, stores the Markdown and JSON blobs, writes one `digest.generated` per project (ruling 4); returns `digest_id`.
- `living/digest_render.py`: `def to_markdown(d: Digest) -> str`, `def to_json(d: Digest) -> str` (canonical JSON, sorted keys).

- [ ] **Step 1: Tests.** `test_digest_lists_cycle_candidates_with_query_ids`, `test_digest_since_last_recorded`, `test_open_decisions_counts_recompute`, `test_listing_cap_and_more`, `test_digest_has_no_text_or_verdict` (no abstract, quote or verdict string in either rendering), `test_digest_agent_view_withholds` (no seed id, no audit or calibration rate), `test_digest_deterministic` (rebuild + `FixedClock` → identical bytes), `test_retired_project_marked`.
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_digest.py -q`.
- [ ] **Step 5: Commit** `feat(living): computed digest`.

### Task 5: CLI, MCP and skill

*Tier: standard.*

**Files:** Modify `cli/main.py`, `cli/render.py`, `mcp/server.py`; Create `plugin/skills/rf-living/SKILL.md`; Modify `plugin/PROVENANCE.md`; Test `tests/test_cli_living.py`, extend MCP tests.

**Interfaces:**
- CLI: `factory conclusions register --statement TEXT --basis KIND:REF … [--predicate JSON]`, `factory conclusions retire ID --reason TEXT`, `factory conclusions status`, `factory conclusions diff [--since SNAPSHOT]`, `factory digest [--project SLUG | --all] [--since EVENT|last] [--format md|json] [--out DIR] [--record]`.
- MCP: `conclusion_status()` (ids, states, fact diffs; no statements), `digest_get(since: str | None = "last")` (agent view; never records). Both refused to pass sessions.
- Skill `rf-living`: for a scheduled agent session: run `factory watch run --due --all`, then `factory digest --all --record --format md --out <dir>`, deliver the file by the channel the researcher configured; never assess notices, prefer documents, register conclusions or record priority hints (human acts); screening of new works only by joining a pass in a separate session under `rf-screen`. Skill hash computed by `skill_ref`.

- [ ] **Step 1: Tests.** `test_cli_digest_writes_md_and_json`, `test_cli_digest_record_writes_one_event_per_project`, `test_cli_conclusions_register_and_diff`, `test_mcp_digest_get_is_agent_view`, `test_mcp_conclusion_status_has_no_statement`, `test_mcp_living_tools_refused_to_pass_session`, `test_skill_ref_for_rf_living`.
- [ ] **Step 2–4:** fail, implement, `uv run pytest tests/test_cli_living.py tests/test_mcp*.py tests/test_skills*.py -q`.
- [ ] **Step 5: Commit** `feat(living): digest and conclusion commands, MCP views, rf-living skill`.

### Task 6: Slice acceptance and scale

*Tier: standard.*

**Files:** Test `tests/test_acceptance_living.py`, `tests/test_living_notice_scale.py`; Modify `docs/runbook-living.md` (pilot steps).

- [ ] **Step 1: Acceptance (fixtures, offline).** One test per spec acceptance criterion 1–14, on a pilot-mode living-review project built with `watch_helpers` and `evidence_helpers`: two cycles (arXiv window, OpenAlex full), new works screened by two scripted passes in separate sessions, one extracted better row, one Crossref retraction on an included work, one correction assessed `affects`, one version-of-record link, one registered conclusion, two snapshots, a recorded digest; then `factory rebuild` and state-hash equality. Names `test_ac01_hash_stability` … `test_ac14_rebuild`.
- [ ] **Step 2: Scale (`slow`).** 10^4 dependent works, `notice_budget = 500`: coverage complete after 20 cycles, each cycle's peak memory bounded by the budget (`tracemalloc`), `work_states` read by indexed queries only (spy: no `list_works`).
- [ ] **Step 3: Pilot (manual, recorded in `docs/pilot/log.md` by the researcher, not by the build).** The runbook lists: declare `watch_plan` by amendment, run two weekly cycles, register one conclusion on a linear-attention group, record a snapshot and a digest. The build does not run the pilot.
- [ ] **Step 4:** `uv run pytest -m "not network and not slow" -q && uv run pytest -m slow tests/test_acceptance_living.py tests/test_living_notice_scale.py -q`.
- [ ] **Step 5: Commit** `test(living): slice 4b acceptance and scale`.

## Verification

`uv run pytest -m "not network and not slow" -q && uv run mypy --strict src && uv run ruff check src tests` from `platform/`; then the `slow` set above.

## Self-review notes

- No digest field is typed by a person or an agent; `open_decisions` counts come from the existing status services (`screen_agreement` disagreement count read through the CLI-side service, `audit_outstanding`, `notice_state`, slice-3a/3b status where present).
- Conclusion statements stay in human events and the CLI; the agent never sees them through this slice's tools.
- The slice's *Proposed* decision entry (spec, "Proposed decisions") is drafted in `docs/decisions.md` only when the researcher accepts the rulings, not by this plan.
