"""The closed registry of `stat` supports (slice 7b, plan W-A, ruling 3).

A stat is a figure the platform computes at write time and stores on the sentence; an agent never
defines one. A new kind needs new code and a new `STATS_VERSION`, recorded on every sentence.

Invariants:
- Every kind returns an `int`; an unknown kind, a wrong argument count, an argument that names
  nothing (an unknown group, an idea that is not confirmed, a field PRISMA lacks) and a value that
  does not exist yet (`prisma:included_in_review` before the full-text stage ran) are refused with
  field `supports` and reason `unknown`.
- Group figures count the rows the views count (`write_rows.visible_rows_by_group`).
"""

from __future__ import annotations

from collections.abc import Sequence

from factory.errors import FactoryValidationError, ValidationIssue
from factory.services.context import Project
from factory.services.extraction_agreement import independence_counts
from factory.services.horizon import timeline_view
from factory.services.ideas import confirmed_ideas
from factory.services.lineage import no_stated_base
from factory.services.prisma import prisma_flow
from factory.services.references import included_works
from factory.services.write_rows import visible_rows_by_group

STATS_VERSION = 1
PRISMA_FIELDS = (
    "duplicates_removed",
    "excluded_total",
    "included",
    "included_in_review",
    "pending",
    "screened",
)
STAT_KINDS: tuple[str, ...] = (
    "group-independent",
    "group-rows",
    "group-works",
    "idea-members",
    "ideas-confirmed",
    "included-works",
    "not-stated-count",
    "prisma",
    "records",
)
_ARITY = {
    "group-independent": 1,
    "group-rows": 1,
    "group-works": 1,
    "idea-members": 1,
    "ideas-confirmed": 0,
    "included-works": 0,
    "not-stated-count": 0,
    "prisma": 1,
    "records": 2,
}


def _unknown(kind: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue("supports", f"unknown: stat {kind}")])


def group_of_stat(kind: str, args: Sequence[str]) -> str | None:
    """The group id a stat names (for the cross-group and work bookkeeping), else None."""
    return args[0] if kind.startswith(("group-", "records")) and args else None


def compute_stat(project: Project, kind: str, args: Sequence[str]) -> int:
    """The value of the stat `kind:args` now. Refused with reason `unknown` as described above."""
    if kind not in _ARITY or len(args) != _ARITY[kind]:
        raise _unknown(kind)
    if kind == "ideas-confirmed":
        return len(confirmed_ideas(project))
    if kind == "included-works":
        return len(included_works(project))
    if kind == "not-stated-count":
        return len(no_stated_base(project).not_stated)
    if kind == "prisma":
        return _prisma(project, args[0])
    if kind == "idea-members":
        return _idea_members(project, args[0])
    visible = visible_rows_by_group(project).groups
    if args[0] not in visible:
        raise _unknown(kind)
    rows = visible[args[0]][1]
    if kind == "group-works":
        return len({r.work_id for r in rows})
    if kind == "group-rows":
        return len(rows)
    if kind == "group-independent":
        return independence_counts(rows).independent
    return _records(project, args[0], args[1], kind)


def _prisma(project: Project, name: str) -> int:
    if name not in PRISMA_FIELDS:
        raise _unknown("prisma")
    flow = prisma_flow(project)
    value = flow.excluded_total if name == "excluded_total" else getattr(flow, name)
    if not isinstance(value, int):
        raise _unknown("prisma")
    return value


def _idea_members(project: Project, idea_id: str) -> int:
    ideas = {i.idea_id: i for i in confirmed_ideas(project)}
    if idea_id not in ideas:
        raise _unknown("idea-members")
    included = set(included_works(project))
    return len(included & set(ideas[idea_id].effective_members))


def _records(project: Project, gid: str, year: str, kind: str) -> int:
    if not year.isdigit() or len(year) != 4:
        raise _unknown(kind)
    view = timeline_view(project, gid)
    return sum(1 for unit in view.units.values() for r in unit.records if r.year == int(year))
