"""The link inbox: capture, withdraw and resolve supplied links (slice 4a).

Capture (`add_links`) is offline and never gated: each link is parsed to one identifier at the
boundary and recorded as an `inbox.link_added` event. Resolution (`resolve_links`) looks each
open item up by identifier as an ordinary recorded query of purpose `supplied`, gated by the
protocol like any search (`supplied_links`, or a deviation), and records the outcome as
`inbox.link_resolved`. Withdrawal is a human act on an open item.

Invariants:
- Invalid input writes nothing and returns structured errors; capture is a batch with partial
  success, and a refused session or actor refuses the whole batch.
- A session that joined a screening or extraction pass may not use the inbox; a session that
  captured a link may not join a screening pass (`services.screening`, ruling 4).
- An agent capture carries `basis` and no note; a human capture carries no `basis`. An agent
  event's `input_blob` is the item as the agent sent it.
- Writes happen under `project.index.exclusive()` after `sync()`; the lookup's fetch runs
  outside the lock, as `seeds.admit_seed` does.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import JsonValue
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.inbox.links import IdentifierKind, LinkIdentifier, parse_link, stored_link
from factory.model.base import StrictModel
from factory.model.inbox import (
    MAX_NOTE,
    Basis,
    InboxLinkAdded,
    InboxLinkResolved,
    InboxLinkWithdrawn,
    InboxRoute,
    ResolveStatus,
)
from factory.model.protocol import SubmitterKind
from factory.model.screening import Channel
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.seed import normalize_openalex
from factory.model.work import Work
from factory.model.work_ids import arxiv_id_from_doi, normalize_arxiv, normalize_doi
from factory.services import passes
from factory.services.context import Project
from factory.services.coverage import held_out_visible
from factory.services.protocol import search_authorization
from factory.services.results import BatchResult, ItemError
from factory.services.search import get_work, list_works, query_issues, register_query, run_query
from factory.sources.registry import SourceFactory

UNSUPPORTED_LINK = "unsupported-link"
ITEM_STATUSES = ("open", "resolved", "withdrawn")
PAGE_LIMIT = 50


@dataclass(frozen=True)
class LinkInput:
    """One link as submitted: the link text, a human's note, or an agent's basis."""

    link: str
    note: str | None = None
    basis: Basis | None = None


@dataclass(frozen=True)
class ResolveOutcome:
    """What one resolve attempt did.

    `status` is set when an `inbox.link_resolved` was written. When `issues` is non-empty no
    resolution was written: with `run_id` None nothing at all was written (the item was refused
    before its lookup); with `run_id` set the lookup's `query.registered` and run events were
    written, but the item was closed (withdrawn or resolved elsewhere) while the run ran, so the
    run stands in the log without a resolution."""

    item_id: str
    status: ResolveStatus | None
    work_id: str | None = None
    run_id: str | None = None
    issues: list[ValidationIssue] = field(default_factory=list)


class InboxItemView(StrictModel):
    """One item as listed: what was captured, by whom, and the last resolution attempt."""

    item_id: str
    route: str
    link: str
    identifier_kind: str
    identifier_value: str
    identifier_version: str | None
    actor_kind: str
    channel: str
    basis_kind: str | None
    note: str | None
    status: str
    last_outcome: str | None
    work_id: str | None


class InboxPage(StrictModel):
    items: list[InboxItemView]
    next_cursor: str | None


_PRE_PASS_OMITTED = frozenset({"link", "identifier_value", "identifier_version"})
"""The fields that state an item's identifier: a held-out seed's reads `[withheld]`."""


def agent_page(project: Project, page: InboxPage) -> dict[str, JsonValue]:
    """`page` as an agent may read it. Before a screening pass, every item loses its link and
    identifier, role-blind, since a scrubbed one would name a held-out seed (decision 81)."""
    data: dict[str, JsonValue] = page.model_dump(mode="json")
    if held_out_visible(project):
        return data
    items: list[JsonValue] = [
        item.model_dump(mode="json", exclude=set(_PRE_PASS_OMITTED)) for item in page.items
    ]
    return {**data, "items": items}


# --- Sessions ---


def inbox_sessions(project: Project) -> set[str]:
    """Every session that captured a link."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT DISTINCT session FROM inbox_items")).all()
    return {str(row[0]) for row in rows}


