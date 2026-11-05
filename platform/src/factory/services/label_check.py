"""The organisation class's own conditions for `check` (slice 3d, plan Regions-C, task 5).

Each function reads the label and term tables by SQL and returns `(total, refs)`: the number of
items in the condition and up to `REF_CAP` of their identifiers, sorted. Nothing here reads a
quote, a label text or a definition, so a finding built from it carries counts and identifiers
only. `services.check` owns severities and messages.
"""

from __future__ import annotations

import re

from sqlalchemy import text

from factory.regions.term_use import SELECTABLE, term_applications
from factory.services.context import Project

REF_CAP = 500
Found = tuple[int, list[str]]

ORGANISATION_ID = re.compile(
    r"\b(?:reg|lbl|lab|trm|cns|cnp)_[0-9A-HJKMNP-TV-Z]{26}\b|\bR@[0-9a-f]{8}\b"
)
"""A region, region version, label application, term or consolidation id: none may appear in an
evidence output (`organisation-leak`)."""


def organisation_present(project: Project) -> bool:
    """Whether the project has any label, term, consolidation pass or region."""
    project.index.sync()
    with project.index.connect() as conn:
        return bool(
            conn.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM labels) OR EXISTS (SELECT 1 FROM terms) "
                    "OR EXISTS (SELECT 1 FROM consolidation_passes) "
                    "OR EXISTS (SELECT 1 FROM regions)"
                )
            ).scalar_one()
        )


def unconfirmed_applications(project: Project) -> Found:
    """Live applications still `inferred`: no verified quote with the key and no human decision."""
    project.index.sync()
    where = (
        "withdrawn = 0 AND status = 'inferred' AND origin = 'agent' AND COALESCE(decision, '') = ''"
    )
    with project.index.connect() as conn:
        total = conn.execute(text(f"SELECT COUNT(*) FROM labels WHERE {where}")).scalar_one()
        found = conn.execute(
            text(
                f"SELECT application_id FROM labels WHERE {where} ORDER BY application_id LIMIT :n"
            ),
            {"n": REF_CAP},
        ).all()
    return int(total), [str(r[0]) for r in found]


def unused_terms(project: Project) -> Found:
    """Live terms with no stated or confirmed application."""
    project.index.sync()
    with project.index.connect() as conn:
        ids = [
            str(r[0])
            for r in conn.execute(
                text("SELECT term_id FROM terms WHERE retired = 0 ORDER BY term_id")
            )
        ]
        unused = [
            t for t in ids if not any(a.status in SELECTABLE for a in term_applications(conn, t))
        ]
    return len(unused), unused[:REF_CAP]
