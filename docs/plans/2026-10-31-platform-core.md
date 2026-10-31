# Platform Core Implementation Plan (slice 1, sub-plan 1 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A tested `factory` Python package that records validated events in append-only session files, stores content-addressed blobs, projects events into a deterministically rebuildable SQLite index, runs a leased task queue, and exposes `init` / `rebuild` / `status` / `serve` through a thin CLI and an MCP server with one tool (`project_status`).

**Architecture:** Events are the only source of truth: services build events, the writer validates and appends them to `projects/<slug>/events/<actor>/<session>.jsonl`, then the index syncs. The projector is the only writer of SQLite; it applies new events incrementally when they sort after everything already applied, and otherwise rebuilds from scratch. Event IDs are monotonic ULIDs whose embedded timestamp *is* the event `ts`, so ID order is the single global order.

**Tech Stack:** Python ≥ 3.11 (pinned 3.12) · uv · pydantic 2 · SQLAlchemy 2 Core on SQLite · typer · official MCP Python SDK (`mcp`, FastMCP) · pytest, pytest-cov, anyio · ruff · mypy `--strict`.

**Spec:** `docs/specs/00-system.md` (§2–§4, §7–§10), `docs/specs/01-rigour.md` (R-04), `docs/specs/slice-1.md` (platform core row; acceptance criteria 1, 11 envelope part, 21). Split approved 2026-10-31: plan 1 = platform core; plans 2–5 add works/sources, question→protocol, screening, reports.

## Global Constraints

- The platform never calls a model; no model SDKs or API keys in `platform/`.
- Business logic lives in `factory/services/`; `mcp/` and `cli/` only parse input, call a service, format output.
- Events are append-only; nothing in the code path edits or deletes an event line. The SQLite index is written only by the projector.
- Invalid input writes nothing and yields structured errors `(field, reason)`.
- Event envelope fields exactly as 00-system §4.2: `id`, `ts`, `project`, `type`, `schema`, `actor{kind,id,user,session,model}`, `refs`, `input_blob`, `payload`; plus `actor.skill` (R-04, CLAUDE.md: "every agent-written event carries model, skill version and `input_blob`").
- IDs: events `ev_<ULID>`; other entities `<prefix>_<ULID>` (`tsk_` in this plan); session = bare ULID. IDs are never reused.
- Blob path: `projects/<slug>/blobs/sha256/<2>/<62>`; ref string `sha256:<64 hex>`.
- Index path: `projects/<slug>/.index/factory.sqlite` (already git-ignored).
- Task lease default: 30 minutes. Task events: `task.created`, `task.claimed`, `task.completed`, `task.released`.
- Rigor modes: `exploratory | pilot | systematic`.
- MCP tool names `<area>_<verb>`; read tools paginated with a fixed maximum page size.
- `mypy --strict` and `ruff check` pass; pytest offline by default, `network` marker for network tests; coverage ≥ 90% for `factory.services` and `factory.model`.
- TDD for every task. Commit after each task on branch `plan-1-platform-core`. Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- All commands below run from `platform/` unless stated.

## Review Focus

1. **A crash mid-append leaves a final line without `\n`.** Reading must skip the incomplete tail (not fail the project), and apply it once it is completed; a malformed *complete* line anywhere is corruption and fails loudly with file and byte offset. → Task 4 tests `test_truncated_tail_is_not_consumed`, `test_corrupt_complete_line_raises_with_location`.
2. **Two sessions claim the same task at the same time.** Exactly one holds the lease (the claim that sorts first); the other must not be able to complete it. → Task 7 test `test_concurrent_claims_first_wins`.
3. **Events from another session arrive with earlier timestamps** (git pull, clock skew between machines). Incremental sync must not apply them out of order; it rebuilds, and the result equals a fresh rebuild. → Task 5 test `test_out_of_order_events_trigger_rebuild`.
4. **The index is stale for reasons other than new events**: projector code changed, the DB was deleted, or an event file shrank/disappeared (history rewritten). Sync must detect each and rebuild. → Task 5 tests `test_projection_version_change_rebuilds`, `test_shrunk_or_missing_file_rebuilds`.
5. **A blob is altered on disk.** Reading it must raise, never return bytes whose hash differs from the ref. → Task 2 test `test_tampered_blob_raises`.

---

## File Structure

```
.mcp.json                                   Claude Code registration of `factory serve` (Task 10)
platform/
  pyproject.toml  .python-version
  src/factory/
    __init__.py  py.typed
    clock.py              Clock protocol, SystemClock, FixedClock
    canonical.py          canonical_json(): the one JSON encoding used for hashing and writing
    errors.py             ValidationIssue, FactoryError, FactoryValidationError, ProjectNotFoundError
    config.py             Settings (root, user) from args/env
    model/
      base.py             StrictModel
      identity.py         ULID generation (monotonic), prefixed IDs, ACTOR_ID_RE, SLUG_RE
      project.py          RigorMode, ProjectCreated payload
      task.py             Task read model, TaskStatus, task.* payloads
    events/
      blobs.py            BlobStore
      envelope.py         Actor, Event
      catalog.py          EventType, EventCatalog, default_catalog()
      validation.py       validate_event()
      factory.py          EventFactory
      writer.py           EventWriter
      reader.py           read_file(), read_all(), event_files()
    index/
      projection.py       Projection, Handler, core tables (meta, sync_state, events)
      index.py            Index: sync(), rebuild(), state_hash(), connect()
      project.py          `project` table + handler
      tasks.py            `tasks` table + handlers
      default.py          default_projection()
    services/
      context.py          ProjectPaths, Project, open_project(), list_projects()
      results.py          ItemError, BatchResult
      project.py          init_project(), project_status(), ProjectStatus
      tasks.py            TaskSpec, create_tasks(), claim_next(), complete_task(), release_task(), …
    mcp/
      conventions.py      PAGE_LIMIT, ok(), fail(), paginate(), make_agent_actor(), guarded()
      server.py           build_server(), run()
    cli/
      main.py             typer app: init, rebuild, status, serve
  tests/  (one test module per source module, plus test_acceptance_rebuild.py)
```

---

### Task 1: Toolchain, package skeleton, clock and identity

**Files:**
- Create: `platform/pyproject.toml`, `platform/.python-version` (`3.12`), `platform/src/factory/__init__.py`, `platform/src/factory/py.typed`, `platform/src/factory/clock.py`, `platform/src/factory/model/__init__.py`, `platform/src/factory/model/base.py`, `platform/src/factory/model/identity.py`
- Test: `platform/tests/conftest.py`, `platform/tests/test_identity.py`, `platform/tests/test_clock.py`

