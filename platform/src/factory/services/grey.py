"""Grey literature (plan SG, PD-7, decision 113): what the protocol declares and what was found.

Grey methods are provenance methods appended after `library-import`, so no existing PRISMA count
moves. A work counts as grey when it carries a grey provenance method. Nothing here judges: the
counts are computed from provenance and the protocol.

Invariants:
- A project whose protocol declares no `grey_sources` reports no grey line anywhere.
- The `included` flag of a declared source only labels; it never removes a work from the corpus.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

import httpx
from pydantic import JsonValue, ValidationError
from sqlalchemy import bindparam, text

from factory.canonical import canonical_json
from factory.document.html_generic import WEB_CAPTURE_HTML
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.grey import GreyContactLogged, GreyMethod, GreySearchReported, GreySource
from factory.model.inbox import Basis
from factory.model.screening import Channel
from factory.model.search import QueryKind, QueryPurpose, QuerySpec
from factory.model.work import ProvenanceMethod
from factory.services.context import Project
from factory.services.fulltext import record_supplied_document
from factory.services.inbox import LinkInput, add_links
from factory.services.protocol import current_protocol
from factory.services.search import register_query, run_query
from factory.sources.http import fetch_page
from factory.sources.registry import SourceFactory
from factory.sources.webcapture import NAME as WEBCAPTURE
from factory.sources.webcapture import WebCaptureSource

GREY_METHOD_VALUES: tuple[str, ...] = (
    ProvenanceMethod.GREY_STRUCTURED.value,
    ProvenanceMethod.GREY_WEBSITE.value,
    ProvenanceMethod.GREY_WEB_SEARCH.value,
    ProvenanceMethod.EXPERT_CONTACT.value,
)


def declared_sources(project: Project) -> tuple[GreySource, ...]:
    """The current protocol's `grey_sources`, or an empty tuple while the section is absent."""
    current = current_protocol(project)
    if current is None or current.spec.grey_sources is None:
        return ()
    return current.spec.grey_sources


def grey_work_ids(project: Project) -> frozenset[str]:
    """Every work carrying a grey provenance method (before dedup canonicalisation)."""
    project.index.sync()
    sql = text("SELECT DISTINCT work_id FROM provenance WHERE method IN :methods").bindparams(
        bindparam("methods", expanding=True)
    )
    with project.index.connect() as conn:
        rows = conn.execute(sql, {"methods": list(GREY_METHOD_VALUES)}).all()
    return frozenset(str(row[0]) for row in rows)


def grey_paragraph(sources: tuple[GreySource, ...], *, reported: int = 0, contacts: int = 0) -> str:
    """The PRISMA-S paragraph for grey sources: each declared source with its stopping rule.

    Agent web searches are reported by the agent and are not verifiable here; the paragraph
    says so."""
    parts = ["Grey literature. Sources declared in the protocol:"]
    for source in sources:
        pooled = "pooled" if source.included else "reported separately"
        parts.append(
            f" {source.method.value} ({source.target}; stopping rule: {source.stopping_rule}; "
            f"{pooled});"
        )
    body = "".join(parts).rstrip(";") + "."
    if reported or contacts:
        body += (
            f" Web searches reported by the agent: {reported}; expert contacts logged: {contacts}."
            " Reported searches were run outside the platform and are not reproducible from it."
        )
    return body


# --- Capture (Task 5) ---

_CAPTURE_HEADERS = ("content-type", "last-modified", "etag", "date", "content-length")
MAX_CAPTURE_BYTES = 50_000_000


@dataclass(frozen=True)
class CaptureResult:
    """What one capture recorded: the run, the work, the document (None when these exact bytes
    were already captured for the work), the bytes' hash and whether the work is new."""

    run_id: str
    work_id: str
    document_id: str | None
    sha256: str
    media_type: str
    new_work: bool


def _media_type(content_type: str, body: bytes) -> str | None:
    base = content_type.split(";")[0].strip().lower()
    if base == "application/pdf" or body[:5] == b"%PDF-":
        return "application/pdf"
    if base in ("text/html", "application/xhtml+xml"):
        return WEB_CAPTURE_HTML
    return None


