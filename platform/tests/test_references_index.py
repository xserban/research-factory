"""Projection of reference and snowball events: extractions, entries, links, contexts, rounds.

Events are recorded directly, as the other index tests do. Every entry is invented.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from factory.events.envelope import Event
from factory.index.chase import round_texts
from factory.index.default import PROJECTION_VERSION
from factory.model.chase import ChaseDirection, ChaseRoundStarted
from factory.model.references import (
    CitationContextsRecorded,
    ReferenceExtracted,
    ReferenceResolutionDecided,
    ReferenceResolved,
    SnowballRoundStarted,
)
from factory.services.context import Project
from tests.test_references_model import (
    BLOB,
    CITED,
    CNV,
    DOC,
    REX,
    RUN,
    SNW,
    WORK,
    entry,
    resolution,
    round_payload,
)

REX2 = "rex_01HZX3K4M5N6P7Q8R9S0TVWXZ0"
OTHER = "rf:lee2020-tokens-9f8e7d6c"


def _record(project: Project, type_: str, payload: Any) -> Event:
    event = project.events.make(type_, payload, project.system_actor())
    project.record([event])
    return event


def _rows(project: Project, sql: str) -> list[tuple[Any, ...]]:
    with project.index.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql)).all()]


def _extract(project: Project, rex: str = REX, n: int = 2, **kw: Any) -> Event:
    payload: dict[str, Any] = {
        "extraction_id": rex,
        "work_id": WORK,
        "document_id": DOC,
        "conversion_id": CNV,
        "parser": "refparse",
        "parser_version": "1",
        "entry_anchors": "b",
        "source_quality": "latex",
        "entries": [
            entry(i, doi="10.9999/invented.1" if i == 1 else None) for i in range(1, n + 1)
        ],
        "marker_count": n,
        "flags": ["marker-gap"],
        "bbl": {"status": "aligned", "archive_blob": BLOB, "bbl_count": n},
    }
    payload.update(kw)
    return _record(project, "reference.extracted", ReferenceExtracted.model_validate(payload))


def _resolve(project: Project, resolutions: list[dict[str, Any]], rex: str = REX) -> Event:
    payload = ReferenceResolved.model_validate(
        {
            "extraction_id": rex,
            "resolutions": resolutions,
            "matcher_version": "1",
            "lookup_runs": [RUN],
        }
    )
    return _record(project, "reference.resolved", payload)


def _decide(project: Project, decision: str, work_id: str | None, by: str | None) -> Event:
    quotes = []
    if decision.startswith("propose"):
        quotes = [
            {"side": "entry", "text": "An invented title"},
            {"side": "candidate", "text": "An Invented Title"},
        ]
    payload = ReferenceResolutionDecided.model_validate(
        {
            "extraction_id": REX,
            "ordinal": 2,
            "decision": decision,
            "work_id": work_id,
            "rationale": "invented rationale",
            "quotes": quotes,
            "confirmed_by": by,
        }
    )
    return _record(project, "reference.resolution_decided", payload)


FUZZY = resolution(
    2,
    state="unconfirmed",
    work_id=OTHER,
    method="source-title",
    confidence="title-fuzzy",
    score=0.91,
    candidates=[{"work_id": OTHER, "score": 0.91}],
    source_blob=BLOB,
)


def test_projection_version_pinned() -> None:
    assert PROJECTION_VERSION == "54"


def test_extraction_and_entries_projected_without_text(project: Project) -> None:
    event = _extract(project)
    assert _rows(
        project,
        "SELECT extraction_id, work_id, document_id, conversion_id, parser_version, entry_anchors,"
        " flags, marker_count, bbl_status, event_id, live FROM reference_extractions",
    ) == [(REX, WORK, DOC, CNV, "1", "b", '["marker-gap"]', 2, "aligned", event.id, 1)]
    entries = _rows(
        project,
        "SELECT ordinal, anchor, label, doi, year, first_author FROM reference_entries"
        " ORDER BY ordinal",
    )
    assert entries == [
        (1, "b1", "[1]", "10.9999/invented.1", 2019, "Smith"),
        (2, "b2", "[2]", None, 2019, "Smith"),
    ]
    columns = {row[1] for row in _rows(project, "PRAGMA table_info(reference_entries)")}
    assert "text" not in columns and "entry_sha256" in columns


def test_later_extraction_supersedes_links_in_projection(project: Project) -> None:
    _extract(project)
    _resolve(project, [resolution(1)])
    _extract(project, REX2, n=1)
    _extract(project)  # a repeated extraction id changes nothing (first write wins)
    assert _rows(
        project, "SELECT extraction_id, live FROM reference_extractions ORDER BY extraction_id"
    ) == [(REX, 0), (REX2, 1)]
    live_links = _rows(
        project,
        "SELECT l.ordinal FROM reference_links l JOIN reference_extractions x"
        " ON x.extraction_id = l.extraction_id WHERE x.live = 1",
    )
    assert live_links == []
    assert len(_rows(project, "SELECT * FROM reference_entries")) == 3


def test_resolution_first_write_wins(project: Project) -> None:
    _extract(project)
    _resolve(project, [resolution(1), FUZZY])
    _resolve(project, [resolution(1, work_id=OTHER)])
    assert _rows(
        project,
        "SELECT ordinal, state, work_id, method, confidence, score, source_blob, matcher_version,"
        " decision, confirmed_by, no_source_record FROM reference_links ORDER BY ordinal",
    ) == [
        (1, "resolved", CITED, "corpus-identifier", "identifier", 1.0, None, "1", None, None, 0),
        (2, "unconfirmed", OTHER, "source-title", "title-fuzzy", 0.91, BLOB, "1", None, None, 0),
    ]


def _link2(project: Project) -> tuple[Any, ...]:
    rows = _rows(
        project,
        "SELECT state, work_id, confidence, decision, confirmed_by, proposal"
        " FROM reference_links WHERE ordinal = 2",
    )
    assert len(rows) == 1
    return rows[0]


def test_decision_overlay_latest_wins_and_reject_after_confirm(project: Project) -> None:
    _extract(project)
    _resolve(project, [resolution(1), FUZZY])
    _decide(project, "propose-confirm", OTHER, None)
    assert _link2(project) == (
        "unconfirmed",
        OTHER,
        "title-fuzzy",
        None,
        None,
        "propose-confirm",
    )
    _decide(project, "confirm", OTHER, "human")
    assert _link2(project) == (
        "resolved",
        OTHER,
        "confirmed",
        "confirm",
        "human",
        "propose-confirm",
    )
    _decide(project, "propose-reject", None, None)  # a proposal never undoes a confirmation
    assert _link2(project)[:5] == ("resolved", OTHER, "confirmed", "confirm", "human")
    _decide(project, "reject", None, "second-agent")
    assert _link2(project) == (
        "unresolved",
        None,
        None,
        "reject",
        "second-agent",
        "propose-reject",
    )


def test_decision_before_resolution_is_folded_when_link_arrives(project: Project) -> None:
    _extract(project)
    _decide(project, "confirm", OTHER, "human")
    assert _rows(project, "SELECT * FROM reference_links") == []
    _resolve(project, [resolution(1), FUZZY])
    assert _link2(project)[:3] == ("resolved", OTHER, "confirmed")


def test_contexts_projected_first_write_wins(project: Project) -> None:
    ctx = {"citing_anchor": "s1.p2", "entry": 1, "marker": "[1]", "method": "numeric"}
    first = CitationContextsRecorded.model_validate(
        {
            "extraction_id": REX,
            "contexts": [
                {**ctx, "state": "matched"},
                {**ctx, "state": "matched"},
                {**ctx, "entry": None, "marker": "[7]", "state": "unmatched"},
            ],
        }
    )
    _record(project, "citation.contexts_recorded", first)
    _record(
        project,
        "citation.contexts_recorded",
        CitationContextsRecorded(extraction_id=REX, contexts=()),
    )
    assert _rows(
        project,
        "SELECT extraction_id, citing_anchor, entry, marker, method, state FROM citation_contexts"
        " ORDER BY position",
    ) == [
        (REX, "s1.p2", 1, "[1]", "numeric", "matched"),
        (REX, "s1.p2", 1, "[1]", "numeric", "matched"),
        (REX, "s1.p2", None, "[7]", "numeric", "unmatched"),
    ]


def test_round_tables_and_derived_citation_count(project: Project) -> None:
    payload = round_payload()
    second_citer = {"work_id": OTHER, "extraction_id": REX2, "ordinal": 4, "anchors": ["s2.p1"]}
    payload["sources"] = sorted([WORK, OTHER])
    payload["extraction_ids"] = [REX, REX2]
    payload["candidates"][0]["cited_by"].append(second_citer)
    payload["queries"] = ["doi:10.9999/invented.1", "reflist:" + REX + ":2"]
    event = _record(project, "snowball.round_started", SnowballRoundStarted.model_validate(payload))
    _record(project, "snowball.round_started", SnowballRoundStarted.model_validate(round_payload()))
    assert _rows(
        project,
        "SELECT round_id, direction, via, round_no, rule, chase_round_id, event_id"
        " FROM snowball_rounds",
    ) == [
        (
            SNW,
            "backward",
            "document-reference-list",
            1,
            '{"max_backward_rounds":2,"max_forward_rounds":0,"stop_when_no_new_included":true}',
            None,
            event.id,
        )
    ]
    assert _rows(
        project,
        "SELECT work_key, cited_by_included, no_source_record FROM snowball_candidates"
        " ORDER BY work_key",
    ) == [(f"{REX}:2", 1, 1), (CITED, 2, 0)]
    assert _rows(project, "SELECT position, query FROM snowball_queries ORDER BY position") == [
        (0, "doi:10.9999/invented.1"),
        (1, "reflist:" + REX + ":2"),
    ]


def test_round_texts_includes_snowball_queries(project: Project) -> None:
    _record(
        project,
        "chase.round_started",
        ChaseRoundStarted(
            round_id="chs_01HZX3K4M5N6P7Q8R9S0TVWXYZ",
            directions=(ChaseDirection.BACKWARD,),
            from_works=(WORK,),
            unchasable=(),
            queries=("cited_by:W1",),
        ),
    )
    _record(project, "snowball.round_started", SnowballRoundStarted.model_validate(round_payload()))
    with project.index.connect() as conn:
        assert round_texts(conn) == {"cited_by:W1", "doi:10.9999/invented.1"}


def test_rebuild_determinism_with_reference_events(project: Project) -> None:
    _extract(project)
    _resolve(project, [resolution(1), FUZZY])
    _decide(project, "confirm", OTHER, "human")
    _decide(project, "reject", None, "human")
    _extract(project, REX2, n=1)
    _record(project, "snowball.round_started", SnowballRoundStarted.model_validate(round_payload()))
    before = project.index.state_hash()
    assert project.index.rebuild() == before
    assert project.index.rebuild() == before


def test_round_texts_waives_snowball_only_text(project: Project) -> None:
    payload = round_payload(queries=["doi:10.9999/only.in.snowball"])
    _record(project, "snowball.round_started", SnowballRoundStarted.model_validate(payload))
    assert _rows(project, "SELECT * FROM chase_queries") == []
    with project.index.connect() as conn:
        texts = round_texts(conn)
    assert "doi:10.9999/only.in.snowball" in texts
    assert "doi:10.9999/unrelated" not in texts


def test_decision_on_unknown_extraction_folds_in_later(project: Project) -> None:
    _decide(project, "confirm", OTHER, "human")  # no extraction and no link yet
    assert _rows(project, "SELECT * FROM reference_extractions") == []
    assert _rows(project, "SELECT * FROM reference_links") == []
    assert len(_rows(project, "SELECT * FROM reference_decisions")) == 1
    _extract(project)
    _resolve(project, [resolution(1), FUZZY])
    assert _link2(project)[:5] == ("resolved", OTHER, "confirmed", "confirm", "human")


def test_proposal_after_binding_decision_leaves_state(project: Project) -> None:
    _extract(project)
    _resolve(project, [resolution(1), FUZZY])
    _decide(project, "reject", None, "human")
    before = _link2(project)[:5]
    assert before == ("unresolved", None, None, "reject", "human")
    _decide(project, "propose-confirm", OTHER, None)
    assert _link2(project) == (*before, "propose-confirm")
