"""Review snapshots of a living review (living-B).

A snapshot is a system event naming a content-addressed blob that holds the computed cumulative
PRISMA flow and the included work ids as the events stood at a cut-off. Snapshots delimit the
updates of a living review (`services.prisma_update`).

Invariants:
- A snapshot is a human act (`trigger="human"`) or the system's (`trigger="cycle"`, from the cycle
  hook); an agent cannot take one and no MCP tool exists for it.
- Refused (nothing written) while a watch cycle is open, except the cycle that is calling the
  hook.
- `cutoff_event` is the last event of the log when the snapshot is taken, under the index lock,
  so the blob is a function of the events up to it: rebuilding the index and recomputing with the
  same cut-off gives the same blob (same hash).
- `conclusion_facts` and `conclusions` stay None until living-D registers sections for them.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Literal

from pydantic import JsonValue
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.index.default import PROJECTION_VERSION
from factory.model.base import StrictModel
from factory.model.living import SnapshotRecorded
from factory.model.protocol import ScreeningStage
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.dedup import canonical_works
from factory.services.prisma import PrismaFlow, prisma_flow
from factory.services.protocol import current_protocol

SnapshotSection = Callable[[Project], tuple[str, JsonValue]]
"""Fills one slot of the blob: returns (`conclusion_facts` | `conclusions`, value)."""

SECTION_SLOTS = ("conclusion_facts", "conclusions")


class SnapshotBlob(StrictModel):
    """What a snapshot pins (schema 1). Every number is computed from events, never typed."""

    schema_version: Literal[1] = 1
    protocol_id: str
    cutoff_event: str
    prisma: PrismaFlow
    included_ids: tuple[str, ...]
    conclusion_facts: JsonValue | None = None
    conclusions: JsonValue | None = None
    update: JsonValue | None = None
    """The `UpdateFlow` this snapshot closes (pinned; None on a snapshot taken before pinning)."""


def snapshot(
    project: Project,
    actor: Actor,
    *,
    trigger: Literal["human", "cycle"],
    extra: Sequence[SnapshotSection] = (),
    ignoring_cycle: str | None = None,
) -> SnapshotRecorded:
    """Record a snapshot of the review as the events stand, and return its event payload.

    Refused, with nothing written, for an actor that does not match the trigger (a human for
    `human`, the system for `cycle`), while a watch cycle other than `ignoring_cycle` is open,
    and when no protocol is recorded. `extra` sections fill the blob's conclusion slots."""
    issues: list[ValidationIssue] = []
    expected = "human" if trigger == "human" else "system"
    if actor.kind != expected:
        issues.append(ValidationIssue("actor", f"a {trigger} snapshot is taken by the {expected}"))
    if issues:
        raise FactoryValidationError(issues)
    with project.index.exclusive():
        project.index.sync()
        open_cycles = [c for c in _open_cycles(project) if c != ignoring_cycle]
        if open_cycles:
            raise FactoryValidationError(
                [ValidationIssue("cycle", f"a watch cycle is open ({open_cycles[0]})")]
            )
        protocol = current_protocol(project)
        if protocol is None:
            raise FactoryValidationError([ValidationIssue("protocol", "record a protocol first")])
        cutoff = _last_event(project)
        snapshot_id = project.ids.new("snp")
        blob = build_snapshot_blob(
            project, cutoff_event=cutoff, extra=extra, snapshot_id=snapshot_id
        )
        ref = project.blobs.put_json(blob.model_dump(mode="json"))
        payload = SnapshotRecorded(
            snapshot_id=snapshot_id,
            cutoff_event=cutoff,
            protocol_id=protocol.protocol_id,
            blob=ref,
            projection_version=PROJECTION_VERSION,
            trigger=trigger,
        )
        event = project.events.make(
            "living.snapshot_recorded", payload, actor, refs=(payload.snapshot_id,)
        )
        project.record([event])
    return payload


def build_snapshot_blob(
    project: Project,
    *,
    cutoff_event: str,
    extra: Sequence[SnapshotSection] = (),
    snapshot_id: str | None = None,
) -> SnapshotBlob:
    """The blob of the review as the events stand now, labelled with `cutoff_event`.

    The caller supplies the last event id of the log it computes over (`snapshot` reads it under
    the index lock); recomputing later with the same id gives the same blob while no earlier
    event changes."""
    from factory.services.prisma_update import pin_update  # prisma_update reads snapshots

    project.index.sync()
    flow = prisma_flow(project)
    protocol = current_protocol(project)
    update = None
    if snapshot_id is not None:
        update = pin_update(project, snapshot_id, cutoff_event).model_dump(mode="json")
    slots: dict[str, JsonValue] = {}
    for section in extra:
        name, value = section(project)
        if name not in SECTION_SLOTS:
            raise ValueError(f"unknown snapshot section {name!r}")
        slots[name] = value
    return SnapshotBlob(
        protocol_id="" if protocol is None else protocol.protocol_id,
        cutoff_event=cutoff_event,
        prisma=flow,
        included_ids=included_work_ids(project, flow),
        conclusion_facts=slots.get("conclusion_facts"),
        conclusions=slots.get("conclusions"),
        update=update,
    )


def snapshots(project: Project) -> list[SnapshotRecorded]:
    """Every snapshot in recording order."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT snapshot_id, cutoff_event, protocol_id, blob, projection_version, trigger"
                " FROM snapshots ORDER BY event_id"
            )
        ).all()
    return [
        SnapshotRecorded.model_validate(
            {
                "snapshot_id": r[0],
                "cutoff_event": r[1],
                "protocol_id": r[2],
                "blob": r[3],
                "projection_version": r[4],
                "trigger": r[5],
            }
        )
        for r in rows
    ]


def snapshot_blob(project: Project, snapshot_id: str) -> SnapshotBlob:
    """The blob of a recorded snapshot; refused (field `snapshot`) for an unknown id."""
    for item in snapshots(project):
        if item.snapshot_id == snapshot_id:
            return SnapshotBlob.model_validate(project.blobs.get_json(item.blob))
    raise FactoryValidationError([ValidationIssue("snapshot", "unknown snapshot")])


def last_snapshot_event(project: Project) -> str | None:
    """The event id of the latest snapshot, or None."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(text("SELECT max(event_id) FROM snapshots")).one()
    return None if row[0] is None else str(row[0])


def included_work_ids(project: Project, flow: PrismaFlow) -> tuple[str, ...]:
    """The canonical works included in the review: at full text once that stage has run, else at
    title/abstract."""
    full_text = flow.included_in_review is not None
    stage = ScreeningStage.FULL_TEXT if full_text else ScreeningStage.TITLE_ABSTRACT
    outcomes = final_outcomes(project, stage=stage)
    included = (w.id for w in canonical_works(project) if outcomes.get(w.id) is Outcome.INCLUDED)
    return tuple(sorted(included))


def _open_cycles(project: Project) -> list[str]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT cycle_id FROM watch_cycles WHERE status = 'open' ORDER BY cycle_id")
        ).all()
    return [str(r[0]) for r in rows]


def _last_event(project: Project) -> str:
    with project.index.connect() as conn:
        row = conn.execute(text("SELECT max(id) FROM events")).one()
    if row[0] is None:
        raise FactoryValidationError([ValidationIssue("project", "the log has no event")])
    return str(row[0])
