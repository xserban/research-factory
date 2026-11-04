"""The offline `reflist` source (slice 3a, ruling 8): stored entries become `other`-type works.

Every entry is invented. The reader is scripted; the service's index reader is tested through
`tests/test_snowball_round.py`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

import pytest

from factory.canonical import canonical_json
from factory.clock import FixedClock
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.work import ProvenanceMethod, WorkType
from factory.model.work_ids import work_id
from factory.sources.base import RawPage, SourceError
from factory.sources.reflist import ReflistEntry, ReflistSource
from factory.sources.registry import INTERFACES, reflist_factory

KEY_A = "rex_01JZ9Q3K5M7N8P0R2S4T6V8W1A:3"
KEY_B = "rex_01JZ9Q3K5M7N8P0R2S4T6V8W1B:12"
RUN = "run_01JZ9Q3K5M7N8P0R2S4T6V8W1C"
QUERY = "qry_01JZ9Q3K5M7N8P0R2S4T6V8W1D"
SHA = "ab" * 32

ENTRY_A = ReflistEntry(
    key=KEY_A,
    title="Sparse kernels for tidal data",
    first_author="Thornbury",
    year=2019,
    doi="10.5555/jim.4",
    arxiv=None,
    url=None,
    venue="Imaginary Methods",
    entry_sha256=SHA,
)
ENTRY_B = ReflistEntry(
    key=KEY_B,
    title="Moss growth under filtered light",
    first_author=None,
    year=2008,
    doi=None,
    arxiv=None,
    url=None,
    venue=None,
    entry_sha256="cd" * 32,
)


def _reader(known: Mapping[str, ReflistEntry], asked: list[list[str]]) -> object:
    def read(keys: Sequence[str]) -> dict[str, ReflistEntry]:
        asked.append(list(keys))
        return {k: known[k] for k in keys if k in known}

    return read


def _run(text: str, known: Mapping[str, ReflistEntry]) -> tuple[object, list[RawPage]]:
    pages: list[RawPage] = []
    asked: list[list[str]] = []

    def archive(page: RawPage) -> str:
        pages.append(page)
        return "sha256:" + "0" * 64

    clock = FixedClock(datetime(2026, 11, 4, 12, 0, tzinfo=UTC))
    source = ReflistSource(_reader(known, asked), clock=clock)  # type: ignore[arg-type]
    spec = QuerySpec(
        source="reflist", kind=QueryKind.ID_LIST, text=text, purpose=QueryPurpose.CHASE
    )
    result = source.run(spec, run_id=RUN, query_id=QUERY, archive=archive)
    return result, pages


def test_reflist_turns_entries_into_other_type_works() -> None:
    result, _ = _run(f"{KEY_A},{KEY_B}", {KEY_A: ENTRY_A, KEY_B: ENTRY_B})
    assert result.status is RunStatus.COMPLETE  # type: ignore[attr-defined]
    assert result.reported_count == 2 and result.retrieved_count == 2  # type: ignore[attr-defined]
    first, second = result.works  # type: ignore[attr-defined]
    assert first.type is WorkType.OTHER and second.type is WorkType.OTHER
    assert first.id == work_id(
        title="Sparse kernels for tidal data",
        authors=["Thornbury"],
        year=2019,
        doi="10.5555/jim.4",
    )
    assert second.id == work_id(title="Moss growth under filtered light", authors=[], year=2008)
    prov = first.provenance[0]
    assert prov.source == "reflist" and prov.method is ProvenanceMethod.CITATION_CHASE
    assert prov.raw_ref == KEY_A and prov.run_id == RUN and prov.query_id == QUERY
    assert first.identifiers.doi == "10.5555/jim.4" and first.venue is not None
    assert first.dates.year == 2019 and first.abstract is None


def test_reflist_page_is_canonical_json_of_fields_and_hash() -> None:
    _, pages = _run(f"{KEY_B},{KEY_A}", {KEY_A: ENTRY_A, KEY_B: ENTRY_B})
    [page] = pages
    body = json.loads(page.body)
    assert page.body.encode() == canonical_json(body)
    assert [e["key"] for e in body["entries"]] == [KEY_A, KEY_B]  # sorted by key
    assert body["entries"][0]["entry_sha256"] == SHA
    assert set(body["entries"][0]) == {
        "key",
        "title",
        "first_author",
        "year",
        "doi",
        "arxiv",
        "url",
        "venue",
        "entry_sha256",
    }
    assert page.url.startswith("reflist:") and page.ordinal == 0


def test_unknown_keys_are_a_shortfall_with_a_note() -> None:
    result, _ = _run(f"{KEY_A},{KEY_B}", {KEY_A: ENTRY_A})
    assert result.reported_count == 2 and result.retrieved_count == 1  # type: ignore[attr-defined]
    assert result.status is RunStatus.COMPLETE  # type: ignore[attr-defined]
    assert KEY_B in str(result.note)  # type: ignore[attr-defined]


@pytest.mark.parametrize("text", ["rf:not-a-key", f"{KEY_A},{KEY_A}", " , "])
def test_malformed_query_is_a_source_error(text: str) -> None:
    with pytest.raises(SourceError):
        _run(text, {KEY_A: ENTRY_A})


def test_registry_names_the_interface_and_kinds() -> None:
    factory = reflist_factory(lambda keys: {})
    assert factory.kinds == frozenset({QueryKind.ID_LIST})
    assert "reflist" in INTERFACES
