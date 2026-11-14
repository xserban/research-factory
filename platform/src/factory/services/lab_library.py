"""Adopting documents another project acquired, and keeping literature once per lab (deploy-C).

Invariants:
- Adoption is an explicit act, never tried by a fetch. It needs a work the title/abstract screening
  promoted, a source document of that very work, a source project the principal may read
  (`may_read_project`: not `private`, or a member), and bytes that the lab library holds and that
  hash to the document's ref. A refusal writes nothing; an unreadable source is refused as one that
  does not exist.
- A document whose provenance is `researcher-supplied` is adopted only from a source project that
  the adopting project's owner confirmed (`library.source_confirmed`).
- Adoption writes, in one append inside `project.writing()`: `fulltext.fetch_started`, a
  `lab-library` `fulltext.attempted`, `fulltext.document_added`, `fulltext.adopted`, and a
  `document.converted` per adopted conversion whose blobs the lab library holds (same hashes; no
  converter runs). PRISMA, status and restore read these as for any document.
- Nothing is written to the source project. Its index may be refreshed, as the portfolio does.
  Nothing here reads seed records or held-out rates of the source.
- `consolidate` verifies the lab copy by hash before it removes a project copy, and keeps every
  copy that failed verification. It writes no event.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import JsonValue
from sqlalchemy import text

from factory.errors import FactoryError, FactoryValidationError, ValidationIssue
from factory.events.blobs import BlobIntegrityError, BlobNotFoundError
from factory.events.envelope import Actor, Event
from factory.events.library import LabLibrary
from factory.model.document import Converted
from factory.model.fulltext import (
    Attempted,
    AttemptOutcome,
    DocumentAdded,
    FetchStarted,
    LicenceStatus,
    Quality,
    Route,
)
from factory.model.identity import IdGenerator
from factory.model.lab_library import FulltextAdopted, SourceConfirmed
from factory.model.members import ProjectRole
from factory.model.screening import Channel
from factory.services.access import Permission, require_actor
from factory.services.context import Principal, Project, list_projects, open_project
from factory.services.fulltext import _Document, _documents, _live, _promoted
from factory.services.human_channel import require_human_channel
from factory.services.members import roles_of
from factory.services.region_adoption import source_readable
from factory.services.work_ref import resolve_work_id

__all__ = [
    "AdoptionCandidate",
    "ConsolidateReport",
    "adopt",
    "adoptable",
    "adoption_sources_missing",
    "confirm_source",
    "consolidate",
    "library_status",
    "may_read_project",
]

_UNREADABLE = "source-unreadable"


def _refuse(field_name: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field_name, reason)])


@dataclass(frozen=True)
class AdoptionCandidate:
    """A document of the same work that a readable project of the lab holds in the lab library."""

    source_project: str
    document_id: str
    route: str
    quality: str
    provenance: str
    licence_status: str
    conversions: int
    confirmed: bool
    """Whether this project's owner confirmed the source (only matters for researcher-supplied)."""


@dataclass(frozen=True)
class _SourceDoc:
    document_id: str
    work_id: str
    route: str
    quality: str
    source_version: str
    raw_hash: str
    media_type: str
    attempt_id: str
    provenance: str
    superseded: bool
    licence: str | None
    licence_status: str
    conversions: tuple[Converted, ...]


def may_read_project(source: Project, principal: Principal) -> bool:
    """Whether `principal` reads `source`: it is not `private`, or the person is a member."""
    return source_readable(source, principal.user)


def _open_source(project: Project, slug: str) -> Project:
    """A reader's handle on another project of this root, or the refusal of an unreadable one: a
    missing project and a private one read the same."""
    if slug == project.paths.slug:
        raise _refuse("source_project", "source-is-this-project")
    try:
        source = open_project(
            project.settings,
            slug,
            session=IdGenerator(project.clock).ulid(),
            clock=project.clock,
            principal=project.principal,
        )
        readable = may_read_project(source, project.principal)
    except FactoryError:
        raise _refuse("source_project", _UNREADABLE) from None
    if not readable:
        raise _refuse("source_project", _UNREADABLE)
    return source


