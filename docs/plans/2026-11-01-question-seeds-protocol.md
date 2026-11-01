# Question, Seeds, Probe and Protocol Implementation Plan (slice 1, sub-plan 3 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A project gets a versioned question (`Q@`), positive and negative seeds resolved to works with a recorded development/held-out split, a scope probe that measures seed recall and negative hits per query and source, and a versioned protocol (`P@`) with PRESS review, amendments (with computed stale rules), deviations and search gating. Claude uses all of it through MCP tools, and the three matching plugin skills ship with the platform.

**Architecture:** As in plans 1–2, every change is an event, the projection is the only read model, and services hold the logic. Version IDs are content hashes over decision-relevant fields only: prose is stripped before hashing (ported from research-factory-old `lock.py`). Seed lookups reuse `run_query` with purpose `probe`. Probe-purpose records are **quarantined**: they are stored, but they are never part of the corpus. The probe never retrieves records. It asks each source for the reported count and for which development-seed IDs the query matches (arXiv `id_list ∩ search_query`, OpenAlex `openalex:` filter combined with the query), and it archives every raw response. Readiness checks over the protocol are a pure function (`protocol_rules`), so the same rules serve `protocol_record`, `protocol_amend` and, in plan 5, `check --promote-to`.

**Tech Stack:** as plans 1–2 (Python 3.12, uv, pydantic 2, SQLAlchemy Core, typer, mcp 2.x, httpx).

**Spec:** `docs/specs/00-system.md` (§3 `Q@`/`P@`/criterion/seed IDs, §4.2 provenance trust, §7), `docs/specs/01-rigour.md` (R-04, R-10–R-16, R-20, R-22, R-24 data side, R-39 roles, R-60, R-61), `docs/specs/slice-1.md` (user flow 1–6; acceptance 6, 7, 13, 19 data side, 22; open questions on seed recall thresholds, κ floor and provenance trust). Old specs: `docs/reference/research-factory-old-spec/stages/00-frame.md`, `01-scope.md`, `02-protocol.md`, `RIGOR-MODES.md`. Code origin: `~/Projects/research-factory-old/src/rf/lock.py` (prose stripping, hashing), `probe.py` (`suggest_terms`, n-grams).

## Global Constraints

- All plan-1 and plan-2 constraints hold:
  - no model calls;
  - logic lives in services;
  - events are append-only;
  - the projector is the only index writer, and handlers are total;
  - validate before writing (invalid input writes nothing and returns structured errors);
  - mypy --strict and ruff must pass;
  - coverage ≥ 90% for `factory.services` and `factory.model`;
  - tests run offline, and live tests carry the `network` marker;
  - the contact address comes only from `FACTORY_MAILTO`.
- Every agent-written event carries model, skill and `input_blob`, where `input_blob` is the canonical JSON of the validated tool input (R-04). The skill reference is computed by the platform from the installed skill file (Task 1); agents pass the bare skill name.
- **Version hashes:** `Q@<sha256[:8]>` and `P@<sha256[:8]>` over `canonical_json` of the hashed fields, with lists sorted as each task specifies. Prose keys are never hashed: `note`, `rationale`, `why`, `reason`, `comment`, `examples`, `duties`, `scheme_rationale`, `objectives`. A prose-only change never produces a new version (acceptance 6).
- **Seed recall thresholds** (slice-1 open question): `exploratory` 0.6, `pilot` 0.9, `systematic` 1.0.
- **κ floor** (slice-1 open question): declared in every pilot or systematic protocol. It is advisory in `pilot` (`kappa_enforced` may be false) and in `systematic` must be ≥ 0.7 with `kappa_enforced = true`.
- **Held-out seeds** (R-20, acceptance 22) are never returned by any agent-facing tool, never sent to a source by the probe, and never accepted as worked examples. Only the human CLI view and the post-search seed check show them.
- **Corpus:** works with at least one provenance row from a query whose purpose is not `probe`. Probe-purpose records stay stored but outside the corpus.
- Any task that changes tables or handlers increments `PROJECTION_VERSION` by one.
- Commit after each task on branch `plan-3-question-protocol`. The commit trailer names the authoring model (`Co-Authored-By: Claude <Model> 5.5 <noreply@anthropic.com>`). Stage only your own files, never `git add -A`.
- All commands below run from `platform/` unless stated.

## Review Focus

1. **Held-out seeds leak through a side channel.** Candidate channels are term-suggestion holders, error messages, counts in `project_status`, an agent's own `input_blob`, and the probe's requests to the source. The expected behaviour is that no held-out seed ID, and no work ID resolved from one, appears in anything an agent can read or in any request sent by the probe. → Task 6 `test_probe_never_mentions_held_out_seeds` (scans the response, the events written and their blobs, and the captured requests); Task 10 `test_agent_tools_never_reveal_held_out_seeds`.
2. **A seed is given in another identifier form.** Examples are a DOI URL, a DataCite arXiv DOI, an arXiv ID with a version suffix, or an upper-case DOI. The seed must resolve via the right source, and re-adding it in another form must be caught as a duplicate. → Task 3 `test_datacite_doi_uses_arxiv_route`, `test_duplicate_seed_in_another_form_is_rejected`.
3. **A criterion is renamed or replaced during an amendment** (EX03 removed, EX04 added with similar text). This must be treated as removed + added, not as a silent rename. Exclusions citing EX03 go stale, and decisions never tested against EX04 go stale. → Task 9 `test_renamed_criterion_is_removed_plus_added`.
4. **A source fails mid-probe**, with a transport error on a count or matching request. Pages already fetched stay archived. That query is reported as failed with the reason, the other queries are still measured, and nothing claims a recall for the failed query. → Task 6 `test_source_error_during_probe_is_reported`.
5. **The question is re-versioned after the protocol is ready.** Searches must be refused until the protocol is amended onto the current question, because a search authorised by a protocol built on a superseded question breaks the trace. → Task 8 `test_search_refused_when_question_changed_after_protocol`.

---

## File Structure

```
platform/src/factory/
  config.py                  + Settings.plugin_dir (FACTORY_PLUGIN_DIR, default <root>/plugin)
  model/
    question.py              Slot, NonGoal, QuestionSpec, question_version(), GoalStated, QuestionRecorded
    seed.py                  SeedKind, SeedSpec, seed.* payloads, AdmissionRoute
    probe.py                 ProbePageArchived, ProbeMeasured, TermSuggestion
    protocol.py              Criterion, SourcePlan, PlannedQuery, Limit, Reviewer, ScreeningPlan,
                             ProtocolSpec, strip_prose(), protocol_version(), search_strategy_hash(),
                             protocol.* payloads (recorded, press_*, deviation_recorded, amended)
  sources/
    base.py                  + Prober protocol, probe_key()
    arxiv.py                 matching() to Prober signature, + count()
    openalex.py              + count(), matching()
  index/
    question.py  seeds.py  probe.py  protocol.py      tables + handlers
  services/
    skills.py                skill_ref(): platform-computed skill hash
    question.py              state_goal(), record_question(), current_question(), goals()
    seeds.py                 add_seeds(), split_seeds(), draw_split(), agent_seeds(), all_seeds(),
                             explain_seed_miss(), seed_check(), seed_recall()
    vocabulary.py            ported probe.py term suggestion (pure)
    probe.py                 run_probe(), ProbeReport
    protocol_rules.py        protocol_issues() (pure), criterion_changes(), stale_rules(), stale_decisions()
    protocol.py              record_protocol(), current_protocol(), press_review(), confirm_press(),
                             record_deviation(), amend_protocol(), search_authorization(), lists
    search.py                list_works(include_probe=False); register_query(deviation_id=…) gated
  mcp/server.py              + question_record, seed_add, seed_list, probe_run, protocol_record,
                               protocol_press_review, protocol_amend, protocol_deviation
  cli/main.py                + seeds [split|explain], protocol confirm-press; status lines
plugin/
  .claude-plugin/plugin.json   PROVENANCE.md
  skills/rf-frame/SKILL.md  skills/rf-probe/SKILL.md  skills/rf-protocol/SKILL.md
```

