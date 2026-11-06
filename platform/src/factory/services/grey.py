"""Grey literature (plan SG, PD-7 provisional): what the protocol declares and what was found.

Grey methods are provenance methods appended after `library-import`, so no existing PRISMA count
moves. A work counts as grey when it carries a grey provenance method. Nothing here judges: the
counts are computed from provenance and the protocol.

Invariants:
- A project whose protocol declares no `grey_sources` reports no grey line anywhere.
- The `included` flag of a declared source only labels; it never removes a work from the corpus.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from pydantic import JsonValue
from sqlalchemy import bindparam, text

from factory.canonical import canonical_json
from factory.document.html_generic import WEB_CAPTURE_HTML
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.grey import GreyMethod, GreySource
from factory.model.search import QueryKind, QueryPurpose, QuerySpec
from factory.model.work import ProvenanceMethod
from factory.services.context import Project
from factory.services.fulltext import record_supplied_document
from factory.services.protocol import current_protocol
from factory.services.search import register_query, run_query
from factory.sources.http import PoliteClient
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
_CLIENT_NAME = "research-factory"
"""A generic client name. The contact address is never sent to a captured site."""
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


def _fetch(url: str) -> httpx.Response:
    client = PoliteClient(
        httpx.Client(timeout=60.0, follow_redirects=True, headers={"User-Agent": _CLIENT_NAME})
    )
    return client.get(url)


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
    if parts.scheme not in ("http", "https") or not parts.netloc:
        issues.append(ValidationIssue("url", "an http or https URL"))
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
        response = (fetch or _fetch)(url)
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
