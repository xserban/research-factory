"""Shared setup for the Import-B tests: imports of synthetic BibTeX over the scripted lookups.

Every title, author and identifier is invented.
"""

from __future__ import annotations

from pathlib import Path

from factory.imports.model import ImportFormat
from factory.model.imports import ImportRole
from factory.services.context import Project
from factory.services.imports import record_import


def bib_entry(key: str, title: str, *, year: int, author: str, doi: str | None = None) -> str:
    extra = f", doi={{{doi}}}" if doi else ""
    return f"@article{{{key}, title={{{title}}}, author={{{author}}}, year={{{year}}}{extra}}}\n"


def import_bib(
    project: Project,
    tmp_path: Path,
    entries: list[str],
    *,
    role: ImportRole = ImportRole.CORPUS,
    collection: str | None = None,
    name: str = "lib.bib",
    split: bool = False,
) -> str:
    """Record a BibTeX export of `entries` (unsplit by default) and return its import id."""
    path = tmp_path / name
    path.write_text("".join(entries))
    return record_import(
        project,
        path,
        format=ImportFormat.BIBTEX,
        role=role,
        collection=collection,
        split=split,
    ).import_id