---

### Task 1: Plan-2 carry-over and platform-computed skill references (provenance trust)

**Files:**
- Modify: `platform/src/factory/config.py`, `platform/src/factory/mcp/conventions.py`, `platform/src/factory/mcp/server.py`, `platform/src/factory/services/search.py`, `platform/src/factory/services/dedup.py`, `platform/src/factory/sources/*.py`, `platform/tests/conftest.py`, `platform/tests/helpers.py`, the MCP tests that pass skills
- Create: `platform/src/factory/services/skills.py`, `platform/tests/test_skills.py`

**Carry-over from the plan-2 final review** (fix these first, failing test first):
- **Static `kinds`.** `Source.kinds` becomes a class attribute on every adapter. `register_query` validates against the factory's class and does not build an adapter, so validation opens no HTTP client. Test: `test_validation_builds_no_adapter`.
- **The triggering actor is recorded.** `run_query(..., actor: Actor | None = None)` records `search.run_started` as `actor` when given; an agent gets `input_blob = {query_id, resume_run}`. The MCP `search_run` tool passes the agent. Test: `test_run_started_records_the_triggering_agent`.
- **Double resume.**
  - `_resume_token` refuses a run that already has a resumer (field `resume_run`, `"already resumed by {run_id}"`).
  - `dedup_run` holds the index's exclusive lock across read → compute → write, using the existing `Index` lock helper. Two concurrent calls must not record the same merge twice.
  - Tests: `test_run_cannot_be_resumed_twice`, `test_concurrent_dedup_runs_record_one_merge`.
- **OpenAlex filter values.** A comma or colon in an OpenAlex `filters` key or value corrupts the filter expression, just as a comma in keyword text did (fixed in plan 2). Reject it in `_spec_issues` (field `filters`). Test: `test_openalex_filter_value_with_comma_rejected`.
- **Resume lookup.** `resume_query_id` must raise when the run's query row is missing, not pass silently.

**Interfaces:**
- Produces:
  - `Settings.plugin_dir: Path` comes from the argument, then env `FACTORY_PLUGIN_DIR`, then `root / "plugin"`.
  - `skill_ref(settings: Settings, skill: str) -> str` in `services/skills.py` returns `f"{name}@{sha256(SKILL.md bytes).hexdigest()[:8]}"`, where the file is `settings.plugin_dir / "skills" / name / "SKILL.md"`.
  - `skill` may be a bare `name` or `name@<hex>`. With `@hex`, the hex must equal the computed hash.
  - `make_agent_actor(settings, session, role, model, skill)` resolves `skill` through `skill_ref` before building the `Actor`.
  - `helpers.install_skill(settings: Settings, name: str, text: str = "test skill") -> str` writes the file and returns the ref.
- Validation issues use field `skill`:
  - malformed: `"must be a skill name like rf-probe"`;
  - not installed: `f"no installed skill {name!r} under {plugin_dir}"`;
  - hash mismatch: `f"skill file changed: installed {ref}, caller sent {skill}"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_bare_name_resolves_to_hash_of_the_installed_file(settings):
    install_skill(settings, "rf-probe", "v1")
    assert skill_ref(settings, "rf-probe") == "rf-probe@" + hashlib.sha256(b"v1").hexdigest()[:8]
def test_matching_supplied_hash_is_accepted(settings): ...
def test_stale_supplied_hash_is_rejected(settings): ...      # FactoryValidationError, issues[0].field == "skill"
def test_unknown_skill_is_rejected(settings): ...
def test_plugin_dir_from_env(monkeypatch, tmp_path): ...     # FACTORY_PLUGIN_DIR
@pytest.mark.anyio
async def test_tool_records_platform_computed_skill(settings, project, mock_sources): ...
    # search_run with skill="rf-search" → query.registered actor.skill == skill_ref(settings, "rf-search")
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_skills.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement.** The `settings` fixture installs the skills the existing tests use, and the MCP tests pass bare names. Do not weaken any existing assertion.
- [ ] **Step 4: Run to verify pass** — `uv run pytest -W error -q` → all PASS.
- [ ] **Step 5: Commit** — `git commit -m "fix: plan-2 carry-over; feat(provenance): skill references computed from installed skill files"`

---

### Task 2: Question (`Q@`) and the verbatim raw goal

**Files:**
- Create: `platform/src/factory/model/question.py`, `platform/src/factory/index/question.py`, `platform/src/factory/services/question.py`, `platform/tests/test_question.py`
- Modify: `platform/src/factory/events/catalog.py`, `platform/src/factory/index/default.py`

**Interfaces:**
- Produces (model):
  - `NON_GOAL_ID_RE = r"^NG\d{2}$"` and `QUESTION_ID_RE = r"^Q@[0-9a-f]{8}$"`.
  - `Slot(name: str, value: str | None = None, open: str | None = None, resolve_in: str | None = None)`. Exactly one of `value`/`open` is set. `value.strip().upper() != "TBD"`. `open` requires a non-empty `resolve_in`.
  - `NonGoal(id: str, text: str)`.
  - `QuestionSpec(scheme: str, primary_question: str, slots: tuple[Slot, ...] (≥1, unique names), non_goals: tuple[NonGoal, ...] (unique ids), scheme_rationale: str = "", rationale: str = "", objectives: str = "")`.
  - `question_version(spec) -> str` hashes `{scheme, primary_question, slots sorted by name as [name, value, open, resolve_in], non_goals sorted by id as [id, text]}`.
  - Payloads:
    - `GoalStated(text: str)`: `text` is stored verbatim, not stripped, and must contain a non-whitespace character.
    - `QuestionRecorded(question_id, supersedes: str | None, reason: str | None, spec: QuestionSpec)`.
  - Events: `question.goal_stated`, `question.recorded`.
- Produces (service):
  - `state_goal(project, actor, text) -> str` returns the event id.
  - `record_question(project, actor, spec, *, reason: str | None = None) -> QuestionResult(question_id: str, created: bool)`.
  - `current_question(project) -> QuestionVersion | None` with fields `question_id, spec, supersedes, reason, recorded_at`.
  - `get_question(project, question_id) -> QuestionVersion | None` and `goals(project) -> list[Goal(text, at, actor_id)]`.
- Rules for `record_question` (issues name the field):
  - At least one goal must be stated first (`raw_goal`).
  - Non-goals: ≥1 in `exploratory`, ≥3 in `pilot`/`systematic` (`non_goals`).
  - Open slots ≤ half of all slots in P/S (`slots`).
  - `rationale` and `objectives` must be non-empty in P/S.
  - An identical spec (every field, prose included) writes nothing and returns `created=False`.
  - A new hash with a prior version requires `reason`, and `supersedes` is set by the platform.
  - The same hash with different prose writes an event with the same `question_id` and `supersedes=None`.
  - An agent's event carries `input_blob`.

- [ ] **Step 1: Write the failing tests**

```python
def test_version_ignores_prose(): ...                         # change rationale/objectives/scheme_rationale → same Q@
def test_version_changes_with_slot_value(): ...
def test_version_is_order_independent(): ...                  # slots and non-goals reordered → same Q@
def test_tbd_slot_rejected(): ...                             # value " tbd " → ValidationError
def test_open_slot_needs_resolve_in(): ...
def test_slot_has_exactly_one_of_value_and_open(): ...
def test_duplicate_slot_names_rejected(): ...
def test_pilot_needs_three_non_goals(project, agent):         # project is pilot
    state_goal(project, agent, "linear attention for vision")
    before = project_status(project).events_total
    with pytest.raises(FactoryValidationError) as e: record_question(project, agent, spec(non_goals=2))
    assert e.value.issues[0].field == "non_goals" and project_status(project).events_total == before
