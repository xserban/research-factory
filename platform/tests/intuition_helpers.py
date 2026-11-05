"""Shared setup for the intuition-layer tests (slice 3c, plan G3-A).

Payload-level builders (`recorded`, `reviewed`, `quote_src`, `cite_src`) write events straight to
the log as the other index tests do. The world fixture (`ilin`, a G2 world with confirmed ideas,
converted papers and live contribution items) is added with the service tests. Every identifier is
invented; document text is hand-written Markdown from `tests/contribution_helpers.py`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from factory.events.envelope import Actor, Event
from factory.services.context import Project
from tests.helpers import S2

ULID = "01HZX3K4M5N6P7Q8R9S0T1V2W"
INT1 = f"int_{ULID}A"
INT2 = f"int_{ULID}B"
INT3 = f"int_{ULID}C"
IDEA1 = "ida_01HZX3K4M5N6P7Q8R9S0000201"
IDEA2 = "ida_01HZX3K4M5N6P7Q8R9S0000202"
PAPER1 = "rf:p1-00000001"
CNV1 = f"cnv_{ULID}A"
DOC1 = f"doc_{ULID}A"


def quote_src(
    work: str = PAPER1,
    conversion: str = CNV1,
    anchor: str = "s1.p2",
    quote: str = "positive random-feature map",
    role: str = "supports",
) -> dict[str, Any]:
    return {
        "kind": "quote",
        "role": role,
        "work_id": work,
        "conversion_id": conversion,
        "anchor": anchor,
        "quote": quote,
    }


def cite_src(*, reference: str | None = None, work: str | None = None) -> dict[str, Any]:
    return {"kind": "citation", "role": "background", "reference": reference, "work_id": work}


def stored(source: dict[str, Any], **computed: Any) -> dict[str, Any]:
    """A source as the recorded event stores it."""
    full: dict[str, Any] = {
        "kind": None,
        "role": None,
        "work_id": None,
        "conversion_id": None,
        "anchor": None,
        "quote": None,
        "reference": None,
        "document_id": None,
        "link_state": None,
        "resolved_work": None,
    }
    full.update(source)
    if source["kind"] == "quote":
        full["document_id"] = DOC1
    full.update(computed)
    return full


def recorded(
    interpretation_id: str = INT1,
    *,
    target: str = IDEA1,
    target_kind: str = "idea",
    author: str = "agent",
    supersedes: str | None = None,
    sources: list[dict[str, Any]] | None = None,
    text_: str = "It approximates the softmax kernel.",
) -> dict[str, Any]:
    return {
        "interpretation_id": interpretation_id,
        "target": target,
        "target_kind": target_kind,
        "text": text_,
        "sources": [stored(s) for s in (sources if sources is not None else [quote_src()])],
        "author": author,
        "supersedes": supersedes,
        "task_id": None,
        "verifier": 1,
    }


def reviewed(
    interpretation_id: str = INT1,
    state: str = "reviewed",
    *,
    note: str = "",
    self_reviewed: bool = False,
    channel: str = "cli",
) -> dict[str, Any]:
    return {
        "interpretation_id": interpretation_id,
        "state": state,
        "note": note,
        "self_reviewed": self_reviewed,
        "channel": channel,
    }


def reviewer(project: Project, user: str | None = None) -> Actor:
    """A human in a session other than the (agent) fixtures'; `user` names another human."""
    base = project.human_actor()
    return base.model_copy(update={"session": S2, "user": user or base.user, "id": user or base.id})


def record_event(
    project: Project, type_: str, payload: dict[str, Any], actor: Actor | None = None
) -> Event:
    model = project.catalog.get(type_).payload.model_validate(payload)
    actor = actor or reviewer(project)
    blob = project.blobs.put_json(payload) if actor.kind == "agent" else None
    event = project.events.make(type_, model, actor, input_blob=blob)
    project.record([event])
    return event


def rows(project: Project, sql: str) -> list[tuple[Any, ...]]:
    project.index.sync()
    with project.index.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql)).all()]


def live_conversion(project: Project, work: str) -> tuple[str, str]:
    """(conversion id, document id) of the latest conversion of a non-superseded document."""
    [(cnv, doc)] = rows(
        project,
        "SELECT c.conversion_id, c.document_id FROM document_conversions c "
        "JOIN fulltext_documents d ON d.document_id = c.document_id "
        f"WHERE d.work_id = '{work}' AND d.superseded_by IS NULL "
        "ORDER BY c.event_id DESC LIMIT 1",
    )
    return str(cnv), str(doc)
