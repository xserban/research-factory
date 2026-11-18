"""Read-only tools for a chat session: quote verification and the outline of a work (plan chat T4a).

Invariants:
- Nothing is written. The index is synced before reading.
- `chat_verify` checks each quote with `quote_in_element` against the Markdown of exactly the
  named anchor's element in the pinned conversion (the manifest entry, as the record paths of
  mining and extraction check it; a table cell is its own element). Results are in item order.
- A conversion id named explicitly must be a conversion of that work, else `no-conversion`; with
  none named, the work's default conversion serves. `conversion_id` and `markdown_hash` of a
  result are those actually used, None when the check did not get that far.
- `chat_sections` lists the section anchors of the pinned conversion in document order. Depth is
  the number of dot-separated parts of the anchor id after `s`; `paragraphs` and `words` count only
  the paragraph anchors whose parent is that section.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text

from factory.document.anchors import AnchorKind, Manifest
from factory.document.quotes import quote_in_element
from factory.errors import FactoryValidationError, ValidationIssue
from factory.services.context import Project
from factory.services.conversions import conversion_manifest, conversion_of
from factory.services.document_read import default_conversion

__all__ = [
    "SectionEntry",
    "VerifyItem",
    "VerifyResult",
    "WorkOutline",
    "chat_sections",
    "chat_verify",
]

_HEADING_MARK = re.compile(r"^\s*#+\s*")


@dataclass(frozen=True)
class VerifyItem:
    """One quote to verify: `quote` in the element `anchor` of `work_id` (default conversion when
    `conversion_id` is None)."""

    work_id: str
    anchor: str
    quote: str
    conversion_id: str | None = None


@dataclass(frozen=True)
class VerifyResult:
    """The outcome for one item: `status` is `accepted`, `unknown-work`, `no-conversion`,
    `anchor-missing` or `quote-not-in-anchor`."""

    item: VerifyItem
    status: str
    conversion_id: str | None
    markdown_hash: str | None


@dataclass(frozen=True)
class SectionEntry:
    """One section: anchor id, heading plain text, depth, paragraphs directly in it and their
    words."""

    anchor: str
    heading: str
    depth: int
    paragraphs: int
    words: int


@dataclass(frozen=True)
class WorkOutline:
    """The section outline of one pinned conversion."""

    work_id: str
    conversion_id: str
    markdown_hash: str
    sections: tuple[SectionEntry, ...]


def _is_work(project: Project, work_id: str) -> bool:
    with project.index.connect() as conn:
        row = conn.execute(text("SELECT 1 FROM works WHERE work_id = :w"), {"w": work_id}).first()
    return row is not None


def _pin(project: Project, work_id: str, conversion_id: str | None) -> tuple[str, str] | None:
    """(conversion id, markdown hash) serving `work_id`, or None when it has none or the named one
    is not a conversion of that work. The caller has synced the index."""
    if conversion_id is None:
        ref = default_conversion(project, work_id)
        if ref is None:
            return None
        conversion_id = ref.conversion_id
    found = conversion_of(project, conversion_id)
    if found is None or found.work_id != work_id:
        return None
    return conversion_id, found.markdown_hash


def chat_verify(project: Project, items: Sequence[VerifyItem]) -> list[VerifyResult]:
    """Verify each item's quote against its anchor's element; results follow the item order.

    Read-only; see the module invariants. A damaged stored conversion reads as `no-conversion`."""
    project.index.sync()
    manifests: dict[str, Manifest | None] = {}
    results: list[VerifyResult] = []
    for item in items:
        if not _is_work(project, item.work_id):
            results.append(VerifyResult(item, "unknown-work", None, None))
            continue
        pin = _pin(project, item.work_id, item.conversion_id)
        if pin is None:
            results.append(VerifyResult(item, "no-conversion", None, None))
            continue
        conversion_id, markdown_hash = pin
        if conversion_id not in manifests:
            try:
                manifests[conversion_id] = conversion_manifest(project, conversion_id)
            except FactoryValidationError:
                manifests[conversion_id] = None
        manifest = manifests[conversion_id]
        if manifest is None:
            results.append(VerifyResult(item, "no-conversion", None, None))
            continue
        anchor = manifest.get(item.anchor)
        if anchor is None:
            status = "anchor-missing"
        elif quote_in_element(anchor.text, item.quote):
            status = "accepted"
        else:
            status = "quote-not-in-anchor"
        results.append(VerifyResult(item, status, conversion_id, markdown_hash))
    return results


def chat_sections(project: Project, work_id: str, conversion_id: str | None = None) -> WorkOutline:
    """The section outline of the work's pinned conversion (see the module invariants).

    Raises `FactoryValidationError` on field `work_id` for an unknown work, and on field
    `conversion_id` when the work has no conversion, the named one is not its conversion, or its
    stored blobs are damaged."""
    project.index.sync()
    if not _is_work(project, work_id):
        raise FactoryValidationError([ValidationIssue("work_id", f"{work_id}: unknown work")])
    pin = _pin(project, work_id, conversion_id)
    if pin is None:
        raise FactoryValidationError(
            [ValidationIssue("conversion_id", f"{work_id}: no such conversion of this work")]
        )
    pinned, markdown_hash = pin
    manifest = conversion_manifest(project, pinned)
    sections: list[SectionEntry] = []
    for anchor in manifest.anchors:
        if anchor.kind is not AnchorKind.SECTION:
            continue
        paragraphs = [
            p for p in manifest.anchors if p.kind is AnchorKind.PARAGRAPH and p.parent == anchor.id
        ]
        sections.append(
            SectionEntry(
                anchor=anchor.id,
                heading=_HEADING_MARK.sub("", anchor.text).strip(),
                depth=len(anchor.id.removeprefix("s").split(".")),
                paragraphs=len(paragraphs),
                words=sum(len(p.text.split()) for p in paragraphs),
            )
        )
    return WorkOutline(work_id, pinned, markdown_hash, tuple(sections))