def test_exploratory_accepts_one_non_goal(settings, clock): ...
def test_open_slots_more_than_half_rejected_in_pilot(project, agent): ...
def test_question_needs_a_stated_goal(project, agent): ...    # field "raw_goal"
def test_goal_is_stored_verbatim(project, agent):
    state_goal(project, agent, "  i want to know if…\n"); assert goals(project)[0].text == "  i want to know if…\n"
def test_identical_resubmission_writes_nothing(project, agent): ...
def test_prose_only_change_keeps_the_version(project, agent): ...
def test_semantic_change_needs_reason_and_records_supersedes(project, agent): ...
def test_agent_question_carries_input_blob(project, agent): ...
def test_question_rebuild_equals_incremental(project, agent): ...   # state_hash() == state after rebuild()
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_question.py -v` → FAIL.
- [ ] **Step 3: Implement** the model, the projection (tables `goals(event_id pk, text, at, actor_id)` and `questions(event_id pk, question_id, supersedes, reason, spec json, at)`, where "current" is the latest `questions` row by `event_id`), the service, and catalog registration. Increment `PROJECTION_VERSION`.
- [ ] **Step 4: Run to verify pass** — `uv run pytest -W error -q`.
- [ ] **Step 5: Commit** — `git commit -m "feat(question): versioned question with verbatim raw goal"`

---

### Task 3: Seeds — adding, resolving, and quarantine of probe records

**Files:**
- Create: `platform/src/factory/model/seed.py`, `platform/src/factory/index/seeds.py`, `platform/src/factory/services/seeds.py`, `platform/tests/test_seeds.py`
- Modify: `platform/src/factory/services/search.py` (`list_works`), `platform/src/factory/services/project.py`, catalog, `index/default.py`

**Interfaces:**
- Consumes: `register_query`, `run_query`, `get_work` (plan 2), `normalize_doi`, `normalize_arxiv`, `arxiv_id_from_doi`.
- Produces (model):
  - `SeedKind(StrEnum)`: `POSITIVE="positive"`, `NEGATIVE="negative"`.
  - `SEED_ID_RE = r"^(SEED|NEG)\d{2,}$"`.
  - `SeedSpec(kind: SeedKind, cite: str, doi: str | None = None, arxiv: str | None = None, openalex: str | None = None, why: str = "")`, with at least one identifier.
  - Payloads:
    - `SeedAdded(seed_id, spec)`;
    - `SeedResolved(seed_id, work_id, run_id)`;
    - `SeedUnresolved(seed_id, run_id: str | None, reason: str)`.
  - Events: `seed.added`, `seed.resolved`, `seed.unresolved`.
- Produces (service):
  - `add_seeds(project, actor, specs: Sequence[SeedSpec], *, sources) -> BatchResult[SeedOutcome]`, with `SeedOutcome(seed_id, work_id: str | None, reason: str | None)`.
  - IDs are assigned in order per kind (`SEED01…`, `NEG01…`, zero-padded to two digits, more when needed).
  - **Lookup route** (one probe-purpose query per seed, registered with the caller's actor):
    - an arXiv ID, or a DOI that `arxiv_id_from_doi` bridges → `QuerySpec(source="arxiv", kind=ID_LIST, text=<normalised id>, purpose=PROBE)`;
    - otherwise a DOI → `QuerySpec(source="openalex", kind=FILTER, text=f"doi:{doi}", purpose=PROBE)`;
    - otherwise → `QuerySpec(source="openalex", kind=FILTER, text=f"openalex:{id}", purpose=PROBE)`.
  - **Lookup outcome:**
    - exactly one work → `seed.resolved`;
    - zero works → `seed.unresolved` with reason `f"not found in {source}"`;
    - a failed run → `seed.unresolved` with the run's note;
    - more than one work → `seed.unresolved` with reason `"ambiguous: n records"`.
  - A seed whose normalised DOI, arXiv ID or OpenAlex ID equals one of an existing seed's (across forms) is rejected with field `doi`/`arxiv`/`openalex` and reason `f"duplicate of {seed_id}"`.
  - `list_works(project, *, include_probe: bool = False)` drops works whose every provenance row comes from a `probe`-purpose query. `dedup_run`, `canonical_works` and `ProjectStatus.works`/`records` use the corpus only; `get_work` is unchanged.

- [ ] **Step 1: Write the failing tests** (sources are `fake_sources`/`mock_sources` from plan 2 with ID_LIST/FILTER kinds as needed)

```python
def test_seed_ids_are_assigned_per_kind(project, agent, mock_sources): ...   # SEED01, SEED02, NEG01
def test_arxiv_seed_resolves_via_id_list_probe_query(project, agent, mock_sources, http_log): ...
def test_doi_seed_resolves_via_openalex_filter(project, agent, mock_sources, http_log): ...
def test_datacite_doi_uses_arxiv_route(project, agent, mock_sources, http_log): ...
def test_unresolvable_seed_is_recorded_with_reason(project, agent, mock_sources): ...
def test_seed_without_identifier_rejected_others_written(project, agent, mock_sources): ...  # BatchResult partial
def test_duplicate_seed_in_another_form_is_rejected(project, agent, mock_sources): ...
    # "https://doi.org/10.48550/arXiv.2301.01234" after "2301.01234v2" → rejected, "duplicate of SEED01"
def test_probe_records_stay_out_of_the_corpus(project, agent, mock_sources):
    add_seeds(...)                      # creates a probe-purpose work
    assert list_works(project) == [] and len(list_works(project, include_probe=True)) == 1
    assert dedup_run(project).works == 0 and project_status(project).works == 0