**Interfaces:**
- Produces:
  - `Clock` (Protocol: `now() -> datetime`), `SystemClock`, `FixedClock(start: datetime)` with `advance(delta: timedelta) -> None`; both return tz-aware UTC; `FixedClock` rejects naive datetimes with `ValueError`.
  - `StrictModel(pydantic.BaseModel)`: `model_config = ConfigDict(extra="forbid", frozen=True)`.
  - `IdGenerator(clock: Clock)`: `.ulid() -> str` (26-char Crockford base32, strictly increasing per instance), `.new(prefix: str) -> str` → `f"{prefix}_{ulid}"`.
  - `ulid_time(ulid: str) -> datetime` (UTC, millisecond precision); `is_prefixed_id(value: str, prefix: str) -> bool`.
  - Regex constants: `ULID_RE = r"[0-9A-HJKMNP-TV-Z]{26}"`, `ACTOR_ID_RE = r"^[a-z0-9][a-z0-9._-]{0,63}$"`, `SLUG_RE = r"^[a-z0-9]+(-[a-z0-9]+)*$"` (max 64 chars).
  - conftest fixtures: `T0 = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)`, `clock` (a `FixedClock(T0)`), `anyio_backend` → `"asyncio"`.

- [ ] **Step 1: Install toolchain and set up the branch**

```bash
command -v uv || brew install uv
cd /Users/obd/Projects/research-factory
git add -A && git commit -m "docs: specs, decisions and slice-1 plan 1"   # initial commit on main
git checkout -b plan-1-platform-core
```
Expected: `uv --version` prints ≥ 0.4; `git branch --show-current` prints `plan-1-platform-core`.

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "factory"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["pydantic>=2.7", "sqlalchemy>=2.0", "typer>=0.12", "mcp>=1.6"]

[project.scripts]
factory = "factory.cli.main:app"

[dependency-groups]
dev = ["pytest>=8", "pytest-cov>=5", "anyio>=4", "mypy>=1.11", "ruff>=0.6"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/factory"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-m 'not network' --strict-markers"
markers = ["network: contacts external services"]

[tool.mypy]
strict = true
plugins = ["pydantic.mypy"]
mypy_path = "src"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM", "RUF"]

[tool.coverage.run]
branch = true
```
Run: `uv sync` → Expected: creates `.venv`, installs Python 3.12 if needed.

- [ ] **Step 3: Write the failing tests**

```python
# tests/test_identity.py
def test_ulids_are_strictly_increasing_within_one_millisecond(clock):
    gen = IdGenerator(clock)
    ids = [gen.ulid() for _ in range(1000)]
    assert ids == sorted(ids) and len(set(ids)) == 1000

def test_ulids_stay_increasing_when_clock_goes_backwards(clock):
    gen = IdGenerator(clock)
    a = gen.ulid()
    clock.advance(timedelta(seconds=-5))
    assert gen.ulid() > a

def test_ulid_time_round_trips_to_the_millisecond(clock):
    clock.advance(timedelta(microseconds=123_456))
    gen = IdGenerator(clock)
    assert ulid_time(gen.ulid()) == T0 + timedelta(milliseconds=123)

def test_prefixed_ids(clock):
    tid = IdGenerator(clock).new("tsk")
    assert re.fullmatch(r"tsk_" + ULID_RE, tid)
    assert is_prefixed_id(tid, "tsk") and not is_prefixed_id(tid, "ev")
    assert not is_prefixed_id("tsk_short", "tsk")

def test_strict_model_rejects_unknown_fields_and_mutation():
    class M(StrictModel):
        a: int
    with pytest.raises(ValidationError):
        M(a=1, b=2)
    with pytest.raises(ValidationError):
        M(a=1).a = 2  # type: ignore[misc]

# tests/test_clock.py
def test_fixed_clock_rejects_naive_datetime():
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 1, 1))

def test_system_clock_is_utc():
    assert SystemClock().now().utcoffset() == timedelta(0)
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/test_identity.py tests/test_clock.py -v` → Expected: FAIL (`ImportError`).

- [ ] **Step 5: Implement `clock.py`, `model/base.py`, `model/identity.py`**

No ULID dependency: encode a 128-bit int (48-bit ms timestamp ‖ 80 bits from `secrets.randbits(80)`) in Crockford base32. Monotonicity rule in `IdGenerator.ulid()`:
```
ms = epoch milliseconds of clock.now()
if last is not None and ms <= last_ms: value = last + 1   # keep the previous timestamp
else:                                   value = (ms << 80) | randbits(80)
```

- [ ] **Step 6: Run tests to verify they pass, then lint and type-check**

Run: `uv run pytest -v && uv run ruff check . && uv run mypy src tests` → Expected: all pass, no errors.

- [ ] **Step 7: Commit** — `git commit -m "feat(platform): package skeleton, clock, monotonic ULIDs"`

---

### Task 2: Content-addressed blob store

**Files:**
- Create: `platform/src/factory/canonical.py`, `platform/src/factory/events/__init__.py`, `platform/src/factory/events/blobs.py`
- Test: `platform/tests/test_blobs.py`, `platform/tests/test_canonical.py`

**Interfaces:**
- Produces:
  - `canonical_json(value: JsonValue) -> bytes`: `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")`. Used for blob JSON, event lines and state hashes.
  - `BlobStore(root: Path)` (root = `projects/<slug>/blobs`): `put(data: bytes) -> str`, `put_json(value: JsonValue) -> str`, `get(ref: str) -> bytes`, `get_json(ref: str) -> JsonValue`, `exists(ref: str) -> bool`, `path(ref: str) -> Path`.
  - `BLOB_REF_RE = r"^sha256:[0-9a-f]{64}$"`; `BlobNotFoundError`, `BlobIntegrityError` (both subclass `FactoryError` from `errors.py`, created here with `class FactoryError(Exception)`).

- [ ] **Step 1: Write the failing tests**

