"""Event order equals append order (slice 5 ruling 3): IDs are minted under the project write lock.

`Project.writing()` holds the lock, syncs and floors the generator at the last applied event, so a
session with a fresh `IdGenerator` or a slower clock still mints above every event in the log.
"""

import ast
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

import factory
from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import OrderingError
from factory.events.envelope import Actor, Event
from factory.index.index import Index
from factory.model.identity import IdGenerator
from factory.model.question import GoalStated
from factory.services.context import Project, open_project
from factory.services.project import init_project
from factory.services.tasks import TaskSpec, claim_next, create_tasks
from tests.helpers import S2, T0


def goal(project: Project) -> Event:
    return project.events.make("question.goal_stated", GoalStated(text="g"), project.human_actor())


def test_floor_makes_next_id_greater() -> None:
    ids = IdGenerator(FixedClock(T0 - timedelta(days=20000)))
    ids.floor("01KZZZZZZZZZZZZZZZZZZZZZZZ")
    assert ids.ulid() > "01KZZZZZZZZZZZZZZZZZZZZZZZ"


def test_floor_never_lowers_the_generator() -> None:
    ids = IdGenerator(FixedClock(T0))
    first = ids.ulid()
    ids.floor("00000000000000000000000000")
    assert ids.ulid() > first


def test_floor_refuses_what_is_not_a_ulid() -> None:
    with pytest.raises(ValueError):
        IdGenerator(FixedClock(T0)).floor("ev_not-a-ulid")


def test_writing_floors_ids_across_processes(
    project: Project, settings: Settings, clock: FixedClock
) -> None:
    behind = open_project(settings, "demo", session=S2, clock=FixedClock(T0 - timedelta(seconds=5)))
    with project.writing():
        last = goal(project)
        project.record([last])
    with behind.writing():
        minted = goal(behind)
    assert minted.id > last.id


def test_the_index_lock_floors_like_writing(
    project: Project, settings: Settings, clock: FixedClock
) -> None:
    """The services take `index.exclusive()`: it is the same context as `writing()`."""
    behind = open_project(settings, "demo", session=S2, clock=FixedClock(T0 - timedelta(seconds=5)))
    with project.index.exclusive():
        last = goal(project)
        project.record([last])
    with behind.index.exclusive():
        minted = goal(behind)
    assert minted.id > last.id


def test_writing_sees_an_event_another_session_appended(
    project: Project, settings: Settings
) -> None:
    """The floor comes from the log, not from an index synced earlier."""
    behind = open_project(settings, "demo", session=S2, clock=FixedClock(T0 - timedelta(seconds=5)))
    behind.index.sync()
    last = goal(project)
    project.writer.append([last])  # on disk, not yet folded by anyone
    with behind.writing():
        assert goal(behind).id > last.id


def test_writing_is_reentrant(project: Project) -> None:
    with project.writing(), project.writing():
        project.record([goal(project)])


def test_a_new_project_can_be_written_inside_writing(settings: Settings) -> None:
    project = init_project(settings, "fresh", "pilot", session=S2, clock=FixedClock(T0))
    with project.writing():
        assert project.index.last_event_id() is not None


# --- Task 2: mint inside `writing()`; the ordering guard ---


@pytest.fixture
def hosted(project: Project, monkeypatch: pytest.MonkeyPatch) -> Project:
    monkeypatch.setattr(Project, "is_hosted", lambda self: True)
    return project


def count_events(project: Project) -> int:
    project.index.sync()
    with project.index.connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM events")).scalar_one())


def test_record_refuses_out_of_order_on_hosted(hosted: Project) -> None:
    before = count_events(hosted)
    early = goal(hosted)
    with hosted.writing():
        hosted.record([goal(hosted)])
    with pytest.raises(OrderingError):
        hosted.record([early])
    assert count_events(hosted) == before + 1


def test_the_guard_reads_the_lowest_id_of_a_batch(hosted: Project) -> None:
    early = goal(hosted)
    with hosted.writing():
        hosted.record([goal(hosted)])
        with pytest.raises(OrderingError):
            hosted.record([goal(hosted), early])


def test_an_unhosted_project_has_no_ordering_requirement(project: Project) -> None:
    early = goal(project)
    project.record([goal(project)])
    project.record([early])  # today's behaviour: the fold rebuilds and stays correct


def event_file(project: Project, actor: Actor) -> Path:
    return project.paths.events_dir / actor.id / f"{actor.session}.jsonl"


def test_a_batch_is_appended_in_id_order_on_hosted(hosted: Project) -> None:
    with hosted.writing():
        first, second = goal(hosted), goal(hosted)
        hosted.record([second, first])
    lines = event_file(hosted, hosted.human_actor()).read_bytes().splitlines()
    ids = [Event.from_line(line).id for line in lines]
    assert ids == sorted(ids)