def test_seed_rebuild_equals_incremental(project, agent, mock_sources): ...
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_seeds.py -v` → FAIL.
- [ ] **Step 3: Implement.** Add a `seeds(seed_id pk, kind, spec json, work_id, run_id, unresolved_reason, added_event)` table and handlers, then increment `PROJECTION_VERSION`.
- [ ] **Step 4: Run to verify pass** — `uv run pytest -W error -q` (plan-2 tests stay green).
- [ ] **Step 5: Commit** — `git commit -m "feat(seeds): seeds resolved by probe-purpose lookups; probe records quarantined"`

---

### Task 4: Hold-out split, seed views and the post-search seed check

**Files:**
- Modify: `platform/src/factory/model/seed.py`, `platform/src/factory/index/seeds.py`, `platform/src/factory/services/seeds.py`, catalog
- Test: `platform/tests/test_seed_split.py`

**Interfaces:**
- Produces (model):
  - `SPLIT_PROCEDURE = "year-stratified-thirds-v1"`.
  - Payloads:
    - `SeedSplitDrawn(random_seed: int (0 ≤ x < 2**32), procedure: str, development: tuple[str, ...], held_out: tuple[str, ...])`;
    - `SeedMissExplained(seed_id, reason: str, route: ProvenanceMethod)`, where `route` is any method except `DATABASE`.
  - Events: `seed.split_drawn`, `seed.miss_explained`.
- Produces (service):
  - `draw_split(positives: Sequence[tuple[str, int | None]], random_seed: int) -> tuple[list[str], list[str]]` is pure and works like this:
    1. Sort by `(year is None, year, seed_id)`.
    2. Cut into consecutive groups of 3.
    3. With one `random.Random(random_seed)`, every group of size 3 or 2 sends one member (by `rng.choice`) to held-out; a group of size 1 stays in development.
    4. Return `(sorted development, sorted held_out)`.
  - `split_seeds(project, *, random_seed: int | None = None) -> SeedSplit(random_seed, development, held_out)`:
    - written by the system actor;
    - the default seed is `secrets.randbits(32)`;
    - refused if already drawn (field `split`) or if any positive is unresolved (field `seeds`);
    - needs ≥3 positives (≥5 in `systematic`, field `seeds`).
  - Positives added after the split are **late**: they count as development and are flagged.
  - `agent_seeds(project) -> list[SeedView(seed_id, kind, cite, why, work_id, late: bool)]` returns negatives plus development positives, never held-out ones. Before the split it returns all seeds.
  - `all_seeds(project) -> list[SeedRecord]` is the human view. Each record has a `role`: `development | held-out | late | unsplit`.
  - `explain_seed_miss(project, actor, seed_id, reason, route)` explains a positive seed's miss.
  - `seed_check(project) -> list[SeedCheck(seed_id, role, status: "retrieved" | "explained" | "missing", matched_work: str | None)]`:
    - covers positives only;
    - a seed counts as retrieved when a corpus work has an equal work id, an equal normalised DOI, or an equal arXiv id (with bridging);
    - otherwise it is explained if a `seed.miss_explained` exists;
    - otherwise it is missing.
  - `seed_recall(project) -> SeedRecall(development: float | None, held_out: float | None)` gives each figure as retrieved / total in its role, or None when that role is empty.

- [ ] **Step 1: Write the failing tests**

```python
def test_split_is_reproducible_from_recorded_seed(): ...      # draw_split(x, 7) twice → equal
def test_split_holds_out_about_a_third():
    assert [len(draw_split(seeds(n), 1)[1]) for n in (3, 4, 5, 9)] == [1, 1, 2, 3]
def test_split_is_year_stratified(): ...                      # years 2019×3, 2021×3, 2023×3 → one held-out per year
def test_split_records_seed_and_procedure(project, ...): ...
def test_split_requires_resolved_positives(project, ...): ...
def test_split_needs_three_positives_in_pilot_five_in_systematic(...): ...
def test_split_drawn_once(project, ...): ...
def test_agent_view_never_contains_held_out(project, ...): ...
def test_late_positive_is_development_and_flagged(project, ...): ...
def test_seed_check_retrieved_explained_missing(project, ...): ...   # incl. retrieval under a bridged identifier
def test_explanation_route_cannot_be_database(project, ...): ...
def test_recall_reported_separately_for_development_and_held_out(project, ...): ...
```

- [ ] **Step 2–4:** fail → implement (add a split table and an explanations table, then increment `PROJECTION_VERSION`) → pass (`uv run pytest -W error -q`).
- [ ] **Step 5: Commit** — `git commit -m "feat(seeds): recorded hold-out split, agent view and seed check"`

---

### Task 5: Probe capabilities in the adapters, and vocabulary suggestions (ported)

**Files:**
- Modify: `platform/src/factory/sources/base.py`, `platform/src/factory/sources/arxiv.py`, `platform/src/factory/sources/openalex.py`
- Create: `platform/src/factory/services/vocabulary.py`, `platform/tests/test_vocabulary.py`
- Test: extend `platform/tests/test_arxiv.py`, `platform/tests/test_openalex.py`

**Interfaces:**
- Produces:
  - `Prober(Protocol)` with `count(self, spec: QuerySpec, *, archive: PageSink) -> int | None` and `matching(self, ids: Sequence[str], spec: QuerySpec, *, archive: PageSink) -> set[str]`, where `ids` are source-native.
  - `probe_key(source: str, work: Work) -> str | None`:
    - for `arxiv`, the normalised arXiv id (directly or bridged from the DOI);
    - for `openalex`, `identifiers.openalex`;
    - otherwise None.
  - arXiv:
    - `count` sends one request with `max_results=0` and reads `totalResults`;
    - `matching` keeps the ported behaviour (`id_list` batches ∩ `search_query`) under the new signature and accepts only `KEYWORD`.
  - OpenAlex:
    - `count` sends one request with `per-page=1` and reads `meta.count`;
    - `matching` sends batches of ≤50 IDs as `filter=openalex:W1|W2[,<spec filter>]` plus `search=<text>` for `KEYWORD`, with `per-page=50`.
  - Every response is archived through `archive` before it is parsed. No request carries a `sort`/`sortBy=relevance` parameter (R-21). A transport failure raises `SourceError`.
  - `vocabulary.py`: a verbatim port of the old `_NOISE`, `_ngrams`, `_query_terms` and `suggest_terms`. The return type is `list[TermSuggestion]`, where `TermSuggestion(term: str, seeds: int, holders: tuple[str, ...])` lives in `model/probe.py`.

- [ ] **Step 1: Write the failing tests**

```python
def test_arxiv_count_reads_total_results_without_records(http_log): ...
def test_arxiv_matching_intersects_ids_with_query(http_log): ...      # captured id_list + search_query; page archived
def test_openalex_count_reads_meta_count(http_log): ...
def test_openalex_matching_batches_ids_and_keeps_the_query(http_log): ...  # 120 ids → 3 requests; search= present
def test_probe_requests_never_sort_by_relevance(http_log): ...
def test_probe_key_bridges_datacite_doi_to_arxiv(): ...
# test_vocabulary.py
def test_suggests_phrase_shared_by_missed_seeds(): ...
def test_ignores_terms_already_in_query(): ...                # incl. field prefixes all:/ti: and boolean operators
def test_single_paper_terms_are_not_suggested(): ...
def test_more_specific_phrase_wins(): ...
def test_noise_words_dropped(): ...
def test_no_missed_seeds_no_suggestions(): ...
```

- [ ] **Step 2–4:** fail → implement → pass (`uv run pytest -W error -q`).
- [ ] **Step 5: Commit** — `git commit -m "feat(sources): count and seed-matching probes; ported vocabulary suggestions"`

---

### Task 6: `run_probe` — seed recall, negative hits, vocabulary

**Files:**
- Create: `platform/src/factory/model/probe.py` (payloads), `platform/src/factory/index/probe.py`, `platform/src/factory/services/probe.py`, `platform/tests/test_probe.py`
- Modify: catalog, `index/default.py`

**Interfaces:**
- Consumes: `Prober`, `probe_key`, `suggest_terms`, `split_seeds`, `agent_seeds`, `current_question`, `register_query`.
- Produces:
  - Payloads:
    - `ProbePageArchived(probe_id, query_id, ordinal, url, fetched_at, raw_blob, role: Literal["count", "match"])`;
    - `ProbeMeasured(probe_id, query_id, source, question_id, reported_count: int | None, development_tested: tuple[str, ...], development_retrieved: tuple[str, ...], negatives_tested, negatives_retrieved, untestable: tuple[str, ...], suggestions: tuple[TermSuggestion, ...])`;
    - `ProbeFailed(probe_id, query_id, source, reason)`.
  - Events: `probe.page_archived`, `probe.measured`, `probe.failed`. IDs use the `prb_` prefix.
  - `run_probe(project, actor, specs: Sequence[QuerySpec], *, sources) -> ProbeReport`:
    - Every spec is validated before anything is written:
      - a current question exists (field `question`);
      - the source exists and implements `Prober` (field `queries[i].source`);
      - `purpose` is forced to `PROBE`.
    - In P/S, the split is drawn automatically through `split_seeds` if it has not been drawn yet; that call's issues propagate.
    - Each spec is registered with the caller's actor, then measured by the system actor.
    - Only development positives (including late ones) and negatives are tested. A seed without a `probe_key` for the source is listed in `untestable` and counts as not retrieved.
    - Suggestions use the missed development seeds' works against all development seeds' works. `holders` are seed IDs.
    - A `SourceError` writes `probe.failed` for that query and the probe carries on.
  - `ProbeReport` contents:
    - `probe_id`, `question_id`;
    - `queries: list[ProbeQueryResult(query_id, source, text, status: "measured" | "failed", reported_count, recall: float | None, retrieved, missed, negatives_retrieved, untestable, suggestions, reason: str | None)]`;
    - `per_source_recall: dict[str, float | None]` (the union over that source's queries ÷ development count);
    - `pooled_recall: float | None`;
    - `threshold: float` (0.6 / 0.9 / 1.0 by mode);
    - `meets_threshold: bool` (False when recall is None).

- [ ] **Step 1: Write the failing tests**

```python
def test_probe_reports_recall_per_query_and_source_and_pooled(...): ...   # acceptance 7
def test_probe_reports_negative_hits(...): ...                            # acceptance 7
def test_probe_never_mentions_held_out_seeds(...):                       # acceptance 22
    # every held-out seed id and its work id/arXiv id/OpenAlex id is absent from: report JSON, events written
    # by the probe, their input/raw blobs, and captured request URLs
