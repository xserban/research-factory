"""The weekly meeting pack and the handover note (IDEA-14, plan SV task 2).

Invariants:
- Read-only: nothing is written; every figure is computed from the events and the index (R-05).
- Counts, ids and titles only. No label, rate, rationale, quote or document text appears.
- Deterministic: the same log and the same `since` give the same pack.
- A fresh project yields empty sections and a notice for each, never an error.
- Delivery is not here (decision 63): the CLI prints the pack or writes it to a file.
"""

from __future__ import annotations

import json

from sqlalchemy import text

from factory.model.base import StrictModel
from factory.services.context import Project
from factory.services.digest import digest_build, last_digest_cutoff
from factory.services.human_queue import HumanItem, human_queue
from factory.services.protocol import current_protocol


class AmendmentRow(StrictModel):
    amendment_id: str
    from_version: str
    to_version: str
    semantic: bool


class OpenTask(StrictModel):
    task_id: str
    kind: str
    status: str


class LabPack(StrictModel):
    slug: str
    since: str | None
    until: str | None
    progress: dict[str, int]
    amendments: list[AmendmentRow]
    discussion: list[HumanItem]
    """Disagreements to discuss: the human-queue gates about two passes that differ."""
    new_literature: list[str]
    """`<work id> <title>` of each work new since `since`, from the digest."""
    more_literature: int
    queue: list[HumanItem]
    open_tasks: list[OpenTask]
    """Handover only."""
    notices: list[str]
    handover: bool


_DISCUSS = ("screening-disagreements", "extraction-disagreements")


def lab_pack(project: Project, since: str | None = "last", *, handover: bool = False) -> LabPack:
    """The pack since `since`: an event id, `last` (the cut-off of the last recorded digest) or
    None (the start of the log). `handover` adds the open tasks."""
    project.index.sync()
    cut = last_digest_cutoff(project) if since == "last" else since
    with project.index.connect() as conn:
        until = conn.execute(text("SELECT max(id) FROM events")).scalar()
        counts = conn.execute(
            text("SELECT type, count(*) FROM events WHERE id > :s GROUP BY type ORDER BY type"),
            {"s": cut or ""},
        ).all()
        amendments = conn.execute(
            text("SELECT payload FROM amendments WHERE event_id > :s ORDER BY event_id"),
            {"s": cut or ""},
        ).all()
        tasks = (
            conn.execute(
                text(
                    "SELECT task_id, kind, status FROM tasks WHERE status != 'completed'"
                    " ORDER BY task_id"
                )
            ).all()
            if handover
            else []
        )
    notices: list[str] = []
    rows = []
    for (raw,) in amendments:
        payload = json.loads(str(raw))
        rows.append(
            AmendmentRow(
                amendment_id=str(payload["amendment_id"]),
                from_version=str(payload["from_version"]),
                to_version=str(payload["to_version"]),
                semantic=bool(payload.get("semantic", True)),
            )
        )
    literature: list[str] = []
    more = 0
    if until is None:
        notices.append("the project has no events yet")
    else:
        part = digest_build([project], since=cut).projects[0]
        literature = [f"{c.work_id} {c.title}" for c in part.new_candidates.items]
        more = part.new_candidates.more
    queue = human_queue(project).items
    discussion = [item for item in queue if item.gate.value in _DISCUSS]
    if current_protocol(project) is None:
        notices.append("no protocol is recorded")
    if not counts:
        notices.append("no event since the cut-off")
    if not queue:
        notices.append("no human decision is pending")
    return LabPack(
        slug=project.paths.slug,
        since=cut,
        until=None if until is None else str(until),
        progress={str(t): int(n) for t, n in counts},
        amendments=rows,
        discussion=discussion,
        new_literature=literature,
        more_literature=more,
        queue=queue,
        open_tasks=[OpenTask(task_id=str(a), kind=str(b), status=str(c)) for a, b, c in tasks],
        notices=notices,
        handover=handover,
    )


def pack_markdown(pack: LabPack) -> str:
    """The pack as Markdown; the handover adds the open tasks and what each gate needs."""
    out = [
        f"# {'Handover' if pack.handover else 'Meeting pack'}: {pack.slug}",
        "",
        f"Events after {pack.since or 'the start'} up to {pack.until or 'none'}.",
        "",
        "## Progress",
        "",
    ]
    out += [f"- {t}: {n}" for t, n in pack.progress.items()] or ["- none"]
    out += ["", "## Amendments", ""]
    out += [
        f"- {a.amendment_id}: {a.from_version} to {a.to_version}"
        f"{'' if a.semantic else ' (prose only)'}"
        for a in pack.amendments
    ] or ["- none"]
    out += ["", "## Disagreements to discuss", ""]
    out += [_item(i) for i in pack.discussion] or ["- none"]
    out += ["", "## New literature", ""]
    out += [f"- {line}" for line in pack.new_literature] or ["- none"]
    if pack.more_literature:
        out.append(f"- and {pack.more_literature} more")
    out += ["", "## Waiting on a human", ""]
    out += [_item(i) for i in pack.queue] or ["- none"]
    if pack.handover:
        out += ["", "## Open tasks", ""]
        out += [f"- {t.task_id} ({t.kind}, {t.status})" for t in pack.open_tasks] or ["- none"]
        out += ["", "## What each pending gate needs", ""]
        out += [f"- {i.gate.value}: run `{i.command}`" for i in pack.queue] or ["- none"]
    if pack.notices:
        out += ["", "## Notices", ""]
        out += [f"- {n}" for n in pack.notices]
    return "\n".join(out) + "\n"


def _item(item: HumanItem) -> str:
    stage = "" if item.stage is None else f" [{item.stage}]"
    return f"- {item.gate.value}{stage}: {item.count}"
