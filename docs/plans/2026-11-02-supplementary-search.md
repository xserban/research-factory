# Supplementary Search Implementation Plan (slice 1, sub-plan 5a of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After screening, the platform chases citations backward and forward from the works whose outcome is `promote`, admits explained seed misses by ID lookup, and feeds every new record through dedup and both screening passes, so that every supplementary record is a separate, provenance-tagged run (R-24, R-25; slice-1 flow 10, acceptance 15).

**Architecture:** As in plans 1–4. A chase is a **round** (`chase.round_started`) that names its direction and its source works. The platform builds the round's OpenAlex filter queries from those works. The queries are registered with `purpose = chase` and run through the existing `register_query` / `run_query` pipeline, so archiving, counts and shortfalls come free. Seed admission reuses the seed-lookup query (`purpose = seed`). New corpus works reach the screening queues through the existing on-demand enqueue; pass B's sample is extended for them by a recorded draw.

**Tech Stack:** as plans 1–4 (Python 3.12, uv, pydantic 2, SQLAlchemy Core, typer, mcp 2.x, httpx).

**Spec:** `docs/specs/00-system.md`, `docs/specs/01-rigour.md` (R-01, R-02, R-04, R-21–R-25), `docs/specs/slice-1.md` (flow 10; acceptance 4, 14, 15, 22). Decision #38 (all six items) is binding for this plan; decision #37 still holds.

## Rulings made in this plan (decision #38, already in `docs/decisions.md`)

1. **One round per call; source works are the `promote` outcomes.** `search_chase` reads `agreement.final_outcomes` and takes every work whose outcome is `promote`. It refuses while any non-calibration corpus work is `pending`. Each call is a new round, so a second round over newly promoted works is possible but explicit.
2. **Chase queries are platform-built and authorised by the round.** `search_authorization` waives the planned-query match for a `chase`-purpose spec only when a recorded round lists that exact text. Every other gate still applies: ready protocol, current question, confirmed PRESS review. An agent cannot register a free-form chase query.
3. **Query shape.** Backward: `cited_by:W1|W2|…`. Forward: `cites:W1|W2|…`. `CHASE_CHUNK = 50` OpenAlex IDs per query, sorted. A source work without an OpenAlex ID is reported as `unchasable` and not queried.
4. **Pass-B sample extension.** At `screen_next` for pass B, corpus works that are neither in the pass-B sample nor in a previous extension are drawn. Each is kept with probability `dual_sample`, using a fresh recorded seed, and the draw is written as one `screening.sample_extended` event. When `dual_sample` is `None` or ≥ 1, pass B already covers the whole corpus and nothing is written.
5. **Seed admission is a human act through the CLI.** Admission names seeds, which may be held out, so it has no MCP tool. It requires a recorded miss explanation with `route = seed-admission`. It runs the seed's ID lookup as a `seed`-purpose query, which gives the work `seed-admission` provenance, and then records `seed.admitted`.
6. **Hand search** remains a recordable route on a miss explanation. Its execution is out of scope for slice 1 and is listed by plan 5b's `check`.

## Global Constraints

- All constraints from plans 1–4 hold. No model calls. Logic lives in services. Events are append-only, and the projector is the only index writer. Validate before writing. `mypy --strict` and ruff pass. Coverage stays ≥ 90 % for `factory.services` and `factory.model`. Tests are offline; live tests are marked `network`.
- Agent-written events carry model, `skill_ref` and `input_blob` (R-04).
- Held-out seeds are never named (seed ID, DOI or arXiv ID) in MCP output (R-20, acceptance 22). The MCP scrub from plan 4 (`_held_out_tokens`) applies to `search_chase` output.
- No relevance sorting, no truncation (R-21): chase queries use the existing adapter paging, and no `limit` is ever set.
- Each task that changes tables or handlers increments `PROJECTION_VERSION` by one (it is 14 at start).
- Branch `plan-5a-supplementary-search`. Commit after each task and stage only your own files. Commit trailer: `Co-Authored-By: Claude <Model> 5.5 <noreply@anthropic.com>`.
- Commands run from `platform/` unless stated.

## Review Focus

1. **A chased work is already in the corpus** (found by the database search), or is found by both directions. Expected: dedup merges it, and it gains a `citation-chase` provenance row without becoming a new work. It is not re-screened, and PRISMA (plan 5b) counts it under databases only. → Task 5 `test_chased_duplicate_is_merged_not_rescreened`.
2. **An agent registers its own `cites:` query with `purpose = chase`** through `search_run`. Expected: refused as unplanned (deviation required), and nothing is written. → Task 2 `test_unplanned_chase_query_refused`.
3. **Chase is called while screening is unfinished**, or with no `promote` works. Expected: a structured refusal naming the pending count, or "no works to chase"; no round is written. → Task 2 `test_chase_refused_while_pending`, `test_chase_refused_without_includes`.
4. **A held-out seed is retrieved only by chasing.** Expected: `seed_check` shows it as retrieved, and `search_chase`'s MCP output neither names nor flags it. → Task 5 `test_held_out_seed_found_by_chase_is_not_named`.
5. **A chase run is interrupted mid-page.** Expected: the run is `partial`/`interrupted` with a resume token (plan-2 behaviour), the round lists the run, and a resume completes it without a new round. → Task 2 `test_interrupted_chase_run_resumes_within_round`.

