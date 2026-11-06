"""Rows of admitted miners in the evidence report (plan EQ task 8; iterate line 89b; R-45).

A miner the protocol lists with `evidence: true` is admitted: its records may reach the report.
Others never do (an exploratory miner's rows stay out).

Invariants:
- Read-only. Only the miner version the protocol lists is read; rows of another version are
  invisible (they stay what `miner-version-unread` reports).
- A miner's rows are grouped only within identical comparability keys of the evidence schema, and
  only when the miner's fields map to those keys and the value field. A group is labelled with the
  miner name and version and is never merged with an evidence group or another miner's group.
- Any other admitted miner, and a row lacking a key or the value field, is listed with no group.
- Rows of a work a notice excludes from synthesis leave this section as they leave the groups.
"""

from __future__ import annotations

from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.model.extraction import MinerScope
from factory.packs import Pack
from factory.services.context import Project
from factory.services.evidence_report import (
    EvidenceReport,
    MinerGroup,
    MinerRowRef,
    MinerUngrouped,
    _row,
    _spec,
    group_id,
)
from factory.services.extraction_agreement import FinalRow, final_rows, group_rows
from factory.services.mining import miner_schema
from factory.services.notices import work_states
from factory.services.protocol import current_protocol
from factory.services.search import get_work


def admitted_miners(project: Project) -> set[tuple[str, int]]:
    """The `(name, version)` of every miner the current protocol admits as evidence."""
    protocol = current_protocol(project)
    if protocol is None:
        return set()
    return {(u.name, u.version) for u in protocol.spec.miners or () if u.evidence}


def miner_rows(
    project: Project, report: EvidenceReport
) -> tuple[list[MinerGroup], list[MinerUngrouped]]:
    """The groups and the ungrouped rows of the admitted miners, in miner and key order. Empty
    for a project without an admitted miner or without an evidence schema (no keys)."""
    keys = list(report.comparability_keys)
    admitted = sorted(admitted_miners(project))
    if not admitted or not keys:
        return [], []
    project.index.sync()
    excluded = {w for w, s in work_states(project).items() if s.synthesis == "excluded"}
    groups: list[MinerGroup] = []
    ungrouped: list[MinerUngrouped] = []
    for name, version in admitted:
        try:
            _, _, pack = miner_schema(project, name)
        except FactoryValidationError:
            continue  # not listed ready or retired: nothing to show
        rows = [
            r
            for r in final_rows(project, scope=MinerScope(name))
            if r.work_id not in excluded and _is_version(project, r, name, version)
        ]
        if not rows:
            continue
        spec = _spec(pack)
        if not _maps(pack, keys, spec.value_field):
            ungrouped.append(_refs(name, version, "fields-do-not-map", rows))
            continue
        usable = [r for r in rows if spec.value_field in r.fields]
        lacking = [r for r in rows if spec.value_field not in r.fields]
        grouped = group_rows(usable, pack, keys)
        titles = _titles(project, {r.work_id for r in rows})
        for key, members in grouped.groups.items():
            shown = sorted(
                (_row(r, spec, titles, pack) for r in members),
                key=lambda e: (e.work_id, e.row_key),
            )
            groups.append(
                MinerGroup(
                    miner=name,
                    version=version,
                    group_id=group_id(key),
                    key=[tuple(pair) for pair in key],
                    rows=shown,
                )
            )
        loose = [*grouped.ungrouped, *lacking]
        if loose:
            ungrouped.append(_refs(name, version, "row-lacks-key", loose))
    groups.sort(key=lambda g: (g.miner, g.version, g.group_id))
    return groups, ungrouped


def _maps(pack: Pack, keys: list[str], value_field: str) -> bool:
    """Whether the miner's fields cover every comparability key and the value field."""
    return all(pack.field(k) is not None for k in keys) and pack.field(value_field) is not None


def _refs(name: str, version: int, reason: str, rows: list[FinalRow]) -> MinerUngrouped:
    return MinerUngrouped(
        miner=name,
        version=version,
        reason=reason,
        rows=sorted(
            (
                MinerRowRef(row_key=r.row_key, work_id=r.work_id, fields=sorted(r.fields))
                for r in rows
            ),
            key=lambda x: (x.work_id, x.row_key),
        ),
    )


def _is_version(project: Project, row: FinalRow, name: str, version: int) -> bool:
    """Whether every field of the row comes from an extraction of `name@version`."""
    ids = sorted({f.extraction_id for f in row.fields.values()})
    if not ids:
        return False
    marks = ",".join(f":e{i}" for i in range(len(ids)))
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                f"SELECT DISTINCT schema_ref FROM extraction_rows WHERE extraction_id IN ({marks})"
            ),
            {f"e{i}": v for i, v in enumerate(ids)},
        ).all()
    return {str(r[0]) for r in found} == {f"{name}@{version}"}


def _titles(project: Project, works: set[str]) -> dict[str, str]:
    titles: dict[str, str] = {}
    for work_id in sorted(works):
        work = get_work(project, work_id)
        titles[work_id] = "" if work is None else work.title
    return titles
