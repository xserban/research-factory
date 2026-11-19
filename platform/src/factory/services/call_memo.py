"""A within-call memo for the expensive read-only derivations that rule code recomputes.

Invariants: a memo exists only between `entering` and its exit, so nothing is ever cached across
calls (the index may change between them); outside a scope a `memoised` function runs normally.
Each hit hands back a copy of the container (lists, dicts, sets shallowly; models deeply), so a
caller that mutates its result cannot corrupt another caller's. The scope assumes the project does
not change while it is open, which holds for read-only checks; a call that does write (a service
under `exclusive()`) is safe too, because `Project.record` calls `invalidate`, which drops every
entry: a read after the write recomputes.

The rule for write paths: the outermost `index.exclusive()` hold drops the memo as soon as it has
the lock and has synced (`Index` `on_write_lock`), since the wait may have lasted minutes and
another process may have changed the project meanwhile. Every decision made under the lock
therefore reads fresh values; only reads made before the lock are discarded.
"""

from __future__ import annotations

import copy
import functools
import inspect
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")

_active: ContextVar[dict[tuple[Any, ...], tuple[Any, Any]] | None] = ContextVar(
    "call_memo", default=None
)


@contextmanager
def entering() -> Iterator[None]:
    """Open a memo scope; a scope already open (a nested call) is reused, not replaced."""
    if _active.get() is not None:
        yield
        return
    token = _active.set({})
    try:
        yield
    finally:
        _active.reset(token)


def invalidate() -> None:
    """Drop every entry of the open scope (none: nothing). Called after events are appended."""
    memo = _active.get()
    if memo is not None:
        memo.clear()


def _fresh(value: Any) -> Any:
    if isinstance(value, (list, dict, set)):
        return copy.copy(value)
    if hasattr(value, "model_copy"):
        return value.model_copy(deep=True)
    return value


def memoised(fn: Callable[P, R]) -> Callable[P, R]:
    """Memoise `fn(project, ...)` within the open scope, keyed by project identity and arguments.
    Arguments after the project must be hashable.
    The undecorated function is `__wrapped__`, which tests may patch to count real computations."""

    signature = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        memo = _active.get()
        if memo is None:
            return wrapper.__wrapped__(*args, **kwargs)
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()  # f(p) and f(p, stage=default) share one entry
        rest = tuple(list(bound.arguments.items())[1:])
        key = (fn.__qualname__, id(args[0]), rest)
        if key not in memo:
            # The project is kept in the entry so its id cannot be reused within the scope.
            memo[key] = (args[0], wrapper.__wrapped__(*args, **kwargs))
        result: R = _fresh(memo[key][1])
        return result

    return wrapper
