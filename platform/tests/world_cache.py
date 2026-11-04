"""Build an expensive test world once per process, then restore it by copying files.

`@snapshot_world` wraps a builder whose first argument is a `Project`. The first call with a given
key runs the builder and snapshots the whole factory root (`settings.root`) together with the
in-memory state a later call could observe: the fixed clock, the project's id generator, the
`http_log` of the conftest `mock_sources` fixture, and the return value. A later call with the same
key restores that snapshot into its own root instead of building again, so every test still gets a
private, independent copy (tests stay isolated and order-insensitive).

The key is conservative. It covers the builder, every argument (models by value, the conftest
`mock_sources` factory by kind, plain functions by code and by the immutable values they capture),
and the state the builder starts from: the project's event log with event ids removed, the clock
reading, the settings, and the bytes of every file under the root outside the project directory.
Anything it cannot key safely (an unknown callable, a function capturing a mutable value, an object
without a value form, a non-fixed clock, a world that stores absolute paths) bypasses the cache and
builds as before. Set `FACTORY_TEST_NO_WORLD_CACHE=1` to disable the cache entirely.

Invariant: a restored world is byte-identical to the template the builder produced in the same
process, event ids included; so tests sharing a key see one random draw of ids per process rather
than one each.
"""

import atexit
import copy
import functools
import hashlib
import os
import shutil
import tempfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from types import CodeType, FunctionType
from typing import Any, ParamSpec, TypeVar

from pydantic import BaseModel

from factory.clock import FixedClock
from factory.events.reader import read_all
from factory.index.default import default_projection
from factory.index.index import Index
from factory.services.context import Project

P = ParamSpec("P")
R = TypeVar("R")

# Callables that are safe to key by name: factories whose behaviour depends only on the arguments
# a builder passes them. `mock_sources` records requests in `http_log`, which is replayed.
_KEYED_CALLABLES = frozenset({"mock_sources.<locals>.make", "fake_sources.<locals>.make"})


@dataclass(frozen=True)
class _Snapshot:
    root: Path
    now: datetime
    last_id: int | None
    http_log: tuple[Any, ...]
    value: Any


_SNAPSHOTS: dict[str, _Snapshot | None] = {}
# Outcome counts per builder ("hit", "miss", "bypass: <reason>"), for checking the cache works.
STATS: Counter[tuple[str, str]] = Counter()
_STORE: list[Path] = []


def _store() -> Path:
    if not _STORE:
        path = Path(tempfile.mkdtemp(prefix="factory-worlds-"))
        atexit.register(shutil.rmtree, path, True)
        _STORE.append(path)
    return _STORE[0]


class _Unkeyable(Exception):
    """An argument the cache cannot key by value; the call bypasses the cache."""


def _function_key(func: FunctionType) -> str:
    """A plain function by its code and the values it closes over.

    Two functions with the same key compute the same thing: same source position, bytecode,
    constants, defaults and captured values. Captured values must be immutable (a captured list
    could be a side channel the test inspects), so a function capturing one is unkeyable.
    """
    code = func.__code__
    consts = [c for c in code.co_consts if not isinstance(c, CodeType)]
    cells = []
    for name, cell in zip(code.co_freevars, func.__closure__ or (), strict=True):
        captured = cell.cell_contents
        if isinstance(captured, list | dict | set) or (
            not isinstance(captured, FunctionType | BaseModel | Enum)
            and callable(captured)
            and not isinstance(captured, type)
        ):
            raise _Unkeyable(f"{func.__qualname__} captures {name}")
        cells.append(f"{name}={_arg_key(captured)}")
    defaults = _arg_key(tuple(func.__defaults__ or ()))
    digest = hashlib.sha256(code.co_code + repr(consts).encode()).hexdigest()
    return (
        f"function:{func.__module__}.{func.__qualname__}@{code.co_firstlineno}:{digest}"
        f"({';'.join(cells)}|{defaults})"
    )