```python
def test_put_returns_sha256_ref_and_uses_two_level_layout(tmp_path):
    store = BlobStore(tmp_path / "blobs")
    ref = store.put(b"hello")
    digest = hashlib.sha256(b"hello").hexdigest()
    assert ref == f"sha256:{digest}"
    assert store.path(ref) == tmp_path / "blobs" / "sha256" / digest[:2] / digest[2:]
    assert store.get(ref) == b"hello"

def test_put_is_idempotent_and_leaves_no_temp_files(tmp_path):
    store = BlobStore(tmp_path / "blobs")
    assert store.put(b"x") == store.put(b"x")
    assert len([p for p in (tmp_path / "blobs").rglob("*") if p.is_file()]) == 1

def test_put_json_is_key_order_independent(tmp_path):
    store = BlobStore(tmp_path / "blobs")
    assert store.put_json({"b": 1, "a": [1, "é"]}) == store.put_json({"a": [1, "é"], "b": 1})
    assert store.get_json(store.put_json({"a": 1})) == {"a": 1}

def test_tampered_blob_raises(tmp_path):
    store = BlobStore(tmp_path / "blobs")
    ref = store.put(b"original")
    store.path(ref).write_bytes(b"changed")
    with pytest.raises(BlobIntegrityError):
        store.get(ref)

def test_missing_and_malformed_refs(tmp_path):
    store = BlobStore(tmp_path / "blobs")
    with pytest.raises(BlobNotFoundError):
        store.get("sha256:" + "0" * 64)
    assert not store.exists("sha256:" + "0" * 64)
    with pytest.raises(ValueError):
        store.path("md5:abc")

def test_canonical_json_rejects_nan():
    with pytest.raises(ValueError):
        canonical_json(float("nan"))
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_blobs.py tests/test_canonical.py -v` → FAIL (`ImportError`).

- [ ] **Step 3: Implement** — atomic write: write to `<target>.tmp-<pid>` in the same directory, `fsync`, `os.replace`; skip the write when the target exists.

- [ ] **Step 4: Run to verify pass** — same command → PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat(platform): content-addressed blob store"`

---

### Task 3: Event envelope, catalog and validation

**Files:**
- Create: `platform/src/factory/errors.py` (extend), `platform/src/factory/events/envelope.py`, `platform/src/factory/events/catalog.py`, `platform/src/factory/events/validation.py`, `platform/src/factory/events/factory.py`
- Test: `platform/tests/test_envelope.py`, `platform/tests/test_event_validation.py`

**Interfaces:**
- Consumes: `IdGenerator`, `ulid_time`, `ACTOR_ID_RE`, `ULID_RE` (Task 1); `BlobStore`, `BLOB_REF_RE`, `canonical_json` (Task 2).
- Produces:
  - `errors.py`: `ValidationIssue(field: str, reason: str)` (frozen dataclass); `FactoryValidationError(FactoryError)` with `.issues: list[ValidationIssue]`; `ProjectNotFoundError(FactoryError)`.
  - `ActorKind = Literal["human", "agent", "system"]`.
  - `Actor(StrictModel)`: `kind`, `id` (ACTOR_ID_RE), `user` (ACTOR_ID_RE), `session` (ULID_RE), `model: str | None = None`, `skill: str | None = None`. Invariant: `kind == "agent"` ⇔ `model` and `skill` both set; for `human`/`system` both must be `None`. `skill` matches `^[a-z0-9][a-z0-9-]*@[0-9a-f]{8,64}$` (skill name @ hash of its text).
  - `Event(StrictModel)`: `id` (`ev_` + ULID), `ts: datetime`, `project` (SLUG_RE), `type`, `schema_version: int` (JSON alias `"schema"`, ≥ 1), `actor: Actor`, `refs: tuple[str, ...] = ()`, `input_blob: str | None = None` (BLOB_REF_RE), `payload: dict[str, JsonValue]`. Invariants: `ts` is UTC and equals `ulid_time(id without "ev_")`; `kind == "agent"` ⇒ `input_blob` is set. Methods: `to_line() -> bytes` (canonical JSON by alias, `ts` as `YYYY-MM-DDTHH:MM:SS.mmmZ`, plus `b"\n"`), `Event.from_line(line: bytes) -> Event`.
  - `EventType(name: str, payload: type[StrictModel], schema: int)`; `EventCatalog`: `register(t: EventType) -> None` (rejects duplicates and names not matching `^[a-z][a-z_]*\.[a-z][a-z_]*$`), `get(name) -> EventType` (KeyError), `__contains__`, `names() -> list[str]`. `default_catalog() -> EventCatalog` (empty until Tasks 6–7 add entries).
  - `validate_event(event: Event, *, catalog: EventCatalog, blobs: BlobStore, project: str) -> list[ValidationIssue]`: type registered; schema equals catalog version; payload validates against the payload model (issue field `payload.<loc>`); `event.project == project`; `input_blob` exists in `blobs`.
  - `EventFactory(project: str, catalog: EventCatalog, ids: IdGenerator)`: `make(type: str, payload: StrictModel, actor: Actor, refs: Sequence[str] = (), input_blob: str | None = None) -> Event` — takes one ULID, sets `id = "ev_"+ulid`, `ts = ulid_time(ulid)`, `schema_version` from the catalog, `payload = payload.model_dump(mode="json")`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_envelope.py  (helper fixtures: `human` Actor, `agent` Actor with model="claude-opus-5-5", skill="rf-screen@1a2b3c4d")
def test_agent_actor_requires_model_and_skill(session_id):
    with pytest.raises(ValidationError):
        Actor(kind="agent", id="screener-a", user="obd", session=session_id, skill="rf-screen@1a2b3c4d")
    with pytest.raises(ValidationError):
        Actor(kind="agent", id="screener-a", user="obd", session=session_id, model="claude-opus-5-5")

def test_human_actor_must_not_carry_model(session_id):
    with pytest.raises(ValidationError):
        Actor(kind="human", id="obd", user="obd", session=session_id, model="claude-opus-5-5")

def test_actor_id_must_be_path_safe(session_id):
    with pytest.raises(ValidationError):
        Actor(kind="human", id="../etc", user="obd", session=session_id)

def test_event_line_round_trip_uses_schema_alias_and_millisecond_z(factory, human):
    ev = factory.make("demo.recorded", Demo(n=1), human)
    line = ev.to_line()
    raw = json.loads(line)
    assert raw["schema"] == 1 and "schema_version" not in raw
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", raw["ts"])
    assert line.endswith(b"\n") and Event.from_line(line) == ev

def test_event_ts_must_match_id_timestamp(factory, human):
    ev = factory.make("demo.recorded", Demo(n=1), human)
    with pytest.raises(ValidationError):
        Event.model_validate({**ev.model_dump(by_alias=True), "ts": T0 + timedelta(seconds=1)})

def test_agent_event_requires_input_blob(factory, agent):
    with pytest.raises(ValidationError):
        factory.make("demo.recorded", Demo(n=1), agent)

def test_catalog_rejects_duplicates_and_bad_names():
    cat = EventCatalog()
    cat.register(EventType("demo.recorded", Demo, 1))
    with pytest.raises(ValueError):
        cat.register(EventType("demo.recorded", Demo, 1))
    with pytest.raises(ValueError):
        cat.register(EventType("Demo", Demo, 1))

