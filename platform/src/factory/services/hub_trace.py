"""One entry point for the hub's "Why this number?" (plan hub-ui, step 8).

`trace_figure(project, figure_id)` maps a figure id to what the existing `trace` service needs (a
reference and a direction), walks it and returns the chain as a flat, JSON-safe `TraceView`: each
node with the event that created it (type, time, actor kind and model), the decisions and works
met, truncated to a page with the count of the rest. Read-only: nothing is written. An unknown or
malformed figure id is refused with `figure_id` named; nothing is read past the registry check.

Registry (`FIGURE_KINDS`):
- `prisma.screened`, `prisma.included`: the current protocol, forward (its criteria, queries and
  everything downstream: the chain behind the PRISMA counts).
- `prisma.excluded.<criterion>` (`EX03`): that criterion of the current protocol, forward (the
  decisions, resolutions and audit items citing it).
- `work.<work id>.screening`: the work, forward, keeping the decisions, resolutions, audits and
  criteria met (what was decided about it, with the criterion cited).
- `work.<work id>.field.<miner>.<field>`: the latest live extraction row of that miner for the
  work that carries the field, back (conversion, anchors, task, work).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterator
from dataclasses import asdict, dataclass
from typing import Any, Literal

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.services.context import Project
from factory.services.protocol import current_protocol
from factory.services.trace import TraceNode, trace
from factory.services.work_ref import resolve_work_id

PAGE = 50
MAX_PAGE = 500
SCREENING_KINDS = frozenset({"decision", "resolution", "audit", "criterion"})
FIGURE_KINDS: dict[str, str] = {
    "prisma.screened": "Records screened (current protocol, everything downstream)",
    "prisma.included": "Works included (current protocol, everything downstream)",
    "prisma.excluded.<criterion>": "Works excluded under one criterion",
    "work.<id>.screening": "Screening decisions about one work",
    "work.<id>.field.<miner>.<field>": "One mined value and where it was read",
}

_EXCLUDED_RE = re.compile(r"^prisma\.excluded\.((?:IN|EX)\d{2})$")
_SCREENING_RE = re.compile(r"^work\.(.+)\.screening$")
_FIELD_RE = re.compile(r"^work\.(.+)\.field\.(m-[a-z0-9]+(?:-[a-z0-9]+)*)\.([^.\s]+)$")


@dataclass(frozen=True)
class _Plan:
    ref: str
    direction: Literal["back", "forward"]
    kinds: frozenset[str] | None
    title: str


@dataclass(frozen=True)
class TraceEntry:
    """One node of the chain. Event fields are empty for a reference that names no row."""

    depth: int
    id: str
    kind: str
    label: str
    event_id: str
    event_type: str | None
    ts: str | None
    actor_kind: str | None
    model: str | None


@dataclass(frozen=True)
class TraceView:
    figure_id: str
    title: str
    ref: str
    direction: str
    total: int
    offset: int
    entries: tuple[TraceEntry, ...]
    rest: int
    decisions: tuple[str, ...]
    works: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def _refuse(reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue("figure_id", reason)])


def _protocol_id(project: Project) -> str:
    current = current_protocol(project)
    if current is None:
        raise _refuse("no protocol recorded")
    return current.protocol_id


def _plan(project: Project, figure_id: str) -> _Plan:
    """The reference, direction and filter of a figure id; refused when it is not registered."""
    if figure_id in ("prisma.screened", "prisma.included"):
        return _Plan(_protocol_id(project), "forward", None, FIGURE_KINDS[figure_id])
    if (m := _EXCLUDED_RE.match(figure_id)) is not None:
        protocol_id = _protocol_id(project)
        current = current_protocol(project)
        known = {c.id for c in current.spec.criteria} if current is not None else set()
        if m.group(1) not in known:
            raise _refuse("unknown criterion")
        return _Plan(f"{protocol_id}:{m.group(1)}", "forward", None, f"Excluded under {m.group(1)}")
    if (m := _FIELD_RE.match(figure_id)) is not None:
        work_id, miner, field = m.groups()
        project.index.sync()
        work = _work(project, work_id)
        with project.index.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT r.extraction_id FROM extraction_rows r JOIN extraction_fields f "
                    "ON f.extraction_id = r.extraction_id WHERE r.scope = :s AND r.work_id = :w "
                    "AND r.superseded_by IS NULL AND f.field = :f ORDER BY r.event_id DESC LIMIT 1"
                ),
                {"s": miner, "w": work, "f": field},
            ).first()
        if row is None:
            raise _refuse("no such mined value")
        return _Plan(str(row[0]), "back", None, f"{field} of {work} read by {miner}")
    if (m := _SCREENING_RE.match(figure_id)) is not None:
        project.index.sync()
        work = _work(project, m.group(1))
        return _Plan(work, "forward", SCREENING_KINDS, f"Screening of {work}")
    raise _refuse("unknown figure")


def _work(project: Project, work_id: str) -> str:
    try:
        return resolve_work_id(project, work_id, field="figure_id")
    except FactoryValidationError:
        raise _refuse("unknown work") from None


def _flatten(node: TraceNode, depth: int = 0) -> Iterator[tuple[int, TraceNode]]:
    """Pre-order walk; children are already in chain order."""
    yield depth, node
    for child in node.children:
        yield from _flatten(child, depth + 1)


def _events(project: Project, ids: Collection[str]) -> dict[str, tuple[str, str, str, str | None]]:
    """`event id -> (type, ts, actor kind, model)` from the index's events table."""
    wanted = sorted({i for i in ids if i})
    out: dict[str, tuple[str, str, str, str | None]] = {}
    with project.index.connect() as conn:
        for start in range(0, len(wanted), 500):
            chunk = wanted[start : start + 500]
            marks = ",".join(f":e{i}" for i in range(len(chunk)))
            rows = conn.execute(
                text(f"SELECT id, type, ts, actor_kind, model FROM events WHERE id IN ({marks})"),
                {f"e{i}": e for i, e in enumerate(chunk)},
            ).all()
            for event_id, type_, ts, kind, model in rows:
                out[str(event_id)] = (
                    str(type_),
                    str(ts),
                    str(kind),
                    None if model is None else str(model),
                )
    return out


