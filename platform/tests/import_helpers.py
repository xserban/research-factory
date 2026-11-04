"""Shared setup for the Import-B tests: imports of synthetic BibTeX over the scripted lookups.

Every title, author and identifier is invented.
"""

from __future__ import annotations

from pathlib import Path

from factory.events.envelope import Actor
from factory.imports.model import ImportFormat
from factory.model.imports import ImportRole
from factory.model.protocol import LibrarySource
from factory.services.context import Project
from factory.services.imports import record_import
from factory.services.protocol import amend_protocol, current_protocol
from tests.references_service_helpers import Lookups, oa_item

LIBRARY = LibrarySource(name="default", format=ImportFormat.BIBTEX, role=ImportRole.CORPUS)


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


def declare_library(project: Project, actor: Actor, *sources: LibrarySource) -> None:
    """Amend the current protocol to declare `sources` (default: the unnamed BibTeX corpus)."""
    old = current_protocol(project)
    assert old is not None
    new = old.spec.model_copy(update={"library_sources": sources or (LIBRARY,)})
    amend_protocol(project, actor, new, reason="declare the library", semantic=True, effects={})


def admit_lookups() -> Lookups:
    """Sources that know the works the admission fixtures resolve to."""
    return Lookups(
        openalex=[oa_item("Sedge Mapping Methods", "Ana Kim", 2015, "W504", doi="10.9999/sedge.1")]
    )


def admission_records(corpus_doi: str) -> list[str]:
    """Four records: one found by identifier outside the corpus, one titled with no identifier,
    one already in the corpus (by DOI) and one with neither title nor identifier."""
    return [
        bib_entry(
            "a", "Sedge Mapping Methods", year=2015, author="Kim, Ana", doi="10.9999/sedge.1"
        ),
        bib_entry("b", "Wholly unknown matters here", year=2001, author="Nobody, Cora"),
        bib_entry("c", "Already Here", year=2020, author="Zhou, Ada", doi=corpus_doi),
        "@misc{d, year={2001}}\n",
    ]