# tests/test_event_validation.py
def test_valid_event_has_no_issues(factory, human, blobs): ...  # == []
def test_unknown_type_is_reported(...):      # issue field "type"
def test_schema_mismatch_is_reported(...):   # issue field "schema"
def test_payload_errors_are_located(factory, human, blobs):
    ev = factory.make("demo.recorded", Demo(n=1), human)
    bad = ev.model_copy(update={"payload": {"n": "x"}})
    assert validate_event(bad, catalog=cat, blobs=blobs, project="demo")[0].field == "payload.n"
def test_wrong_project_is_reported(...):     # issue field "project"
def test_missing_input_blob_is_reported(factory, agent, blobs):
    ev = factory.make("demo.recorded", Demo(n=1), agent, input_blob="sha256:" + "0" * 64)
    assert [i.field for i in validate_event(ev, catalog=cat, blobs=blobs, project="demo")] == ["input_blob"]
```
`Demo(StrictModel)` with `n: int` is a test-only payload registered as `demo.recorded` in a test catalog. Add to conftest: `SESSION`, `S2` (fixed ULID strings), fixtures `session_id`, `cat` (test catalog), `blobs` (`BlobStore(tmp_path / "blobs")`), `factory` (`EventFactory("demo", cat, IdGenerator(clock))`), `human`, `other_session_human`, `agent`. Later tasks reuse them.

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_envelope.py tests/test_event_validation.py -v` → FAIL.
- [ ] **Step 3: Implement** the modules above.
- [ ] **Step 4: Run to verify pass**, then `uv run mypy src tests` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(events): envelope, catalog, validation, factory"`

---

### Task 4: Session-file writer and reader

**Files:**
- Create: `platform/src/factory/events/writer.py`, `platform/src/factory/events/reader.py`
- Test: `platform/tests/test_event_log.py`

**Interfaces:**
- Consumes: `Event`, `EventCatalog`, `validate_event`, `BlobStore`, `FactoryValidationError`.
- Produces:
  - `EventWriter(events_dir: Path, *, project: str, catalog: EventCatalog, blobs: BlobStore)`: `append(events: Sequence[Event]) -> None`. Validates every event first; if any issue, raises `FactoryValidationError` with fields prefixed `events[<i>].` and writes nothing. Otherwise groups by `(actor.id, actor.session)` and appends to `events_dir/<actor.id>/<session>.jsonl` (`"ab"`, one `write` per file, `flush` + `os.fsync`).
  - `event_files(events_dir: Path) -> list[Path]`: all `*/*.jsonl`, sorted by relative path.
  - `ReadResult(events: list[Event], end_offset: int, truncated_tail: bool)`.
  - `read_file(path: Path, catalog: EventCatalog, start: int = 0) -> ReadResult`: reads complete lines from byte `start`; an incomplete last line (no `\n`) is not consumed (`end_offset` stops before it, `truncated_tail=True`); a complete line that fails `Event.from_line` or has a type unknown to `catalog` raises `EventLogCorruptError(path, offset, reason)`.
  - `read_all(events_dir: Path, catalog: EventCatalog) -> list[Event]`: all events, sorted by `id`.
  - `EventLogCorruptError(FactoryError)` with `.path`, `.offset`.

- [ ] **Step 1: Write the failing tests**

```python
def test_append_writes_one_file_per_actor_and_session(writer, factory, human, other_session_human, events_dir):
    a = factory.make("demo.recorded", Demo(n=1), human)
    b = factory.make("demo.recorded", Demo(n=2), other_session_human)
    writer.append([a, b])
    assert sorted(p.relative_to(events_dir).as_posix() for p in event_files(events_dir)) == sorted(
        [f"obd/{human.session}.jsonl", f"obd/{other_session_human.session}.jsonl"])

def test_invalid_batch_writes_nothing(writer, factory, human, events_dir):
    good = factory.make("demo.recorded", Demo(n=1), human)
    writer.append([good])
    before = event_files(events_dir)[0].read_bytes()
    bad = good.model_copy(update={"project": "other"})
    with pytest.raises(FactoryValidationError) as err:
        writer.append([factory.make("demo.recorded", Demo(n=2), human), bad])
    assert err.value.issues[0].field == "events[1].project"
    assert event_files(events_dir)[0].read_bytes() == before

def test_read_all_merges_files_in_id_order(...):   # events from two sessions interleaved → sorted by id

def test_truncated_tail_is_not_consumed(writer, factory, human, events_dir, cat):
    writer.append([factory.make("demo.recorded", Demo(n=1), human)])
    path = event_files(events_dir)[0]
    full = path.stat().st_size
    with path.open("ab") as f:
        f.write(b'{"id": "ev_')
    res = read_file(path, cat)
    assert len(res.events) == 1 and res.end_offset == full and res.truncated_tail

def test_corrupt_complete_line_raises_with_location(writer, factory, human, events_dir, cat):
    writer.append([factory.make("demo.recorded", Demo(n=1), human)])
    path = event_files(events_dir)[0]
    offset = path.stat().st_size
    with path.open("ab") as f:
        f.write(b"not json\n")
    with pytest.raises(EventLogCorruptError) as err:
        read_file(path, cat)
    assert err.value.path == path and err.value.offset == offset

def test_read_from_offset_returns_only_new_events(...):  # second append; read_file(path, cat, start=first.end_offset) → 1 event
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_event_log.py -v` → FAIL.
- [ ] **Step 3: Implement** `writer.py`, `reader.py`.
- [ ] **Step 4: Run to verify pass** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(events): append-only session writer and reader"`

---

### Task 5: Projector, incremental sync, rebuild, state hash

**Files:**
- Create: `platform/src/factory/index/__init__.py`, `platform/src/factory/index/projection.py`, `platform/src/factory/index/index.py`
- Test: `platform/tests/test_index.py`

**Interfaces:**
- Consumes: `read_file`, `event_files`, `Event`, `EventCatalog`, `canonical_json`.
- Produces:
  - `Handler = Callable[[Connection, Event], None]`.
  - `Projection(version: str, metadata: MetaData, handlers: Mapping[str, Handler])`. `core_tables(metadata) -> None` adds `meta(key PK, value)`, `sync_state(file PK, offset)`, `events(id PK, ts, type, actor_kind, actor_id, user, session, model, skill, input_blob, refs JSON text)`. Events with no handler still get an `events` row.
  - `SyncResult(applied: int, rebuilt: bool)`.
  - `Index(db_path: Path, events_dir: Path, catalog: EventCatalog, projection: Projection)`: `sync() -> SyncResult`, `rebuild() -> str` (returns state hash), `state_hash() -> str` (`"sha256:<hex>"`), `connect() -> ContextManager[Connection]` (read access for services).
  - `NON_STATE_TABLES = {"meta", "sync_state"}`.

