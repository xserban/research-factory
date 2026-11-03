"""The full-text fetch service: gate, route order, version rule and changed sources (plan 2A).

Routes are stubs with canned `RouteResult`s, so no test touches the network. The screening
fixtures reuse the pilot corpus helpers; a work is promoted once both passes include it.
"""

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.fulltext import (
    AttemptOutcome,
    Route,
)
from factory.model.screening import Channel, PassLabel
from factory.model.work import Work
from factory.services.agreement import Outcome, final_outcomes
from factory.services.calibration import calibration_items, label_calibration
from factory.services.context import Project
from factory.services.fulltext import fetch_fulltext
from factory.services.screening import open_pass
from factory.services.search import list_works
from factory.sources.fulltext.base import RouteResult, not_retrieved, transport_failure
from factory.sources.registry import SourceFactory
from tests.helpers import _setup
from tests.test_screening_next import _decide, _draw

SourcesFor = Callable[..., Mapping[str, SourceFactory]]
Answer = Callable[[Work], RouteResult]


class StubRoute:
    """A route whose answer for each work comes from `answer`. `calls` lists the works asked."""

    def __init__(self, route: Route, answer: Answer) -> None:
        self.route = route
        self._answer = answer
        self.calls: list[str] = []

    def fetch(self, work: Work, *, version: str | None = None) -> RouteResult:
        self.calls.append(work.id)
        return self._answer(work)


def always(result: RouteResult) -> Answer:
    return lambda _work: result


def answers(*results: RouteResult) -> Answer:
    """Each call gets the next result; the list is consumed in order."""
    queue = list(results)
    return lambda _work: queue.pop(0)


def retrieved(
    route: Route,
    content: bytes,
    *,
    version: str | None = "v2",
    licence: str | None = None,
    url: str | None = None,
    media_type: str | None = "text/html",
    metadata: bytes | None = None,
) -> RouteResult:
    return RouteResult(
        route=route,
        outcome=AttemptOutcome.RETRIEVED,
        url=url or f"https://arxiv.org/html/2101.00001{version or ''}",
        http_status=200,
        content=content,
        media_type=media_type,
        source_version=version,
        licence=licence,
        metadata=metadata,
    )


def missing(route: Route, reason: str) -> RouteResult:
    return not_retrieved(route, AttemptOutcome.NOT_AVAILABLE, reason)


def routes_for(**answering: Answer) -> dict[Route, StubRoute]:
    """One stub per automatic route, keyed by route, with the answers given by route value."""
    return {
        route: StubRoute(route, answering.get(route.name.lower(), always(missing(route, "none"))))
        for route in (Route.ARXIV_HTML, Route.ARXIV_SOURCE, Route.OA_PDF)
    }


def _events(project: Project) -> list[Event]:
    return read_all(project.paths.events_dir, project.catalog)


def _of_type(project: Project, type_: str) -> list[Event]:
    return [event for event in _events(project) if event.type == type_]


def _include_all(
    project: Project, agent: Actor, human: Actor, protocol_id: str, *, leave: str | None = None
) -> None:
    """Both passes include every ordinary work and the human labels every calibration work."""
    calibration = set(calibration_items(project))
    for work in sorted(w.id for w in list_works(project)):
        if work == leave:
            continue
        if work in calibration:
            label_calibration(project, human, work, "include", None, Channel.CLI)
            continue
        _decide(project, agent, work, "A", "screening", "include", None, protocol_id)
        _decide(project, agent, work, "B", "screening", "include", None, protocol_id)


@pytest.fixture
def screened(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> Callable[..., str]:
    """Build a corpus with both passes opened and every ordinary work included.

    With `leave_one`, the first ordinary work is left undecided, so it is not promoted.
    """

    def build(*, leave_one: bool = False) -> str:
        protocol_id = _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
        _draw(project)
        open_pass(project, agent, PassLabel.A)
        open_pass(project, agent, PassLabel.B)
        leave = _ordinary_pending(project) if leave_one else None
        _include_all(project, agent, human, protocol_id, leave=leave)
        return protocol_id

    return build


def _promoted(project: Project) -> list[str]:
    return sorted(
        w for w, outcome in final_outcomes(project).items() if outcome is Outcome.INCLUDED
    )


def _ordinary_pending(project: Project) -> str:
    """An ordinary (non-calibration) corpus work, to be left undecided."""
    calibration = set(calibration_items(project))
    return sorted(w.id for w in list_works(project) if w.id not in calibration)[0]


def _files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()] if root.is_dir() else []


