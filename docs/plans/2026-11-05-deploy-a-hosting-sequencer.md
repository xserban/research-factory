# Hosting and Single-Writer Sequencing Implementation Plan (slice 5, sub-plan deploy-A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** Slice 5 is built last (build order), after slice M. Bumps `PROJECTION_VERSION` by one from the value it finds.

> **Dependencies.** None within slice 5; this is its first plan. Slices 1–2 merged. Sub-plans teams-A, deploy-B and deploy-C consume this plan's Interfaces blocks exactly. Ends with every earlier test passing unchanged except the `PROJECTION_VERSION` pin.

**Goal:** Make a project safe to host on a shared server: one writer per hosted project, event IDs minted under the project write lock so that append order equals ID order across concurrent sessions, a host check that refuses foreign writers, and a server-side commit job.

**Architecture:** `Project.writing()` wraps `Index.exclusive()`, re-reads the last event ID from the index meta and floors the project's `IdGenerator` above it. Services that mint events do so inside `writing()`. `project.hosted` names a host id; `EventWriter` refuses appends when the project is hosted elsewhere. `services/hosting.py` holds the host logic; `services/commit.py` drives `git` through `subprocess` with fixed arguments.

**Tech Stack:** as slice 2; `git` CLI on the server; no new Python dependency.

**Spec:** `docs/specs/slice-5-teams-deployment.md` rulings 2, 3, 4, 5; Design "Concurrency"; acceptance 1, 5, 6, 15.

## Rulings made in this plan

1. **Host id.** `Settings.host_id: str | None`, from argument, `FACTORY_HOST_ID`, or the file `<root>/.server/host_id` (written by `factory server init`, teams-A Task 6); `None` on personal machines. Pattern `ACTOR_ID_RE`. [confirm]
2. **Unhosted projects are unchanged.** No `project.hosted` event → no host check, no ordering requirement beyond today's. [confirm]
3. **Ordering guard.** In a hosted project, `Project.record` refuses (`FactoryError("ordering")`, nothing written) when the first event's ID is not greater than the last applied ID; this can only happen if a service minted outside `writing()`, so it is a programming error caught by tests, not a user error. [confirm]
4. **Commit scope.** `factory commit` stages only `projects/<slug>/events/**` and `projects/<slug>/blobs/**` of hosted projects, refuses if any staged path is under `library/`, `.index/` or `.server/`, and commits as `factory-server <host_id>` with `-S` when `--sign` is given. [confirm]

## Global Constraints

- Events are the source of truth; the index is written by the projector alone; never edit or delete an event line.
- The platform never calls a model.
- Business logic in `services/`; `cli/` parses and formats only.
- Invalid input writes nothing and returns structured errors.
- `uv run pytest -m "not network and not slow"`, `mypy --strict`, ruff pass; coverage ≥ 90% for `services/` and `model/`.

## Review Focus

1. Eight threads claiming tasks on one hosted project: zero rebuilds, one holder per task (Task 2, `test_concurrent_claims_never_rebuild`).
2. A second process with a fresh `IdGenerator` mints above the last event of the first (Task 1, `test_writing_floors_ids_across_processes`).
3. A foreign host appends nothing and the error names the host (Task 3, `test_foreign_host_cannot_append`).
4. `factory commit` never stages a library file even when `.gitignore` is missing (Task 5, `test_commit_refuses_library_paths`).

## File Structure

- Modify `model/identity.py` (`IdGenerator.floor`), `services/context.py` (`Project.writing`, ordering guard), `services/tasks.py`, `config.py` (`host_id`), `events/writer.py` (host check hook), `events/catalog.py`, `index/project.py`, `services/check.py`, `cli/main.py`.
- Create `model/hosting.py` (`ProjectHosted`), `services/hosting.py`, `services/commit.py`.
- Tests: `tests/test_sequencing.py`, `tests/test_hosting.py`, `tests/test_commit.py`.

---

### Task 1: ID floor and `Project.writing()`

*Tier: critical.*

**Files:** Modify `model/identity.py`, `services/context.py`; Test `tests/test_sequencing.py`.

**Interfaces:**
- Consumes: `IdGenerator(clock)`, `Index.exclusive()`, index meta `last_event_id`.
- Produces: `IdGenerator.floor(ulid: str) -> None` (next `ulid()` is strictly greater than `ulid`); `Index.last_event_id() -> str | None` (read under the held lock); `Project.writing() -> ContextManager[None]` (re-entrant; holds the exclusive lock, syncs, floors `ids` at `last_event_id`).

- [ ] **Step 1: Tests.**
```python
def test_floor_makes_next_id_greater(clock_at_epoch):
    ids = IdGenerator(clock_at_epoch); ids.floor("01KZZZZZZZZZZZZZZZZZZZZZZZ"); assert ids.ulid() > "01KZZZZZZZZZZZZZZZZZZZZZZZ"
def test_writing_floors_ids_across_processes(tmp_project_factory):
    a, b = tmp_project_factory(session="A"), tmp_project_factory(session="B", clock=behind_by(seconds=5))
    with a.writing(): a.record([event(a)])
    with b.writing(): e = event(b)
    assert e.id > last_id(a)
def test_writing_is_reentrant(project): 
    with project.writing(), project.writing(): pass
```
- [ ] **Step 2:** Run `uv run pytest tests/test_sequencing.py -q`; expect failures.
- [ ] **Step 3:** Implement `floor` (sets `_last = max(_last, decode(ulid))`), `last_event_id`, `writing`.
- [ ] **Step 4:** Run the tests; expect pass. Run the full suite.
- [ ] **Step 5:** Commit `feat(sequencing): id floor and project write context`.

