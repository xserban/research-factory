"""The offline `stored` source (decision 135): stored works re-served with fresh provenance.

Every work is invented. The reader is scripted; the service's reader is tested through
`tests/test_snowball_backward_select.py`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime

import pytest

from factory.clock import FixedClock
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.work import Dates, Identifiers, Provenance, ProvenanceMethod, Work
from factory.sources.base import RawPage, SourceError
from factory.sources.registry import INTERFACES, stored_factory
from factory.sources.stored import NAME, StoredSource

RUN = "run_01JZ9Q3K5M7N8P0R2S4T6V8W1C"
QUERY = "qry_01JZ9Q3K5M7N8P0R2S4T6V8W1D"
OLD_RUN = "run_01JZ9Q3K5M7N8P0R2S4T6V8W1E"
OLD_QUERY = "qry_01JZ9Q3K5M7N8P0R2S4T6V8W1F"
BLOB = "sha256:" + "1" * 64


def _work(title: str, doi: str) -> Work:
    return Work.build(
        title=title,
        abstract="An invented abstract.",
        identifiers=Identifiers(doi=doi),
        dates=Dates(published=date(2025, 3, 1)),
        provenance=[
            Provenance(
                source="crossref",
                run_id=OLD_RUN,
                query_id=OLD_QUERY,
                at=datetime(2026, 1, 1, tzinfo=UTC),
                raw_blob=BLOB,
            )
        ],
    )


A = _work("Sparse kernels for tidal data", "10.5555/a.1")
B = _work("Moss growth under filtered light", "10.5555/b.2")


def _run(text: str, known: Mapping[str, Work]) -> tuple[object, list[RawPage]]:
    pages: list[RawPage] = []

    def read(ids: Sequence[str]) -> dict[str, Work]:
        return {i: known[i] for i in ids if i in known}

    def archive(page: RawPage) -> str:
        pages.append(page)
        return "sha256:" + "0" * 64

    source = StoredSource(read, clock=FixedClock(datetime(2026, 11, 18, 12, 0, tzinfo=UTC)))
    spec = QuerySpec(source=NAME, kind=QueryKind.ID_LIST, text=text, purpose=QueryPurpose.CHASE)
    return source.run(spec, run_id=RUN, query_id=QUERY, archive=archive), pages


def test_stored_works_are_served_with_one_fresh_provenance_row() -> None:
    result, pages = _run(f"{A.id},{B.id}", {A.id: A, B.id: B})
    assert result.status is RunStatus.COMPLETE and result.note is None  # type: ignore[attr-defined]
    works = result.works  # type: ignore[attr-defined]
    assert sorted(w.id for w in works) == sorted([A.id, B.id])
    for served, original in zip(
        sorted(works, key=lambda w: w.id), sorted([A, B], key=lambda w: w.id), strict=True
    ):
        assert served.title == original.title and served.abstract == original.abstract
        assert served.identifiers == original.identifiers and served.dates == original.dates
        [row] = served.provenance
        assert (row.source, row.run_id, row.query_id) == (NAME, RUN, QUERY)
        assert row.method is ProvenanceMethod.CITATION_CHASE and row.raw_ref == served.id
    [page] = pages
    assert [w["id"] for w in json.loads(page.body)["works"]] == sorted([A.id, B.id])


def test_a_missing_id_is_a_named_shortfall() -> None:
    result, _ = _run(f"{A.id},{B.id}", {A.id: A})
    assert [w.id for w in result.works] == [A.id]  # type: ignore[attr-defined]
    assert B.id in str(result.note)  # type: ignore[attr-defined]


@pytest.mark.parametrize("text", ["not-an-id", "rf:x", ","])
def test_a_malformed_text_is_a_source_error(text: str) -> None:
    with pytest.raises(SourceError):
        _run(text, {})


def test_a_repeated_id_is_a_source_error() -> None:
    with pytest.raises(SourceError):
        _run(f"{A.id},{A.id}", {A.id: A})


def test_the_factory_and_the_interface_text() -> None:
    assert INTERFACES[NAME].endswith("(offline)")
    assert stored_factory(lambda ids: {}).kinds == frozenset({QueryKind.ID_LIST})
