"""Shared conventions for every MCP tool: result shape, pagination, actors, error mapping."""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel, JsonValue, ValidationError

from factory.config import Settings
from factory.errors import FactoryValidationError, ProjectNotFoundError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.fulltext import ROUTE_ORDER, Route
from factory.model.protocol import ProtocolSpec, ScreeningStage
from factory.model.question import QuestionSpec
from factory.model.screening import Channel
from factory.services.context import Principal
from factory.services.skills import skill_ref
from factory.services.stages import require_pass_stage
from factory.services.withholding import WITHHELD as WITHHELD
from factory.services.withholding import withhold as withhold

PAGE_LIMIT = 50

T = TypeVar("T")
M = TypeVar("M", bound=BaseModel)

_ACTOR_FIELDS = {"id": "role", "model": "model", "skill": "skill"}
_SPEC_FIELDS = frozenset(QuestionSpec.model_fields) | frozenset(ProtocolSpec.model_fields)


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


def make_agent_actor(
    settings: Settings,
    session: str,
    role: str,
    model: str,
    skill: str,
    principal: Principal | None = None,
) -> Actor:
    """An agent's actor, with its skill resolved to the reference of the installed file. It acts
    for `principal`, by default the local user."""
    delegator = principal or Principal.local(settings, Channel.MCP)
    if not model:
        raise FactoryValidationError([ValidationIssue("model", "must not be empty")])
    ref = skill_ref(settings, skill)
    try:
        return Actor(
            kind="agent",
            id=role,
            user=delegator.user,
            session=session,
            model=model,
            skill=ref,
            credential=delegator.credential,
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


def parse_routes(values: Sequence[str] | None, field: str) -> list[Route] | None:
    """Route names as a fetch names them, or None when none were given.

    Each name must be one of the automatic routes (`ROUTE_ORDER`). `researcher-supplied` is refused
    with its own reason, since it is imported, not fetched. Every bad name is reported by its
    position, as `<field>.<index>`.
    """
    if values is None:
        return None
    choices = ", ".join(route.value for route in ROUTE_ORDER)
    parsed: list[Route] = []
    issues: list[ValidationIssue] = []
    for index, value in enumerate(values):
        if value == Route.RESEARCHER.value:
            issues.append(
                ValidationIssue(
                    f"{field}.{index}", "a researcher-supplied route is imported, not fetched"
                )
            )
            continue
        try:
            route = Route(value)
        except ValueError:
            issues.append(ValidationIssue(f"{field}.{index}", f"must be one of: {choices}"))
            continue
        parsed.append(route)
    if issues:
        raise FactoryValidationError(issues)
    return parsed


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


def parse_stage(value: str) -> ScreeningStage:
    """The screening stage named by `value`: `title-abstract` or `full-text`, else an error on
    field `stage` (including `either`, which is a criterion's scope and not a stage of a run)."""
    try:
        stage = ScreeningStage(value)
    except ValueError:
        raise FactoryValidationError(
            [ValidationIssue("stage", "must be title-abstract or full-text")]
        ) from None
    return require_pass_stage(stage)
