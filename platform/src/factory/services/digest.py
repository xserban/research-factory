"""The digest of a living review: computed facts since a cut-off, bounded, verdict-free (living-D).

`digest_build` assembles a `Digest` from the living-A to -C services and the existing status
services; `record_digest` stores its rendering and writes one `digest.generated` per project.
A builder: it writes nothing except `digest.generated` through `record_digest`.

Invariants:
- Every number and listing is computed from events; no field is typed by a person or an agent.
- A digest carries no abstract, no quotation, no verdict and no conclusion statement. Titles are
  bibliographic metadata. Listings are capped at `watch_plan.digest_listing_cap` (50 without a
  plan) and say how many more there are (plan ruling 5).
- The window is `(since_event, cutoff_event]`; `since` is the cut-off of the project's last
  `digest.generated` (`"last"`), an event id, or the start of the log (`None`) (ruling 4).
- A held-out seed's work reads as any corpus work (decision 37 item 9): nothing is filtered by
  held-out status. The agent view drops the update flow's per-work list and nothing else.
- Closed update flows are read from the snapshot that pinned them, never recomputed.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import text

from factory.living.counts import source_counts
from factory.model.base import StrictModel
from factory.model.conclusions import ConclusionDiff
from factory.model.digest import (
    CandidateRow,
    CycleSummaryRow,
    DigestGenerated,
    Listing,
    NoticeRow,
    VersionRow,
)
from factory.model.notices import unassessed_notices
from factory.model.watch import CycleStatus
from factory.services.conclusions import conclusion_diff
from factory.services.context import Project
from factory.services.human_queue import Gate, human_queue
from factory.services.inbox_watch import route_labels
from factory.services.notices import assessments, observed_notices
from factory.services.prisma_update import UpdateFlow, update_query_ids, update_work_ids
from factory.services.protocol import current_protocol
from factory.services.references import reference_counts
from factory.services.search import get_work
from factory.services.snapshots import snapshot_blob
from factory.services.status_lookup import unrecovered_failures
from factory.services.watch import watch_status

# Module kind (slice M): a builder; its system output event is digest.generated.

DEFAULT_CAP = 50
DECISION_KEYS = (
    "screening-disagreements",
    "calibration-labels",
    "audit-labels",
    "notice-assessments",
    "inferred-relations",
    "fuzzy-reference-links",
)


class DigestProject(StrictModel):
    """One project's digest. `status` is `retired` once the watch has ended (`until` passed or
    the plan removed after cycles ran) and `no-watch` for a project that never watched."""

    slug: str
    status: Literal["active", "retired", "no-watch"]
    since_event: str | None
    cutoff_event: str
    cycles: tuple[CycleSummaryRow, ...]
    new_candidates: Listing[CandidateRow]
    open_decisions: dict[str, int]
    notices: Listing[NoticeRow]
    versions: Listing[VersionRow]
    conclusions: tuple[ConclusionDiff, ...]
    failures: tuple[str, ...]
    overdue: tuple[str, ...]
    update_flow: UpdateFlow | None


class Digest(StrictModel):
    """The digest of one or more projects; `digest_id` is None until it is recorded."""

    digest_id: str | None
    generated_at: datetime
    projects: tuple[DigestProject, ...]


def digest_build(
    projects: Sequence[Project],
    *,
    since: str | Literal["last"] | None = "last",
    now: datetime | None = None,
) -> Digest:
    """The digest of `projects` since `since` (`"last"`: each project's last recorded digest;
    an event id; `None`: the start of the log). Read-only."""
    if now is None:
        if not projects:
            raise ValueError("a digest of no project needs an explicit time")
        now = projects[0].clock.now()
    return Digest(
        digest_id=None,
        generated_at=now,
        projects=tuple(_project_digest(p, since) for p in projects),
    )


def agent_digest(d: Digest) -> Digest:
    """`d` as an agent may read it: a candidate that came by `seed-admission` reads `other`, as
    in `report_discovery`, so the digest never marks a work as a seed. Nothing else is dropped:
    no conclusion statement, label-derived rate or seed mark exists in a digest to begin with."""
    return d.model_copy(
        update={
            "projects": tuple(
                p.model_copy(
                    update={
                        "new_candidates": p.new_candidates.model_copy(
                            update={
                                "items": tuple(
                                    c.model_copy(update={"route": "other"})
                                    if c.route == "seed-admission"
                                    else c
                                    for c in p.new_candidates.items
                                )
                            }
                        )
                    }
                )
                for p in d.projects
            )
        }
    )


def record_digest(projects: Sequence[Project], d: Digest) -> str:
    """Store the rendering of `d` and write one `digest.generated` per project; returns the
    digest id (shared by every project's event).

    Each project's blobs hold that project's part of the digest only. The next `since="last"`
    starts at the cut-off recorded here."""
    from factory.living.digest_render import to_json, to_markdown

    if not projects:
        raise ValueError("record_digest needs a project")
    digest_id = projects[0].ids.new("dig")
    by_slug = {p.paths.slug: p for p in projects}
    for part in d.projects:
        project = by_slug[part.slug]
        single = Digest(digest_id=digest_id, generated_at=d.generated_at, projects=(part,))
        payload = DigestGenerated(
            digest_id=digest_id,
            project=part.slug,
            since_event=part.since_event,
            cutoff_event=part.cutoff_event,
            blob=project.blobs.put(to_json(single).encode()),
            markdown_blob=project.blobs.put(to_markdown(single).encode()),
            counts=digest_counts(part),
        )
        project.record(
            [
                project.events.make(
                    "digest.generated", payload, project.system_actor(), refs=(digest_id,)
                )
            ]
        )
    return digest_id


def digest_counts(part: DigestProject) -> dict[str, int]:
    """The counts a recorded digest names, computed from it."""
    counts = {
        "cycles": len(part.cycles),
        "new_candidates": len(part.new_candidates.items) + part.new_candidates.more,
        "notices": len(part.notices.items) + part.notices.more,
        "versions": len(part.versions.items) + part.versions.more,
        "conclusions_changed": sum(1 for c in part.conclusions if c.state != "unchanged"),
        "failures": len(part.failures),
        "overdue": len(part.overdue),
    }
    counts.update({f"open:{key}": value for key, value in part.open_decisions.items()})
    return dict(sorted(counts.items()))


def last_digest_cutoff(project: Project) -> str | None:
    """The cut-off event of the project's last recorded digest, or None."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT cutoff_event FROM digests ORDER BY event_id DESC LIMIT 1")
        ).first()
    return None if row is None else str(row[0])