Sync algorithm (the only non-obvious logic in this plan; implement exactly):
```
sync():
  if db missing or meta.projection_version != projection.version: return rebuild
  known = sync_state rows; files = event_files(events_dir)
  if any known file is missing, or any file's size < its stored offset: return rebuild
  new = []; for f in files: r = read_file(f, catalog, known.get(f, 0)); new += r.events; offsets[f] = r.end_offset
  if not new: return SyncResult(0, False)
  sort new by id; if new[0].id <= meta.last_event_id: return rebuild
  in one transaction: for ev in new: insert events row; handlers.get(ev.type)(conn, ev)
                      upsert sync_state offsets; meta.last_event_id = new[-1].id
  return SyncResult(len(new), False)

rebuild():
  build into "<db>.tmp" (create_all, meta.projection_version, apply read_all() in id order, offsets), then os.replace over db_path
  (remove stale -wal/-shm first); return state_hash()
```
`sync_state.file` stores the path relative to `events_dir` (POSIX) so copies of the project hash identically. `state_hash()`: for every table not in `NON_STATE_TABLES`, sorted by name, rows ordered by primary key, hash `name\n` then `canonical_json(row)\n` per row. SQLite opened with `PRAGMA journal_mode=WAL`.

- [ ] **Step 1: Write the failing tests** (test projection: version `"t1"`, a `demo_totals(key PK, total)` table, a handler for `demo.recorded` that adds `payload.n` to the total)

```python
def test_rebuild_is_deterministic_and_location_independent(tmp_path, populated_project):
    h1 = populated_project.index.rebuild()
    assert populated_project.index.rebuild() == h1
    copy = tmp_path / "copy"; shutil.copytree(populated_project.dir, copy, ignore=shutil.ignore_patterns(".index"))
    assert make_index(copy).rebuild() == h1

def test_incremental_sync_equals_rebuild(writer, factory, human, index):
    writer.append([factory.make("demo.recorded", Demo(n=1), human)])
    assert index.sync() == SyncResult(applied=1, rebuilt=True)      # first sync builds the DB
    writer.append([factory.make("demo.recorded", Demo(n=2), human)])
    assert index.sync() == SyncResult(applied=1, rebuilt=False)
    incremental = index.state_hash()
    assert index.rebuild() == incremental
    assert total(index) == 3

def test_out_of_order_events_trigger_rebuild(writer, human, other_session_human, index, clock, cat):
    early = EventFactory("demo", cat, IdGenerator(FixedClock(T0 - timedelta(hours=1))))
    late = EventFactory("demo", cat, IdGenerator(clock))
    writer.append([late.make("demo.recorded", Demo(n=1), human)]); index.sync()
    writer.append([early.make("demo.recorded", Demo(n=5), other_session_human)])
    assert index.sync().rebuilt
    assert index.state_hash() == index.rebuild() and total(index) == 6

def test_projection_version_change_rebuilds(...):  # reopen Index with Projection(version="t2", ...) → sync().rebuilt
def test_shrunk_or_missing_file_rebuilds(...):     # truncate a synced file to 0 bytes → rebuilt; delete a file → rebuilt
def test_truncated_tail_applied_once_complete(...): # partial line → sync applies 0; finish line with b'...\n' → applies 1
def test_events_table_has_row_per_event(...):      # count(events) == number appended, incl. types without handler
def test_deleted_index_is_rebuilt_on_sync(...):    # rm db file → sync().rebuilt and same state hash as before
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_index.py -v` → FAIL.
- [ ] **Step 3: Implement** `projection.py`, `index.py` with SQLAlchemy Core.
- [ ] **Step 4: Run to verify pass** → PASS; `uv run mypy src tests` clean.
- [ ] **Step 5: Commit** — `git commit -m "feat(index): projector with incremental sync and deterministic rebuild"`

---

### Task 6: Settings, project context, `init` and `status` services

**Files:**
- Create: `platform/src/factory/config.py`, `platform/src/factory/model/project.py`, `platform/src/factory/index/project.py`, `platform/src/factory/index/default.py`, `platform/src/factory/services/__init__.py`, `platform/src/factory/services/context.py`, `platform/src/factory/services/project.py`
- Modify: `platform/src/factory/events/catalog.py` (`default_catalog` registers `project.created`)
- Test: `platform/tests/test_config.py`, `platform/tests/test_project_service.py`; conftest gains `settings` (root `tmp_path`, user `"obd"`) and `project` (an initialised `demo` project in `pilot` mode).

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces:
  - `Settings(root: Path, user: str)`; `Settings.load(root: Path | None = None, user: str | None = None) -> Settings` — precedence: argument, then env `FACTORY_ROOT` / `FACTORY_USER`, then `Path.cwd()` / `getpass.getuser()`; invalid user (not ACTOR_ID_RE) → `FactoryValidationError([ValidationIssue("user", …)])`.
  - `RigorMode(StrEnum)`: `EXPLORATORY="exploratory"`, `PILOT="pilot"`, `SYSTEMATIC="systematic"`. `ProjectCreated(StrictModel)`: `slug: str`, `rigor_mode: RigorMode`. Event type `project.created`, schema 1.
  - `default_projection() -> Projection` (version string `PROJECTION_VERSION = "1"`; bump on any projector change), including the `project(slug PK, rigor_mode, created_at, created_by)` table.
  - `ProjectPaths(root: Path, slug: str)` with properties `dir` (`root/projects/slug`), `events_dir`, `blobs_dir`, `index_path`.
  - `Project` (dataclass): `paths`, `settings`, `session: str`, `clock: Clock`, `ids: IdGenerator`, `catalog`, `blobs: BlobStore`, `events: EventFactory`, `writer: EventWriter`, `index: Index`; method `record(events: Sequence[Event]) -> None` (= `writer.append` then `index.sync()`); `human_actor() -> Actor` and `system_actor() -> Actor` (id = `settings.user` / `"factory"`, user = `settings.user`, this session).
  - `open_project(settings: Settings, slug: str, *, session: str, clock: Clock) -> Project` (raises `ProjectNotFoundError` if `paths.dir` has no `events/`); `list_projects(settings) -> list[str]`.
  - `init_project(settings, slug: str, rigor_mode: str, *, session: str, clock: Clock) -> Project`: validates slug (SLUG_RE, ≤ 64) and mode; refuses an existing project dir (issue field `slug`, reason `"project already exists"`); creates dirs and records one `project.created` event as the human actor. On any validation failure creates nothing.
  - `ProjectStatus(StrictModel)`: `slug`, `rigor_mode`, `created_at: datetime`, `events_total: int`, `events_by_type: dict[str, int]`, `last_event_at: datetime | None`.
  - `project_status(project: Project) -> ProjectStatus` (calls `index.sync()` first).

