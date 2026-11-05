import json
from collections.abc import Callable, Mapping
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.blobs import BlobStore
from factory.events.envelope import Actor
from factory.exports.keys import bib_key
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.dedup import active_merges, dedup_run
from factory.services.exports import (
    export_bibliography,
    export_prisma_svg,
    iter_works,
    select_works,
)
from factory.services.prisma import prisma_flow
from factory.services.search import list_works
from factory.sources.registry import SourceFactory
from tests.fulltext_helpers import FT, _ft_world
from tests.screening_helpers import MERGE_TITLE, _corpus, _merge_items, _settle

SourcesFor = Callable[..., Mapping[str, SourceFactory]]


def _text(project: Project, fmt: str = "bibtex", **kw: Any) -> str:
    return "".join(export_bibliography(project, fmt, **kw))  # type: ignore[arg-type]


def test_included_scope_uses_last_declared_stage(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    world = _ft_world(project, agent, human, mock_sources)
    outcomes = final_outcomes(project, stage=FT)
    expected = sorted(w for w, o in outcomes.items() if o is Outcome.INCLUDED)
    selected = select_works(project, "included")
    assert selected == expected
    assert world.eligible[0] not in selected  # excluded at full text
    assert len(selected) < len(list_works(project))


def test_included_scope_without_full_text_plan(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    pid = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, pid)
    assert select_works(project, "included") == sorted(w.id for w in list_works(project))


def test_corpus_scope_follows_dedup(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _corpus(project, agent, human, mock_sources, extra=_merge_items())
    before = select_works(project, "corpus")
    dedup_run(project)
    [merge] = active_merges(project)
    after = select_works(project, "corpus")
    assert len(after) == len(before) - 1
    assert merge.primary in after and not set(merge.absorbed) & set(after)
    out = _text(project, scope="corpus")
    assert out.count(MERGE_TITLE) == 1
    assert "10.1000/merge" in out  # the merged record keeps the DOI


def test_ids_scope_and_validation(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _corpus(project, agent, human, mock_sources)
    ids = select_works(project, "corpus")
    assert select_works(project, ids=[ids[3], ids[1]]) == [ids[1], ids[3]]
    with pytest.raises(FactoryValidationError) as unknown:
        select_works(project, ids=["rf:nope-00000000"])
    assert unknown.value.issues[0].field == "ids"
    with pytest.raises(FactoryValidationError) as neither:
        select_works(project)
    assert neither.value.issues[0].field == "scope"
    with pytest.raises(FactoryValidationError):
        select_works(project, "corpus", ids=ids[:1])
    with pytest.raises(FactoryValidationError):
        export_bibliography(project, "bibtex", ids=["rf:nope-00000000"])  # eager, nothing yielded
    with pytest.raises(FactoryValidationError):
        export_bibliography(project, "ris")  # type: ignore[arg-type]


def test_export_formats_and_keys(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _corpus(project, agent, human, mock_sources)
    ids = select_works(project, "corpus")
    bib = _text(project, scope="corpus")
    assert bib.count("@") == len(ids)
    assert f"{{{bib_key(ids[0])}," in bib
    data = json.loads(_text(project, "csl", scope="corpus"))
    assert [i["id"] for i in data] == [bib_key(w) for w in ids]
    assert _text(project, ascii_only=True, scope="corpus").isascii()


def test_iter_works_pages(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _corpus(project, agent, human, mock_sources)
    ids = select_works(project, "corpus")
    assert [w.id for w in iter_works(project, ids)] == ids
    assert list(iter_works(project, [])) == []


def test_export_byte_identical_across_rebuilds(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    pid = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, pid)
    first = _text(project)
    project.index.rebuild()
    assert _text(project) == first
    assert first


def test_export_reads_no_library(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _corpus(project, agent, human, mock_sources)

    def boom(*args: object, **kwargs: object) -> bytes:
        raise AssertionError("an export must not read blobs")

    monkeypatch.setattr(BlobStore, "get", boom)
    assert _text(project, scope="corpus")
    assert export_prisma_svg(project)


def test_prisma_svg_matches_flow(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    pid = _corpus(project, agent, human, mock_sources, extra=_merge_items())
    _settle(project, agent, human, pid)
    dedup_run(project)
    flow = prisma_flow(project)
    svg = export_prisma_svg(project)
    assert f"Records screened (n = {flow.screened})" in svg
    assert f"Duplicate records removed (n = {flow.duplicates_removed})" in svg