def capture_url(
    project: Project,
    actor: Actor,
    url: str,
    *,
    source_id: str,
    title: str,
    fetch: Callable[[str], httpx.Response] | None = None,
    deviation_id: str | None = None,
) -> CaptureResult:
    """Fetch `url` once into the project library and record it as a grey `website` work.

    `source_id` names a declared `website` entry of `grey_sources` (the gate re-checks it; a
    deviation may waive it). The fetch runs outside any lock; bytes go to the library only, and
    the event log holds the hash, timestamp and a few response headers. A PDF is recorded with
    `application/pdf` and converts through the PDF converter; an HTML page with the capture media
    type and `html-generic`. A repeat capture whose bytes changed is a new document of the same
    work (superseding the earlier), never an overwrite; identical bytes record nothing new.
    """
    issues: list[ValidationIssue] = []
    parts = urlsplit(url)
    if parts.scheme == "http":
        issues.append(
            ValidationIssue(
                "url",
                "an https URL: the outbound guard refuses http, so an http page cannot be fetched",
            )
        )
    elif parts.scheme != "https" or not parts.netloc:
        issues.append(ValidationIssue("url", "an https URL"))
    if not title.strip():
        issues.append(ValidationIssue("title", "must not be blank"))
    declared = any(
        s.method is GreyMethod.WEBSITE and s.target == source_id for s in declared_sources(project)
    )
    if not declared and deviation_id is None:
        issues.append(ValidationIssue("source_id", "not a declared website grey source"))
    if issues:
        raise FactoryValidationError(issues)
    try:
        response = (fetch or fetch_page)(url)
    except (httpx.HTTPError, OSError) as exc:
        raise FactoryValidationError([ValidationIssue("url", f"fetch failed: {exc}")]) from exc
    body = response.content
    if len(body) > MAX_CAPTURE_BYTES:
        raise FactoryValidationError([ValidationIssue("url", "page exceeds the capture limit")])
    media_type = _media_type(response.headers.get("content-type", ""), body)
    if media_type is None:
        raise FactoryValidationError(
            [ValidationIssue("url", "not a PDF or HTML page; nothing was recorded")]
        )
    digest = hashlib.sha256(body).hexdigest()
    headers: dict[str, JsonValue] = {
        k: response.headers[k] for k in _CAPTURE_HEADERS if k in response.headers
    }
    filters = {
        "source_id": source_id,
        "title": title.strip(),
        "sha256": f"sha256:{digest}",
        "captured_at": project.clock.now().isoformat(),
        "status": str(response.status_code),
        "headers": canonical_json(headers).decode(),
    }
    spec = QuerySpec(
        source=WEBCAPTURE,
        kind=QueryKind.FILTER,
        text=url,
        purpose=QueryPurpose.GREY,
        filters=filters,
    )
    adapters = {
        WEBCAPTURE: SourceFactory(
            WebCaptureSource.kinds, lambda _settings, clock: WebCaptureSource(clock=clock)
        )
    }
    query_id = register_query(project, actor, spec, sources=adapters, deviation_id=deviation_id)
    summary = run_query(project, query_id, sources=adapters, actor=actor)
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT work_id FROM provenance WHERE run_id = :r"), {"r": summary.run_id}
        ).first()
    if row is None:
        raise FactoryValidationError([ValidationIssue("url", "the capture run recorded no work")])
    work_id = str(row[0])
    with project.index.exclusive():
        project.index.sync()
        document_id = record_supplied_document(
            project,
            work_id,
            content=body,
            source_version=f"web:{digest[:12]}",
            media_type=media_type,
            actor=project.system_actor(),
        )
    return CaptureResult(
        run_id=summary.run_id,
        work_id=work_id,
        document_id=document_id,
        sha256=f"sha256:{digest}",
        media_type=media_type,
        new_work=summary.new_works > 0,
    )


# --- Reported searches and expert contact (Task 6) ---


@dataclass(frozen=True)
class ReportOutcome:
    """What a reported search or contact wrote: its id and the inbox items its URLs became
    (`offered`) against the URLs the inbox could not parse to an identifier (`unparsed`)."""

    record_id: str
    offered: tuple[str, ...]
    unparsed: tuple[str, ...]


def _offer(project: Project, actor: Actor, urls: tuple[str, ...]) -> ReportOutcome | None:
    """Offer URLs to the inbox as capture-only items; never enrols a work."""
    if not urls:
        return None
    items = [
        LinkInput(url, basis=Basis(kind="knowledge") if actor.kind == "agent" else None)
        for url in urls
    ]
    result = add_links(project, actor, items, Channel.MCP if actor.kind == "agent" else Channel.CLI)
    unparsed = tuple(urls[e.index] for e in result.rejected)
    return ReportOutcome("", tuple(result.written), unparsed)


def _input_blob(project: Project, actor: Actor, sent: dict[str, JsonValue]) -> str | None:
    return project.blobs.put_json(sent) if actor.kind == "agent" else None