- [ ] **Step 1: Write the failing tests**

```python
def test_settings_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_ROOT", str(tmp_path / "env")); monkeypatch.setenv("FACTORY_USER", "envuser")
    assert Settings.load().root == tmp_path / "env" and Settings.load().user == "envuser"
    assert Settings.load(root=tmp_path, user="obd") == Settings(root=tmp_path, user="obd")

def test_init_creates_layout_and_one_event(settings, clock):
    p = init_project(settings, "linear-attention-vision", "pilot", session=SESSION, clock=clock)
    assert (p.paths.dir / "events" / "obd" / f"{SESSION}.jsonl").exists()
    st = project_status(p)
    assert (st.slug, st.rigor_mode, st.events_total) == ("linear-attention-vision", RigorMode.PILOT, 1)
    assert st.events_by_type == {"project.created": 1}

@pytest.mark.parametrize("slug", ["Bad", "a--b", "-a", "", "a" * 65, "../x"])
def test_invalid_slug_creates_nothing(settings, clock, slug):
    with pytest.raises(FactoryValidationError) as err:
        init_project(settings, slug, "pilot", session=SESSION, clock=clock)
    assert err.value.issues[0].field == "slug" and not (settings.root / "projects").exists()

def test_invalid_mode_is_rejected(settings, clock): ...   # "rigorous" → issue field "rigor_mode"
def test_duplicate_init_is_refused(settings, clock): ...  # second init same slug → reason "project already exists"
def test_open_unknown_project_raises(settings, clock): ... # ProjectNotFoundError
def test_list_projects(settings, clock): ...               # two inits → sorted slugs
def test_status_survives_index_deletion(project):
    before = project_status(project)
    shutil.rmtree(project.paths.dir / ".index")
    assert project_status(project) == before
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_config.py tests/test_project_service.py -v` → FAIL.
- [ ] **Step 3: Implement** the modules above.
- [ ] **Step 4: Run to verify pass** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(services): settings, project context, init and status"`

---

### Task 7: Task queue with leases

**Files:**
- Create: `platform/src/factory/model/task.py`, `platform/src/factory/index/tasks.py`, `platform/src/factory/services/results.py`, `platform/src/factory/services/tasks.py`
- Modify: `events/catalog.py` (register task types), `index/default.py` (tasks table + handlers; bump `PROJECTION_VERSION` to `"2"`), `services/project.py` (`ProjectStatus.tasks: TaskCounts`)
- Test: `platform/tests/test_tasks.py`, extend `platform/tests/test_project_service.py`

**Interfaces:**
- Consumes: `Project`, `Actor`, `BlobStore.put_json`, `Index.connect`.
- Produces:
  - Payloads (schema 1): `TaskCreated(task_id, kind)`, `TaskClaimed(task_id, lease_until: datetime)`, `TaskCompleted(task_id, result_refs: tuple[str, ...] = ())`, `TaskReleased(task_id, reason: str)`. Task content is the event's `input_blob`; subject IDs are the event's `refs`.
  - `TaskStatus(StrEnum)`: `OPEN`, `CLAIMED`, `COMPLETED`. `Task(StrictModel)`: `task_id`, `kind`, `status`, `content_blob`, `refs: tuple[str, ...]`, `created_at`, `claimed_by: str | None`, `claim_session: str | None`, `lease_until: datetime | None`.
  - `TASK_LEASE = timedelta(minutes=30)`; `TASK_KIND_RE = r"^[a-z][a-z_]*$"`.
  - `ItemError(index: int, issues: list[ValidationIssue])`; `BatchResult[T]`: `written: list[T]`, `rejected: list[ItemError]`.
  - `TaskSpec(kind: str, content: JsonValue, refs: tuple[str, ...] = ())`.
  - `create_tasks(project, actor, specs: Sequence[TaskSpec]) -> BatchResult[str]` (valid items written in one append; returns task IDs).
  - `claim_next(project, actor, kind: str, lease: timedelta = TASK_LEASE) -> Task | None`.
  - `complete_task(project, actor, task_id: str, result_refs: Sequence[str] = ()) -> None`; `release_task(project, actor, task_id: str, reason: str) -> None` — both raise `FactoryValidationError` (field `task_id`) unless the task is claimed by this `actor.session` with `lease_until > clock.now()`.
  - `get_task(project, task_id) -> Task | None`; `task_content(project, task: Task) -> JsonValue`.
  - `TaskCounts(open, claimed, expired, completed)`; `task_counts(project) -> TaskCounts` (`expired` = claimed with `lease_until <= clock.now()`).

Projector rules (deterministic; they use only event data, never the wall clock):
- `task.created` → row with status `open`.
- `task.claimed` takes effect iff status is `open`, or status is `claimed` and `lease_until <= event.ts`; otherwise ignored (row unchanged). `lease_until = event.ts + lease` is computed by the service and carried in the payload.
- `task.completed` / `task.released` take effect iff status is `claimed`, `event.actor.session == claim_session` and `event.ts < lease_until`; released → `open` with claim fields cleared.

`claim_next`: sync; select claimable rows (`open`, or `claimed` with `lease_until <= now`) of `kind`, ordered by `task_id`; for each candidate, record a claim, re-read the row, return it if `claim_session == actor.session`, else continue; return `None` when exhausted.

- [ ] **Step 1: Write the failing tests**

