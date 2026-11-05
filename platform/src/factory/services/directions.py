"""The failed-directions registry: closing a direction by hand and searching the rows (slice 6, plan
XP-B task 6; spec ruling 27; R-52, R-124).

Invariants:
- Rows are a projection (`index.directions`): a refuted, inconclusive or abandoned hypothesis, a
  discarded lead, a baseline that did not reproduce, and a direction a human closed. Each states a
  reason and the conditions it failed under. A row is never removed; a later success of a similar
  direction is a new artefact and leaves the old row ("failed here", not "impossible").
- Closing a direction is a human act (`actor`: `human-only`); every key must name something the
  project holds, so a row is searchable by what it is about.
- `summary` is a fixed template of ids, names and counts: no lead text, rationale, statement or
  document text.
- On an agent path (`agent=True`) a row of a baseline that reproduces on the confirmatory split is
  left out until the design is unlocked, and nothing else is withheld (decision 94). `prior` is
  stored in events agents read, so it always takes the agent reading.
- `prior_from_registry` fills `services.leads.PRIOR_SOURCES` and `direction_exists` fills
  `DIRECTION_RESOLVERS` at import; `services.leads` imports this module where it reads either list.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Sequence

from pydantic import ValidationError
from sqlalchemy import bindparam, text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.index.directions import key_known
from factory.model.base import StrictModel
from factory.model.directions import (
    DIR_ID_RE,
    Conditions,
    DirectionClosed,
    DirectionReason,
)
from factory.services import leads as lead_service
from factory.services.context import Project
from factory.services.extraction_agreement import final_rows
from factory.services.ideas import resolve_idea
from factory.services.xrun_accounting import hidden_baselines

MAX_LIMIT = 200


class RegistryRow(StrictModel):
    direction_id: str
    source_kind: str
    reason: str
    conditions: Conditions
    keys: tuple[str, ...]
    summary: str
    event_id: str
    text: str | None = None
    """What a human typed when closing a direction."""


class RegistryPage(StrictModel):
    rows: list[RegistryRow]
    total: int
    next: str | None


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def _summary(source_kind: str, direction_id: str, reason: str, c: Conditions) -> str:
    subject = {
        "hypothesis": f"Hypothesis {direction_id}",
        "lead": f"Lead {direction_id}",
        "baseline": f"Baseline {direction_id.split(':')[-1]} of experiment "
        f"{direction_id.split(':')[0]}",
        "closed": f"Direction {direction_id}",
    }[source_kind]
    verb = {
        "hypothesis": f"failed here: {reason}",
        "lead": "discarded",
        "baseline": "did not reproduce",
        "closed": f"closed by the researcher: {reason}",
    }[source_kind]
    parts: list[str] = []
    if c.e_version:
        parts.append(f"design {c.e_version}")
    if c.datasets:
        parts.append("datasets " + ", ".join(c.datasets))
    if c.gpu_hours_used:
        parts.append(f"{c.gpu_hours_used} GPU-hours used")
    if c.models:
        parts.append("models " + ", ".join(c.models))
    if c.code_commit:
        parts.append(f"commit {c.code_commit}")
    where = f" ({'; '.join(parts)})" if parts else ""
    return f"{subject} {verb}{where}."


def _row(project: Project, r: object) -> RegistryRow:
    m = r._mapping  # type: ignore[attr-defined]
    conditions = Conditions.model_validate(json.loads(str(m["conditions_json"])))
    with project.index.connect() as conn:
        keys = tuple(
            str(k)
            for k in conn.execute(
                text("SELECT key FROM direction_keys WHERE direction_id = :d ORDER BY key"),
                {"d": m["direction_id"]},
            ).scalars()
        )
    return RegistryRow(
        direction_id=str(m["direction_id"]),
        source_kind=str(m["source_kind"]),
        reason=str(m["reason"]),
        conditions=conditions,
        keys=keys,
        summary=_summary(
            str(m["source_kind"]),
            str(m["direction_id"]),
            str(m["reason"]),
            conditions,
        ),
        event_id=str(m["event_id"]),
        text=None if m["text"] is None else str(m["text"]),
    )


def _expanded(project: Project, keys: Collection[str]) -> list[str]:
    out = set(keys)
    for key in keys:
        if key.startswith("ida_"):
            out.add(resolve_idea(project, key))
    return sorted(out)


def registry_query(
    project: Project,
    keys: Collection[str] = (),
    *,
    reasons: Collection[str] | None = None,
    limit: int = 50,
    after: str | None = None,
    agent: bool = False,
) -> RegistryPage:
    """Rows that share at least one of `keys` (all rows when none is given), optionally of the
    given reasons, in id order from just after `after`; the total is of the whole match. A reason
    outside `DirectionReason` is refused (`reasons`: `unknown`), a limit outside 1 to 200 too."""
    if not 1 <= limit <= MAX_LIMIT:
        raise _refuse("limit", f"between 1 and {MAX_LIMIT}")
    wanted = {r for r in (reasons or ())}
    if not wanted <= {r.value for r in DirectionReason}:
        raise _refuse("reasons", "unknown")
    project.index.sync()
    where = ["1 = 1"]
    params: dict[str, object] = {}
    if keys:
        where.append(
            "d.direction_id IN (SELECT direction_id FROM direction_keys WHERE key IN :keys)"
        )
        params["keys"] = _expanded(project, keys)
    if wanted:
        where.append("d.reason IN :reasons")
        params["reasons"] = sorted(wanted)
    hidden = sorted(f"{e}:{k}" for e, k in hidden_baselines(project)) if agent else []
    if hidden:
        where.append("d.direction_id NOT IN :hidden")
        params["hidden"] = hidden
    clause = " AND ".join(where)
    with project.index.connect() as conn:

        def run(sql: str, extra: dict[str, object]) -> object:
            statement = text(sql)
            for name in ("keys", "reasons", "hidden"):
                if name in params:
                    statement = statement.bindparams(bindparam(name, expanding=True))
            return conn.execute(statement, {**params, **extra})

        total = run(f"SELECT COUNT(*) FROM directions d WHERE {clause}", {}).scalar_one()  # type: ignore[attr-defined]
        rows = run(  # type: ignore[attr-defined]
            f"SELECT d.* FROM directions d WHERE {clause} AND d.direction_id > :after "
            "ORDER BY d.direction_id LIMIT :limit",
            {"after": after or "", "limit": limit + 1},
        ).all()
    page = rows[:limit]
    return RegistryPage(
        rows=[_row(project, r) for r in page],
        total=int(total),
        next=str(page[-1]._mapping["direction_id"]) if len(rows) > limit else None,
    )


# --- Closing -------------------------------------------------------------------------------


def key_resolves(project: Project, key: str) -> bool:
    """Whether a key names something the project holds (`index.directions.key_known`); an evidence
    row must be a final one here, where the fold can only ask that it was extracted."""
    if key.startswith("rk_"):
        return any(r.row_key == key for r in final_rows(project))
    with project.index.connect() as conn:
        return key_known(conn, key)


def close_direction(
    project: Project,
    actor: Actor,
    text_: str,
    reason: DirectionReason,
    conditions: Conditions,
    keys: Sequence[str],
) -> str:
    """Close a direction that never became a hypothesis (a human act) and return its `dir_` id.
    Refused, with nothing written: a non-human actor (`actor`: `human-only`); a blank or long text,
    no key or more than twenty (`text`, `keys`); a key that names nothing the project holds
    (`keys.<i>`: `unknown`)."""
    if actor.kind != "human":
        raise _refuse("actor", "human-only")
    with project.index.exclusive():
        project.index.sync()
        direction_id = project.ids.new("dir")
        try:
            payload = DirectionClosed(
                direction_id=direction_id,
                text=text_.strip(),
                reason=reason,
                conditions=conditions,
                keys=tuple(dict.fromkeys(keys)),
            )
        except ValidationError as exc:
            raise FactoryValidationError(
                [
                    ValidationIssue(".".join(str(p) for p in err["loc"]), str(err["msg"]))
                    for err in exc.errors()
                ]
            ) from exc
        issues = [
            ValidationIssue(f"keys.{i}", "unknown")
            for i, key in enumerate(payload.keys)
            if not key_resolves(project, key)
        ]
        if issues:
            raise FactoryValidationError(issues)
        event = project.events.make("direction.closed", payload, actor, refs=[direction_id])
        project.record([event])
    return direction_id


# --- Hooks ----------------------------------------------------------------------------------


def prior_from_registry(project: Project, keys: Collection[str]) -> list[str]:
    """Ids of the registry rows sharing at least one key: the provider of
    `services.leads.PRIOR_SOURCES`."""
    if not keys:
        return []
    return [r.direction_id for r in registry_query(project, keys, limit=MAX_LIMIT, agent=True).rows]


def direction_exists(project: Project, ref: str) -> bool:
    """Whether `ref` is a closed direction: the resolver of `DIRECTION_RESOLVERS` (a `direction`
    trigger names a `dir_` id)."""
    import re

    if re.fullmatch(DIR_ID_RE, ref) is None:
        return False
    project.index.sync()
    with project.index.connect() as conn:
        return (
            conn.execute(
                text("SELECT 1 FROM directions WHERE direction_id = :d AND source_kind = 'closed'"),
                {"d": ref},
            ).first()
            is not None
        )


if prior_from_registry not in lead_service.PRIOR_SOURCES:
    lead_service.PRIOR_SOURCES.append(prior_from_registry)
if direction_exists not in lead_service.DIRECTION_RESOLVERS:
    lead_service.DIRECTION_RESOLVERS.append(direction_exists)
