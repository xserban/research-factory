"""Conversions: the pure library and blob reads behind document reading (plan 2C).

`conversion_manifest` and `resolve_anchor` find one conversion by id and return its verified
manifest or one anchor. They apply no INCLUDED gate and no work scoping, so they must not be
exposed through a tool without that gate. This module imports neither `agreement` nor `screening`.

Invariants:
- Read-only: the index is only synced.
- A missing or damaged Markdown or manifest blob is refused, naming `factory document convert
  --restore`; the message never carries document text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from factory.document.anchors import Anchor, Manifest, ManifestError
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.blobs import BlobIntegrityError, BlobNotFoundError
from factory.model.fulltext import Quality, Route
from factory.services.context import Project

_RESTORE_HINT = "run `factory document convert --restore` to regenerate it"


@dataclass(frozen=True)
class Conversion:
    """A conversion joined to its document, as the projection holds them."""

    conversion_id: str
    document_id: str
    work_id: str
    route: Route
    quality: Quality
    source_version: str
    converter: str
    converter_version: str
    markdown_hash: str
    manifest_hash: str
    live: bool
    document_event_id: str
    conversion_event_id: str


_SELECT = (
    "SELECT c.conversion_id, c.document_id, d.work_id, d.route, d.quality, d.source_version, "
    "c.converter, c.converter_version, c.markdown_hash, c.manifest_hash, "
    "d.superseded_by, d.event_id AS document_event_id, c.event_id AS conversion_event_id "
    "FROM document_conversions c JOIN fulltext_documents d ON d.document_id = c.document_id"
)


def conversion_manifest(project: Project, conversion_id: str) -> Manifest:
    """The manifest of one conversion, read from the library and verified by hash.

    Both the Markdown and the manifest blob must be present and hash correctly, as in
    `document_read`. Raises `FactoryValidationError` on field `conversion_id` if the conversion is
    unknown or either blob is missing or damaged (naming `factory document convert --restore`).

    No INCLUDED gate and no work scoping apply: the conversion is found by id alone. Do not expose
    this through a tool without the gate of `document_read`.
    """
    project.index.sync()
    conversion = _find(project, "c.conversion_id = :cid", {"cid": conversion_id})
    if conversion is None:
        raise FactoryValidationError(
            [ValidationIssue("conversion_id", f"{conversion_id}: unknown conversion")]
        )
    return _load(project, conversion)


def conversion_document(project: Project, conversion_id: str) -> str | None:
    """The document a conversion belongs to, or None when the conversion is unknown. Read-only;
    the caller syncs the index."""
    found = _find(project, "c.conversion_id = :cid", {"cid": conversion_id})
    return None if found is None else found.document_id


def conversion_work(project: Project, conversion_id: str) -> str | None:
    """The work a conversion belongs to, or None when the conversion is unknown. Read-only; the
    caller syncs the index."""
    found = _find(project, "c.conversion_id = :cid", {"cid": conversion_id})
    return None if found is None else found.work_id


def resolve_anchor(project: Project, conversion_id: str, anchor_id: str) -> Anchor:
    """The anchor `anchor_id` of one conversion, exactly as its manifest holds it.

    Verifies the blobs as `conversion_manifest` does. Raises `FactoryValidationError` on field
    `conversion_id` if the conversion is unknown or damaged, and on field `anchor` if the conversion
    has no such anchor.

    No INCLUDED gate and no work scoping apply. Do not expose this through a tool without the gate.
    """
    manifest = conversion_manifest(project, conversion_id)
    return _anchor_or_refuse(manifest, anchor_id, conversion_id)


def _find(project: Project, where: str, params: dict[str, Any]) -> Conversion | None:
    rows = _query(project, where, params)
    return rows[-1] if rows else None


def _query(project: Project, where: str, params: dict[str, Any]) -> list[Conversion]:
    """Matching conversions, oldest first by conversion event id."""
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text(f"{_SELECT} WHERE {where} ORDER BY c.event_id"),
                params,
            )
            .mappings()
            .all()
        )
    return [
        Conversion(
            conversion_id=str(row["conversion_id"]),
            document_id=str(row["document_id"]),
            work_id=str(row["work_id"]),
            route=Route(str(row["route"])),
            quality=Quality(str(row["quality"])),
            source_version=str(row["source_version"]),
            converter=str(row["converter"]),
            converter_version=str(row["converter_version"]),
            markdown_hash=str(row["markdown_hash"]),
            manifest_hash=str(row["manifest_hash"]),
            live=row["superseded_by"] is None,
            document_event_id=str(row["document_event_id"]),
            conversion_event_id=str(row["conversion_event_id"]),
        )
        for row in rows
    ]


def _load(project: Project, conversion: Conversion) -> Manifest:
    """The conversion's manifest, after verifying that its Markdown and manifest blobs exist and
    hash correctly. The one loading path for `document_read`, `conversion_manifest` and
    `resolve_anchor`.

    A missing, mismatching, unreadable or unparseable blob is refused on field `conversion_id`,
    naming the restore command. The exception message is not carried, since it may name a path.
    """
    try:
        project.library.get(conversion.markdown_hash)
        return Manifest.from_json(project.library.get(conversion.manifest_hash))
    except (BlobNotFoundError, BlobIntegrityError, ManifestError, OSError) as exc:
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "conversion_id",
                    f"{conversion.conversion_id}: stored Markdown or manifest is missing or "
                    f"damaged; {_RESTORE_HINT}",
                )
            ]
        ) from exc


def _anchor_or_refuse(manifest: Manifest, anchor_id: str, conversion_id: str) -> Anchor:
    found = manifest.get(anchor_id)
    if found is None:
        raise FactoryValidationError(
            [ValidationIssue("anchor", f"{anchor_id}: not an anchor of {conversion_id}")]
        )
    return found
