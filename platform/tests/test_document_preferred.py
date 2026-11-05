"""The preferred document: a human moves the extraction basis of one work to another document.

Two live documents of one work (arXiv HTML, then arXiv source as HTML bytes so the stub converter
reads it) are converted; the automatic default is the HTML route's. A preference names the other.
"""

from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.fulltext import Route
from factory.services.context import Project
from factory.services.document_read import (
    automatic_default_document,
    default_conversion,
    document_read,
)
from factory.services.fulltext import fetch_fulltext
from factory.services.search import list_works
from factory.services.versions import prefer_document
from tests.document_helpers import ARTICLE, make_registry, run_convert
from tests.helpers import SourcesFor
from tests.notice_helpers import NoticeWorld, dependent_world, numbered_records
from tests.route_helpers import StubRoute, always, retrieved


@pytest.fixture
def two_documents(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> tuple[NoticeWorld, str, str, str]:
    """(world, work, html document, source document): both live and converted."""
    world = dependent_world(project, agent, human, mock_sources, numbered_records(2))
    work = world.included[0]
    html = ARTICLE
    source = ARTICLE + b"<!-- source copy -->"
    fetch_fulltext(
        project,
        routes={
            Route.ARXIV_HTML: StubRoute(Route.ARXIV_HTML, always(retrieved(Route.ARXIV_HTML, html)))
        },
        work_ids=[work],
        only=[Route.ARXIV_HTML],
    )
    fetch_fulltext(
        project,
        routes={
            Route.ARXIV_SOURCE: StubRoute(
                Route.ARXIV_SOURCE, always(retrieved(Route.ARXIV_SOURCE, source))
            )
        },
        work_ids=[work],
        only=[Route.ARXIV_SOURCE],
    )
    run_convert(project, make_registry())
    with project.index.connect() as conn:
        from sqlalchemy import text

        docs = {
            str(r): str(d)
            for r, d in conn.execute(
                text("SELECT route, document_id FROM fulltext_documents WHERE work_id = :w"),
                {"w": work},
            )
        }
    return world, work, docs["arxiv-html"], docs["arxiv-source"]


def test_agent_cannot_prefer(
    two_documents: tuple[NoticeWorld, str, str, str], agent: Actor
) -> None:
    world, work, _, source = two_documents
    with pytest.raises(FactoryValidationError) as err:
        prefer_document(world.project, agent, work, source, "better")
    assert err.value.issues[0].field == "actor"


def test_prefer_requires_live_document_of_same_work(
    two_documents: tuple[NoticeWorld, str, str, str],
) -> None:
    world, work, html, source = two_documents
    human = world.project.human_actor()
    other_work = world.included[1]
    before = len(read_all(world.project.paths.events_dir, world.project.catalog))
    for work_id, document, rationale in [
        (other_work, source, "wrong work"),
        (work, "doc_" + "0" * 26, "unknown"),
        (work, source, "  "),
    ]:
        with pytest.raises(FactoryValidationError):
            prefer_document(world.project, human, work_id, document, rationale)
    assert len(read_all(world.project.paths.events_dir, world.project.catalog)) == before
    # A superseded document is not live: refresh the HTML route with new bytes.
    fetch_fulltext(
        world.project,
        routes={
            Route.ARXIV_HTML: StubRoute(
                Route.ARXIV_HTML,
                always(retrieved(Route.ARXIV_HTML, ARTICLE + b"<!-- v3 -->", version="v3")),
            )
        },
        work_ids=[work],
        only=[Route.ARXIV_HTML],
    )
    with pytest.raises(FactoryValidationError) as err:
        prefer_document(world.project, human, work, html, "old html")
    assert "superseded" in err.value.issues[0].reason


def test_preference_changes_default_conversion(
    two_documents: tuple[NoticeWorld, str, str, str],
) -> None:
    world, work, html, source = two_documents
    project = world.project
    default = default_conversion(project, work)
    assert default is not None and default.document_id == html
    prefer_document(project, project.human_actor(), work, source, "the source copy is complete")
    preferred = default_conversion(project, work)
    assert preferred is not None and preferred.document_id == source
    # Another work is untouched, and a read with no document named serves the preference.
    other = default_conversion(project, world.included[1])
    assert other is None or other.document_id not in {source}
    page = document_read(project, work_id=work)
    assert page.document_id == source


def test_preferring_default_clears_override(
    two_documents: tuple[NoticeWorld, str, str, str],
) -> None:
    world, work, html, source = two_documents
    project = world.project
    human = project.human_actor()
    prefer_document(project, human, work, source, "use the source")
    prefer_document(project, human, work, html, "back to the automatic order")
    [first, second] = [
        e.payload
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "document.preferred"
    ]
    assert first["automatic"] is False and second["automatic"] is True
    assert automatic_default_document(project, work) == html
    current = default_conversion(project, work)
    assert current is not None and current.document_id == html
    # The override is cleared, not merely outvoted: a later better route would be followed.
    assert list_works(project)  # the project is intact
    assert project.index.rebuild() == project.index.state_hash()


def test_trace_lists_the_preference(two_documents: tuple[NoticeWorld, str, str, str]) -> None:
    from factory.services.trace import trace

    world, work, _, source = two_documents
    prefer_document(world.project, world.project.human_actor(), work, source, "use the source")
    tree = trace(world.project, work, direction="forward")
    kinds: list[tuple[str, str]] = []
    stack = [tree]
    while stack:
        node = stack.pop()
        kinds.append((node.kind, node.label))
        stack.extend(node.children)
    assert ("preference", f"preferred document {source}") in kinds