def _source_document(source: Project, document_id: str) -> _SourceDoc | None:
    source.index.sync()
    with source.index.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT d.document_id, d.work_id, d.route, d.quality, d.source_version, "
                    "d.raw_hash, d.media_type, d.attempt_id, d.provenance, d.superseded_by, "
                    "a.licence, a.licence_status FROM fulltext_documents d "
                    "LEFT JOIN fulltext_attempts a ON a.attempt_id = d.attempt_id "
                    "WHERE d.document_id = :doc"
                ),
                {"doc": document_id},
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        conversions = conn.execute(
            text(
                "SELECT conversion_id, document_id, converter, converter_version, raw_hash, "
                "markdown_hash, manifest_hash, counts, warnings FROM document_conversions "
                "WHERE document_id = :doc ORDER BY event_id"
            ),
            {"doc": document_id},
        ).mappings()
        parsed = tuple(
            Converted(
                conversion_id=str(c["conversion_id"]),
                document_id=str(c["document_id"]),
                converter=str(c["converter"]),
                converter_version=str(c["converter_version"]),
                raw_hash=str(c["raw_hash"]),
                markdown_hash=str(c["markdown_hash"]),
                manifest_hash=str(c["manifest_hash"]),
                counts=json.loads(str(c["counts"])),
                warnings=json.loads(str(c["warnings"])),
            )
            for c in conversions
        )
    licence = row["licence"]
    return _SourceDoc(
        document_id=str(row["document_id"]),
        work_id=str(row["work_id"]),
        route=str(row["route"]),
        quality=str(row["quality"]),
        source_version=str(row["source_version"]),
        raw_hash=str(row["raw_hash"]),
        media_type=str(row["media_type"]),
        attempt_id=str(row["attempt_id"]),
        provenance=str(row["provenance"]),
        superseded=row["superseded_by"] is not None,
        licence=None if licence is None else str(licence),
        licence_status=str(row["licence_status"] or LicenceStatus.NOT_REPORTED.value),
        conversions=parsed,
    )


def _confirmed_sources(project: Project) -> set[str]:
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT source_project FROM library_source_confirmations")).all()
    return {str(row[0]) for row in rows}


def _lab_holds(project: Project, ref: str) -> bool:
    """Whether the lab library holds `ref` and the bytes hash to it."""
    lab = project.library.lab
    if lab is None or not lab.exists(ref):
        return False
    try:
        lab.get(ref)
    except (BlobNotFoundError, BlobIntegrityError, OSError):
        return False
    return True


def adoptable(project: Project, work_id: str) -> list[AdoptionCandidate]:
    """Live documents of `work_id` in other projects that the principal may read and whose bytes
    the lab library holds, in project then event order. An unreadable source is absent."""
    project.index.sync()
    work_id = resolve_work_id(project, work_id)
    if work_id not in _promoted(project):
        raise _refuse("work_id", "not promoted at title/abstract")
    confirmed = _confirmed_sources(project)
    found: list[AdoptionCandidate] = []
    for slug in list_projects(project.settings):
        if slug == project.paths.slug:
            continue
        try:
            source = _open_source(project, slug)
            source.index.sync()
            with source.index.connect() as conn:
                ids = [
                    str(r[0])
                    for r in conn.execute(
                        text(
                            "SELECT document_id FROM fulltext_documents "
                            "WHERE work_id = :w AND superseded_by IS NULL ORDER BY event_id"
                        ),
                        {"w": work_id},
                    )
                ]
        except FactoryError:
            continue
        for document_id in ids:
            doc = _source_document(source, document_id)
            if doc is None or not _lab_holds(project, doc.raw_hash):
                continue
            found.append(
                AdoptionCandidate(
                    source_project=slug,
                    document_id=doc.document_id,
                    route=doc.route,
                    quality=doc.quality,
                    provenance=doc.provenance,
                    licence_status=doc.licence_status,
                    conversions=len(doc.conversions),
                    confirmed=slug in confirmed,
                )
            )
    return found


def adopt(
    project: Project,
    actor: Actor,
    work_id: str,
    source_project: str,
    source_doc: str,
) -> str:
    """Adopt `source_doc` of `source_project` as this project's document for `work_id`; return the
    new document's id.

    Refused with nothing written (fields `permission`, `work_id`, `source_project`, `source_doc`,
    `library`): the actor lacks `work:run`; the work is not promoted; the source is this project or
    unreadable; the document is unknown, superseded, of another work or already held; the lab
    library has no verified bytes; a researcher-supplied document comes from an unconfirmed
    source."""
    require_actor(project, actor, Permission.WORK_RUN)
    project.index.sync()
    work_id = resolve_work_id(project, work_id)
    source = _open_source(project, source_project)
    doc = _source_document(source, source_doc)
    if doc is None or doc.work_id != work_id or doc.superseded:
        raise _refuse("source_doc", "no live document of this work in the source project")
    request: JsonValue = {
        "work_id": work_id,
        "source_project": source_project,
        "source_doc": source_doc,
    }
    with project.writing():
        project.index.sync()
        if work_id not in _promoted(project):
            raise _refuse("work_id", "not promoted at title/abstract")
        if project.library.lab is None:
            raise _refuse("library", "no lab library: run `factory library consolidate` first")
        if not _lab_holds(project, doc.raw_hash):
            raise _refuse("library", "the lab library does not hold the document's bytes")
        held = _documents(project, work_id)
        if any(d.raw_hash == doc.raw_hash for d in held):
            raise _refuse("source_doc", "this project already holds these bytes for the work")
        if doc.provenance == "researcher-supplied" and source_project not in _confirmed_sources(
            project
        ):
            raise _refuse(
                "source_project", "researcher-supplied: the owner must confirm the source"
            )
        blob = project.blobs.put_json(request) if actor.kind == "agent" else None
        events = _adoption_events(project, actor, work_id, source_project, doc, held, blob)
        project.record(events)
    return _new_document(events)