```python
def test_create_and_claim_returns_content(project, agent):
    res = create_tasks(project, project.system_actor(), [TaskSpec("demo", {"q": 1}, ("rf:x",))])
    task = claim_next(project, agent, "demo")
    assert task is not None and task.task_id == res.written[0] and task.refs == ("rf:x",)
    assert task_content(project, task) == {"q": 1}
    assert task.lease_until == T0 + TASK_LEASE

def test_batch_partial_success(project):
    res = create_tasks(project, project.system_actor(), [TaskSpec("demo", 1), TaskSpec("Bad Kind", 1)])
    assert len(res.written) == 1 and res.rejected[0].index == 1 and res.rejected[0].issues[0].field == "kind"

def test_active_lease_blocks_other_sessions_until_expiry(project, project_other_session, agent, agent_other, clock):
    create_tasks(project, project.system_actor(), [TaskSpec("demo", 1)])
    assert claim_next(project, agent, "demo") is not None
    assert claim_next(project_other_session, agent_other, "demo") is None
    clock.advance(TASK_LEASE + timedelta(seconds=1))
    assert task_counts(project).expired == 1
    assert claim_next(project_other_session, agent_other, "demo") is not None

def test_only_the_holder_can_complete(project, project_other_session, agent, agent_other):
    create_tasks(project, project.system_actor(), [TaskSpec("demo", 1)])
    t = claim_next(project, agent, "demo")
    with pytest.raises(FactoryValidationError):
        complete_task(project_other_session, agent_other, t.task_id)
    complete_task(project, agent, t.task_id, ["dec_x"])
    assert get_task(project, t.task_id).status == TaskStatus.COMPLETED

def test_complete_after_expiry_is_rejected(...):      # advance past lease → FactoryValidationError
def test_release_makes_task_claimable_again(...):     # release → status open; other session claims it

def test_concurrent_claims_first_wins(project, project_other_session, agent, agent_other):
    ids = create_tasks(project, project.system_actor(), [TaskSpec("demo", 1), TaskSpec("demo", 2)]).written
    for p, a in ((project, agent), (project_other_session, agent_other)):   # both claim task 1 without syncing
        lease = p.clock.now() + TASK_LEASE
        blob = get_task(project, ids[0]).content_blob
        p.writer.append([p.events.make("task.claimed", TaskClaimed(task_id=ids[0], lease_until=lease), a, input_blob=blob)])
    t = get_task(project, ids[0])
    assert t.claim_session == project.session
    assert claim_next(project_other_session, agent_other, "demo").task_id == ids[1]

def test_status_reports_task_counts(project, agent): ...  # 2 created, 1 claimed → TaskCounts(open=1, claimed=1, expired=0, completed=0)
def test_task_flow_rebuild_equals_incremental(project, agent): ...  # after create/claim/complete/release: index.state_hash() == index.rebuild()
```
Fixtures: `project_other_session` = `open_project` on the same root and slug with a second session ID and the same `clock`; `agent` / `agent_other` = agent actors on the respective sessions. Agent-written claim events carry `input_blob` = the task's `content_blob` (the content the agent saw).

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_tasks.py -v` → FAIL.
- [ ] **Step 3: Implement** the modules above.
- [ ] **Step 4: Run to verify pass** — `uv run pytest -v` → all PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(services): leased task queue"`

---

### Task 8: MCP server, tool conventions and `project_status`

**Files:**
- Create: `platform/src/factory/mcp/__init__.py`, `platform/src/factory/mcp/conventions.py`, `platform/src/factory/mcp/server.py`
- Test: `platform/tests/test_mcp_conventions.py`, `platform/tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `Settings`, `open_project`, `project_status`, `Actor`, `FactoryValidationError`, `ProjectNotFoundError`, `IdGenerator`.
- Produces:
  - `PAGE_LIMIT = 50`.
  - `ok(data: JsonValue) -> dict[str, JsonValue]` → `{"ok": True, "data": data}`; `fail(issues: Sequence[ValidationIssue]) -> dict[str, JsonValue]` → `{"ok": False, "errors": [{"field": …, "reason": …}]}`.
  - `Page[T](items: list[T], next_cursor: str | None)`; `paginate(items: Sequence[T], cursor: str | None, limit: int = PAGE_LIMIT) -> Page[T]` — cursor is the decimal offset as a string; `limit` is clamped to `1..PAGE_LIMIT`; a malformed cursor raises `FactoryValidationError` (field `cursor`).
  - `make_agent_actor(settings, session: str, role: str, model: str, skill: str) -> Actor` — wraps pydantic errors as `FactoryValidationError` with fields `role` / `model` / `skill`.
  - `guarded(fn: Callable[[], JsonValue]) -> dict[str, JsonValue]` — returns `ok(fn())`; maps `FactoryValidationError` → `fail(issues)`, `ProjectNotFoundError` → `fail([ValidationIssue("project", "unknown project")])`.
  - `build_server(settings: Settings, clock: Clock = SystemClock()) -> FastMCP` — creates one session ULID per server instance; registers tool `project_status(project: str)` returning `guarded(...)` with `ProjectStatus.model_dump(mode="json")`.
  - `run(settings: Settings) -> None` — `build_server(settings).run("stdio")`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_conventions.py
def test_paginate_walks_all_items_with_cursor():
    items = list(range(120))
    p1 = paginate(items, None); p2 = paginate(items, p1.next_cursor); p3 = paginate(items, p2.next_cursor)
    assert p1.items + p2.items + p3.items == items and p3.next_cursor is None and len(p1.items) == PAGE_LIMIT

def test_paginate_clamps_limit_and_rejects_bad_cursor():
    assert len(paginate(list(range(500)), None, limit=10_000).items) == PAGE_LIMIT
    with pytest.raises(FactoryValidationError):
        paginate([1], "abc")

def test_make_agent_actor_reports_fields(settings):
    with pytest.raises(FactoryValidationError) as err:
        make_agent_actor(settings, SESSION, "screener-a", model="", skill="rf-screen@1a2b3c4d")
    assert err.value.issues[0].field == "model"

def test_guarded_maps_errors():
    def boom() -> JsonValue: raise FactoryValidationError([ValidationIssue("x", "bad")])
    assert guarded(boom) == {"ok": False, "errors": [{"field": "x", "reason": "bad"}]}

# tests/test_mcp_server.py
@pytest.mark.anyio
async def test_project_status_tool(settings, project):
    server = build_server(settings, clock=project.clock)
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        names = [t.name for t in (await client.list_tools()).tools]
        assert names == ["project_status"]
        res = await client.call_tool("project_status", {"project": "demo"})
        body = json.loads(res.content[0].text)
        assert body["ok"] and body["data"]["rigor_mode"] == "pilot"

@pytest.mark.anyio
async def test_unknown_project_returns_structured_error(settings): ...  # body == {"ok": False, "errors": [{"field": "project", "reason": "unknown project"}]}
```
`create_connected_server_and_client_session` is from `mcp.shared.memory`.

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_mcp_conventions.py tests/test_mcp_server.py -v` → FAIL.
- [ ] **Step 3: Implement** the modules above.
- [ ] **Step 4: Run to verify pass** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(mcp): server skeleton, tool conventions, project_status"`

---