def test_probe_requires_a_question(...): ...
def test_probe_draws_the_split_in_pilot(...): ...                          # seed.split_drawn written once
def test_probe_validates_all_specs_before_writing(...): ...               # one unknown source → nothing written
def test_probe_creates_no_works(...): ...                                  # list_works(include_probe=True) unchanged
def test_probe_pages_archived_before_measurement(...): ...                # event order
def test_source_error_during_probe_is_reported(...): ...                  # failed query listed with reason; others measured
def test_threshold_by_mode(...): ...                                      # pilot recall 0.8 → meets_threshold False
def test_suggestions_name_development_seeds(...): ...
def test_probe_rebuild_equals_incremental(...): ...
```

- [ ] **Step 2–4:** fail → implement (add a `probes` table keyed by `(probe_id, query_id)` with source, status, reported_count and payload JSON, then increment `PROJECTION_VERSION`) → pass.
- [ ] **Step 5: Commit** — `git commit -m "feat(probe): seed recall and negative hits per query and source"`

---

### Task 7: Protocol model, version hash and readiness rules (pure)

**Files:**
- Create: `platform/src/factory/model/protocol.py`, `platform/src/factory/services/protocol_rules.py`, `platform/tests/test_protocol_model.py`, `platform/tests/test_protocol_rules.py`

**Interfaces:**
- Produces (model):
  - Enums:
    - `MethodProfile(StrEnum)`: `systematic-review`, `scoping-review`, `se-systematic-review`, `mapping-study`, `rapid-review`, `living-review`;
    - `ScreeningStage(StrEnum)`: `title-abstract`, `full-text`, `either`;
    - `CriterionKind`: `inclusion`, `exclusion`.
  - `CRITERION_ID_RE = r"^(IN|EX)\d{2}$"`, `PARENT_RE = r"^(slot:.+|NG\d{2})$"`, `PROTOCOL_ID_RE = r"^P@[0-9a-f]{8}$"`.
  - `Criterion(id, parent: str | None = None, statement: str, rule: str, applies_at: ScreeningStage, priority: int | None = None (≥0), examples: CriterionExamples = {include: (), exclude: ()}, note: str = "")`:
    - the `kind` property comes from the prefix;
    - an exclusion requires `priority`, and an inclusion must have None.
  - Supporting models:
    - `SourcePlan(name, included: bool, probe_id: str | None = None, why: str = "")`;
    - `PlannedQuery(source, kind: QueryKind, text, filters: dict[str, str] = {})`, with `matches(spec: QuerySpec) -> bool`, which compares source, kind, stripped text and filters;
    - `Limit(field, value, why: str = "")`;
    - `ReviewerRole`: `reviewer-of-record`, `assisting`;
    - `Reviewer(role, actor: str, kind: Literal["human", "agent"], duties: str = "")`.
  - `ScreeningPlan`:
    - `passes: Literal[1, 2]`;
    - `dual_sample: float | None` (0 < x ≤ 1);
    - `kappa_floor: float | None` (0..1);
    - `kappa_enforced: bool = False`;
    - `calibration_size: int = 30`;
    - `audit_fraction: float = 0.02`;
    - `audit_minimum: int = 50`;
    - `reviewers: tuple[Reviewer, ...]`.
  - `ProtocolSpec(question_id, method_profile, criteria, sources, queries, limits = (), screening, rationale: str = "")`.
  - `PROSE_KEYS` (Global Constraints) and `strip_prose(value: JsonValue) -> JsonValue`, ported from `lock.py`.
  - `protocol_version(spec) -> str` hashes `strip_prose(dump)` with criteria sorted by id, sources by name, queries by `(source, kind, text)` and limits by `(field, value)`.
  - `search_strategy_hash(spec) -> str` is the same hash restricted to `sources`, `queries`, `limits`.
  - `criterion_ref(protocol_id, cid) -> str` returns `f"{protocol_id}:{cid}"`.
- Produces (rules):
  - `protocol_issues(spec, *, question: QuestionVersion, current_question_id: str, mode: RigorMode, seeds: Sequence[SeedRecord], probes: Mapping[str, set[str]], known_sources: set[str]) -> ProtocolCheck(errors: list[ValidationIssue], gaps: list[ValidationIssue])`. `probes` maps probe_id to the set of sources it measured.
  - **errors** (always block a write):
    - `question_id` is not the current question;
    - a duplicate criterion id (`criteria[i].id`);
    - a parent that does not resolve to a slot name or non-goal of that question (`criteria[i].parent`);
    - a missing parent in P/S (`criteria[i].parent`, `"every criterion names its parent question element or non-goal (R-11)"`; acceptance 13);
    - an example that is an unknown seed or a held-out seed (`criteria[i].examples`);
    - an unknown source name (`sources[i].name`);
    - a query on a source that is not included (`queries[i].source`).
  - **gaps** (block `ready` only):
    - P/S: every non-goal is the parent of ≥1 exclusion;
    - P/S: every *filled* slot is the parent of ≥1 inclusion;
    - P/S: exclusion priorities are distinct;
    - P/S: every included source has a `probe_id` that measured it;
    - ≥1 included source and ≥1 query;
    - screening in `pilot`: `passes == 2` with `dual_sample` set, and `kappa_floor` declared;
    - screening in `systematic`: `passes == 2`, `dual_sample in (None, 1.0)`, `kappa_floor ≥ 0.7` and `kappa_enforced`;
    - all modes: exactly one `reviewer-of-record`, and that reviewer is `human`.

- [ ] **Step 1: Write the failing tests**

```python
def test_prose_does_not_change_version(): ...                 # note/why/rationale/examples/duties edited → same P@ (acceptance 6)
def test_rule_change_changes_version(): ...
def test_version_is_order_independent(): ...
def test_search_strategy_hash_ignores_criteria(): ...
def test_criterion_kind_and_priority_rules(): ...
def test_parentless_criterion_rejected_in_pilot_and_systematic(): ...   # acceptance 13
def test_parentless_criterion_allowed_in_exploratory(): ...
def test_parent_must_resolve_to_slot_or_non_goal(): ...
def test_held_out_seed_cannot_be_worked_example(): ...
def test_question_must_be_current(): ...
def test_unreferenced_non_goal_is_a_gap_in_pilot(): ...
def test_unreferenced_filled_slot_is_a_gap_open_slots_exempt(): ...
def test_duplicate_exclusion_priority_is_a_gap(): ...
def test_included_source_needs_probe_evidence_in_pilot(): ...
def test_systematic_needs_enforced_kappa_floor_of_at_least_0_7(): ...
def test_pilot_kappa_is_advisory(): ...
def test_exactly_one_human_reviewer_of_record(): ...
def test_query_must_use_an_included_source(): ...
```

- [ ] **Step 2–4:** fail → implement → pass.
- [ ] **Step 5: Commit** — `git commit -m "feat(protocol): versioned protocol model and readiness rules"`

---

### Task 8: Recording the protocol, PRESS review, deviations and search gating

**Files:**
- Create: `platform/src/factory/index/protocol.py`, `platform/src/factory/services/protocol.py`, `platform/tests/test_protocol_service.py`
- Modify: `platform/src/factory/model/protocol.py` (payloads), `platform/src/factory/services/search.py`, `platform/src/factory/mcp/server.py` (`search_run` gains `deviation_id`), catalog, `index/default.py`, `platform/tests/conftest.py`

**Interfaces:**
- Produces (payloads, IDs `prs_`, `dev_`):
  - `ProtocolStatus`: `draft`, `ready`.
  - `ProtocolRecorded(protocol_id, status, spec)`.
  - `PressElement(StrEnum)` (PRESS 2015): `translation`, `boolean-proximity`, `subject-headings`, `text-words`, `spelling-syntax-line-numbers`, `limits-filters`.
  - `PressFinding(element, finding: str, severity: Literal["minor", "major"])`.
  - `PressReviewed(review_id, protocol_id, findings: tuple[PressFinding, ...])`.
  - `PressConfirmed(review_id, protocol_id, responses: tuple[str, ...])`, holding one response per finding, in order.
  - `DeviationRecorded(deviation_id, protocol_id, description, reason, affects: tuple[str, ...])`.
  - Events: `protocol.recorded`, `protocol.press_reviewed`, `protocol.press_confirmed`, `protocol.deviation_recorded`.
- Produces (service):
  - `record_protocol(project, actor, spec, *, ready: bool) -> ProtocolResult(protocol_id, status, created: bool, gaps: list[ValidationIssue])`:
    - errors → `FactoryValidationError`;
    - `ready` with gaps → `FactoryValidationError(gaps)`;
    - a draft is written with its gaps returned;
    - while the current protocol is a draft it may be replaced freely;
    - once a protocol is `ready`, field `protocol` reads `"protocol is ready; change it with protocol_amend"`;
    - an identical spec and status writes nothing.
  - `current_protocol(project) -> ProtocolVersion(protocol_id, spec, status, recorded_at, press: "none" | "reviewed" | "confirmed") | None`.
  - `press_review(project, actor, protocol_id, findings) -> str`: agent actors only (field `actor`); `protocol_id` must be current.
  - `confirm_press(project, actor, review_id, responses) -> None`: human only; exactly one non-empty response per finding (field `responses`).
  - `record_deviation(project, actor, *, description, reason, affects=()) -> str`: a protocol must exist.
  - `search_authorization(project, spec: QuerySpec, *, deviation_id: str | None) -> list[ValidationIssue]`:
    - applies only when `spec.purpose == SEARCH` and the mode is `pilot`/`systematic`;
    - the current protocol must be `ready` and built on the current question (`"protocol is built on {old}; amend it to the current question"`);
    - a confirmed PRESS review must exist for some protocol version with an equal `search_strategy_hash`;
    - and either a `PlannedQuery.matches(spec)`, or `deviation_id` names a deviation of the current protocol.
  - `register_query(..., deviation_id: str | None = None)` calls `search_authorization`. Its event `refs` add the current protocol id and the deviation id when present.
- Test fixtures: plan-2 tests that exercise search mechanics in a pilot project switch to a new `explore_project` fixture (exploratory mode). Keep every assertion. Add `helpers.ready_protocol(project, agent, human, …) -> str` for gated tests.

- [ ] **Step 1: Write the failing tests**

```python
def test_draft_with_gaps_is_written_and_gaps_returned(...): ...
def test_ready_with_gaps_writes_nothing(...): ...
def test_structural_error_writes_nothing(...): ...            # parentless criterion in pilot
def test_draft_can_be_replaced_ready_cannot(...): ...
def test_identical_resubmission_writes_nothing(...): ...
def test_press_review_needs_agent_and_current_protocol(...): ...
def test_press_confirmation_answers_every_finding(...): ...
def test_press_confirmation_is_human_only(...): ...
def test_search_refused_without_ready_protocol_in_pilot(...): ...
def test_search_refused_before_press_confirmed(...): ...
def test_search_refused_for_unplanned_query(...): ...
def test_unplanned_query_runs_with_recorded_deviation(...): ...       # refs include dev_ id
def test_search_refused_when_question_changed_after_protocol(...): ...
def test_probe_and_exploratory_searches_are_not_gated(...): ...
def test_query_registered_refs_protocol_version(...): ...
def test_protocol_rebuild_equals_incremental(...): ...
```

- [ ] **Step 2–4:** fail → implement (add tables for protocol versions, press reviews and deviations, then increment `PROJECTION_VERSION`) → pass (`uv run pytest -W error -q`, all plan-1/2 tests green).
- [ ] **Step 5: Commit** — `git commit -m "feat(protocol): record, PRESS review, deviations and search gating"`

---

### Task 9: Amendments and stale rules

**Files:**
- Modify: `platform/src/factory/model/protocol.py`, `platform/src/factory/services/protocol_rules.py`, `platform/src/factory/services/protocol.py`, `platform/src/factory/index/protocol.py`, catalog
- Test: `platform/tests/test_amendments.py`

**Interfaces:**
- Produces (model, IDs `amd_`):
  - `ChangeKind`: `added`, `removed`, `changed`.
  - `CriterionEffect`: `loosened`, `tightened`, `clarified`.
  - `CriterionChange(cid, change: ChangeKind, effect: CriterionEffect | None)`.
  - `StaleRule(criterion: str, stales: Literal["exclusions-citing", "inclusions", "untested"], stage: ScreeningStage)`.
  - `ProtocolAmended(amendment_id, from_version, to_version, spec, reason, semantic: bool, changes: tuple[CriterionChange, ...], stale_rules: tuple[StaleRule, ...], other_changes: tuple[str, ...])`. `other_changes` lists the changed top-level hashed fields among `question_id`, `method_profile`, `sources`, `queries`, `limits`, `screening`.
  - Event: `protocol.amended`.
- Produces (pure, in `protocol_rules.py`):
  - `criterion_changes(old, new) -> list[tuple[str, ChangeKind]]` compares by CID. A criterion counts as changed when its prose-stripped dumps differ.
  - `stale_rules(changes, old, new) -> list[StaleRule]`:
    - added → `untested` at the new criterion's `applies_at`;
    - removed → `exclusions-citing` at the old criterion's `applies_at`;
    - loosened → `exclusions-citing`;
    - tightened → `inclusions`;
    - clarified → no rule.
  - `stale_decisions(amendments: Sequence[AmendmentRecord], lineage: Sequence[str], decisions: Sequence[DecisionRef]) -> list[str]`, where `DecisionRef(decision_id, verdict: str, criterion: str | None, protocol_id, stage: ScreeningStage)` and `criterion` is version-qualified (`P@x:EX03`).
    - A decision can be staled by amendment A only if it was recorded under a version that comes before `A.to_version` in `lineage`.
    - `exclusions-citing`: the verdict is `exclude` and the CID matches.
    - `inclusions`: the verdict is `include`.
    - `untested`: any verdict.
    - The stage must match, with `either` matching both stages.
    - Returns sorted unique ids.
  - Plan 4 calls this with real decisions.
- Produces (service):
  - `amend_protocol(project, actor, spec, *, reason: str, semantic: bool, effects: Mapping[str, CriterionEffect]) -> AmendResult(amendment_id, from_version, to_version, stale_rules, prose_only: bool)`. Validation:
    - the current protocol must be `ready` (field `protocol`);
    - `reason` must be non-empty;
    - errors and gaps both block, because the amended protocol stays `ready`;
    - `effects` must name exactly the `changed` CIDs (field `effects`, naming the missing or unexpected ones);
    - `semantic` must be False if and only if there are no added/removed criteria, no `other_changes`, and every effect is `clarified` (field `semantic`).
  - The prose-only case (an equal version hash) still records `protocol.amended` with `from_version == to_version` and no changes. No new `P@` is minted (acceptance 6).
  - `protocol_lineage(project) -> list[str]`, `list_amendments(project)`, `list_deviations(project)` (acceptance 19, data side).

- [ ] **Step 1: Write the failing tests**

```python
def test_prose_only_amendment_keeps_version(...): ...                          # acceptance 6
def test_loosening_exclusion_stales_exclusions_citing_it(...):                 # acceptance 6
    # synthetic DecisionRefs: exclude citing P@a:EX03 → stale; exclude citing P@a:EX02 → not; include → not