def _new_document(events: list[Event]) -> str:
    for event in events:
        if event.type == "fulltext.document_added":
            return str(event.payload["document_id"])
    raise AssertionError("an adoption always adds a document")


def _adoption_events(
    project: Project,
    actor: Actor,
    work_id: str,
    source_project: str,
    doc: _SourceDoc,
    held: list[_Document],
    blob: str | None,
) -> list[Event]:
    fetch_id = project.ids.new("fft")
    attempt_id = project.ids.new("att")
    document_id = project.ids.new("doc")
    system = project.system_actor()
    licence = doc.licence if doc.licence_status == LicenceStatus.REPORTED.value else None
    events = [
        project.events.make(
            "fulltext.fetch_started",
            FetchStarted(
                fetch_id=fetch_id, work_ids=[work_id], routes=[Route.LAB_LIBRARY], refresh=False
            ),
            actor,
            refs=(fetch_id,),
            input_blob=blob,
        ),
        project.events.make(
            "fulltext.attempted",
            Attempted(
                attempt_id=attempt_id,
                fetch_id=fetch_id,
                work_id=work_id,
                route=Route.LAB_LIBRARY,
                url=None,
                outcome=AttemptOutcome.RETRIEVED,
                reason=None,
                retrieved_at=project.clock.now(),
                source_version=doc.source_version,
                licence=licence,
                licence_status=LicenceStatus(doc.licence_status),
                media_type=doc.media_type,
                raw_hash=doc.raw_hash,
                document_id=document_id,
            ),
            system,
            refs=(attempt_id, work_id),
        ),
        project.events.make(
            "fulltext.document_added",
            DocumentAdded(
                document_id=document_id,
                work_id=work_id,
                route=Route.LAB_LIBRARY,
                quality=Quality(doc.quality),
                source_version=doc.source_version,
                raw_hash=doc.raw_hash,
                media_type=doc.media_type,
                attempt_id=attempt_id,
                provenance="researcher-supplied"
                if doc.provenance == "researcher-supplied"
                else "retrieved",
                supersedes=_live(held, Route.LAB_LIBRARY),
            ),
            system,
            refs=(document_id, work_id, attempt_id),
        ),
    ]
    adopted: list[str] = []
    converted: list[Event] = []
    for conversion in doc.conversions:
        if not (
            _lab_holds(project, conversion.markdown_hash)
            and _lab_holds(project, conversion.manifest_hash)
        ):
            continue
        adopted.append(conversion.conversion_id)
        conversion_id = project.ids.new("cnv")
        converted.append(
            project.events.make(
                "document.converted",
                conversion.model_copy(
                    update={"conversion_id": conversion_id, "document_id": document_id}
                ),
                system,
                refs=(document_id, conversion_id),
            )
        )
    events.append(
        project.events.make(
            "fulltext.adopted",
            FulltextAdopted(
                work_id=work_id,
                source_project=source_project,
                source_doc=doc.document_id,
                source_attempt=doc.attempt_id,
                document_id=document_id,
                attempt_id=attempt_id,
                sha256=doc.raw_hash,
                licence_status=LicenceStatus(doc.licence_status),
                conversions=tuple(adopted),
            ),
            actor,
            refs=(document_id, work_id, attempt_id, source_project),
            input_blob=blob,
        )
    )
    return [*events, *converted]