### Task 9: Thin CLI — `init`, `rebuild`, `status`, `serve`

**Files:**
- Create: `platform/src/factory/cli/__init__.py`, `platform/src/factory/cli/main.py`
- Test: `platform/tests/test_cli.py`

**Interfaces:**
- Consumes: `Settings.load`, `init_project`, `open_project`, `list_projects`, `project_status`, `Index.rebuild`, `mcp.server.run`, `IdGenerator`.
- Produces: typer `app` with global options `--root` (env `FACTORY_ROOT`) and `--project` (env `FACTORY_PROJECT`). Project resolution when `--project` is absent: the only project under the root, else exit code 2 with `"several projects: <slugs>; pass --project"` (or `"no project; run factory init"`). Each invocation uses a fresh session ULID.
  - `factory init <slug> [--mode pilot]` → prints `initialised <slug> (<mode>)`; validation errors print `<field>: <reason>` lines to stderr, exit 1.
  - `factory rebuild` → prints `state sha256:<hex>`.
  - `factory status [--json]` → human-readable lines (`project`, `rigor mode`, `events`, `tasks open/claimed/expired/completed`) or `ProjectStatus` JSON.
  - `factory serve` → `run(settings)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_init_status_rebuild(tmp_path):
    env = {"FACTORY_ROOT": str(tmp_path), "FACTORY_USER": "obd"}
    assert runner.invoke(app, ["init", "demo", "--mode", "pilot"], env=env).exit_code == 0
    st = json.loads(runner.invoke(app, ["status", "--json"], env=env).stdout)
    assert st["slug"] == "demo" and st["events_total"] == 1
    out = runner.invoke(app, ["rebuild"], env=env)
    assert out.exit_code == 0 and re.fullmatch(r"state sha256:[0-9a-f]{64}\n", out.stdout)

def test_rebuild_output_is_stable(tmp_path): ...       # two `rebuild` runs print the same line
def test_init_invalid_slug_exit_1(tmp_path): ...       # "Bad" → exit 1, stderr contains "slug:"
def test_ambiguous_project_exit_2(tmp_path): ...       # two inits, `status` without --project → exit 2, message lists both
def test_explicit_project_option(tmp_path): ...        # `--project b status --json` → slug "b"
```
`runner = CliRunner(mix_stderr=False)` from `typer.testing` (if the installed Click no longer accepts `mix_stderr`, use `CliRunner()` and `result.stderr`).

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_cli.py -v` → FAIL.
- [ ] **Step 3: Implement** `cli/main.py` (no logic beyond parsing, calling services, formatting).
- [ ] **Step 4: Run to verify pass** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(cli): init, rebuild, status, serve"`

---

### Task 10: Acceptance test, quality gates, Claude Code registration

**Files:**
- Create: `platform/tests/test_acceptance_rebuild.py`, `.mcp.json` (repo root)
- Modify: `CLAUDE.md` (Status line)

**Interfaces:**
- Consumes: the CLI and services from Tasks 6–9.

- [ ] **Step 1: Write the acceptance test (slice-1 criterion 1, end to end)**

```python
def test_rebuild_after_deleting_index_yields_same_state_hash(tmp_path, clock):
    settings = Settings(root=tmp_path, user="obd")
    p1 = init_project(settings, "demo", "pilot", session=S1, clock=clock)
    p2 = open_project(settings, "demo", session=S2, clock=clock)
    ids = create_tasks(p1, p1.system_actor(), [TaskSpec("demo", i) for i in range(5)]).written
    a, b = agent_on(p1), agent_on(p2)
    t1 = claim_next(p1, a, "demo"); t2 = claim_next(p2, b, "demo")
    complete_task(p1, a, t1.task_id); release_task(p2, b, t2.task_id, "context limit")
    clock.advance(timedelta(minutes=1)); claim_next(p2, b, "demo")
    before = p1.index.state_hash()
    shutil.rmtree(p1.paths.dir / ".index")
    out = CliRunner().invoke(app, ["--root", str(tmp_path), "rebuild"], env={"FACTORY_USER": "obd"})
    assert out.stdout.strip() == f"state {before}"
    copy = tmp_path / "elsewhere"; shutil.copytree(tmp_path / "projects", copy / "projects")
    assert open_project(Settings(root=copy, user="obd"), "demo", session=S3, clock=clock).index.rebuild() == before
```

- [ ] **Step 2: Run it** — `uv run pytest tests/test_acceptance_rebuild.py -v` → Expected: PASS (it exercises finished code; if it fails, debug with superpowers:systematic-debugging before changing anything).

- [ ] **Step 3: Register the server for Claude Code** — `.mcp.json`:

```json
{"mcpServers": {"factory": {"command": "uv", "args": ["run", "--project", "platform", "factory", "serve"]}}}
```
Verify: `cd .. && uv run --project platform factory --help` lists `init`, `rebuild`, `status`, `serve`.

- [ ] **Step 4: Run all quality gates**

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests
uv run pytest --cov=factory.services --cov=factory.model --cov-report=term-missing --cov-fail-under=90
```
Expected: ruff clean, `Success: no issues found`, all tests pass, total coverage ≥ 90%.

- [ ] **Step 5: Update `CLAUDE.md`** — Status line: `planning complete for slice 1; sub-plan 1 (platform core) implemented — see docs/plans/2026-10-31-platform-core.md.`

- [ ] **Step 6: Commit** — `git commit -m "test: rebuild-determinism acceptance; register MCP server"`

---

## Self-review notes

- **Spec coverage (plan-1 scope):** event envelope/writer/reader/validation (§4.1–4.2) → Tasks 3–4; blobs (§4.3) → Task 2; index, projector-only writes, deterministic rebuild, no migrations (§4.4) → Task 5; task queue with 30-min lease (§8) → Task 7; IDs (§3, events/sessions/`tsk_`) → Task 1; MCP conventions (§7: names, structured errors, partial batch success, pagination, actor context, session from process) → Tasks 7–8; CLI `init`/`rebuild`/`status`/`serve` (§9) → Task 9; quality gates (§10) → Task 10; R-04 model + skill + `input_blob` on agent events → Task 3. Deferred by the approved split: `trace`, `check`, `report` CLI commands (plan 5); `*_next` tools that create tasks (plan 4).
- **Decision #3** (SQLite via SQLAlchemy) honoured with SQLAlchemy Core; no ORM, no migrations.
- **Known limitation, recorded for later:** `sync` rebuilds whenever events from another session sort before the last applied one; with frequent `git pull`s this costs a full rebuild, acceptable at ≤ 300 records (slice-1 scale).