# --- Gate and validation ---


def test_unpromoted_work_refused_and_nothing_written(
    project: Project, agent: Actor, human: Actor, screened: Callable[..., str]
) -> None:
    screened(leave_one=True)
    leave = _ordinary_pending(project)
    promoted = _promoted(project)
    stubs = routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"x")))
    before = len(_events(project))

    with pytest.raises(FactoryValidationError) as raised:
        fetch_fulltext(project, routes=stubs, work_ids=[promoted[0], leave])

    assert raised.value.issues == [
        ValidationIssue("work_ids", f"{leave}: not promoted at title/abstract")
    ]
    assert len(_events(project)) == before
    assert stubs[Route.ARXIV_HTML].calls == []


def test_unknown_work_refused(project: Project) -> None:
    before = len(_events(project))
    with pytest.raises(FactoryValidationError) as raised:
        fetch_fulltext(project, routes=routes_for(), work_ids=["rf:nope-00000000"])
    assert raised.value.issues == [
        ValidationIssue("work_ids", "rf:nope-00000000: not promoted at title/abstract")
    ]
    assert len(_events(project)) == before


def test_only_and_limit_refused_together(project: Project) -> None:
    stubs = routes_for()
    with pytest.raises(FactoryValidationError) as raised:
        fetch_fulltext(
            project,
            routes=stubs,
            only=[Route.RESEARCHER, Route.ARXIV_HTML],
            limit=0,
        )
    assert ValidationIssue("only", "a researcher-supplied route is imported, not fetched") in (
        raised.value.issues
    )
    assert ValidationIssue("limit", "must be between 1 and 200") in raised.value.issues


def test_limit_upper_bound_refused(project: Project) -> None:
    with pytest.raises(FactoryValidationError) as raised:
        fetch_fulltext(project, routes=routes_for(), limit=201)
    assert raised.value.issues == [ValidationIssue("limit", "must be between 1 and 200")]


def test_only_names_a_supplied_route(project: Project) -> None:
    with pytest.raises(FactoryValidationError) as raised:
        fetch_fulltext(project, routes={}, only=[Route.OA_PDF])
    assert raised.value.issues == [ValidationIssue("only", "no route supplied for oa-pdf")]


def test_empty_only_and_no_routes_refused(project: Project) -> None:
    with pytest.raises(FactoryValidationError) as empty:
        fetch_fulltext(project, routes=routes_for(), only=[])
    assert empty.value.issues == [ValidationIssue("only", "name at least one route")]
    with pytest.raises(FactoryValidationError) as none:
        fetch_fulltext(project, routes={})
    assert none.value.issues == [ValidationIssue("routes", "no automatic route supplied")]


def test_input_blob_must_be_a_stored_blob(project: Project) -> None:
    with pytest.raises(FactoryValidationError) as malformed:
        fetch_fulltext(project, routes=routes_for(), input_blob="not-a-ref")
    assert malformed.value.issues == [ValidationIssue("input_blob", "not a blob reference")]
    absent = "sha256:" + "c" * 64
    with pytest.raises(FactoryValidationError) as missing_blob:
        fetch_fulltext(project, routes=routes_for(), input_blob=absent)
    assert missing_blob.value.issues == [ValidationIssue("input_blob", "no such blob")]


# --- Route order and the first-success rule ---


