"""The offline `importlist` source (Import-B task 3): stored import records become works.

Every record is invented. The reader is scripted.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from factory.canonical import canonical_json
from factory.clock import FixedClock
from factory.model.imports import ImportAdmissionPlanned, PlannedImportQuery
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.work import ProvenanceMethod, WorkType
from factory.model.work_ids import work_id
from factory.services.context import Project
from factory.services.search import register_query, run_query
from factory.sources.base import RawPage, SourceError
from factory.sources.importlist import ImportlistEntry, ImportlistSource, entry_keys
from factory.sources.registry import INTERFACES, importlist_factory
from tests.import_helpers import bib_entry, import_bib

IMP = "imp_01JZ9Q3K5M7N8P0R2S4T6V8W1A"
KEY_A = f"{IMP}:3"
KEY_B = f"{IMP}:4"
RUN = "run_01JZ9Q3K5M7N8P0R2S4T6V8W1C"
QUERY = "qry_01JZ9Q3K5M7N8P0R2S4T6V8W1D"
SHA = "ab" * 32

ENTRY_A = ImportlistEntry(
    key=KEY_A,
    title="Sparse kernels for tidal data",
    first_author="Thornbury",
    year=2019,
    doi="10.5555/jim.4",
    arxiv=None,
    url=None,
    venue="Imaginary Methods",
    record_sha256=SHA,
)
ENTRY_B = ImportlistEntry(
    key=KEY_B,
    title="Moss growth under filtered light",
    first_author=None,
    year=None,
    doi=None,
    arxiv=None,
    url=None,
    venue=None,
    record_sha256="cd" * 32,
)


def _run(text: str, known: Mapping[str, ImportlistEntry]) -> tuple[object, list[RawPage]]:
    pages: list[RawPage] = []

    def read(keys: Sequence[str]) -> dict[str, ImportlistEntry]:
        return {k: known[k] for k in keys if k in known}

    def archive(page: RawPage) -> str:
        pages.append(page)
        return "sha256:" + "0" * 64

    clock = FixedClock(datetime(2026, 11, 5, 12, 0, tzinfo=UTC))
    source = ImportlistSource(read, clock=clock)
    spec = QuerySpec(
        source="importlist", kind=QueryKind.ID_LIST, text=text, purpose=QueryPurpose.IMPORT
    )
    return source.run(spec, run_id=RUN, query_id=QUERY, archive=archive), pages


def test_importlist_builds_works_from_fields_only() -> None:
    result, pages = _run(f"{KEY_A},{KEY_B}", {KEY_A: ENTRY_A, KEY_B: ENTRY_B})
    assert result.status is RunStatus.COMPLETE  # type: ignore[attr-defined]
    first, second = result.works  # type: ignore[attr-defined]
    assert first.type is WorkType.OTHER and first.abstract is None
    assert first.id == work_id(
        title="Sparse kernels for tidal data",
        authors=["Thornbury"],
        year=2019,
        doi="10.5555/jim.4",
    )
    assert second.id == work_id(title="Moss growth under filtered light", authors=[], year=None)
    assert second.dates.year is None
    prov = first.provenance[0]
    assert prov.source == "importlist" and prov.method is ProvenanceMethod.LIBRARY_IMPORT
    assert prov.raw_ref == KEY_A and prov.run_id == RUN and prov.query_id == QUERY
    [page] = pages
    body = json.loads(page.body)
    assert page.body.encode() == canonical_json(body)
    assert [e["key"] for e in body["entries"]] == [KEY_A, KEY_B]
    assert set(body["entries"][0]) == {
        "key",
        "title",
        "first_author",
        "year",
        "doi",
        "arxiv",
        "url",
        "venue",
        "abstract",  # the record's abstract is kept (9d84d59, PD-4)
        "record_sha256",
    }
    assert page.url.startswith("importlist:") and page.ordinal == 0


@pytest.mark.parametrize(
    "text",
    [",", "rex_01JZ9Q3K5M7N8P0R2S4T6V8W1A:1", f"{IMP}:0", f"{IMP}:x", f"{KEY_A},{KEY_A}"],
)
def test_importlist_malformed_key_fails_run(text: str) -> None:
    with pytest.raises(SourceError):
        _run(text, {KEY_A: ENTRY_A})
    with pytest.raises(SourceError):
        entry_keys(text)


def test_importlist_shortfall_named() -> None:
    result, _ = _run(f"{KEY_A},{KEY_B}", {KEY_A: ENTRY_A})
    assert result.reported_count == 2 and result.retrieved_count == 1  # type: ignore[attr-defined]
    assert KEY_B in (result.note or "")  # type: ignore[attr-defined]


def test_importlist_takes_id_list_only() -> None:
    source = ImportlistSource(lambda _k: {}, clock=FixedClock(datetime(2026, 11, 5, tzinfo=UTC)))
    spec = QuerySpec(source="importlist", kind=QueryKind.KEYWORD, text="x")
    with pytest.raises(SourceError):
        source.run(spec, run_id=RUN, query_id=QUERY, archive=lambda _p: "sha256:" + "0" * 64)


def test_importlist_is_registered_with_an_interface() -> None:
    assert "importlist" in INTERFACES
    factory = importlist_factory(lambda _k: {})
    assert factory.kinds == frozenset({QueryKind.ID_LIST})


def test_failed_run_when_the_planned_text_is_malformed(
    explore_project: Project, tmp_path: Path
) -> None:
    project = explore_project
    imp = import_bib(project, tmp_path, [bib_entry("a", "Made-Up Pears", year=2019, author="Q, A")])
    spec = QuerySpec(
        source="importlist", kind=QueryKind.ID_LIST, text="not-a-key", purpose=QueryPurpose.IMPORT
    )
    payload = ImportAdmissionPlanned(
        import_id=imp,
        queries=(PlannedImportQuery(source="importlist", kind=spec.kind, text=spec.text),),
    )
    project.record(
        [project.events.make("import.admission_planned", payload, project.human_actor())]
    )
    sources = {"importlist": importlist_factory(lambda _k: {})}
    query_id = register_query(project, project.human_actor(), spec, sources=sources, import_id=imp)
    run = run_query(project, query_id, sources=sources)
    assert run.status is RunStatus.FAILED
