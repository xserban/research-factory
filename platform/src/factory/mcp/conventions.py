"""Shared conventions for every MCP tool: result shape, pagination, actors, error mapping."""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import JsonValue, ValidationError

from factory.config import Settings
from factory.errors import FactoryValidationError, ProjectNotFoundError, ValidationIssue
from factory.events.envelope import Actor
from factory.services.skills import skill_ref

PAGE_LIMIT = 50

T = TypeVar("T")

_ACTOR_FIELDS = {"id": "role", "model": "model", "skill": "skill"}


def ok(data: JsonValue) -> dict[str, JsonValue]:
    return {"ok": True, "data": data}


def fail(issues: Sequence[ValidationIssue]) -> dict[str, JsonValue]:
    errors: list[JsonValue] = [{"field": i.field, "reason": i.reason} for i in issues]
    return {"ok": False, "errors": errors}


@dataclass(frozen=True)
class Page(Generic[T]):
    items: list[T]
    next_cursor: str | None


def paginate(items: Sequence[T], cursor: str | None, limit: int = PAGE_LIMIT) -> Page[T]:
    """Return one page. The cursor is the decimal offset of the next item, as a string."""
    start = 0
    if cursor is not None:
        if re.fullmatch(r"[0-9]+", cursor) is None:
            raise FactoryValidationError([ValidationIssue("cursor", "must be a decimal offset")])
        start = int(cursor)
    size = min(max(limit, 1), PAGE_LIMIT)
    end = start + size
    next_cursor = str(end) if end < len(items) else None
    return Page(items=list(items[start:end]), next_cursor=next_cursor)


def make_agent_actor(settings: Settings, session: str, role: str, model: str, skill: str) -> Actor:
    """An agent's actor, with its skill resolved to the reference of the installed file."""
    if not model:
        raise FactoryValidationError([ValidationIssue("model", "must not be empty")])
    ref = skill_ref(settings, skill)
    try:
        return Actor(
            kind="agent",
            id=role,
            user=settings.user,
            session=session,
            model=model,
            skill=ref,
        )
    except ValidationError as exc:
        issues = [
            ValidationIssue(
                _actor_field(err["loc"]),
                str(err["msg"]),
            )
            for err in exc.errors()
        ]
        raise FactoryValidationError(issues) from exc


def _actor_field(loc: tuple[int | str, ...]) -> str:
    if not loc:
        return "actor"
    name = str(loc[0])
    return _ACTOR_FIELDS.get(name, name)


def guarded(fn: Callable[[], JsonValue]) -> dict[str, JsonValue]:
    """Run a tool body and turn expected domain errors into a structured `fail` result."""
    try:
        return ok(fn())
    except FactoryValidationError as exc:
        return fail(exc.issues)
    except ProjectNotFoundError:
        return fail([ValidationIssue("project", "unknown project")])
