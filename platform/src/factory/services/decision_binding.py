"""Binding records to decisions (slice 8, plan A7), kept apart from `decisions` on purpose.

`bind` is how the question, seed, probe and protocol records cite the decisions they implement. A
cited id must be a known decision at the record's level, cited once, in every mode. In `pilot` and
`systematic` the record must also cite at least one decision, and each cited decision must have an
accepted selection and not be superseded. A "none of these" selection (with its required note)
counts as an accepted selection. Whether the act matches the selection is a check rule, not a
refusal.

This module imports nothing from `withholding`: `withholding` reads seeds, `seeds` binds, and
`decisions` scrubs through `withholding`, so `bind` living in `decisions` closed an import cycle.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.decisions import DecisionLevel
from factory.model.project import RigorMode
from factory.services.context import Project


def bind(
    project: Project, level: DecisionLevel, decision_ids: Sequence[str] | None
) -> tuple[str, ...]:
    """The decision ids a record cites, checked, for the event's `decision_ids`. The caller has
    synced the index. Refused, with nothing written (`decision_ids` and `decision_ids.<i>`): a
    duplicate, an unknown id, a decision at another level; and, outside `exploratory`, no id at all
    or an id with no accepted selection (open, or superseded). A cited decision is a selection the
    record implements; an empty result is legal only in `exploratory`."""
    ids = tuple(decision_ids or ())
    if len(set(ids)) != len(ids):
        raise FactoryValidationError([ValidationIssue("decision_ids", "a decision is cited once")])
    with project.index.connect() as conn:
        mode = RigorMode(
            str(
                conn.execute(
                    text("SELECT rigor_mode FROM project WHERE slug = :slug"),
                    {"slug": project.paths.slug},
                ).scalar_one()
            )
        )
        issues: list[ValidationIssue] = []
        for i, decision_id in enumerate(ids):
            row = conn.execute(
                text(
                    "SELECT d.level, d.superseded_by, "
                    "(SELECT COUNT(*) FROM decision_items x WHERE x.decision_id = d.decision_id "
                    " AND x.status IN ('validated', 'rejected')) "
                    "FROM decision_sets d WHERE d.decision_id = :d"
                ),
                {"d": decision_id},
            ).first()
            field = f"decision_ids.{i}"
            if row is None:
                issues.append(ValidationIssue(field, "unknown decision"))
            elif str(row[0]) != level.value:
                issues.append(ValidationIssue(field, f"is a {row[0]} decision, not {level.value}"))
            elif mode is not RigorMode.EXPLORATORY:
                if row[1] is not None:
                    issues.append(ValidationIssue(field, f"superseded by {row[1]}"))
                elif not int(row[2]):
                    issues.append(ValidationIssue(field, "has no accepted selection"))
    if not ids and mode is not RigorMode.EXPLORATORY:
        issues.append(
            ValidationIssue(
                "decision_ids",
                f"{mode.value} needs a selected {level.value} decision "
                "(decision_suggest, then the scientist's selection)",
            )
        )
    if issues:
        raise FactoryValidationError(issues)
    return ids
