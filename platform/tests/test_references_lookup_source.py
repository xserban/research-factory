"""The lookup source of reference resolution (IDEA-89): Crossref by default, OpenAlex on request,
no request for a flagged title. Every entry is invented."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.references import LinkState
from factory.services.context import Project
from factory.services.reference_resolve import load_corpus, resolve_entries
from factory.services.references import extract_references, re_resolve
from tests.document_helpers import events_of_type
from tests.references_service_helpers import Lookups, converted_work, oa_item

ENTRIES = [
    "R. Thornbury. Sparse kernels for tidal data. Imaginary Methods, 2019. doi:10.5555/jim.4."
]
RECORD = oa_item("Sparse kernels for tidal data", "Rae Thornbury", 2019, "W9", "10.5555/jim.4")


@dataclass(frozen=True)
class _Entry:
    ordinal: int
    title: str | None
    doi: str | None = None
    arxiv: str | None = None
    url: str | None = None
    year: int | None = 2020
    first_author: str | None = "Zhou"
    venue: str | None = None


def test_default_lookup_source_is_crossref(project: Project, corpus: None, agent: Actor) -> None:
    converted_work(project, ENTRIES, ["x {cite:1}"])
    lookups = Lookups(openalex=[RECORD])
    [result] = extract_references(project, agent, None, sources=lookups.sources()).extractions
    assert lookups.asked == ["crossref doi:10.5555/jim.4"]
    assert result.states[LinkState.RESOLVED] == 1
    [resolved] = events_of_type(project, "reference.resolved")
    r = cast(dict[str, Any], cast(list[Any], resolved.payload["resolutions"])[0])
    assert r["method"] == "lookup-identifier" and r["no_source_record"] is False


def test_openalex_is_selectable(project: Project, corpus: None, agent: Actor) -> None:
    converted_work(project, ENTRIES, ["x {cite:1}"])
    lookups = Lookups(openalex=[RECORD])
    extract_references(project, agent, None, sources=lookups.sources(), lookup_source="openalex")
    assert lookups.asked == ["openalex doi:10.5555/jim.4"]


def test_re_resolve_defaults_to_crossref_and_takes_openalex(
    project: Project, corpus: None, agent: Actor
) -> None:
    converted_work(project, ENTRIES, ["x {cite:1}"])
    extract_references(project, agent, None, sources={})  # nothing asked: source-error
    lookups = Lookups(openalex=[RECORD])
    summary = re_resolve(project, agent, sources=lookups.sources())
    assert lookups.asked == ["crossref doi:10.5555/jim.4"]
    assert summary.re_resolved[0].states[LinkState.RESOLVED] == 1


def test_unknown_source_is_refused_and_writes_nothing(
    project: Project, corpus: None, agent: Actor
) -> None:
    converted_work(project, ENTRIES, ["x {cite:1}"])
    lookups = Lookups(openalex=[RECORD])
    before = len(events_of_type(project, "reference.extracted"))
    with pytest.raises(FactoryValidationError) as bad:
        extract_references(project, agent, None, sources=lookups.sources(), lookup_source="s2")
    assert [i.field for i in bad.value.issues] == ["source"]
    with pytest.raises(FactoryValidationError):
        re_resolve(project, agent, sources=lookups.sources(), lookup_source="s2")
    assert len(events_of_type(project, "reference.extracted")) == before == 0
    assert lookups.asked == []


@pytest.mark.parametrize("title", ["A. Zhou, B. Liu, C. Chen", "et al. something", "Tidal"])
def test_flagged_title_is_not_searched(
    project: Project, corpus: None, agent: Actor, title: str | None
) -> None:
    lookups = Lookups(openalex=[RECORD])
    outcome = resolve_entries(
        project,
        agent,
        [_Entry(1, title)],
        sources=lookups.sources(),
        corpus=load_corpus(project),
    )
    [r] = outcome.resolutions
    assert r.state is LinkState.UNRESOLVED and r.reason == "no-identifier-no-title"
    assert lookups.asked == [] and outcome.lookup_runs == () and outcome.flagged_titles == 1


def test_an_entry_without_a_title_is_not_searched_either(
    project: Project, corpus: None, agent: Actor
) -> None:
    lookups = Lookups(openalex=[RECORD])
    outcome = resolve_entries(
        project, agent, [_Entry(1, None)], sources=lookups.sources(), corpus=load_corpus(project)
    )
    assert outcome.resolutions[0].reason == "no-identifier-no-title" and lookups.asked == []


def test_usable_title_is_searched_in_the_chosen_source(
    project: Project, corpus: None, agent: Actor
) -> None:
    lookups = Lookups(openalex=[RECORD])
    entry = _Entry(1, "Sparse kernels for tidal data", year=2019, first_author="Thornbury")
    for source in ("crossref", "openalex"):
        resolve_entries(
            project,
            agent,
            [entry],
            sources=lookups.sources(),
            corpus=load_corpus(project),
            lookup_source=source,
        )
    assert lookups.asked == [
        "crossref title.search:sparse kernels for tidal data",
        "openalex title.search:sparse kernels for tidal data",
    ]