def test_tightening_stales_inclusions_only(...): ...
def test_added_criterion_stales_decisions_untested_at_its_stage(...): ...      # full-text criterion leaves title-abstract decisions alone
def test_removed_criterion_stales_its_exclusions(...): ...
def test_renamed_criterion_is_removed_plus_added(...): ...
def test_clarification_stales_nothing(...): ...
def test_effects_must_cover_exactly_the_changed_criteria(...): ...
def test_semantic_flag_must_match_changes(...): ...
def test_amendment_on_draft_refused(...): ...
def test_amended_protocol_must_stay_ready(...): ...                             # a gap → nothing written
def test_decisions_after_the_amendment_are_not_stale(...): ...
def test_press_carries_over_when_search_strategy_unchanged(...): ...
def test_query_change_needs_new_press(...): ...
def test_amendments_and_deviations_listed_separately(...): ...                 # acceptance 19 (data)
def test_amendment_rebuild_equals_incremental(...): ...
```

- [ ] **Step 2–4:** fail → implement (increment `PROJECTION_VERSION`) → pass.
- [ ] **Step 5: Commit** — `git commit -m "feat(protocol): amendments with computed stale rules"`

---

### Task 10: MCP tools, CLI, acceptance and gates

**Files:**
- Modify: `platform/src/factory/mcp/server.py`, `platform/src/factory/mcp/conventions.py`, `platform/src/factory/cli/main.py`, `platform/src/factory/services/project.py`, `CLAUDE.md` (status line only)
- Create: `platform/tests/test_mcp_protocol.py`, `platform/tests/test_acceptance_protocol.py`
- Test: extend `platform/tests/test_cli.py`

**Interfaces:**
- Produces:
  - `parse_input(model: type[M], data: JsonValue, field: str) -> M` in `conventions.py`. It raises `FactoryValidationError` with dotted field paths (`spec.criteria.0.parent`).
  - Tools (every mutating one takes `role, model, skill`; outputs `ok(...)` / structured errors):
    - `question_record(project, spec: dict, raw_goal: str | None = None, reason: str | None = None)`, which states `raw_goal` first when given;
    - `seed_add(project, seeds: list[dict])` → BatchResult;
    - `seed_list(project)` → `agent_seeds` (read-only, paginated);
    - `probe_run(project, queries: list[dict])`, where each dict is `{source, query, kind="keyword", filters={}}`;
    - `protocol_record(project, spec: dict, ready: bool = False)`;
    - `protocol_press_review(project, protocol_id, findings: list[dict])`;
    - `protocol_amend(project, spec: dict, reason: str, semantic: bool, effects: dict[str, str])`;
    - `protocol_deviation(project, description, reason, affects: list[str] = [])`.
  - `ProjectStatus` adds:
    - `question: str | None`;
    - `protocol: ProtocolSummary(protocol_id, status, press) | None`;
    - `seeds: SeedCounts(positive, negative, unresolved, split_drawn: bool)`.
    - It contains no held-out identities.
  - CLI:
    - `factory seeds` prints the human table: id, kind, role, resolution and seed-check status;
    - `factory seeds split [--random-seed N]`;
    - `factory seeds explain SEED03 --route citation-chase --reason "…"`;
    - `factory protocol confirm-press <review_id> --response "…" [--response …]`.
  - `status` lines:
    - `question: Q@… | none`;
    - `protocol: P@… (ready, PRESS confirmed) | none`;
    - `seeds: <p> positive (split drawn|not split), <n> negative, <u> unresolved`.

- [ ] **Step 1: Write the acceptance tests** (MCP client over `build_server(settings, clock, sources=mock_sources)`)

```python
async def test_prose_only_change_mints_no_new_version_and_loosening_stales_exclusions(...): ...  # acceptance 6
async def test_probe_run_reports_recall_and_negative_hits_per_query_and_source(...): ...        # acceptance 7
async def test_parentless_criterion_is_rejected_and_nothing_written(...): ...                   # acceptance 13
async def test_amendments_and_deviations_are_stored_separately(...): ...                        # acceptance 19 (data)
async def test_agent_tools_never_reveal_held_out_seeds(...): ...                                # acceptance 22
    # split recorded with random_seed; seed_list, probe_run, project_status, protocol_* responses contain no held-out id