def test_first_success_stops(project: Project, agent: Actor, human: Actor, screened: Any) -> None:
    screened()
    work = _promoted(project)[0]
    stubs = routes_for(
        arxiv_html=always(retrieved(Route.ARXIV_HTML, b"html bytes")),
        arxiv_source=always(retrieved(Route.ARXIV_SOURCE, b"source bytes")),
        oa_pdf=always(retrieved(Route.OA_PDF, b"pdf bytes", media_type="application/pdf")),
    )

    summary = fetch_fulltext(project, routes=stubs, work_ids=[work])

    assert len(summary.works[0].attempts) == 1
    assert len(summary.works[0].documents) == 1
    assert summary.works[0].status == "retrieved"
    assert stubs[Route.ARXIV_SOURCE].calls == []
    assert stubs[Route.OA_PDF].calls == []


def test_not_retrieved_has_per_route_reasons(project: Project, screened: Any) -> None:
    screened()
    work = _promoted(project)[0]
    stubs = routes_for(
        arxiv_html=always(missing(Route.ARXIV_HTML, "no-html-rendering")),
        arxiv_source=always(transport_failure(Route.ARXIV_SOURCE)),
        oa_pdf=always(
            not_retrieved(Route.OA_PDF, AttemptOutcome.FAILED, "not-a-pdf", http_status=200)
        ),
    )

    summary = fetch_fulltext(project, routes=stubs, work_ids=[work])

    assert summary.works[0].status == "not-retrieved"
    assert summary.works[0].documents == []
    assert len(summary.works[0].attempts) == 3
    reasons = [event.payload["reason"] for event in _of_type(project, "fulltext.attempted")]
    assert reasons == ["no-html-rendering", "transport", "not-a-pdf"]


def test_transport_failure_is_an_outcome(project: Project, screened: Any) -> None:
    screened()
    work = _promoted(project)[0]
    stubs = routes_for(
        arxiv_html=always(transport_failure(Route.ARXIV_HTML)),
        arxiv_source=always(transport_failure(Route.ARXIV_SOURCE)),
        oa_pdf=always(retrieved(Route.OA_PDF, b"pdf", media_type="application/pdf")),
    )

    summary = fetch_fulltext(project, routes=stubs, work_ids=[work])

    assert summary.works[0].status == "retrieved"
    assert len(summary.works[0].attempts) == 3
    assert [e.payload["outcome"] for e in _of_type(project, "fulltext.attempted")] == [
        "failed",
        "failed",
        "retrieved",
    ]


def test_only_routes_fetches_all_named(project: Project, screened: Any) -> None:
    screened()
    work = _promoted(project)[0]
    stubs = routes_for(
        arxiv_html=always(retrieved(Route.ARXIV_HTML, b"html bytes")),
        arxiv_source=always(retrieved(Route.ARXIV_SOURCE, b"source bytes", media_type="x")),
        oa_pdf=always(retrieved(Route.OA_PDF, b"pdf bytes", media_type="application/pdf")),
    )

    summary = fetch_fulltext(
        project, routes=stubs, work_ids=[work], only=[Route.ARXIV_SOURCE, Route.ARXIV_HTML]
    )

    assert summary.works[0].status == "retrieved"
    assert len(summary.works[0].documents) == 2
    assert stubs[Route.OA_PDF].calls == []
    started = _of_type(project, "fulltext.fetch_started")[-1]
    assert started.payload["routes"] == ["arxiv-html", "arxiv-source"]
    qualities = sorted(
        str(e.payload["quality"]) for e in _of_type(project, "fulltext.document_added")
    )
    assert qualities == ["latex", "structured-html"]


# --- The version rule ---


def test_newer_arxiv_version_is_new_document_superseding(project: Project, screened: Any) -> None:
    screened()
    work = _promoted(project)[0]
    first = fetch_fulltext(
        project,
        routes=routes_for(
            arxiv_html=always(retrieved(Route.ARXIV_HTML, b"v2 bytes", version="v2"))
        ),
        work_ids=[work],
    )
    doc_v2 = first.works[0].documents[0]

    second = fetch_fulltext(
        project,
        routes=routes_for(
            arxiv_html=always(retrieved(Route.ARXIV_HTML, b"v3 bytes", version="v3"))
        ),
        work_ids=[work],
        refresh=True,
    )

    assert second.works[0].status == "retrieved"
    added = _of_type(project, "fulltext.document_added")[-1]
    assert added.payload["source_version"] == "v3"
    assert added.payload["supersedes"] == doc_v2