---

## File Structure

```
platform/src/factory/
  model/chase.py             ChaseDirection, ChaseRoundStarted, SampleExtended, SeedAdmitted
  events/catalog.py          + chase.round_started, screening.sample_extended, seed.admitted
  index/chase.py             tables chase_rounds, chase_queries; sample_extensions; seed_admissions
  services/chase.py          chase_sources, search_chase, chase_rounds
  services/protocol.py       search_authorization: waive the planned match for round-listed chase specs
  services/screening.py      pass-B sample extension
  services/seeds.py          admit_seed; seed_check unchanged
  mcp/server.py              + search_chase
  cli/main.py                + search chase, seed admit
plugin/skills/rf-search/SKILL.md   new: chasing step
```

---

### Task 1: Model, events and projection

**Files:**
- Create: `platform/src/factory/model/chase.py`, `platform/src/factory/index/chase.py`
- Modify: `platform/src/factory/events/catalog.py`, `platform/src/factory/index/projection.py` (register handlers; `PROJECTION_VERSION = 15`)
- Test: `platform/tests/test_chase_model.py`, `platform/tests/test_index.py` (rebuild test)

**Interfaces:**
- Produces:
  - `class ChaseDirection(StrEnum): BACKWARD = "backward"; FORWARD = "forward"`
  - `CHASE_CHUNK: Final = 50`
  - `class ChaseRoundStarted(StrictModel)`: `round_id: str` (prefix `chs_`), `directions: tuple[ChaseDirection, ...]` (1–2, unique), `from_works: tuple[str, ...]` (sorted, ≥ 1), `unchasable: tuple[str, ...]`, `queries: tuple[str, ...]` (query texts, in the order they are registered)
  - `class SampleExtended(StrictModel)`: `pass_label: PassLabel` (must be `B`), `random_seed: int`, `considered: tuple[str, ...]`, `added: tuple[str, ...]` (⊆ considered)
  - `class SeedAdmitted(StrictModel)`: `seed_id: str`, `run_id: str`, `work_id: str | None`
  - Index readers in `index/chase.py`: `round_texts(conn) -> set[str]`, `extended_works(conn) -> set[str]`, `considered_works(conn) -> set[str]`
- Consumes: `PassLabel` from `model/screening.py`; ID minting `project.ids.new(prefix)` (register `chs` where prefixes are declared, as plan 4 did for `dec`).

- [ ] **Step 1: Write failing tests.**
  - `test_round_requires_source_works`: an empty `from_works` raises a ValidationError.
  - `test_round_directions_unique`: `(BACKWARD, BACKWARD)` raises.
  - `test_sample_extension_added_subset`: an `added` work not in `considered` raises.
  - `test_sample_extension_pass_a_rejected`.
  - `test_rebuild_reproduces_chase_tables`: append one event of each type, rebuild the index, and the three readers return the same values as the live fold.
- [ ] **Step 2: Run `uv run pytest tests/test_chase_model.py -v`.** Expected: FAIL (import error).
- [ ] **Step 3: Implement the models, catalog entries (schema 1), tables and total handlers.**
- [ ] **Step 4: Run `uv run pytest -q && uv run mypy --strict src && uv run ruff check`.** Expected: all pass.
- [ ] **Step 5: Commit** `feat(chase): round, sample-extension and admission events`.

---

### Task 2: `search_chase` service and the authorisation waiver

**Files:**
- Create: `platform/src/factory/services/chase.py`
- Modify: `platform/src/factory/services/protocol.py` (`search_authorization`)
- Test: `platform/tests/test_chase_service.py`, with a fake OpenAlex source (reuse the fake-source pattern in `tests/test_search_service.py` / `tests/helpers.py`)