# --- assembly ---


def _project_digest(project: Project, since: str | None) -> DigestProject:
    project.index.sync()
    cutoff = _last_event(project)
    since_event = last_digest_cutoff(project) if since == "last" else since
    protocol = current_protocol(project)
    plan = None if protocol is None else protocol.spec.watch_plan
    cap = DEFAULT_CAP if plan is None else plan.digest_listing_cap
    status = watch_status(project)
    ever_ran = _cycle_count(project) > 0
    now = project.clock.now()
    ended = (plan is not None and plan.until is not None and now.date() > plan.until) or (
        plan is None and ever_ran
    )
    if plan is None and not ever_ran:
        state: Literal["active", "retired", "no-watch"] = "no-watch"
    else:
        state = "retired" if ended else "active"
    failures = [f"status-run:{run}" for run in unrecovered_failures(project)]
    overdue: list[str] = []
    for item in status.sources:
        if plan is not None and item.consecutive_failures >= plan.max_consecutive_failures:
            failures.append(f"source:{item.source}:failing")
        if (
            state == "active"
            and item.next_due is not None
            and now > item.next_due + timedelta(days=item.interval_days)
        ):
            overdue.append(f"source:{item.source}")
    cycles = _cycles(project, since_event, cutoff)
    failures += [f"cycle:{c.cycle_id}:{c.status.value}" for c in cycles if c.status in _BAD]
    return DigestProject(
        slug=project.paths.slug,
        status=state,
        since_event=since_event,
        cutoff_event=cutoff,
        cycles=cycles,
        new_candidates=_candidates(project, since_event, cutoff, cap),
        open_decisions=_open_decisions(project),
        notices=_notices(project, since_event, cutoff, cap),
        versions=_versions(project, since_event, cutoff, cap),
        conclusions=tuple(conclusion_diff(project)),
        failures=tuple(sorted(failures)),
        overdue=tuple(sorted(overdue)),
        update_flow=_update_flow(project, since_event, cutoff),
    )


_BAD = (CycleStatus.PARTIAL, CycleStatus.FAILED)


def _last_event(project: Project) -> str:
    with project.index.connect() as conn:
        return str(conn.execute(text("SELECT max(id) FROM events")).scalar_one())


def _cycle_count(project: Project) -> int:
    with project.index.connect() as conn:
        return int(conn.execute(text("SELECT count(*) FROM watch_cycles")).scalar_one())


def _cycles(project: Project, since: str | None, cutoff: str) -> tuple[CycleSummaryRow, ...]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT cycle_id, started_at, status FROM watch_cycles"
                " WHERE (:since IS NULL OR started_event > :since) AND started_event <= :cutoff"
                " ORDER BY started_event"
            ),
            {"since": since, "cutoff": cutoff},
        ).all()
    return tuple(
        CycleSummaryRow(
            cycle_id=str(cycle_id),
            status=CycleStatus(str(status)),
            started_at=str(started),
            counts=source_counts(project, str(cycle_id)),
        )
        for cycle_id, started, status in rows
    )


