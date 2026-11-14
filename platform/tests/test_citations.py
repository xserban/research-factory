"""In-corpus citation counts (IDEA-57): rows are written straight into the projection, which this
test may do because the service only reads it."""

import json
from pathlib import Path

import pytest
from sqlalchemy import text

from factory.services import citations, site_corpus
from factory.services.citations import citation_report
from factory.services.context import Project
from factory.services.site_explorer import build_explorer


def _work(project: Project, wid: str, title: str, year: int, authors: list[str]) -> None:
    data = {
        "title": title,
        "dates": {"published": f"{year}-01-01"},
        "authors": [{"name": a} for a in authors],
    }
    with project.index._engine.begin() as conn:
        conn.execute(
            text("INSERT INTO works (work_id, data, first_event_id) VALUES (:w, :d, 'e')"),
            {"w": wid, "d": json.dumps(data)},
        )


def _extraction(project: Project, xid: str, wid: str, n_entries: int, live: int = 1) -> None:
    with project.index._engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO reference_extractions (extraction_id, work_id, document_id, "
                "conversion_id, parser, parser_version, entry_anchors, source_quality, flags, "
                "marker_count, bbl_status, event_id, live) VALUES (:x, :w, 'd', 'c', 'p', '1', "
                "'[]', 'q', '[]', 0, 'none', 'e', :live)"
            ),
            {"x": xid, "w": wid, "live": live},
        )
        for i in range(1, n_entries + 1):
            conn.execute(
                text(
                    "INSERT INTO reference_entries (extraction_id, ordinal, anchor, entry_sha256, "
                    "title, year) VALUES (:x, :o, :a, :s, :t, 2020)"
                ),
                {
                    "x": xid,
                    "o": i,
                    "a": f"b{i}",
                    "s": f"{xid}{i}",
                    "t": f"Unlinked paper {xid} {i}",
                },
            )


def _link(project: Project, xid: str, ordinal: int, state: str, target: str | None) -> None:
    with project.index._engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO reference_links (extraction_id, ordinal, state, work_id, base_state, "
                "candidates, no_source_record, event_id, matcher_version) VALUES (:x, :o, :s, :w, "
                ":s, '[]', 0, 'e', '1')"
            ),
            {"x": xid, "o": ordinal, "s": state, "w": target},
        )


def test_unknown_not_zero_without_extractions(project: Project) -> None:
    _work(project, "rf:a", "A", 2020, ["Ann Lee"])
    rep = citation_report(project, as_of_year=2025)
    assert rep.extractions == 0
    assert [(w.cited_by, w.self_cited_by, w.per_year) for w in rep.works] == [(None, None, None)]


def test_counts_denominators_self_and_rate(project: Project) -> None:
    _work(project, "rf:a", "A", 2020, ["Ann Lee"])
    _work(project, "rf:b", "B", 2022, ["Ann  Lee", "Bo Chan"])
    _work(project, "rf:c", "C", 2023, ["Cy Dunn"])
    _extraction(project, "x1", "rf:b", 3)
    _extraction(project, "x2", "rf:c", 3)
    _extraction(project, "x3", "rf:a", 1, live=0)  # superseded: ignored
    _link(project, "x1", 1, "resolved", "rf:a")
    _link(project, "x1", 2, "resolved", "rf:a")  # same citing work: counted once
    _link(project, "x1", 3, "resolved", "rf:b")  # itself: ignored
    _link(project, "x2", 1, "resolved", "rf:a")
    _link(project, "x2", 2, "unconfirmed", "rf:b")  # not resolved
    _link(project, "x3", 1, "resolved", "rf:c")  # superseded extraction
    rep = citation_report(project, as_of_year=2025)
    assert (rep.works_total, rep.extractions, rep.entries, rep.resolved_links) == (3, 2, 6, 4)
    by = {w.work_id: w for w in rep.works}
    assert by["rf:a"].cited_by == 2 and by["rf:a"].citers == ("rf:b", "rf:c")
    assert by["rf:a"].self_cited_by == 1 and by["rf:a"].cited_by_excluding_self == 1
    assert by["rf:a"].per_year == 2 / 6
    assert by["rf:b"].cited_by == 0 and by["rf:c"].cited_by == 0


def test_candidates_are_cited_items_not_resolved(project: Project) -> None:
    _work(project, "rf:a", "A", 2020, [])
    _work(project, "rf:b", "B", 2021, [])
    _extraction(project, "x1", "rf:a", 2)
    _extraction(project, "x2", "rf:b", 1)
    _link(project, "x1", 1, "resolved", "rf:b")
    _link(project, "x1", 2, "unresolved", None)
    _link(project, "x2", 1, "unresolved", None)
    rep = citation_report(project, as_of_year=2025)
    titles = {c.title for c in rep.candidates}
    assert "Unlinked paper x1 2" in titles and "Unlinked paper x1 1" not in titles


