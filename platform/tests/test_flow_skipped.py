"""Parsing of archived pages for the skipped-records reader, and the run gap arithmetic.

The index and blob reads are exercised on the pilot, not here; these tests pin the page readers
and the gap rule on fixed input.
"""

import pytest

from factory.services import flow_skipped
from factory.services.call_memo import entering
from factory.services.context import Project
from factory.services.flow_skipped import _arxiv_entries, _gap, _openalex_entries, _Run

_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>3</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2301.01234v2</id>
    <title>  A  Titled
      Paper </title>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2301.09999v1</id>
    <title></title>
  </entry>
  <entry>
    <title>No id but titled</title>
  </entry>
</feed>
"""


def test_arxiv_entries_normalise_id_and_collapse_title() -> None:
    entries = _arxiv_entries(_ATOM)
    assert [(e.native_id, e.title) for e in entries] == [
        ("2301.01234", "A Titled Paper"),
        ("2301.09999", None),
        (None, "No id but titled"),
    ]


def test_arxiv_entries_unparseable_page_yields_nothing() -> None:
    assert _arxiv_entries("<feed><entry>") == []


def test_openalex_entries_use_display_name_then_title() -> None:
    body = (
        '{"results": ['
        '{"id": "https://openalex.org/W1", "display_name": "First"},'
        '{"id": "https://openalex.org/W2", "title": "Second"},'
        '{"id": "https://openalex.org/W3", "display_name": ""},'
        '"not an object"]}'
    )
    entries = _openalex_entries(body)
    assert [(e.native_id, e.title) for e in entries] == [
        ("W1", "First"),
        ("W2", "Second"),
        ("W3", None),
    ]


def test_openalex_entries_non_object_payload_yields_nothing() -> None:
    assert _openalex_entries("[1, 2]") == []
    assert _openalex_entries("not json") == []


def _run(run_id: str, status: str, reported: int | None, retrieved: int) -> _Run:
    return _Run(
        run_id=run_id,
        query_id="qry_x",
        source="openalex",
        status=status,
        reported_count=reported,
        retrieved_count=retrieved,
        skipped=0,
        note=None,
    )


def test_gap_sums_resumed_runs_and_takes_last_reported() -> None:
    gap = _gap(
        "qry_x",
        [
            _run("run_1", "partial", 4074, 200),
            _run("run_2", "failed", None, 0),
            _run("run_3", "complete", 4074, 3872),
        ],
    )
    assert (gap.reported, gap.retrieved, gap.gap) == (4074, 4072, 2)
    assert [r.run_id for r in gap.runs] == ["run_1", "run_2", "run_3"]


def test_gap_is_none_when_no_run_reported_a_total() -> None:
    gap = _gap("qry_x", [_run("run_1", "failed", None, 0)])
    assert (gap.reported, gap.gap) == (None, None)


def test_archived_pages_and_runs_are_computed_once_per_call_scope(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"pages": 0, "runs": 0}
    real_pages = flow_skipped._archived_pages.__wrapped__  # type: ignore[attr-defined]
    real_runs = flow_skipped._search_runs.__wrapped__  # type: ignore[attr-defined]

    def pages(p: Project) -> dict[str, list[str]]:
        calls["pages"] += 1
        return real_pages(p)  # type: ignore[no-any-return]

    def runs(p: Project) -> list[flow_skipped._Run]:
        calls["runs"] += 1
        return real_runs(p)  # type: ignore[no-any-return]

    monkeypatch.setattr(flow_skipped._archived_pages, "__wrapped__", pages)
    monkeypatch.setattr(flow_skipped._search_runs, "__wrapped__", runs)
    with entering():
        flow_skipped.skipped_records(project)
        flow_skipped.run_gaps(project)
        flow_skipped._archived_pages(project)
    assert calls == {"pages": 1, "runs": 1}