async def test_question_to_gated_search_flow(...): ...
    # goal → question → seeds → probe → protocol draft → PRESS review → CLI confirm-press → ready →
    # planned search_run ok; unplanned refused (field "query"); with protocol_deviation id → ok
def test_protocol_rebuild_is_deterministic(...): ...   # delete .index, CLI rebuild → same state hash
```

- [ ] **Step 2: Write the MCP and CLI tests**: one structured-error test per tool, each with a field path; `test_seeds_cli_shows_held_out_roles`; `test_confirm_press_cli`; and `test_status_shows_question_protocol_and_seeds`.
- [ ] **Step 3: Run to verify failure, implement, run to verify pass** — `uv run pytest -W error -q`.
- [ ] **Step 4: Run all quality gates**

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests
uv run pytest -W error --cov=factory.services --cov=factory.model --cov-report=term-missing --cov-fail-under=90
```
Expected: clean, all pass, coverage ≥ 90%.

- [ ] **Step 5: Update `CLAUDE.md`.** Set the status line to `slice 1: sub-plans 1–3 (platform core; works and acquisition; question, seeds, probe, protocol) implemented — see docs/plans/.`
- [ ] **Step 6: Commit** — `git commit -m "feat(mcp): question, seed, probe and protocol tools; acceptance tests"`

