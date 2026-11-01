"""Shared conventions for every MCP tool: result shape, pagination, actors, error mapping."""

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel, JsonValue, ValidationError

from factory.config import Settings
from factory.errors import FactoryValidationError, ProjectNotFoundError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.protocol import ProtocolSpec
from factory.model.question import QuestionSpec
from factory.services.skills import skill_ref

PAGE_LIMIT = 50

T = TypeVar("T")
M = TypeVar("M", bound=BaseModel)

_ACTOR_FIELDS = {"id": "role", "model": "model", "skill": "skill"}
_SPEC_FIELDS = frozenset(QuestionSpec.model_fields) | frozenset(ProtocolSpec.model_fields)
WITHHELD = "[withheld]"


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


def parse_input(model: type[M], data: JsonValue, field: str) -> M:
    """Validate one tool argument. Every error names its dotted path below `field`, such as
    `spec.criteria.0.parent`; nothing is written here, so a refusal writes nothing."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise FactoryValidationError(
            [ValidationIssue(_path(field, err["loc"]), str(err["msg"])) for err in exc.errors()]
        ) from exc


def _path(field: str, loc: tuple[int | str, ...]) -> str:
    return ".".join([field, *(str(part) for part in loc)]) if loc else field


def dotted(field: str) -> str:
    """A service's field path in the tool's dotted form: `criteria[0].parent` is
    `criteria.0.parent`."""
    return re.sub(r"\[(\d+)\]", r".\1", field)


def spec_path(field: str) -> str:
    """The dotted form, prefixed with `spec.` when the field belongs to a question or protocol
    spec, so that `criteria[0].parent` is reported as `spec.criteria.0.parent`."""
    head = re.split(r"[.\[]", field, maxsplit=1)[0]
    return f"spec.{dotted(field)}" if head in _SPEC_FIELDS else dotted(field)


def withhold(value: JsonValue, tokens: Iterable[str]) -> JsonValue:
    """`value` with every whole-identifier occurrence of a token replaced in its strings.

    Tokens match case-insensitively and only as whole identifiers, so `10.1000/p2` does not
    match inside `10.1000/p21`. An agent-facing response passes through this with the identifiers
    of every held-out seed (R-20); nothing else is changed.
    """
    cleaned = sorted({token for token in tokens if token}, key=len, reverse=True)
    if not cleaned:
        return value
    pattern = re.compile(
        r"(?<![0-9A-Za-z])(?:" + "|".join(re.escape(t) for t in cleaned) + r")(?![0-9A-Za-z])",
        re.IGNORECASE,
    )
    return _scrub(value, pattern)


def _scrub(value: JsonValue, pattern: re.Pattern[str]) -> JsonValue:
    if isinstance(value, str):
        return pattern.sub(WITHHELD, value)
    if isinstance(value, dict):
        return {key: _scrub(item, pattern) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item, pattern) for item in value]
    return value


def guarded(
    fn: Callable[[], JsonValue], rename: Callable[[str], str] = str
) -> dict[str, JsonValue]:
    """Run a tool body and turn expected domain errors into a structured `fail` result.

    `rename` maps each issue's field to the path the tool reports (`spec_path`, `dotted`)."""
    try:
        return ok(fn())
    except FactoryValidationError as exc:
        return fail([ValidationIssue(rename(i.field), i.reason) for i in exc.issues])
    except ProjectNotFoundError:
        return fail([ValidationIssue("project", "unknown project")])
