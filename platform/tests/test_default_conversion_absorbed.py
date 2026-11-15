"""`default_conversion` for a canonical work: the documents of works merged into it count.

The canonical work has no document of its own, the absorbed one has a converted full text: the
canonical work resolves to it. Its own document wins over an absorbed one; a reverted merge is
ignored; a researcher's preference wins over both.
"""

from __future__ import annotations

from sqlalchemy import text

from factory.events.envelope import Actor
from factory.services.context import Project
from factory.services.document_read import default_conversion, default_conversions
from tests.document_helpers import ARTICLE, fetched_document, make_registry, run_convert
from tests.helpers import SourcesFor
from tests.notice_helpers import dependent_world, numbered_records
from tests.region_helpers import merge_works


def _world(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> tuple[str, str]:
    world = dependent_world(project, agent, human, mock_sources, numbered_records(3))
    return world.included[0], world.included[1]


def test_absorbed_document_serves_the_canonical_work(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    canonical, absorbed = _world(project, agent, human, mock_sources)
    doc = fetched_document(project, absorbed, ARTICLE)
    run_convert(project, make_registry())
    assert default_conversion(project, canonical) is None
    merge_works(project, canonical, absorbed)
    ref = default_conversion(project, canonical)
    assert ref is not None and ref.document_id == doc
    assert default_conversion(project, absorbed) is not None


def test_own_document_wins_over_absorbed(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    canonical, absorbed = _world(project, agent, human, mock_sources)
    own = fetched_document(project, canonical, ARTICLE)
    fetched_document(project, absorbed, ARTICLE + b"<!-- other -->")
    run_convert(project, make_registry())
    merge_works(project, canonical, absorbed)
    ref = default_conversion(project, canonical)
    assert ref is not None and ref.document_id == own


def test_reverted_merge_is_ignored(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    canonical, absorbed = _world(project, agent, human, mock_sources)
    fetched_document(project, absorbed, ARTICLE)
    run_convert(project, make_registry())
    merge_works(project, canonical, absorbed)
    with project.index.connect() as conn:
        conn.execute(text("UPDATE merges SET status = 'reverted'"))
        conn.commit()
    assert default_conversion(project, canonical) is None


def test_preference_wins_over_own_and_absorbed(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    canonical, absorbed = _world(project, agent, human, mock_sources)
    fetched_document(project, canonical, ARTICLE)
    other = fetched_document(project, absorbed, ARTICLE + b"<!-- other -->")
    run_convert(project, make_registry())
    merge_works(project, canonical, absorbed)
    # The preference is recorded for the canonical work and names the absorbed work's document.
    with project.index.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO document_preferences (event_id, work_id, document_id, rationale, "
                "automatic, actor_id, preferred_at) "
                "VALUES ('ev_zzz', :w, :d, 'r', 0, 'a', '2026-01-01')"
            ),
            {"w": canonical, "d": other},
        )
        conn.commit()
    ref = default_conversion(project, canonical)
    assert ref is not None and ref.document_id == other


def test_bulk_form_agrees_with_the_single_form(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    world = dependent_world(project, agent, human, mock_sources, numbered_records(4))
    canonical, absorbed, own, bare = world.included[:4]
    fetched_document(project, absorbed, ARTICLE)
    fetched_document(project, own, ARTICLE + b"<!-- own -->")
    run_convert(project, make_registry())
    merge_works(project, canonical, absorbed)
    ids = [canonical, absorbed, own, bare]
    bulk = default_conversions(project, ids)
    assert bulk == {w: default_conversion(project, w) for w in ids}
    assert bulk[canonical] is not None and bulk[bare] is None