**Interfaces:**
- Consumes: `agreement.final_outcomes(project) -> dict[str, Outcome]`, `calibration.calibration_items(project)`, `search.register_query`, `search.run_query`, `search.get_work`, `QuerySpec(source="openalex", kind=QueryKind.FILTER, text=…, purpose=QueryPurpose.CHASE)`.
- Produces:
  - `class ChaseSummary(StrictModel)`: `round_id: str`, `directions: list[ChaseDirection]`, `from_works: list[str]`, `unchasable: list[str]`, `runs: list[RunSummary]`, `new_works: int` (corpus size after minus before, computed)
  - `def chase_sources(project: Project) -> tuple[list[str], list[str]]`: returns `(chasable, unchasable)` work IDs among the `promote` outcomes, both sorted. A work is chasable when `work.identifiers.openalex` is set.
  - `def search_chase(project: Project, actor: Actor, directions: Sequence[ChaseDirection], *, sources: Mapping[str, SourceFactory]) -> ChaseSummary`
  - `def chase_rounds(project: Project) -> list[ChaseRoundStarted]`
  - `def chase_queries(directions, openalex_ids: Sequence[str]) -> list[str]`, pure: for each direction in `BACKWARD, FORWARD` order, chunks of `CHASE_CHUNK` sorted IDs joined by `|`, prefixed `cited_by:` (backward) or `cites:` (forward).

`search_chase` follows this order. Under one `project.index.exclusive()` it validates first and writes nothing on a refusal:
1. Pending count is 0 (excluding calibration works); otherwise `ValidationIssue("screening", "<n> works still pending")`.
2. At least one chasable work; otherwise `ValidationIssue("works", "no works to chase")`.
3. `search_authorization` passes for the first built spec, given the round about to be written.

It then records `chase.round_started`, registers each query, and releases the lock. Finally it runs each query with `run_query(actor=actor)`. A `SourceError` is recorded by `run_query` as before and does not abort the remaining queries.

In `search_authorization`, when `spec.purpose is QueryPurpose.CHASE` and `spec.text` is in `round_texts`, the planned-query issue is not raised. All other issues still are.

- [ ] **Step 1: Write failing tests.**
  - `test_chase_queries_chunks_and_prefixes`: 120 IDs and both directions give 6 texts. The first starts with `cited_by:`, the fourth with `cites:`, and each chunk holds ≤ 50 sorted IDs.
  - `test_chase_refused_while_pending`: with one pending work, the issue text contains `1 works still pending` and the event count is unchanged.
  - `test_chase_refused_without_includes`.
  - `test_unchasable_work_reported_not_queried`: a promote work without an OpenAlex ID appears in `unchasable` and in no query text.
  - `test_chase_records_round_then_runs`: the event order is `chase.round_started`, then `query.registered` ×k, then the run events. Every new work has a provenance row with method `citation-chase`.
  - `test_unplanned_chase_query_refused`: `register_query` with a `cites:` chase spec not in any round is refused under a pilot protocol, and nothing is written.
  - `test_interrupted_chase_run_resumes_within_round`: the fake source raises mid-run, the run is resumable, and `run_query(resume_run=…)` completes it. `chase_rounds` still has one round.
  - `test_agent_round_carries_provenance`: an agent actor's round event has model, skill and an `input_blob` equal to `{"directions": [...]}`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite, mypy and ruff.** Expected: pass.
- [ ] **Step 5: Commit** `feat(chase): platform-built citation chasing rounds`.

---

### Task 3: Pass-B sample extension

**Files:**
- Modify: `platform/src/factory/services/screening.py` (`_enqueue` path for pass B; a new private `_extend_sample`)
- Test: `platform/tests/test_screening_next.py`

**Interfaces:**
- Consumes: `SampleExtended`, `extended_works`, `considered_works`, `_pass_row`.
- Produces: no new public function. Pass B's effective sample becomes `sample ∪ extended_works`; `screen_next` and `pass_progress` must both use it (check `agreement._load` / `_queue` and `audit` for every reader of `passes.sample`, and route them through one helper `pass_b_sample(project) -> tuple[str, ...] | None` in `services/screening.py`).

Draw: `candidates = sorted(corpus − sample − considered_works − calibration_items)`. If there are candidates, `seed = secrets.randbits(32)` (as `open_pass` does; tests inject a fixed seed via a `random_seed: int | None = None` keyword on the private helper), `rng = random.Random(seed)`, and `added = [w for w in candidates if rng.random() < dual_sample]`. Record the event even when `added` is empty, so the same candidates are not drawn again.

- [ ] **Step 1: Write failing tests.**
  - `test_new_work_after_open_is_considered_once`: add a work after pass B opens, call `screen_next(B)` twice, and exactly one `screening.sample_extended` exists.
  - `test_extension_respects_fraction`: with `dual_sample = 0.5`, a fixed seed and 200 new works, `len(added)` lies in 70–130, and replaying the seed gives the same set.
  - `test_full_dual_coding_writes_no_extension`: with `dual_sample = None`, nothing is written.
  - `test_agreement_counts_extended_works_as_dual_coded`: an added work decided in both passes appears in κ, and a non-added one is single-pass.
- [ ] **Step 2–4: Fail, implement, pass (full suite, mypy, ruff).**
- [ ] **Step 5: Commit** `feat(screening): extend pass B's sample for late works`.