def _refuse_actor(project: Project, actor: Actor) -> None:
    """Refuse a system actor and any session that joined a screening or extraction pass."""
    if actor.kind not in ("human", "agent"):
        raise FactoryValidationError([ValidationIssue("actor", "a human or an agent")])
    if passes.is_pass_session(project, actor.session):
        raise FactoryValidationError(
            [ValidationIssue("session", "this session has joined a pass and cannot use the inbox")]
        )


# --- Capture ---


def _item_issues(
    actor: Actor, item: LinkInput
) -> tuple[LinkIdentifier | None, list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    identifier = parse_link(item.link)
    if identifier is None:
        issues.append(ValidationIssue("link", UNSUPPORTED_LINK))
    if actor.kind == "agent":
        if item.note is not None:
            issues.append(ValidationIssue("note", "an agent capture gives a basis, not a note"))
        if item.basis is None:
            issues.append(ValidationIssue("basis", "an agent capture must give a basis"))
    else:
        if item.basis is not None:
            issues.append(ValidationIssue("basis", "only an agent capture gives a basis"))
        if item.note is not None and len(item.note) > MAX_NOTE:
            issues.append(ValidationIssue("note", f"at most {MAX_NOTE} characters"))
    return identifier, issues


def _as_sent(item: LinkInput) -> dict[str, JsonValue]:
    sent: dict[str, JsonValue] = {"link": item.link}
    if item.note is not None:
        sent["note"] = item.note
    if item.basis is not None:
        sent["basis"] = item.basis.model_dump(mode="json")
    return sent


def add_links(
    project: Project, actor: Actor, items: Sequence[LinkInput], channel: Channel
) -> BatchResult[str]:
    """Capture links as inbox items. Offline: no source is contacted and no protocol is needed.

    Each valid item writes one `inbox.link_added`; invalid ones are returned with their index
    and issues (`link: unsupported-link`, `note`, `basis`). Returns the new item ids in order.
    """
    _refuse_actor(project, actor)
    written: list[str] = []
    rejected: list[ItemError] = []
    with project.index.exclusive():
        project.index.sync()
        events = []
        for index, item in enumerate(items):
            identifier, issues = _item_issues(actor, item)
            if issues or identifier is None:
                rejected.append(ItemError(index=index, issues=issues))
                continue
            note = item.note.strip() if item.note is not None and item.note.strip() else None
            item_id = project.ids.new("inb")
            payload = InboxLinkAdded(
                item_id=item_id,
                route=InboxRoute.LINK,
                link=stored_link(item.link),
                identifier_kind=identifier.kind,
                identifier_value=identifier.value,
                identifier_version=identifier.version,
                note=note,
                basis=item.basis,
                channel=channel,
            )
            input_blob = project.blobs.put_json(_as_sent(item)) if actor.kind == "agent" else None
            events.append(
                project.events.make(
                    "inbox.link_added", payload, actor, refs=(item_id,), input_blob=input_blob
                )
            )
            written.append(item_id)
        if events:
            project.record(events)
    return BatchResult[str](written=written, rejected=rejected)


# --- Withdrawal ---


def withdraw_link(project: Project, actor: Actor, item_id: str, reason: str) -> None:
    """Withdraw an open item (human only). A resolved or withdrawn item cannot be withdrawn."""
    if actor.kind != "human":
        raise FactoryValidationError([ValidationIssue("actor", "withdrawal is a human act")])
    issues: list[ValidationIssue] = []
    if not reason.strip():
        issues.append(ValidationIssue("reason", "must not be blank"))
    with project.index.exclusive():
        project.index.sync()
        if _status(project, item_id) != "open":
            issues.append(ValidationIssue("item_id", "not an open inbox item"))
        if issues:
            raise FactoryValidationError(issues)
        payload = InboxLinkWithdrawn(item_id=item_id, reason=reason.strip())
        project.record(
            [project.events.make("inbox.link_withdrawn", payload, actor, refs=(item_id,))]
        )


# --- Resolution ---


@dataclass(frozen=True)
class _Item:
    item_id: str
    kind: IdentifierKind
    value: str
    actor_kind: str


def lookup_query(kind: IdentifierKind, value: str) -> QuerySpec:
    """The `supplied` lookup for one identifier, built as the seed lookup is: arXiv by id, else
    OpenAlex by DOI or work id."""
    if kind is IdentifierKind.ARXIV:
        return QuerySpec(
            source="arxiv", kind=QueryKind.ID_LIST, text=value, purpose=QueryPurpose.SUPPLIED
        )
    prefix = "doi" if kind is IdentifierKind.DOI else "openalex"
    return QuerySpec(
        source="openalex",
        kind=QueryKind.FILTER,
        text=f"{prefix}:{value}",
        purpose=QueryPurpose.SUPPLIED,
    )


def resolve_links(
    project: Project,
    actor: Actor,
    *,
    sources: Mapping[str, SourceFactory],
    item_ids: Sequence[str] | None = None,
    deviation_id: str | None = None,
) -> list[ResolveOutcome]:
    """Look up open items (all, or `item_ids`) in id order, one recorded `supplied` query each.

    Each item is authorised on its own, with `supplied_by` the kind of actor that captured it; a
    refused item is returned with its issues and writes nothing. An attempted item records one
    `inbox.link_resolved`: `new` or `in-corpus` (the found work already had non-probe
    provenance before the run) for exactly one work, `ambiguous` for several (never truncated
    to one, R-21), `not-found` for none on a complete run, `failed` for none on an incomplete
    run (the item stays open and may be resolved again).

    An `item_ids` entry that is not an open item refuses the whole call before anything runs.
    """
    _refuse_actor(project, actor)
    project.index.sync()
    items = _open_items(project)
    if item_ids is not None:
        wanted = set(item_ids)
        issues = [
            ValidationIssue(f"item_ids.{n}", "not an open inbox item")
            for n, item_id in enumerate(item_ids)
            if item_id not in {item.item_id for item in items}
        ]
        if issues:
            raise FactoryValidationError(issues)
        items = [item for item in items if item.item_id in wanted]
    return [_resolve_one(project, actor, item, sources, deviation_id) for item in items]


def _resolve_one(
    project: Project,
    actor: Actor,
    item: _Item,
    sources: Mapping[str, SourceFactory],
    deviation_id: str | None,
) -> ResolveOutcome:
    query = lookup_query(item.kind, item.value)
    supplied_by: SubmitterKind = "human" if item.actor_kind == "human" else "agent"
    with project.index.exclusive():
        project.index.sync()
        issues = query_issues(project, query, sources)
        issues += search_authorization(
            project, query, deviation_id=deviation_id, supplied_by=supplied_by
        )
    if issues:
        return ResolveOutcome(item_id=item.item_id, status=None, issues=issues)
    before = _corpus_keys(project)
    query_id = register_query(
        project, actor, query, sources=sources, deviation_id=deviation_id, inbox_item=item.item_id
    )
    run = run_query(project, query_id, sources=sources, actor=actor)
    works = _run_works(project, run.run_id)
    work_id: str | None = None
    if len(works) > 1:
        status = ResolveStatus.AMBIGUOUS
    elif works:
        work_id = works[0]
        in_corpus = _in_corpus(project, work_id, before)
        status = ResolveStatus.IN_CORPUS if in_corpus else ResolveStatus.NEW
    elif run.status is RunStatus.COMPLETE:
        status = ResolveStatus.NOT_FOUND
    else:
        status = ResolveStatus.FAILED
    payload = InboxLinkResolved(
        item_id=item.item_id,
        query_id=query_id,
        run_id=run.run_id,
        status=status,
        work_id=work_id,
        deviation_id=deviation_id,
    )
    refs = tuple(ref for ref in (item.item_id, query_id, run.run_id, work_id) if ref is not None)
    with project.index.exclusive():
        project.index.sync()
        if _status(project, item.item_id) != "open":
            issue = ValidationIssue(
                "item_id", "closed while its lookup ran; the query and run are recorded"
            )
            return ResolveOutcome(
                item_id=item.item_id, status=None, run_id=run.run_id, issues=[issue]
            )
        input_blob = (
            project.blobs.put_json({"item_id": item.item_id, "deviation_id": deviation_id})
            if actor.kind == "agent"
            else None
        )
        project.record(
            [
                project.events.make(
                    "inbox.link_resolved", payload, actor, refs=refs, input_blob=input_blob
                )
            ]
        )
    return ResolveOutcome(item_id=item.item_id, status=status, work_id=work_id, run_id=run.run_id)


def _run_works(project: Project, run_id: str) -> list[str]:
    """The distinct works a run's provenance names, sorted."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT DISTINCT work_id FROM provenance WHERE run_id = :run ORDER BY work_id"),
            {"run": run_id},
        ).all()
    return [str(row[0]) for row in rows]


def _work_keys(work: Work) -> set[str]:
    """A work's id and its normalised identifiers: the keys dedup would merge it by."""
    ids = work.identifiers
    keys = {work.id}
    if ids.doi:
        bridged = arxiv_id_from_doi(ids.doi)
        keys.add(f"arxiv:{bridged}" if bridged else f"doi:{normalize_doi(ids.doi)}")
    if ids.arxiv:
        keys.add(f"arxiv:{normalize_arxiv(ids.arxiv)}")
    if ids.openalex:
        keys.add(f"openalex:{normalize_openalex(ids.openalex)}")
    return keys


def _corpus_keys(project: Project) -> set[str]:
    """The keys of every corpus work (non-probe provenance)."""
    return {key for work in list_works(project) for key in _work_keys(work)}


def _in_corpus(project: Project, work_id: str, before: set[str]) -> bool:
    """Whether the found work was in the corpus before the run: same id or a shared identifier."""
    work = get_work(project, work_id)
    return work is not None and bool(_work_keys(work) & before)


def _open_items(project: Project) -> list[_Item]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT item_id, identifier_kind, identifier_value, actor_kind FROM inbox_items"
                " WHERE status = 'open' ORDER BY item_id"
            )
        ).all()
    return [
        _Item(str(item_id), IdentifierKind(str(kind)), str(value), str(actor_kind))
        for item_id, kind, value, actor_kind in rows
    ]