def trace_figure(
    project: Project, figure_id: str, *, offset: int = 0, limit: int = PAGE
) -> TraceView:
    """The chain behind one figure, one page of it. Refused (`figure_id`, or `offset` / `limit`)
    with nothing read or written for a bad request; see the module docstring for the registry."""
    if offset < 0:
        raise FactoryValidationError([ValidationIssue("offset", "must not be negative")])
    if not 1 <= limit <= MAX_PAGE:
        raise FactoryValidationError([ValidationIssue("limit", f"must be 1 to {MAX_PAGE}")])
    plan = _plan(project, figure_id)
    try:
        root = trace(project, plan.ref, direction=plan.direction)
    except FactoryValidationError:
        raise _refuse("unknown figure") from None
    nodes = [
        (depth, node)
        for depth, node in _flatten(root)
        if plan.kinds is None or depth == 0 or node.kind in plan.kinds
    ]
    page = nodes[offset : offset + limit]
    events = _events(project, [n.event_id for _, n in page])
    entries = tuple(
        TraceEntry(
            depth=depth,
            id=node.id,
            kind=node.kind,
            label=node.label,
            event_id=node.event_id,
            event_type=(e := events.get(node.event_id)) and e[0],
            ts=e[1] if e else None,
            actor_kind=e[2] if e else None,
            model=e[3] if e else None,
        )
        for depth, node in page
    )
    return TraceView(
        figure_id=figure_id,
        title=plan.title,
        ref=plan.ref,
        direction=plan.direction,
        total=len(nodes),
        offset=offset,
        entries=entries,
        rest=max(len(nodes) - offset - len(page), 0),
        decisions=tuple(n.id for _, n in nodes if n.kind == "decision"),
        works=tuple(n.id for _, n in nodes if n.kind == "work"),
    )
