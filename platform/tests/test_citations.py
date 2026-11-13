"""In-corpus citation counts (IDEA-57): rows are written straight into the projection, which this
test may do because the service only reads it."""

import json
from pathlib import Path

from sqlalchemy import text

from factory.services.citations import citation_report
from factory.services.context import Project


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