def confirm_source(
    project: Project,
    actor: Actor,
    source_project: str,
    reason: str,
    channel: Channel = Channel.CLI,
) -> str:
    """The owner confirms `source_project` as a source of researcher-supplied documents (once);
    return the event id, or the earlier event's when already confirmed.

    Refused with nothing written (fields `actor`, `permission`, `source_project`, `reason`,
    `channel`): not a person; not the project's owner; an unreadable source; a blank reason."""
    if actor.kind != "human":
        raise _refuse("actor", "only a person confirms a source")
    _open_source(project, source_project)
    with project.writing():
        require_human_channel(project, actor, channel, "sign-off")
        if ProjectRole.OWNER not in roles_of(project, actor.user):
            raise _refuse("permission", "only an owner confirms a source")
        with project.index.connect() as conn:
            earlier = conn.execute(
                text("SELECT event_id FROM library_source_confirmations WHERE source_project = :s"),
                {"s": source_project},
            ).scalar_one_or_none()
        if earlier is not None:
            return str(earlier)
        try:
            payload = SourceConfirmed(source_project=source_project, reason=reason)
        except ValueError as exc:
            raise _refuse("reason", str(exc)) from exc
        event = project.events.make(
            "library.source_confirmed", payload, actor, refs=(source_project,)
        )
        project.record([event])
        return event.id


def adoption_sources_missing(project: Project) -> list[tuple[str, str]]:
    """(document id, work id) of each adoption whose source project or source document is gone from
    this root. A source the principal may not read is not reported: nothing can be said of it."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT document_id, work_id, source_project, source_doc "
                "FROM fulltext_adoptions ORDER BY event_id"
            )
        ).all()
    missing: list[tuple[str, str]] = []
    for document_id, work_id, slug, source_doc in rows:
        try:
            source = open_project(
                project.settings,
                str(slug),
                session=IdGenerator(project.clock).ulid(),
                clock=project.clock,
                principal=project.principal,
            )
        except FactoryError:
            missing.append((str(document_id), str(work_id)))
            continue
        try:
            if not may_read_project(source, project.principal):
                continue
            if _source_document(source, str(source_doc)) is None:
                missing.append((str(document_id), str(work_id)))
        except FactoryError:
            continue
    return missing


@dataclass(frozen=True)
class ConsolidateReport:
    """What `consolidate` did: files moved, files the lab already held (verified, then removed from
    the project), and project copies kept because they failed verification."""

    moved: int = 0
    already: int = 0
    kept: list[str] = field(default_factory=list)


def _local_files(root: Path) -> list[tuple[str, Path]]:
    """(ref, path) of each blob file of a store, by its place. Temporary files are skipped."""
    base = root / "sha256"
    if not base.is_dir():
        return []
    found: list[tuple[str, Path]] = []
    for path in sorted(base.glob("??/*")):
        if path.is_file() and ".tmp-" not in path.name:
            found.append((f"sha256:{path.parent.name}{path.name}", path))
    return found


def consolidate(project: Project) -> ConsolidateReport:
    """Move this project's local library files into the lab library by hash (ruling 5).

    Each file is hashed; one whose content does not match its name is kept and reported. The lab
    copy is written (or found) and read back through the hash before the project copy is removed.
    The lab library directory is created when absent. No event is written."""
    lab = project.library.lab
    if lab is None:
        lab = _create_lab(project)
    moved = already = 0
    kept: list[str] = []
    with project.writing():
        for ref, path in _local_files(project.paths.library_dir):
            try:
                data = path.read_bytes()
            except OSError:
                kept.append(ref)
                continue
            if f"sha256:{hashlib.sha256(data).hexdigest()}" != ref:
                kept.append(ref)
                continue
            present = lab.exists(ref)
            try:
                if not present:
                    lab.put_verified(ref, data)
                verified = lab.get(ref) == data
            except (BlobNotFoundError, BlobIntegrityError, OSError):
                verified = False
            if not verified:
                kept.append(ref)
                continue
            try:
                path.unlink()
            except OSError:
                kept.append(ref)
                continue
            if present:
                already += 1
            else:
                moved += 1
    return ConsolidateReport(moved=moved, already=already, kept=kept)


def _create_lab(project: Project) -> LabLibrary:
    lab = LabLibrary(project.settings.root)
    lab.directory.mkdir(parents=True, exist_ok=True)
    return lab


def library_status(project: Project) -> dict[str, int]:
    """Counts: documents, adoptions, project-local files not yet consolidated, and references the
    lab library cannot serve. Read from the projection and the file tree."""
    project.index.sync()
    with project.index.connect() as conn:
        documents = conn.execute(text("SELECT COUNT(*) FROM fulltext_documents")).scalar_one()
        adoptions = conn.execute(text("SELECT COUNT(*) FROM fulltext_adoptions")).scalar_one()
    from factory.index.library import referenced_hashes

    unserved = sum(1 for ref in referenced_hashes(project.index) if not project.library.exists(ref))
    return {
        "documents": int(documents),
        "adoptions": int(adoptions),
        "local_files": len(_local_files(project.paths.library_dir)),
        "unserved": unserved,
    }