def _status(project: Project, item_id: str) -> str | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT status FROM inbox_items WHERE item_id = :item"), {"item": item_id}
        ).one_or_none()
    return None if row is None else str(row[0])


# --- Listing ---


def list_items(
    project: Project,
    *,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = PAGE_LIMIT,
) -> InboxPage:
    """Items in id order with their last resolution attempt; `cursor` is a decimal offset."""
    issues: list[ValidationIssue] = []
    if status is not None and status not in ITEM_STATUSES:
        issues.append(ValidationIssue("status", f"must be one of: {', '.join(ITEM_STATUSES)}"))
    if cursor is not None and not (cursor.isascii() and cursor.isdigit()):
        issues.append(ValidationIssue("cursor", "must be a decimal offset"))
    if issues:
        raise FactoryValidationError(issues)
    start = int(cursor) if cursor is not None else 0
    size = min(max(limit, 1), PAGE_LIMIT)
    project.index.sync()
    sql = (
        "SELECT i.item_id, i.route, i.link, i.identifier_kind, i.identifier_value,"
        " i.identifier_version, i.actor_kind, i.channel, i.basis, i.note, i.status,"
        " (SELECT r.status FROM inbox_resolutions r WHERE r.item_id = i.item_id"
        "  ORDER BY r.event_id DESC LIMIT 1),"
        " (SELECT r.work_id FROM inbox_resolutions r WHERE r.item_id = i.item_id"
        "  ORDER BY r.event_id DESC LIMIT 1)"
        " FROM inbox_items i"
    )
    params: dict[str, object] = {"limit": size + 1, "offset": start}
    if status is not None:
        sql += " WHERE i.status = :status"
        params["status"] = status
    sql += " ORDER BY i.item_id LIMIT :limit OFFSET :offset"
    with project.index.connect() as conn:
        rows = conn.execute(text(sql), params).all()
    views = [
        InboxItemView(
            item_id=str(r[0]),
            route=str(r[1]),
            link=str(r[2]),
            identifier_kind=str(r[3]),
            identifier_value=str(r[4]),
            identifier_version=None if r[5] is None else str(r[5]),
            actor_kind=str(r[6]),
            channel=str(r[7]),
            basis_kind=None if r[8] is None else Basis.model_validate_json(str(r[8])).kind,
            note=None if r[9] is None else str(r[9]),
            status=str(r[10]),
            last_outcome=None if r[11] is None else str(r[11]),
            work_id=None if r[12] is None else str(r[12]),
        )
        for r in rows
    ]
    more = len(views) > size
    return InboxPage(items=views[:size], next_cursor=str(start + size) if more else None)