def report_search(
    project: Project,
    actor: Actor,
    *,
    target: str,
    engine: str,
    query: str,
    timestamp: datetime,
    urls: Sequence[str],
    stopping_rule: str,
) -> ReportOutcome:
    """Record a web search run in the agent (an explicit R-21 exception, PD-7).

    `target` must be a declared `agent-web-search` entry of `grey_sources`; the run states its own
    `stopping_rule`. The platform cannot verify the search: the event records what the agent said.
    Its URLs are offered to the inbox (an identifier is parsed, anything else is listed as
    unparsed); no work is enrolled by this call. Writes happen under `project.writing()`; the
    inbox offer follows as its own recorded step.
    """
    issues: list[ValidationIssue] = []
    if actor.kind not in ("agent", "human"):
        issues.append(ValidationIssue("actor", "a human or an agent"))
    if not any(
        s.method is GreyMethod.AGENT_WEB_SEARCH and s.target == target
        for s in declared_sources(project)
    ):
        issues.append(ValidationIssue("target", "not a declared agent-web-search grey source"))
    unique = tuple(dict.fromkeys(u.strip() for u in urls if u.strip()))
    try:
        payload = GreySearchReported(
            report_id=project.ids.new("grs"),
            target=target,
            engine=engine,
            query=query,
            timestamp=timestamp,
            urls=unique,
            stopping_rule=stopping_rule,
        )
    except ValidationError as exc:
        issues.extend(ValidationIssue(".".join(map(str, e["loc"])), e["msg"]) for e in exc.errors())
    if issues:
        raise FactoryValidationError(issues)
    sent: dict[str, JsonValue] = payload.model_dump(mode="json")
    with project.writing():
        project.record(
            [
                project.events.make(
                    "grey.search_reported",
                    payload,
                    actor,
                    refs=(payload.report_id,),
                    input_blob=_input_blob(project, actor, sent),
                )
            ]
        )
    offered = _offer(project, actor, unique)
    if offered is None:
        return ReportOutcome(payload.report_id, (), ())
    return ReportOutcome(payload.report_id, offered.offered, offered.unparsed)


def log_contact(
    project: Project,
    actor: Actor,
    *,
    target: str,
    contacted_on: datetime,
    summary: str,
    urls: Sequence[str] = (),
) -> ReportOutcome:
    """Log an expert contact. `target` must be a declared `expert-contact` entry. The log holds a
    label and a summary, never an address; its URLs are offered to the inbox as for a search."""
    issues: list[ValidationIssue] = []
    if not any(
        s.method is GreyMethod.EXPERT_CONTACT and s.target == target
        for s in declared_sources(project)
    ):
        issues.append(ValidationIssue("target", "not a declared expert-contact grey source"))
    unique = tuple(dict.fromkeys(u.strip() for u in urls if u.strip()))
    try:
        payload = GreyContactLogged(
            contact_id=project.ids.new("grc"),
            target=target,
            contacted_on=contacted_on,
            summary=summary,
            urls=unique,
        )
    except ValidationError as exc:
        issues.extend(ValidationIssue(".".join(map(str, e["loc"])), e["msg"]) for e in exc.errors())
    if issues:
        raise FactoryValidationError(issues)
    sent: dict[str, JsonValue] = payload.model_dump(mode="json")
    with project.writing():
        project.record(
            [
                project.events.make(
                    "grey.contact_logged",
                    payload,
                    actor,
                    refs=(payload.contact_id,),
                    input_blob=_input_blob(project, actor, sent),
                )
            ]
        )
    offered = _offer(project, actor, unique)
    if offered is None:
        return ReportOutcome(payload.contact_id, (), ())
    return ReportOutcome(payload.contact_id, offered.offered, offered.unparsed)


def reported_counts(project: Project) -> tuple[int, int]:
    """(reported searches, logged contacts), for the methods text."""
    project.index.sync()
    with project.index.connect() as conn:
        searches = conn.execute(text("SELECT COUNT(*) FROM grey_searches")).scalar_one()
        contacts = conn.execute(text("SELECT COUNT(*) FROM grey_contacts")).scalar_one()
    return int(searches), int(contacts)


def reported_only_sources(project: Project) -> list[str]:
    """Declared, pooled `agent-web-search` targets with reports while no `structured` or
    `website` source of the protocol has yielded a work: the evidence rests on reports alone
    (review focus 2). Empty while nothing was reported."""
    sources = declared_sources(project)
    project.index.sync()
    with project.index.connect() as conn:
        reported = {
            str(r[0]) for r in conn.execute(text("SELECT DISTINCT target FROM grey_searches")).all()
        }
        verifiable = conn.execute(
            text("SELECT 1 FROM provenance WHERE method IN (:a, :b) LIMIT 1"),
            {
                "a": ProvenanceMethod.GREY_STRUCTURED.value,
                "b": ProvenanceMethod.GREY_WEBSITE.value,
            },
        ).first()
    if verifiable is not None:
        return []
    return sorted(
        s.target
        for s in sources
        if s.method is GreyMethod.AGENT_WEB_SEARCH and s.included and s.target in reported
    )
