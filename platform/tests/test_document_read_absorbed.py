"""`document_read` for a canonical work reads the documents of works merged into it.

A full-text batch pins the default conversion of the canonical work, which may belong to an
absorbed work (`default_conversion`). Naming that conversion or its document, or naming neither,
must read it; a document of a work outside the merge is still refused.
"""

from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.services.context import Project
from factory.services.document_read import default_conversion, document_read
from tests.document_helpers import ARTICLE, fetched_document, make_registry, run_convert
from tests.helpers import SourcesFor
from tests.notice_helpers import dependent_world, numbered_records
from tests.region_helpers import merge_works


def _merged(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> tuple[str, str, str]:
    world = dependent_world(project, agent, human, mock_sources, numbered_records(3))
    canonical, absorbed, outsider = world.included[:3]
    fetched_document(project, absorbed, ARTICLE)
    fetched_document(project, outsider, ARTICLE + b"<!-- outsider -->")
    run_convert(project, make_registry())
    merge_works(project, canonical, absorbed)
    return canonical, absorbed, outsider


def test_absorbed_conversion_named_explicitly_is_read(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    canonical, _, _ = _merged(project, agent, human, mock_sources)
    ref = default_conversion(project, canonical)
    assert ref is not None
    page = document_read(project, work_id=canonical, conversion_id=ref.conversion_id)
    assert page.conversion_id == ref.conversion_id


def test_absorbed_document_named_explicitly_is_read(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    canonical, _, _ = _merged(project, agent, human, mock_sources)
    ref = default_conversion(project, canonical)
    assert ref is not None
    page = document_read(project, work_id=canonical, document_id=ref.document_id)
    assert page.document_id == ref.document_id


def test_canonical_work_without_its_own_document_reads_the_absorbed_one(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    canonical, _, _ = _merged(project, agent, human, mock_sources)
    ref = default_conversion(project, canonical)
    assert ref is not None
    assert document_read(project, work_id=canonical).conversion_id == ref.conversion_id


def test_conversion_of_a_work_outside_the_merge_is_refused(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    canonical, _, outsider = _merged(project, agent, human, mock_sources)
    other = default_conversion(project, outsider)
    assert other is not None
    with pytest.raises(FactoryValidationError):
        document_read(project, work_id=canonical, conversion_id=other.conversion_id)
