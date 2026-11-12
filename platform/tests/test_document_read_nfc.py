"""`document_read` matches work ids after NFC normalisation (IDEA-49, part 1).

A Hangul word of an id (surname or title slug) is stored decomposed (jamo: `normalize_title`
applies NFKD), while a model writes it composed. The two spellings look identical and differ as
strings; on 2026-11-09 a full-text screener was refused with "not a record of a batch this
session holds" for such a work.
"""

import unicodedata
from collections.abc import Callable, Mapping

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.protocol import ScreeningStage
from factory.model.screening import Channel, PassLabel, ScreeningItem, Verdict
from factory.services.calibration import calibration_items, draw_calibration, label_calibration
from factory.services.context import Project
from factory.services.document_read import document_read
from factory.services.screening import ScreenBatch, screen_next, screen_record
from factory.sources.registry import SourceFactory
from tests.document_helpers import promoted_works
from tests.fulltext_helpers import _convert, _world
from tests.helpers import openalex_item

FT = ScreeningStage.FULL_TEXT
SourcesFor = Callable[..., Mapping[str, SourceFactory]]

KOREAN = openalex_item(
    title="Agents 과학 discovery",
    author="Minsu Ahn",
    published="2021-01-01",
    openalex_id="W901",
    doi="10.1000/k1",
)


def _korean(project: Project) -> str:
    """The Korean work's stored id, decomposed (its Hangul title word is stored as jamo)."""
    (stored,) = [w for w in promoted_works(project) if unicodedata.normalize("NFC", w) != w]
    return stored


@pytest.fixture
def batch(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> tuple[ScreenBatch, str, str]:
    """A full-text pass A batch that holds the Korean work, the session holding it, and the
    work's stored id. Pass A screens the calibration batch, then sessions claim ordinary batches
    in turn until one holds the work."""
    _world(project, agent, human, mock_sources, extra_items=[KOREAN])
    _convert(project, promoted_works(project))
    draw_calibration(project, project.system_actor(), random_seed=3, stage=FT)
    stored = _korean(project)
    first = screen_next(project, agent, PassLabel.A, stage=FT).batch
    assert first is not None
    if stored in {str(r["work_id"]) for r in first.records}:
        return first, agent.session, stored
    for item in calibration_items(project, stage=FT):
        label_calibration(project, human, item, "include", None, Channel.CLI, stage=FT)
    items = [
        ScreeningItem(
            work_id=str(r["work_id"]),
            verdict=Verdict.INCLUDE,
            quote="Lorem ipsum dolor sit amet.",
            rationale="it fits",
            anchor="s3.p1",
        )
        for r in first.records
    ]
    assert len(screen_record(project, agent, first.task_id, items).written) == len(items)
    screener = agent
    for _ in range(20):
        served = screen_next(project, screener, PassLabel.A, stage=FT)
        assert served.batch is not None, served
        if stored in {str(r["work_id"]) for r in served.batch.records}:
            return served.batch, screener.session, stored
        screener = agent.model_copy(update={"session": project.ids.ulid()})
    raise AssertionError("no pass A batch holds the Korean work")


def test_screener_reads_a_decomposed_work_named_composed(
    project: Project, batch: tuple[ScreenBatch, str, str]
) -> None:
    held, session, stored = batch
    composed = unicodedata.normalize("NFC", stored)
    page = document_read(project, work_id=composed, session=session)
    record = next(r for r in held.records if r["work_id"] == stored)
    assert page.work_id == stored
    assert page.conversion_id == record["conversion_id"]
    assert page.segments == document_read(project, work_id=stored, session=session).segments


def test_researcher_reads_a_decomposed_work_named_composed(
    project: Project, batch: tuple[ScreenBatch, str, str]
) -> None:
    _, _, stored = batch
    composed = unicodedata.normalize("NFC", stored)
    assert document_read(project, work_id=composed).work_id == stored


def test_an_id_matching_no_work_is_still_refused(
    project: Project, batch: tuple[ScreenBatch, str, str]
) -> None:
    _, session, stored = batch
    with pytest.raises(FactoryValidationError) as caught:
        document_read(project, work_id=stored + "x", session=session)
    assert [issue.field for issue in caught.value.issues] == ["work_id"]