def test_same_version_same_hash_adds_no_document(project: Project, screened: Any) -> None:
    screened()
    work = _promoted(project)[0]
    first = fetch_fulltext(
        project,
        routes=routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"same"))),
        work_ids=[work],
    )
    doc = first.works[0].documents[0]

    second = fetch_fulltext(
        project,
        routes=routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"same"))),
        work_ids=[work],
        refresh=True,
    )

    assert len(_of_type(project, "fulltext.document_added")) == 1
    assert second.works[0].documents == []
    assert second.works[0].status == "already-retrieved"
    attempt = _of_type(project, "fulltext.attempted")[-1]
    assert attempt.payload["document_id"] == doc
    assert _of_type(project, "fulltext.source_changed") == []


def test_same_version_new_hash_records_source_changed(project: Project, screened: Any) -> None:
    screened()
    work = _promoted(project)[0]
    first = fetch_fulltext(
        project,
        routes=routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"original"))),
        work_ids=[work],
    )
    doc = first.works[0].documents[0]
    original_hash = str(_of_type(project, "fulltext.document_added")[0].payload["raw_hash"])

    second = fetch_fulltext(
        project,
        routes=routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"edited"))),
        work_ids=[work],
        refresh=True,
    )

    assert second.works[0].status == "source-changed"
    assert second.works[0].documents == []
    change = _of_type(project, "fulltext.source_changed")[0].payload
    assert change["document_id"] == doc
    assert change["expected_hash"] == original_hash
    assert change["observed_hash"] != original_hash
    assert project.library.exists(original_hash)
    assert project.library.exists(str(change["observed_hash"]))
    attempt = _of_type(project, "fulltext.attempted")[-1].payload
    assert attempt["outcome"] == "retrieved"
    assert attempt["document_id"] == doc
    assert attempt["raw_hash"] == change["observed_hash"]


def test_explicit_work_with_document_is_already_retrieved(project: Project, screened: Any) -> None:
    screened()
    work = _promoted(project)[0]
    fetch_fulltext(
        project,
        routes=routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"kept"))),
        work_ids=[work],
    )
    stubs = routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"other")))

    summary = fetch_fulltext(project, routes=stubs, work_ids=[work])

    assert summary.works[0].status == "already-retrieved"
    assert summary.works[0].attempts == []
    assert stubs[Route.ARXIV_HTML].calls == []


# --- Selection, limit and remaining ---


def test_limit_and_remaining(project: Project, screened: Any) -> None:
    screened()
    promoted = _promoted(project)
    assert len(promoted) >= 3
    stubs = routes_for(
        arxiv_html=lambda work: retrieved(Route.ARXIV_HTML, work.id.encode()),
    )

    first = fetch_fulltext(project, routes=stubs, limit=2)

    assert [w.work_id for w in first.works] == promoted[:2]
    assert first.remaining == len(promoted) - 2

    rest = fetch_fulltext(project, routes=stubs, limit=200)

    assert [w.work_id for w in rest.works] == promoted[2:]
    assert rest.remaining == 0


def test_selection_skips_documented_works(project: Project, screened: Any) -> None:
    screened()
    promoted = _promoted(project)
    fetch_fulltext(
        project,
        routes=routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"one"))),
        work_ids=[promoted[0]],
    )

    summary = fetch_fulltext(
        project,
        routes=routes_for(arxiv_html=lambda work: retrieved(Route.ARXIV_HTML, work.id.encode())),
    )

    assert promoted[0] not in [w.work_id for w in summary.works]
    assert summary.remaining == 0


def test_failed_works_are_not_reselected_by_default(project: Project, screened: Any) -> None:
    screened()
    promoted = _promoted(project)
    assert len(promoted) >= 3
    stubs = routes_for()

    first = fetch_fulltext(project, routes=stubs, limit=2)
    second = fetch_fulltext(project, routes=stubs, limit=2)

    assert [w.work_id for w in first.works] == promoted[:2]
    assert [w.work_id for w in second.works] == promoted[2:4]
    assert stubs[Route.ARXIV_HTML].calls == promoted[:4]
    assert second.remaining == len(promoted)