def _candidates(
    project: Project, since: str | None, cutoff: str, cap: int
) -> Listing[CandidateRow]:
    new, _duplicates = update_work_ids(project, since, cutoff)
    queries = update_query_ids(project, new, since, cutoff)
    ordered = sorted(new, key=lambda w: (queries.get(w, ()), w))
    shown = ordered[:cap]
    routes = route_labels(project, shown)
    items: list[CandidateRow] = []
    for work_id in shown:
        work = get_work(project, work_id)
        items.append(
            CandidateRow(
                work_id=work_id,
                title="" if work is None else work.title,
                query_ids=queries.get(work_id, ()),
                route=routes.get(work_id, ("unknown", ""))[0],
            )
        )
    return Listing[CandidateRow](items=tuple(items), more=len(ordered) - len(shown))


def _open_decisions(project: Project) -> dict[str, int]:
    gates: dict[str, int] = {}
    for item in human_queue(project).items:
        gates[item.gate.value] = gates.get(item.gate.value, 0) + item.count
    unassessed = unassessed_notices(observed_notices(project), assessments(project))
    return {
        "screening-disagreements": gates.get(Gate.SCREENING_DISAGREEMENTS.value, 0),
        "calibration-labels": gates.get(Gate.CALIBRATION_LABELS.value, 0),
        "audit-labels": gates.get(Gate.SCREENING_AUDIT.value, 0)
        + gates.get(Gate.EXTRACTION_AUDIT.value, 0),
        "notice-assessments": len(unassessed),
        "inferred-relations": 0,  # slice 3b's lineage is not built; its count joins here
        "fuzzy-reference-links": reference_counts(project).unconfirmed,
    }


def _notices(project: Project, since: str | None, cutoff: str, cap: int) -> Listing[NoticeRow]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT notice_id, work_id, kind, notice_date, source FROM notices"
                " WHERE (:since IS NULL OR event_id > :since) AND event_id <= :cutoff"
            ),
            {"since": since, "cutoff": cutoff},
        ).all()
    assessed = {a.notice_id for _, a in assessments(project)}
    found = sorted(
        (
            NoticeRow(
                notice_id=str(r[0]),
                work_id=str(r[1]),
                kind=str(r[2]),
                notice_date=None if r[3] is None else str(r[3]),
                source=str(r[4]),
                assessed=str(r[0]) in assessed,
            )
            for r in rows
        ),
        key=lambda n: (n.notice_date is None, n.notice_date or "", n.work_id, n.notice_id),
    )
    return Listing[NoticeRow](items=tuple(found[:cap]), more=max(0, len(found) - cap))


def _versions(project: Project, since: str | None, cutoff: str, cap: int) -> Listing[VersionRow]:
    window = {"since": since, "cutoff": cutoff}
    with project.index.connect() as conn:
        observed = conn.execute(
            text(
                "SELECT work_id, route, source_version FROM version_observations"
                " WHERE (:since IS NULL OR event_id > :since) AND event_id <= :cutoff"
            ),
            window,
        ).all()
        linked = conn.execute(
            text(
                "SELECT work_id, identifiers FROM version_links WHERE conflicts_with IS NULL"
                " AND (:since IS NULL OR event_id > :since) AND event_id <= :cutoff"
            ),
            window,
        ).all()
    rows = [
        VersionRow(work_id=str(w), kind="newer-version", detail=f"{r} {v}") for w, r, v in observed
    ]
    for work_id, identifiers in linked:
        named = {k: v for k, v in json.loads(str(identifiers)).items() if v is not None}
        detail = " ".join(f"{k}:{named[k]}" for k in sorted(named))
        rows.append(VersionRow(work_id=str(work_id), kind="version-of-record", detail=detail))
    rows.sort(key=lambda v: (v.work_id, v.kind, v.detail))
    return Listing[VersionRow](items=tuple(rows[:cap]), more=max(0, len(rows) - cap))


def _update_flow(project: Project, since: str | None, cutoff: str) -> UpdateFlow | None:
    """The update the latest snapshot in the window closed, read from its pinned blob."""
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT snapshot_id FROM snapshots"
                " WHERE (:since IS NULL OR event_id > :since) AND event_id <= :cutoff"
                " ORDER BY event_id DESC LIMIT 1"
            ),
            {"since": since, "cutoff": cutoff},
        ).first()
    if row is None:
        return None
    pinned = snapshot_blob(project, str(row[0])).update
    return None if pinned is None else UpdateFlow.model_validate(pinned)