def test_page_shows_denominators_and_unknown(project: Project, tmp_path: Path) -> None:
    from factory.services.site_citations import build_citations

    _work(project, "rf:a", "Alpha paper", 2020, [])
    build_citations(project, tmp_path)
    assert "every in-corpus count is unknown" in (tmp_path / "index.html").read_text()
    _work(project, "rf:b", "Beta paper", 2021, [])
    _extraction(project, "x1", "rf:b", 1)
    _link(project, "x1", 1, "resolved", "rf:a")
    build_citations(project, tmp_path)
    page = (tmp_path / "index.html").read_text()
    assert "1 entries, of which 1 resolved" in page and "Alpha paper" in page


def test_candidates_skip_items_without_year_or_identifier(project: Project) -> None:
    _work(project, "rf:a", "A", 2020, [])
    _extraction(project, "x1", "rf:a", 1)
    with project.index._engine.begin() as conn:
        conn.execute(text("UPDATE reference_entries SET year = NULL"))
    assert citation_report(project, as_of_year=2025).candidates == []


def _miner_row(project: Project, eid: str, wid: str, schema: str) -> None:
    """One live pass-A row of a listed miner, so the work enters the corpus payload."""
    with project.index._engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO extraction_rows (extraction_id, scope, pack, cited_extraction_id, "
                "cited_ordinal, cited_marker, work_id, pass_label, task_id, protocol_id, "
                "schema_ref, document_id, conversion_id, row_key, supersedes, superseded_by, "
                "event_id) VALUES (:e, 'evidence', NULL, NULL, NULL, NULL, :w, 'A', 't', 'p', "
                ":s, 'd', 'c', :e, NULL, NULL, 'e')"
            ),
            {"e": eid, "w": wid, "s": schema},
        )


@pytest.fixture
def listed_miners(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every default role's miner is listed, so works with a row of it are in the payload."""
    schemas = {name: f"{name}@1" for name in site_corpus.DEFAULT_ROLES.values()}
    monkeypatch.setattr(site_corpus, "_listed_schemas", lambda _project: schemas)


def _corpus_works(project: Project) -> dict[str, dict[str, object]]:
    payload = site_corpus.corpus_payload(project)
    return {str(w["id"]): w for w in payload["works"]}


def test_payload_carries_in_corpus_citations(project: Project, listed_miners: None) -> None:
    _work(project, "rf:a", "A", 2020, ["Ann Lee"])
    _work(project, "rf:b", "B", 2022, ["Bo Chan"])
    _work(project, "rf:c", "C", 2023, ["Cy Dunn"])
    for i, wid in enumerate(("rf:a", "rf:b", "rf:c"), start=1):
        _miner_row(project, f"m{i}", wid, "m-classification@1")
    _extraction(project, "x1", "rf:b", 2)
    _extraction(project, "x2", "rf:c", 1)
    _link(project, "x1", 1, "resolved", "rf:a")
    _link(project, "x1", 2, "resolved", "rf:a")  # same citing work: counted once
    _link(project, "x2", 1, "resolved", "rf:a")
    works = _corpus_works(project)
    assert works["rf:a"]["cited_in_corpus"] == 2
    assert works["rf:b"]["cited_in_corpus"] == 0
    assert works["rf:c"]["cited_in_corpus"] == 0


def test_payload_in_corpus_citations_are_unknown_without_extractions(
    project: Project, listed_miners: None
) -> None:
    _work(project, "rf:a", "A", 2020, [])
    _miner_row(project, "m1", "rf:a", "m-classification@1")
    assert _corpus_works(project)["rf:a"]["cited_in_corpus"] is None


def test_citation_report_is_computed_once_per_payload(
    project: Project, listed_miners: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _work(project, "rf:a", "A", 2020, [])
    _work(project, "rf:b", "B", 2021, [])
    _miner_row(project, "m1", "rf:a", "m-classification@1")
    _miner_row(project, "m2", "rf:b", "m-classification@1")
    calls: list[int] = []
    real = citations.citation_report

    def counting(project: Project, *, as_of_year: int) -> citations.CitationReport:
        calls.append(1)
        return real(project, as_of_year=as_of_year)

    monkeypatch.setattr(site_corpus, "citation_report", counting)
    site_corpus.corpus_payload(project)
    assert len(calls) == 1


def test_explorer_page_has_the_cited_by_filter(
    project: Project, listed_miners: None, tmp_path: Path
) -> None:
    _work(project, "rf:a", "A", 2020, [])
    _miner_row(project, "m1", "rf:a", "m-classification@1")
    build_explorer(project, tmp_path)
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert 'id="citemin"' in page
    assert "cited_in_corpus" in page
    assert "Cited by" in page