def test_explicit_work_ids_beyond_limit_refused_and_nothing_written(
    project: Project, screened: Any
) -> None:
    screened()
    promoted = _promoted(project)
    assert len(promoted) >= 3
    stubs = routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"x")))
    before = len(_events(project))

    with pytest.raises(FactoryValidationError) as raised:
        fetch_fulltext(project, routes=stubs, work_ids=promoted[:3], limit=2)

    assert raised.value.issues == [ValidationIssue("limit", "3 work_ids exceed limit 2")]
    assert len(_events(project)) == before
    assert stubs[Route.ARXIV_HTML].calls == []


def test_each_work_is_one_record_call(
    project: Project, screened: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    screened()
    promoted = _promoted(project)[:2]
    calls: list[int] = []
    original = project.record

    def counting(events: list[Event]) -> None:
        calls.append(len(events))
        original(events)

    monkeypatch.setattr(project, "record", counting)
    fetch_fulltext(
        project,
        routes=routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"bytes"))),
        work_ids=promoted,
    )

    # One FetchStarted, then one call per work whose events are written as a whole.
    assert calls[0] == 1
    assert len(calls) == 1 + len(promoted)


# --- Triggers and provenance ---


def test_agent_trigger_carries_input_blob(project: Project, screened: Any, agent: Actor) -> None:
    screened()
    work = _promoted(project)[0]

    summary = fetch_fulltext(
        project,
        routes=routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"bytes"))),
        work_ids=[work],
        actor=agent,
    )

    started = _of_type(project, "fulltext.fetch_started")[-1]
    assert started.actor.kind == "agent"
    assert started.input_blob is not None
    request = json.loads(project.blobs.get(started.input_blob))
    assert request["work_ids"] == [work]
    assert started.payload["fetch_id"] == summary.fetch_id
    for event in _of_type(project, "fulltext.attempted"):
        assert event.actor.kind == "system"
        assert event.input_blob is None


def test_system_trigger_has_no_input_blob(project: Project, screened: Any) -> None:
    screened()
    work = _promoted(project)[0]
    fetch_fulltext(
        project,
        routes=routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"bytes"))),
        work_ids=[work],
    )
    started = _of_type(project, "fulltext.fetch_started")[-1]
    assert started.actor.kind == "system"
    assert started.input_blob is None


def test_explicit_input_blob_is_kept(project: Project, screened: Any, agent: Actor) -> None:
    screened()
    work = _promoted(project)[0]
    blob = project.blobs.put(b'{"caller": "kept"}')
    fetch_fulltext(
        project,
        routes=routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"bytes"))),
        work_ids=[work],
        actor=agent,
        input_blob=blob,
    )
    assert _of_type(project, "fulltext.fetch_started")[-1].input_blob == blob


# --- Recorded facts: outcomes, licences, redaction, bytes ---


def test_no_source_version_is_a_failed_attempt(project: Project, screened: Any) -> None:
    screened()
    work = _promoted(project)[0]
    stubs = routes_for(
        arxiv_html=always(retrieved(Route.ARXIV_HTML, b"no version", version=None)),
        arxiv_source=always(retrieved(Route.ARXIV_SOURCE, b"source", version="v4")),
    )

    summary = fetch_fulltext(project, routes=stubs, work_ids=[work])

    first = _of_type(project, "fulltext.attempted")[0].payload
    assert first["outcome"] == "failed"
    assert first["reason"] == "no-source-version"
    assert first["document_id"] is None
    assert summary.works[0].status == "retrieved"
    added = [e.payload["route"] for e in _of_type(project, "fulltext.document_added")]
    assert added == ["arxiv-source"]