### Task 2: Mint inside `writing()`; ordering guard

*Tier: critical.*

**Files:** Modify `services/context.py` (`Project.record` guard when hosted), `services/tasks.py` (`claim_next`, `create_tasks`, `complete_task`, `release_task`), every service that calls `project.events.make` before `project.index.exclusive()` (list produced by `grep -n "events.make" services/*.py` and recorded in the task's commit message); Test `tests/test_sequencing.py`.

**Interfaces:**
- Produces: `Project.is_hosted() -> bool` (stub returning False until Task 3); `Project.record` raises `OrderingError(FactoryError)` on a hosted project when `events[0].id <= last_event_id`.

- [ ] **Step 1: Tests.**
```python
def test_record_refuses_out_of_order_on_hosted(hosted_project):
    early = mint(hosted_project); with hosted_project.writing(): hosted_project.record([mint(hosted_project)])
    with pytest.raises(OrderingError): hosted_project.record([early])
    assert count_events(hosted_project) == 1
def test_concurrent_claims_never_rebuild(hosted_project_with_tasks):   # 8 threads x 20 claims
    results = run_threads(8, lambda s: claim_all(open_as(s)))
    assert rebuild_count(hosted_project_with_tasks) == 0
    assert all(len(holders(t)) == 1 for t in tasks())
    assert ids_increase_in_append_order(events_dir())
```
`rebuild_count` wraps `Index._build` with a counter (monkeypatch). `ids_increase_in_append_order` reads every file in append order and checks the global merge by file mtime-independent sequence: within each file strictly increasing, and the projection's `last_event_id` equals the maximum.
- [ ] **Step 2:** Run; expect failures (the concurrency test should rebuild today).
- [ ] **Step 3:** Move minting inside `with project.writing():` in the listed services; add the guard.
- [ ] **Step 4:** Run `uv run pytest -m "not network and not slow" -q`; expect pass.
- [ ] **Step 5:** Commit `fix(sequencing): mint events under the project write lock`.

### Task 3: `project.hosted` and the host check

*Tier: critical.*

**Files:** Create `model/hosting.py`, `services/hosting.py`; Modify `config.py`, `events/catalog.py`, `index/project.py`, `services/context.py`, `events/writer.py`; Test `tests/test_hosting.py`.

**Interfaces:**
- Produces: `ProjectHosted(host_id: str, previous_host: str | None)`; event `project.hosted` schema 1; index table `project_hosts(event_id, host_id, previous_host)`; `services/hosting.py::current_host(project) -> str | None`, `host_project(project, actor: Actor, host_id: str) -> str` (refused when already hosted by the same host; `previous_host` filled from the fold); `EventWriter(..., host_guard: Callable[[], str | None] | None = None)` refusing with `ValidationIssue("host", "project is hosted by <id>")` when the guard returns a host different from `Settings.host_id`; `Project.is_hosted()` reads `current_host`.

- [ ] **Step 1: Tests.** `test_unhosted_project_unchanged` (no guard effect; state hash equal to a pre-plan fixture log except projection version), `test_host_records_event_and_previous_host`, `test_foreign_host_cannot_append` (settings `host_id="laptop"` on a project hosted by `"lab1"`: `FactoryValidationError`, file sizes unchanged), `test_rehost_names_previous`.
- [ ] **Step 2–4:** Fail, implement, pass; full suite.
- [ ] **Step 5:** Commit `feat(hosting): project.hosted and the single-writer host check`.

### Task 4: `host-mismatch` check and `factory server check`

*Tier: standard.*

**Files:** Modify `services/check.py`, `cli/main.py`; Create `services/server_check.py`; Test `tests/test_hosting.py`.

**Interfaces:**
- Produces: check finding `host-mismatch` (error): an event file of a hosted project that contains an event later than `project.hosted` and was added to git history by a commit whose author is not `factory-server <host_id>` (read with `git log --format=%an --diff-filter=A -- <file>`; skipped with an advisory note when the root is not a git repository). Sessions write no event, so authorship of the commit is the only durable writer record; the writer-side guard of Task 3 prevents the case on the server itself. [confirm]
- Produces: `server_check(settings) -> list[ValidationIssue]`: root on a local file system (Linux: `/proc/mounts` type not in `nfs, nfs4, cifs, smbfs, fuse.sshfs`; macOS: `mount` output parsed), a two-process `flock` exclusion probe, `.gitignore` contains `library/`, `.index/`, `.server/`.

- [ ] **Step 1: Tests.** `test_server_check_flags_missing_gitignore`, `test_server_check_flock_probe`, `test_host_mismatch_flags_foreign_commit` (temp git repo; a file committed by another author after hosting).
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(hosting): server check and host-mismatch finding`.

### Task 5: `factory commit`

*Tier: standard.*

**Files:** Create `services/commit.py`; Modify `cli/main.py`; Test `tests/test_commit.py`.

**Interfaces:**
- Produces: `commit_hosted(settings: Settings, *, sign: bool, push: str | None) -> CommitReport` with `CommitReport(projects: dict[str, int], commit: str | None, pushed: bool)`; `git` called as `["git", "-C", root, ...]` with fixed arguments only; CLI `factory commit [--sign] [--push REMOTE]`.

- [ ] **Step 1: Tests.** `test_commit_adds_only_events_and_text_blobs`, `test_commit_refuses_library_paths` (remove `.gitignore`, create a library file: refused, nothing committed), `test_commit_is_noop_without_changes`, `test_commit_author_is_factory_server`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Verification `uv run pytest -m "not network and not slow" -q && uv run mypy --strict src && uv run ruff check .`; commit `feat(hosting): server commit job`.

## Later (not v1)

None: every task of this plan is in v1.