---

### Task 4: Seed admission

**Files:**
- Modify: `platform/src/factory/services/seeds.py` (add `admit_seed`; reuse `_lookup_query`, `_run_works`)
- Test: `platform/tests/test_seeds.py`

**Interfaces:**
- Produces: `def admit_seed(project: Project, actor: Actor, seed_id: str, *, sources: Mapping[str, SourceFactory]) -> SeedAdmitted`.
- Rules:
  - `actor.kind` must be `"human"`; otherwise `ValidationIssue("actor", "seed admission is a human act")`.
  - The seed must have a `seed.miss_explained` whose route is `seed-admission`.
  - The seed must not already be retrieved (`seed_check` status `retrieved`) or already admitted.
  - The query is `_lookup_query(spec)` with `purpose = QueryPurpose.SEED`. Register it with the gate. If the protocol does not plan it, the caller passes `deviation_id`, and the CLI requires one in pilot and systematic. Then run it.
  - `work_id` is the first work of the run, or `None` when the lookup found nothing. The event is recorded in both cases.
  - Messages never echo the seed ID (as in `explain_seed_miss`).
- Signature therefore: `admit_seed(project, actor, seed_id, *, sources, deviation_id: str | None = None)`.

- [ ] **Step 1: Write failing tests.**
  - `test_admission_requires_seed_admission_route`: a miss explained with route `hand-search` is refused.
  - `test_admission_refuses_agent_actor`.
  - `test_admitted_work_has_seed_admission_provenance_and_checks_retrieved`: after admission, `seed_check` gives `retrieved`, and the work's provenance method is `seed-admission`.
  - `test_admission_not_found_is_recorded`: the fake source returns nothing, so `work_id is None` and `seed_check` stays `explained`.
  - `test_admission_twice_refused`.
- [ ] **Step 2–4: Fail, implement, pass.**
- [ ] **Step 5: Commit** `feat(seeds): admit explained misses by ID lookup`.

---

### Task 5: MCP, CLI, skill and acceptance

**Files:**
- Modify: `platform/src/factory/mcp/server.py` (tool `search_chase(directions: list[str], model: str, skill: str)`), `platform/src/factory/cli/main.py` (`search chase [--backward/--forward]`, `seed admit SEED_ID [--deviation ID]`), `platform/src/factory/services/project.py` (status lines: `chase rounds: n`, `admitted seeds: n`, and new works awaiting screening is already covered by screening status)
- Create: `plugin/skills/rf-search/SKILL.md` (frontmatter as in `plugin/skills/rf-screen/SKILL.md`). The chasing step: after `screen_agreement` and every resolution, call `search_chase` with both directions, then `dedup_run`, then return to screening. It never writes chase queries by hand.
- Test: `platform/tests/test_mcp_search.py`, `platform/tests/test_cli.py`, `platform/tests/test_acceptance_supplementary.py`

**Interfaces:**
- Consumes: `search_chase`, `admit_seed`, `dedup_run`, the plan-4 screening services and helpers in `tests/helpers.py`.
- MCP output is `ChaseSummary` JSON passed through the plan-4 scrub with `include_work_ids=True` (screening-style: work IDs visible, seed identifiers withheld). A refusal follows the MCP error convention in `mcp/conventions.py`.

- [ ] **Step 1: Write failing tests.**
  - `test_mcp_search_chase_returns_round`.
  - `test_mcp_search_chase_rejects_unknown_direction` (nothing written).
  - `test_cli_seed_admit_requires_deviation_in_pilot`.
  - Acceptance file, all offline with the fake OpenAlex:
    - `test_supplementary_flow_end_to_end`: search, dedup, calibrate, two passes, agreement, then chase both directions, dedup, screen the new works in A and in sampled B, agreement again. Every new work's provenance is `citation-chase`, and each chase query is a separate run with archived pages (R-03, R-25).
    - `test_chased_duplicate_is_merged_not_rescreened`.
    - `test_held_out_seed_found_by_chase_is_not_named`: the MCP JSON of `search_chase` contains no held-out seed ID, DOI or arXiv form, and `seed_check` (human view) shows the seed as `retrieved`.
    - `test_seed_check_passes_after_admission` (acceptance 15): one positive seed missed, explained with route `seed-admission`, admitted by CLI. No seed is `missing`.
- [ ] **Step 2–4: Fail, implement, pass. Then run the full suite with coverage:** `uv run pytest --cov=factory.services --cov=factory.model --cov-fail-under=90 -q`, mypy and ruff.
- [ ] **Step 5: Update** `docs/specs/slice-1.md` (flow 10 implemented in plan 5a) **and commit** `feat(chase): search_chase tool, seed admit command, acceptance`.