---

### Task 11: Plugin skills `rf-frame`, `rf-probe`, `rf-protocol`

**Files:**
- Create: `plugin/.claude-plugin/plugin.json`, `plugin/PROVENANCE.md`, `plugin/skills/rf-frame/SKILL.md`, `plugin/skills/rf-probe/SKILL.md`, `plugin/skills/rf-protocol/SKILL.md`, `platform/tests/test_plugin.py`

**Interfaces:**
- Consumes: the tools from Task 10 and the CLI commands for the human steps. The skill texts adapt `docs/reference/research-factory-old-spec/stages/00-frame.md`, `01-scope.md` and `02-protocol.md` to those tools.
- Produces:
  - `plugin.json`: `{"name": "research-factory", "version": "0.1.0", "description": …}`.
  - Each `SKILL.md` has frontmatter `name` and `description` (a "Use when …" trigger) and a procedure body.
  - `PROVENANCE.md` lists each source document with the research-factory-old commit SHA (`git -C ~/Projects/research-factory-old rev-parse HEAD`).
- Required content:
  - **rf-frame**: interview ≤5 questions and never ask what the raw goal already answers; record the raw goal verbatim via `question_record(raw_goal=…)` and quote it back; use `open:` with `resolve_in`, never TBD; apply the plausible-paper test for non-goals; propose the rigor mode with reasoning.
  - **rf-probe**: collect positive and negative seeds with identifiers; the hold-out split is drawn by the platform; never ask which seeds are held out; use narrow and broad candidate queries per source; the probe is metadata-only; iterate on suggestions; the thresholds are 0.6/0.9/1.0; route the result as proceed, amend or reframe.
  - **rf-protocol**: every criterion has a parent; rules are yes/no; declare `applies_at`; set exclusion priorities; cite development seeds as examples; the screening plan and κ floor are fixed before screening; PRESS review runs in a separate subagent with no authoring context, and the human then confirms with `factory protocol confirm-press`; amendment versus deviation; an amendment's `semantic` flag and effects.
  - Every skill tells Claude to pass the bare skill name as `skill`, because the platform computes the hash.

- [ ] **Step 1: Write the failing test**

```python
def test_plugin_skills_resolve_and_have_frontmatter():
    s = Settings.load(root=REPO_ROOT)               # plugin_dir defaults to <repo>/plugin
    for name in ("rf-frame", "rf-probe", "rf-protocol"):
        assert skill_ref(s, name).startswith(f"{name}@")
        assert frontmatter(name)["name"] == name and frontmatter(name)["description"].startswith("Use when")
```

- [ ] **Step 2–4:** fail → write the plugin files (prose; consult superpowers:writing-skills for structure) → pass.
- [ ] **Step 5: Commit** — `git commit -m "feat(plugin): rf-frame, rf-probe and rf-protocol skills"`

---

## Self-review notes

- **Spec coverage:**
  - question with verbatim raw goal and `Q@` (flow 2, R-10) → Task 2;
  - seeds resolved to works (flow 3) → Task 3;
  - recorded hold-out split (R-20, acceptance 22) → Tasks 4 and 6;
  - probe recall, negative hits and vocabulary (flow 4, R-20, acceptance 7) → Tasks 5–6;
  - protocol with method profile, parented criteria, `applies_at` and priority, sources, PRISMA-S queries, limits, screening plan, roles and κ floor (flow 5, R-11–R-13, R-39, R-60; acceptance 13) → Tasks 7–8;
  - PRESS before search (R-61) and search gating (deferred from plan 2) → Task 8;
  - amendments with stale computation, plus deviations kept separate (R-14, R-15; acceptance 6, 19 data) → Tasks 8–9;
  - provenance trust (slice-1 open question) → Task 1;
  - plugin skills → Task 11.
- **Rulings made in this plan:**
  1. The skill hash is computed by the platform, and an unknown skill is rejected. `model` stays agent-reported; plan 5's methods statement says so.
  2. Seed lookups are probe-purpose runs, and probe-purpose records are quarantined from the corpus.
  3. The probe never retrieves records. It uses counts and seed matching.
  4. The split is drawn automatically at the first probe in P/S, and positives added later are late development seeds.
  5. Prose-only edits of the question or protocol are recorded but keep the version.
  6. A draft protocol can be replaced freely, and a ready one only by amendment.
  7. PRESS confirmation is tied to the search-strategy hash.
  8. `seed_list` and `protocol_press_review` are tools beyond the slice-1 list. The agent needs to read its seeds and record a review, and PRESS confirmation is a human CLI action.
  9. Seed-miss explanation is a human CLI action.
  10. The exploratory seed-recall threshold is 0.6, from the old Gate 01.
- **Carried to plan 5 from plan-2 review:** `DedupMerged.records` counts distinct works, not input records. PRISMA "duplicates removed" must be computed from provenance rows.
- **Deferred:**
  - `check` failing on unexplained seed misses (acceptance 15) and `report_methods` (acceptance 19 report side, 22 recall report) → plan 5;
  - applying `stale_decisions` to real screening decisions, and the protocol-must-be-ready refusal in `screen_next` (R-16) → plan 4;
  - competing candidate questions and the screening-burden estimate (old Stage 01 step 6) are not in slice 1's acceptance criteria and are not planned.