def test_blank_media_type_and_missing_content_are_failures(project: Project, screened: Any) -> None:
    screened()
    work = _promoted(project)[0]
    stubs = routes_for(
        arxiv_html=always(retrieved(Route.ARXIV_HTML, b"bytes", media_type="  ")),
        arxiv_source=always(
            RouteResult(route=Route.ARXIV_SOURCE, outcome=AttemptOutcome.RETRIEVED)
        ),
        oa_pdf=always(RouteResult(route=Route.OA_PDF, outcome=AttemptOutcome.RESTORED)),
    )

    summary = fetch_fulltext(project, routes=stubs, work_ids=[work])

    reasons = [e.payload["reason"] for e in _of_type(project, "fulltext.attempted")]
    assert reasons == ["no-media-type", "no-content", "unexpected-outcome"]
    assert summary.works[0].status == "not-retrieved"
    assert summary.works[0].documents == []


def test_not_retrieved_without_reason_gets_a_placeholder(project: Project, screened: Any) -> None:
    screened()
    work = _promoted(project)[0]
    bare = RouteResult(route=Route.ARXIV_HTML, outcome=AttemptOutcome.FAILED)
    stubs = routes_for(arxiv_html=always(bare))

    fetch_fulltext(project, routes=stubs, work_ids=[work])

    assert _of_type(project, "fulltext.attempted")[0].payload["reason"] == "unspecified"


@pytest.mark.parametrize(
    ("licence", "status", "recorded"),
    [
        ("cc-by-4.0", "reported", "cc-by-4.0"),
        ("  ", "not-reported", None),
        (None, "not-reported", None),
    ],
)
def test_licence_maps_to_status(
    project: Project, screened: Any, licence: str | None, status: str, recorded: str | None
) -> None:
    screened()
    work = _promoted(project)[0]
    fetch_fulltext(
        project,
        routes=routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, b"b", licence=licence))),
        work_ids=[work],
    )
    attempt = _of_type(project, "fulltext.attempted")[0].payload
    assert attempt["licence_status"] == status
    assert attempt["licence"] == recorded


def test_url_is_redacted_before_recording(project: Project, screened: Any) -> None:
    screened()
    work = _promoted(project)[0]
    secret_url = "https://api.openalex.org/works/W1?mailto=ada.lovelace@example.org"
    fetch_fulltext(
        project,
        routes=routes_for(
            arxiv_html=always(retrieved(Route.ARXIV_HTML, b"b", url=secret_url)),
        ),
        work_ids=[work],
    )
    recorded = _of_type(project, "fulltext.attempted")[0].payload["url"]
    assert recorded == "https://api.openalex.org/works/W1"
    raw = "".join(p.read_text(encoding="utf-8") for p in _files(project.paths.events_dir))
    assert "ada.lovelace@example.org" not in raw


def test_metadata_is_archived_and_failed_routes_keep_theirs(
    project: Project, screened: Any
) -> None:
    screened()
    work = _promoted(project)[0]
    stubs = routes_for(
        arxiv_html=always(
            not_retrieved(
                Route.ARXIV_HTML,
                AttemptOutcome.NOT_AVAILABLE,
                "no-html-rendering",
                metadata=b'{"lookup": 1}',
            )
        ),
        arxiv_source=always(retrieved(Route.ARXIV_SOURCE, b"tar", metadata=b"<feed/>")),
    )

    fetch_fulltext(project, routes=stubs, work_ids=[work])

    first, second = (e.payload for e in _of_type(project, "fulltext.attempted"))
    assert project.blobs.get(str(first["metadata_blob"])) == b'{"lookup": 1}'
    assert project.blobs.get(str(second["metadata_blob"])) == b"<feed/>"


def test_no_document_bytes_under_blobs(project: Project, screened: Any) -> None:
    screened()
    work = _promoted(project)[0]
    content = b"FULL TEXT BYTES THAT MUST STAY IN THE LIBRARY"
    fetch_fulltext(
        project,
        routes=routes_for(arxiv_html=always(retrieved(Route.ARXIV_HTML, content))),
        work_ids=[work],
    )

    stored = [path.read_bytes() for path in _files(project.paths.blobs_dir)]
    assert content not in stored
    library_hash = str(_of_type(project, "fulltext.document_added")[0].payload["raw_hash"])
    assert project.library.get(library_hash) == content
