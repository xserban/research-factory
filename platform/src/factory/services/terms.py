"""Terms: promoted label keys with a definition, aliases and a classified set of applications
(slice 3d ruling 16, plan Regions-C).

A term is organisation, not evidence: it names a label key (with aliases) so that a region rule
may select by it, and it asserts nothing about any paper. Only a term's stated and confirmed
applications select (R-91).

Invariants:
- Promotion, revision and retirement are human (gate `terms.promote`); an agent proposes only
  labels and merges.
- A key (the name or an alias, folded) belongs to at most one live term.
- A revision is a new version of the term (the event it supersedes is recorded); a retired term
  stays in the log and refuses every rule that names it.
- `refers_to` is navigation only and must name a recorded idea or concept.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Sequence
from typing import Any

from pydantic import ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.engine import Connection

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.labels import (
    TermPromoted,
    TermRetired,
    TermRevised,
    key_problem,
    label_key,
)
from factory.regions.concept_use import concept_exists
from factory.regions.rules import MemberType
from factory.regions.term_use import SELECTABLE, TermApplication, term_row
from factory.regions.term_use import term_applications as _applications
from factory.services.context import Project
from factory.services.gates import gate_issues

PROMOTION_MIN_TARGETS = 3
ORGANISATION = "organisation"


def _refuse(*issues: ValidationIssue) -> FactoryValidationError:
    return FactoryValidationError(list(issues))


class TermView(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    """A term as a reader sees it; `counts` are its live applications by status, and
    `class_` is `organisation` on every row."""

    term_id: str
    name: str
    aliases: tuple[str, ...]
    definition: str
    applies_to: tuple[MemberType, ...]
    refers_to: str | None
    from_keys: tuple[str, ...]
    retired: bool
    version: int
    counts: dict[str, int]
    class_: str = Field(default=ORGANISATION, serialization_alias="class")


# --- Writes ---


def _issues(
    project: Project,
    *,
    term_id: str | None,
    name: str,
    aliases: Sequence[str],
    refers_to: str | None,
    from_keys: Sequence[str],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    keys: dict[str, str] = {}
    for field, value in (("name", name), *((f"aliases[{i}]", a) for i, a in enumerate(aliases))):
        problem = key_problem(value)
        if problem is not None:
            issues.append(ValidationIssue(field, problem))
        else:
            keys[label_key(value)] = field
    with project.index.connect() as conn:
        for key, field in keys.items():
            owner = conn.execute(
                text(
                    "SELECT a.term_id FROM term_aliases a JOIN terms t ON t.term_id = a.term_id "
                    "WHERE a.key = :k AND t.retired = 0 AND a.term_id != :me"
                ),
                {"k": key, "me": term_id or ""},
            ).scalar_one_or_none()
            if owner is not None:
                issues.append(ValidationIssue(field, f"key-taken:{owner}"))
        if refers_to is not None:
            known = (
                conn.execute(
                    text("SELECT 1 FROM ideas WHERE idea_id = :i"), {"i": refers_to}
                ).first()
                is not None
                if refers_to.startswith("ida_")
                else refers_to.startswith("cpt_") and concept_exists(conn, refers_to)
            )
            if not known:
                issues.append(ValidationIssue("refers_to", "refers-to-unknown"))
        for key in from_keys:
            seen = conn.execute(
                text("SELECT 1 FROM labels WHERE key = :k LIMIT 1"), {"k": key}
            ).first()
            if seen is None:
                issues.append(ValidationIssue("from_keys", f"label-unknown:{key}"))
    return issues


def _human_gate(project: Project, actor: Actor, noun: str) -> list[ValidationIssue]:
    issues = gate_issues(project, actor, "terms.promote")
    if actor.kind != "human":
        issues = issues or [ValidationIssue("actor", f"only a human {noun} a term")]
    return issues


def _payload(model: type[TermPromoted], **fields: Any) -> tuple[Any, list[ValidationIssue]]:
    try:
        return model(**fields), []
    except ValidationError as exc:
        found = [
            ValidationIssue(str(e["loc"][0]) if e["loc"] else "term", str(e["msg"]))
            for e in exc.errors()
        ]
        return None, found


def promote_term(
    project: Project,
    actor: Actor,
    *,
    name: str,
    definition: str,
    applies_to: Sequence[MemberType],
    aliases: Sequence[str] = (),
    refers_to: str | None = None,
    from_keys: Sequence[str] = (),
) -> str:
    """Promote a label key to a term (human only; gate `terms.promote`) and return its id
    (`trm_...`). Refused with every issue (fields `actor`, `name`, `aliases[i]`, `definition`,
    `applies_to`, `refers_to`, `from_keys`; reason `key-taken:<term>` for a key another live
    term holds) and nothing written."""
    with project.index.exclusive():
        project.index.sync()
        term_id = f"trm_{project.ids.ulid()}"
        issues = _human_gate(project, actor, "promotes")
        payload, shape = _payload(
            TermPromoted,
            term_id=term_id,
            name=name.strip(),
            aliases=tuple(a.strip() for a in aliases),
            definition=definition,
            applies_to=tuple(applies_to),
            refers_to=refers_to,
            from_keys=tuple(from_keys),
        )
        issues += shape
        if payload is not None:
            issues += _issues(
                project,
                term_id=None,
                name=payload.name,
                aliases=payload.aliases,
                refers_to=payload.refers_to,
                from_keys=payload.from_keys,
            )
        if issues:
            raise _refuse(*issues)
        event = project.events.make("term.promoted", payload, actor, refs=[term_id])
        project.record([event])
        return term_id


def revise_term(
    project: Project,
    actor: Actor,
    term_id: str,
    *,
    name: str,
    definition: str,
    applies_to: Sequence[MemberType],
    aliases: Sequence[str] = (),
    refers_to: str | None = None,
    from_keys: Sequence[str] = (),
) -> str:
    """Record a new version of a term (human only) and return the event id. Refusals as
    `promote_term`, and `term_id` for an unknown or retired term."""
    with project.index.exclusive():
        project.index.sync()
        issues = _human_gate(project, actor, "revises")
        with project.index.connect() as conn:
            row = term_row(conn, term_id)
            current = conn.execute(
                text("SELECT event_id FROM terms WHERE term_id = :t"), {"t": term_id}
            ).scalar_one_or_none()
        if row is None or current is None:
            issues.append(ValidationIssue("term_id", "term-unknown"))
        elif row.retired:
            issues.append(ValidationIssue("term_id", "term-retired"))
        payload: Any = None
        if current is not None:
            payload, shape = _payload(
                TermRevised,
                term_id=term_id,
                name=name.strip(),
                aliases=tuple(a.strip() for a in aliases),
                definition=definition,
                applies_to=tuple(applies_to),
                refers_to=refers_to,
                from_keys=tuple(from_keys),
                supersedes=str(current),
            )
            issues += shape
        if payload is not None:
            issues += _issues(
                project,
                term_id=term_id,
                name=payload.name,
                aliases=payload.aliases,
                refers_to=payload.refers_to,
                from_keys=payload.from_keys,
            )
        if issues:
            raise _refuse(*issues)
        event = project.events.make("term.revised", payload, actor, refs=[term_id])
        project.record([event])
        return event.id


def retire_term(project: Project, actor: Actor, term_id: str, reason: str) -> str:
    """Retire a term (human only) and return the event id; a region rule that names it then
    refuses. Refused for an unknown or retired term and a blank reason."""
    with project.index.exclusive():
        project.index.sync()
        issues = _human_gate(project, actor, "retires")
        with project.index.connect() as conn:
            row = term_row(conn, term_id)
        if row is None:
            issues.append(ValidationIssue("term_id", "term-unknown"))
        elif row.retired:
            issues.append(ValidationIssue("term_id", "term-retired"))
        if not reason.strip():
            issues.append(ValidationIssue("reason", "state why"))
        if issues:
            raise _refuse(*issues)
        event = project.events.make(
            "term.retired", TermRetired(term_id=term_id, reason=reason), actor, refs=[term_id]
        )
        project.record([event])
        return event.id


# --- Reads ---


def term_applications(
    project: Project,
    term_id: str,
    *,
    status: Collection[str] | None = SELECTABLE,
) -> list[TermApplication]:
    """The live applications of a term, classified (module `factory.regions.term_use`); by
    default only the stated and confirmed ones, `status=None` for all."""
    project.index.sync()
    with project.index.connect() as conn:
        found = _applications(conn, term_id)
    return [a for a in found if status is None or a.status in status]


def _visible_keys(conn: Connection, keys: list[str], agent: bool) -> tuple[str, ...]:
    """The keys, minus those only an import's tag gives when the view is an agent's."""
    if not agent:
        return tuple(keys)
    return tuple(
        k
        for k in keys
        if conn.execute(
            text(
                "SELECT 1 FROM labels WHERE key = :k AND origin != 'import-tag' "
                "AND withdrawn = 0 LIMIT 1"
            ),
            {"k": k},
        ).first()
    )


def list_terms(
    project: Project,
    *,
    include_retired: bool = False,
    exclude_import_tags: bool = False,
    limit: int = 500,
    offset: int = 0,
) -> list[TermView]:
    """Terms by id, one page, with their live applications counted by status. An agent's view
    passes `exclude_import_tags`: applications that came from an import's tags are then left out
    of the counts."""
    project.index.sync()
    where = "" if include_retired else "WHERE retired = 0 "
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT term_id, name, aliases, definition, applies_to, refers_to, from_keys, "
                f"retired, version FROM terms {where}ORDER BY term_id LIMIT :n OFFSET :o"
            ),
            {"n": limit, "o": offset},
        ).all()
        views: list[TermView] = []
        for r in rows:
            counts = {"confirmed": 0, "stated": 0, "inferred": 0}
            for app in _applications(conn, str(r[0])):
                if not (exclude_import_tags and app.origin == "import-tag"):
                    counts[app.status] += 1
            views.append(
                TermView(
                    term_id=str(r[0]),
                    name=str(r[1]),
                    aliases=tuple(json.loads(str(r[2]))),
                    definition=str(r[3]),
                    applies_to=tuple(MemberType(t) for t in json.loads(str(r[4]))),
                    refers_to=None if r[5] is None else str(r[5]),
                    from_keys=_visible_keys(conn, json.loads(str(r[6])), exclude_import_tags),
                    retired=bool(r[7]),
                    version=int(r[8]),
                    counts=counts,
                )
            )
    return views


def promotion_suggestions(project: Project) -> list[tuple[str, int]]:
    """Live label keys with at least `PROMOTION_MIN_TARGETS` distinct targets that no live term
    holds, as `(key, targets)` by targets descending then key."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT live_key, COUNT(DISTINCT target_type || ':' || target) AS n FROM labels "
                "WHERE withdrawn = 0 AND COALESCE(decision, '') != 'reject' "
                "AND live_key NOT IN (SELECT a.key FROM term_aliases a JOIN terms t "
                "ON t.term_id = a.term_id WHERE t.retired = 0) "
                "GROUP BY live_key HAVING n >= :m ORDER BY n DESC, live_key"
            ),
            {"m": PROMOTION_MIN_TARGETS},
        ).all()
    return [(str(k), int(n)) for k, n in rows]