def _arg_key(value: Any) -> str:
    if isinstance(value, BaseModel):
        return f"{type(value).__qualname__}:{value.model_dump_json()}"
    if isinstance(value, Enum):
        return f"{type(value).__qualname__}.{value.name}"
    if isinstance(value, type):
        return f"type:{value.__module__}.{value.__qualname__}"
    if callable(value):
        name = getattr(value, "__qualname__", "")
        if name in _KEYED_CALLABLES:
            return f"callable:{name}"
        if isinstance(value, FunctionType):
            return _function_key(value)
        raise _Unkeyable(name)
    if isinstance(value, set | frozenset):
        return f"{type(value).__name__}[" + ",".join(sorted(_arg_key(v) for v in value)) + "]"
    if isinstance(value, list | tuple):
        return f"{type(value).__name__}[" + ",".join(_arg_key(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(f"{k!r}:{_arg_key(v)}" for k, v in value.items()) + "}"
    if value is None or isinstance(value, str | int | float | bool | bytes):
        return repr(value)
    raise _Unkeyable(type(value).__qualname__)


def _tree_digest(root: Path, skip: Path) -> str:
    digest = hashlib.sha256()
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if path == skip or skip in path.parents or not path.is_file():
                continue
            digest.update(path.relative_to(root).as_posix().encode() + b"\0")
            digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def _state_key(project: Project) -> str:
    """The project's starting state, without the random parts (event ids)."""
    if not isinstance(project.clock, FixedClock):
        raise _Unkeyable("clock")
    settings = project.settings
    events = [
        e.model_dump_json(exclude={"id"})
        for e in read_all(project.paths.events_dir, project.catalog)
    ]
    parts = [
        project.paths.slug,
        project.session,
        settings.model_dump_json(exclude={"root"}),
        project.clock.now().isoformat(),
        "\n".join(events),
        _tree_digest(settings.root, project.paths.dir),
    ]
    if settings.plugin_override is not None:
        parts.append(_tree_digest(settings.plugin_override, project.paths.dir))
    return "\x1e".join(parts)


def _http_log(args: tuple[Any, ...]) -> list[Any] | None:
    """The `http_log` list a `mock_sources` factory among `args` appends to, if any."""
    for arg in args:
        code = getattr(arg, "__code__", None)
        closure = getattr(arg, "__closure__", None)
        if code is None or closure is None:
            continue
        for name, cell in zip(code.co_freevars, closure, strict=True):
            if name == "http_log" and isinstance(cell.cell_contents, list):
                log: list[Any] = cell.cell_contents
                return log
    return None


def _mentions_root(tree: Path, roots: set[bytes]) -> bool:
    for path in tree.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            if any(root in data for root in roots):
                return True
    return False


def _clear(root: Path) -> None:
    for child in root.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def _reopen_index(project: Project) -> None:
    """Point the project at the restored database; the old engine held the replaced file."""
    old = project.index
    project.index = Index(
        project.paths.index_path, project.paths.events_dir, project.catalog, default_projection()
    )
    old._engine.dispose()


def snapshot_world(build: Callable[P, R]) -> Callable[P, R]:
    """Cache `build` (first argument: the `Project`) as a restorable on-disk snapshot."""
    name = f"{build.__module__}.{build.__qualname__}"

    @functools.wraps(build)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        project = args[0] if args else None
        if os.environ.get("FACTORY_TEST_NO_WORLD_CACHE") or not isinstance(project, Project):
            return build(*args, **kwargs)
        try:
            key_text = "\x1f".join(
                [
                    name,
                    _arg_key(list(args[1:])),
                    _arg_key(dict(sorted(kwargs.items()))),
                    _state_key(project),
                ]
            )
        except _Unkeyable as exc:
            STATS[name, f"bypass: {exc}"] += 1
            return build(*args, **kwargs)
        key = hashlib.sha256(key_text.encode()).hexdigest()
        clock = project.clock
        assert isinstance(clock, FixedClock)
        root = project.settings.root
        log = _http_log(tuple(args) + tuple(kwargs.values()))

        if key in _SNAPSHOTS:
            snap = _SNAPSHOTS[key]
            if snap is None:  # known not to be cacheable
                STATS[name, "bypass: absolute paths"] += 1
                return build(*args, **kwargs)
            STATS[name, "hit"] += 1
            _clear(root)
            shutil.copytree(snap.root, root, dirs_exist_ok=True, symlinks=True)
            _reopen_index(project)
            clock.advance(snap.now - clock.now())
            project.ids._last = snap.last_id
            if log is not None:
                log.extend(snap.http_log)
            result: R = copy.deepcopy(snap.value)
            return result

        STATS[name, "miss"] += 1
        log_start = len(log) if log is not None else 0
        value = build(*args, **kwargs)
        target = _store() / key
        shutil.copytree(root, target, symlinks=True)
        roots = {str(root).encode(), str(root.resolve()).encode()}
        if _mentions_root(target, roots):
            shutil.rmtree(target)
            _SNAPSHOTS[key] = None
            return value
        _SNAPSHOTS[key] = _Snapshot(
            root=target,
            now=clock.now(),
            last_id=project.ids._last,
            http_log=tuple(log[log_start:]) if log is not None else (),
            value=copy.deepcopy(value),
        )
        return value

    return wrapper
