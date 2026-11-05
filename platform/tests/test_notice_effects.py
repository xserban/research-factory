"""Read-time effects of notices and of a preferred document on extraction rows (living-C).

These run over the full-text extraction world of plan D (slow): included works with converted
documents, a declared schema and recorded rows. A fixture row set is written for two works so that
the effect of an act on one work can be compared with the other's, unit by unit.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import pytest

from factory.events.envelope import Actor
from factory.model.fulltext import Route
from factory.model.protocol import ScreeningStage
from factory.model.screening import PassLabel
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.document_read import default_conversion
from factory.services.extraction import (
    ExtractBatch,
    extract_next,
    extract_record,
    stale_extractions,
    unit_states,
)
from factory.services.fulltext import fetch_fulltext
from factory.services.tasks import complete_task
from factory.services.versions import prefer_document
from factory.sources.registry import SourceFactory
from tests.document_helpers import ARTICLE, make_registry, run_convert
from tests.test_acceptance_fulltext_screening import _screened_full_text_world
from tests.test_extraction_next import _declare, _extractor
from tests.test_extraction_record import _row
from tests.test_fulltext_service import StubRoute, always, retrieved

pytestmark = pytest.mark.slow  # over ~60 s per file: dev runs deselect with -m "not slow"

FT = ScreeningStage.FULL_TEXT
SourcesFor = Callable[..., Mapping[str, SourceFactory]]
SESSION_A = "01JZ9Q3K5M7N8P0R2S4T6V8W1A"


@pytest.fixture
def ext_a() -> Actor:
    return _extractor(SESSION_A, "claude-opus-5-5")


@pytest.fixture
def world(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, mock_sources: SourcesFor
) -> list[str]:
    """The included works of the full-text world, extraction declared (every work dual)."""
    _screened_full_text_world(project, agent, agent_other, human, mock_sources)
    _declare(project, agent, 1.0)
    return sorted(w for w, o in final_outcomes(project, stage=FT).items() if o is Outcome.INCLUDED)


def _extract_work(project: Project, actor: Actor, work: str) -> tuple[str, str]:
    """Serve pass-A tasks until `work`'s, close it with two rows; (plain, latency) row ids."""
    for _ in range(60):
        batch: ExtractBatch | None = extract_next(project, actor, PassLabel.A).batch
        assert batch is not None, f"no task of {work}"
        if batch.records[0]["work_id"] != work:
            complete_task(project, actor, batch.task_id)
            continue
        res = extract_record(
            project,
            actor,
            batch.task_id,
            [_row(), _row("2", "t1.r3.c3", latency=_latency())],
            finish=True,
        )
        assert res.completed and not res.rows.rejected, res.rows.rejected
        plain, with_latency = res.rows.written
        return plain, with_latency
    raise AssertionError("too many tasks")


def _latency():  # type: ignore[no-untyped-def]
    from factory.model.extraction import FieldInput

    return FieldInput(value="1", anchor="t1", cell="t1.r3.c2", quote="1")


def _second_document(project: Project, work: str) -> str:
    """A second live document of `work` (arXiv source, HTML bytes) with a conversion."""
    body = ARTICLE + b"<!-- source copy -->"
    route = StubRoute(Route.ARXIV_SOURCE, always(retrieved(Route.ARXIV_SOURCE, body)))
    fetch_fulltext(
        project, routes={Route.ARXIV_SOURCE: route}, work_ids=[work], only=[Route.ARXIV_SOURCE]
    )
    run_convert(project, make_registry())
    from sqlalchemy import text

    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT document_id FROM fulltext_documents "
                "WHERE work_id = :w AND route = 'arxiv-source' AND superseded_by IS NULL"
            ),
            {"w": work},
        ).one()
    return str(row[0])


def test_preference_stales_one_work(project: Project, ext_a: Actor, world: list[str]) -> None:
    first, second = world[0], world[1]
    first_rows = set(_extract_work(project, ext_a, first))
    second_rows = set(_extract_work(project, ext_a, second))
    assert stale_extractions(project) == set()
    before = {(s.work_id, s.pass_label): (s.state, s.reason) for s in unit_states(project)}

    preferred = _second_document(project, first)
    default = default_conversion(project, first)
    assert default is not None and default.document_id != preferred
    prefer_document(project, project.human_actor(), first, preferred, "complete source copy")

    assert stale_extractions(project) == first_rows  # that work's rows, and only those
    assert not stale_extractions(project) & second_rows
    after = {(s.work_id, s.pass_label): (s.state, s.reason) for s in unit_states(project)}
    changed = {k for k in after if after[k] != before[k]}
    assert changed == {(first, PassLabel.A)}
    assert after[(first, PassLabel.A)] == ("stale", "document-version")