def test_record_holds_the_lock_from_append_to_sync(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No other session can slip an event between the guard, the append and the fold."""
    held: list[bool] = []
    append = project.writer.append

    def spy(events: Sequence[Event]) -> None:
        held.append(project.index._holding)
        append(events)

    monkeypatch.setattr(project.writer, "append", spy)
    project.record([goal(project)])
    assert held == [True]


THREADS = 8
CLAIMS = 20


def claim_all(project: Project, actor: Actor) -> list[str]:
    claimed: list[str] = []
    while (task := claim_next(project, actor, "demo")) is not None:
        claimed.append(task.task_id)
    return claimed


def test_concurrent_claims_never_rebuild(
    hosted: Project, settings: Settings, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance 6: N sessions on one project, no rebuild, one holder per task, IDs in order."""
    specs = [TaskSpec("demo", {"n": n}) for n in range(THREADS * CLAIMS)]
    tasks = create_tasks(hosted, hosted.human_actor(), specs).written
    hosted.index.sync()

    builds: list[int] = []
    build = Index._build

    def counted(self: Index) -> int:
        builds.append(1)
        return build(self)

    monkeypatch.setattr(Index, "_build", counted)
    minter = IdGenerator(clock)
    sessions = [minter.ulid() for _ in range(THREADS)]

    def work(session: str) -> list[str]:
        opened = open_project(settings, "demo", session=session, clock=clock)
        return claim_all(opened, opened.human_actor())

    with ThreadPoolExecutor(THREADS) as pool:
        results = list(pool.map(work, sessions))

    assert builds == []
    assert sorted(t for claimed in results for t in claimed) == sorted(tasks)
    hosted.index.sync()
    with hosted.index.connect() as conn:
        claims = conn.execute(
            text("SELECT refs, COUNT(*) FROM events WHERE type = 'task.claimed' GROUP BY refs")
        ).all()
    assert len(claims) == len(tasks) and all(count == 1 for _, count in claims)

    seen: list[str] = []
    for path in hosted.paths.events_dir.rglob("*.jsonl"):
        ids = [Event.from_line(line).id for line in path.read_bytes().splitlines()]
        assert ids == sorted(set(ids))
        seen += ids
    assert hosted.index.last_event_id() == max(seen) and len(seen) == len(set(seen))


# Static pin: the review of the mint sites, kept. A function that mints or records outside a lock
# block passes only if every reference to it sits inside one (directly, or through such a caller).

SRC = Path(factory.__file__).parent
LOCKS = (".exclusive()", ".writing()")
Function = tuple[str, str]  # module, name


@dataclass
class Module:
    name: str
    imported: dict[str, str] = field(default_factory=dict)  # local name -> source module


@dataclass
class Facts:
    unlocked: dict[Function, list[int]] = field(default_factory=dict)
    # (module, name referenced) -> (enclosing function or "", under a lock?)
    references: dict[Function, list[tuple[str, bool]]] = field(default_factory=dict)


class Scan(ast.NodeVisitor):
    def __init__(self, module: Module, facts: Facts) -> None:
        self.module, self.facts = module, facts
        self.function, self.lock = "", 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        outer = self.function, self.lock
        self.function, self.lock = node.name, 0
        self.generic_visit(node)
        self.function, self.lock = outer

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self.module.imported[alias.asname or alias.name] = node.module or ""

    def visit_With(self, node: ast.With) -> None:
        held = any(ast.unparse(i.context_expr).endswith(LOCKS) for i in node.items)
        self.lock += held
        self.generic_visit(node)
        self.lock -= held

    def visit_Call(self, node: ast.Call) -> None:
        callee = ast.unparse(node.func)
        if callee.endswith((".events.make", ".record")) and not self.lock:
            key = self.module.name, self.function
            self.facts.unlocked.setdefault(key, []).append(node.lineno)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        key = self.module.name, node.id
        self.facts.references.setdefault(key, []).append((self.function, self.lock > 0))


def scan_package() -> tuple[dict[str, Module], Facts]:
    modules: dict[str, Module] = {}
    facts = Facts()
    for path in sorted(SRC.rglob("*.py")):
        name = "factory." + ".".join(path.relative_to(SRC).with_suffix("").parts)
        modules[name] = Module(name)
        Scan(modules[name], facts).visit(ast.parse(path.read_text()))
    return modules, facts


def references_to(
    function: Function, modules: dict[str, Module], facts: Facts
) -> list[tuple[str, str, bool]]:
    home, name = function
    found = [
        (module.name, caller, locked)
        for module in modules.values()
        if module.name == home or module.imported.get(name) == home
        for caller, locked in facts.references.get((module.name, name), [])
    ]
    return [r for r in found if (r[0], r[1]) != function]


def unlocked_writes() -> list[str]:
    modules, facts = scan_package()

    def guarded(function: Function, path: tuple[Function, ...]) -> bool:
        if function in path:
            return True
        references = references_to(function, modules, facts)
        return bool(references) and all(
            locked or (bool(caller) and guarded((module, caller), (*path, function)))
            for module, caller, locked in references
        )

    return [
        f"{module}:{line} ({name})"
        for (module, name), lines in sorted(facts.unlocked.items())
        for line in lines
        if module.startswith("factory.services") and not guarded((module, name), ())
    ]


def test_every_mint_and_record_is_under_the_write_lock() -> None:
    assert unlocked_writes() == []
