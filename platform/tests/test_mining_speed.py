"""The call-scoped speed-ups of the mining calls: the read scope of the event log, the typed read,
the clean-hold sync of the index and the memo drop on a write. Each has an invalidation rule."""

from pathlib import Path

from factory.clock import SystemClock
from factory.config import Settings
from factory.events.reader import cached_reads, read_all, read_typed
from factory.model.identity import IdGenerator
from factory.services import call_memo
from factory.services.project import init_project
from factory.services.tasks import TaskSpec, create_tasks


def _project(tmp_path: Path):  # type: ignore[no-untyped-def]
    clock = SystemClock()
    settings = Settings(root=tmp_path, user="obd")
    return init_project(settings, "demo", "pilot", session=IdGenerator(clock).ulid(), clock=clock)


def _ids(events) -> list[str]:  # type: ignore[no-untyped-def]
    return [e.id for e in events]


def test_cached_read_equals_plain_read_and_sees_appends(tmp_path: Path) -> None:
    project = _project(tmp_path)
    create_tasks(project, project.human_actor(), [TaskSpec("k", {"i": 1})])
    plain = read_all(project.paths.events_dir, project.catalog)
    with cached_reads():
        first = read_all(project.paths.events_dir, project.catalog)
        assert _ids(first) == _ids(plain)
        create_tasks(project, project.human_actor(), [TaskSpec("k", {"i": 2})])
        second = read_all(project.paths.events_dir, project.catalog)
        assert _ids(second) == _ids(read_all(project.paths.events_dir, project.catalog))
        assert len(second) > len(first)
        second.clear()  # a caller's list is its own
        assert len(read_all(project.paths.events_dir, project.catalog)) > len(first)


def test_typed_read_is_the_type_filter_of_the_full_read(tmp_path: Path) -> None:
    project = _project(tmp_path)
    create_tasks(project, project.human_actor(), [TaskSpec("k", {"i": 1}), TaskSpec("k", {"i": 2})])
    wanted = {"task.created"}
    expected = [
        e.id for e in read_all(project.paths.events_dir, project.catalog) if e.type in wanted
    ]
    assert expected
    assert _ids(read_typed(project.paths.events_dir, project.catalog, wanted)) == expected
    with cached_reads():
        assert _ids(read_typed(project.paths.events_dir, project.catalog, wanted)) == expected
        create_tasks(project, project.human_actor(), [TaskSpec("k", {"i": 3})])
        again = _ids(read_typed(project.paths.events_dir, project.catalog, wanted))
    assert len(again) == len(expected) + 1


def test_sync_after_an_append_in_a_hold_reads_it(tmp_path: Path) -> None:
    project = _project(tmp_path)
    with project.index.exclusive():
        project.index.sync()
        assert project.index.sync().applied == 0  # clean: nothing to read
        create_tasks(project, project.human_actor(), [TaskSpec("k", {"i": 1})])
        with project.index.connect() as conn:
            rows = conn.exec_driver_sql("SELECT COUNT(*) FROM tasks").scalar()
        assert rows == 1


def test_a_write_drops_the_memo_of_the_open_scope(tmp_path: Path) -> None:
    project = _project(tmp_path)
    calls: list[int] = []

    @call_memo.memoised
    def probe(proj) -> int:  # type: ignore[no-untyped-def]
        calls.append(1)
        return len(calls)

    with call_memo.entering():
        assert probe(project) == probe(project) == 1
        create_tasks(project, project.human_actor(), [TaskSpec("k", {"i": 1})])
        assert probe(project) == 2


def test_a_lock_taken_after_a_memoised_read_drops_the_memo(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Another process may change the project while this call waits for the write lock; a decision
    made under the lock must not use a value memoised before it."""
    from factory.services import context

    project = _project(tmp_path)

    @call_memo.memoised
    def probe(proj) -> int:  # type: ignore[no-untyped-def]
        return len(
            [e for e in read_all(proj.paths.events_dir, proj.catalog) if e.type == "task.created"]
        )

    with call_memo.entering():
        before = probe(project)
        # Another process writes: its `invalidate` never reaches this call's memo.
        with monkeypatch.context() as patch:
            patch.setattr(context, "invalidate", lambda: None)
            patch.setattr(project.index, "_on_write_lock", None)
            create_tasks(project, project.human_actor(), [TaskSpec("k", {"i": 1})])
        assert project.index._on_write_lock is not None
        assert probe(project) == before  # the stale value, as the memo promises within a scope
        with project.index.exclusive():
            assert probe(project) == before + 1


def test_lab_sync_after_an_append_in_a_hold_reads_it(tmp_path: Path) -> None:
    from factory.services.lab import init_lab, register_user

    clock = SystemClock()
    lab = init_lab(
        Settings(root=tmp_path, user="obd"), session=IdGenerator(clock).ulid(), clock=clock
    )
    with lab.index.exclusive():
        lab.index.sync()
        assert lab.index.sync().applied == 0  # clean: nothing to read
        register_user(lab, lab.human_actor(), "obd", "Obd", None, ["admin"])  # type: ignore[list-item]
        with lab.index.connect() as conn:
            assert conn.exec_driver_sql("SELECT COUNT(*) FROM users").scalar() == 1


def test_a_torn_tail_truncated_and_refilled_to_the_same_size_is_read(tmp_path: Path) -> None:
    project = _project(tmp_path)
    create_tasks(project, project.human_actor(), [TaskSpec("k", {"i": 1})])
    files = sorted(project.paths.events_dir.rglob("*.jsonl"))
    sizes = {f: f.stat().st_size for f in files}
    create_tasks(project, project.human_actor(), [TaskSpec("k", {"i": 2})])
    grown = [f for f in files if f.stat().st_size != sizes[f]]
    assert len(grown) == 1
    path = grown[0]
    full = path.read_bytes()
    head, added = full[: sizes[path]], full[sizes[path] :]
    path.write_bytes(head + b"x" * len(added))  # a failed write: unterminated, as long as `added`
    with cached_reads():
        torn = _ids(read_all(project.paths.events_dir, project.catalog))
        path.write_bytes(full)  # the writer truncated the tail, a later append restored the size
        assert path.stat().st_size == len(head) + len(added)
        healed = _ids(read_all(project.paths.events_dir, project.catalog))
    assert len(healed) == len(torn) + 1


def test_no_service_mutates_a_shared_event_payload() -> None:
    """Cached reads share frozen Events whose `payload` dict is mutable: nothing may write to it."""
    import ast

    root = Path(__file__).resolve().parents[1] / "src" / "factory"
    mutators = {"update", "pop", "popitem", "setdefault", "clear", "append", "extend", "remove"}

    def on_payload(node: ast.AST) -> bool:
        while isinstance(node, (ast.Subscript, ast.Attribute, ast.Call)):
            if isinstance(node, ast.Attribute) and node.attr == "payload":
                return True
            node = node.func if isinstance(node, ast.Call) else node.value
        return False

    found: list[str] = []
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            targets: list[ast.AST] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            elif isinstance(node, ast.Delete):
                targets = list(node.targets)
            for target in targets:
                if isinstance(target, ast.Subscript) and on_payload(target):
                    found.append(f"{path.name}:{node.lineno}")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in mutators
                and isinstance(node.func.value, (ast.Attribute, ast.Subscript))
                and on_payload(node.func.value)
            ):
                found.append(f"{path.name}:{node.lineno}")
    assert not found, found
