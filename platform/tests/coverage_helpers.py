"""A constructed project for the coverage tests: a promoted database corpus and an import whose
records fall in every bucket. Every title, author and identifier is invented.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from factory.events.envelope import Actor
from factory.model.protocol import Limit
from factory.model.search import QueryKind, QueryPurpose, QuerySpec
from factory.services.context import Project
from factory.services.import_resolve import resolve_import
from factory.services.protocol import amend_protocol, current_protocol, record_deviation
from factory.services.search import register_query, run_query
from tests.import_helpers import bib_entry, import_bib
from tests.references_service_helpers import Lookups, oa_item

MISS_DOI = "10.7777/miss.{n}"
FOUND_DOI = "10.1000/p{n}"


@dataclass
class Coverage:
    project: Project
    import_id: str
    lookups: Lookups


def found_database(n: int) -> str:
    """A record of a work the database search found (the `corpus` fixture's Paper n)."""
    return bib_entry(
        f"f{n}", f"Paper {n}", year=2020, author="Zhou, Ada", doi=FOUND_DOI.format(n=n)
    )


def query_miss(n: int, *, year: int = 2018) -> str:
    """A record of a work OpenAlex knows (the lookups return it) that no search found."""
    return bib_entry(
        f"m{n}",
        f"Missed Study {n} Of Reeds",
        year=year,
        author="Kim, Ana",
        doi=MISS_DOI.format(n=n),
    )


def miss_item(n: int, *, year: int = 2018) -> dict[str, object]:
    return oa_item(
        f"Missed Study {n} Of Reeds", "Ana Kim", year, f"W9{n}", doi=MISS_DOI.format(n=n)
    )


def not_in_sources(n: int) -> str:
    """A DOI record that OpenAlex was asked about and does not return."""
    return bib_entry(
        f"n{n}", f"Absent Study {n} Of Moss", year=2019, author="Roe, Sam", doi=f"10.7777/none.{n}"
    )


def unchecked(n: int) -> str:
    """An arXiv-only record: the OpenAlex-only protocol never asked a source about it."""
    return (
        f"@misc{{u{n}, title={{Unchecked Preprint {n} Of Ferns}}, author={{Lee, Jo}}, "
        f"year={{2019}}, eprint={{2401.0000{n}}}, archiveprefix={{arXiv}}}}\n"
    )


def set_limits(project: Project, actor: Actor, *limits: Limit) -> None:
    old = current_protocol(project)
    assert old is not None
    new = old.spec.model_copy(update={"limits": tuple(limits)})
    amend_protocol(project, actor, new, reason="set limits", semantic=True, effects={})


def run_other_purpose(
    project: Project,
    actor: Actor,
    lookups: Lookups,
    purpose: QueryPurpose,
    text: str,
    kind: QueryKind = QueryKind.FILTER,
) -> None:
    """Run one openalex query of `purpose` under a recorded deviation (the protocol plans none)."""
    deviation = record_deviation(project, actor, description="extra route", reason="test")
    spec = QuerySpec(source="openalex", kind=kind, text=text, purpose=purpose)
    query_id = register_query(
        project, actor, spec, sources=lookups.sources(), deviation_id=deviation
    )
    run_query(project, query_id, sources=lookups.sources())


def build(
    project: Project,
    tmp_path: Path,
    entries: list[str],
    lookups: Lookups,
    *,
    split: bool = False,
) -> Coverage:
    """Record the import of `entries` and resolve it over `lookups`."""
    import_id = import_bib(project, tmp_path, entries, split=split)
    resolve_import(project, import_id, sources=lookups.sources())
    return Coverage(project, import_id, lookups)
