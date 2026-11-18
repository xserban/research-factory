"""Selectors over manifests and populations (M-C, task 4)."""

# ruff: noqa: F811
import inspect
from dataclasses import replace
from typing import Any

import pytest

from factory.document.anchorise import anchorise
from factory.document.anchors import AnchorKind, Manifest, parse_manifest
from factory.events.envelope import Actor
from factory.mining.select import selected_anchors
from factory.mining.spec import Population, Selector
from factory.model.decisions import DecisionLevel
from factory.model.seed import SeedKind, SeedSpec
from factory.services.context import Project
from factory.services.document_read import default_conversion
from factory.services.mining import population, population_works
from factory.services.search import list_works
from factory.services.seeds import add_seeds
from tests.contribution_helpers import screened, with_references, world  # noqa: F401
from tests.helpers import bind_ids, openalex_item

DOC_V1 = """# 1 Introduction

We study things.

# 2 Experiments

Our model reaches 82.4 on the benchmark.

## 2.1 Ablations

Removing the module costs 3 points.

# 3 Related work

Earlier work reports 80.1.

| A | B |
| --- | --- |
| x | 1 |
"""

DOC_V2 = DOC_V1.replace("# 2 Experiments", "# 4 Experiments").replace("## 2.1", "## 4.1")


def _manifest(markdown: str) -> Manifest:
    return parse_manifest(anchorise(markdown))


def _texts(manifest: Manifest, ids: tuple[str, ...]) -> list[str]:
    return [a.text for i in ids if (a := manifest.get(i)) is not None]


def test_heading_pattern_selects_results_tables() -> None:
    manifest = _manifest(DOC_V1)
    selector = Selector(
        Population.CORPUS, elements=(AnchorKind.PARAGRAPH,), heading_patterns=("experiments",)
    )
    texts = _texts(manifest, selected_anchors(manifest, selector))
    assert "Our model reaches 82.4 on the benchmark." in texts
    assert "Removing the module costs 3 points." in texts  # a subsection of the match
    assert "Earlier work reports 80.1." not in texts
    assert "We study things." not in texts


def test_pattern_is_case_insensitive_search_on_normalised_heading() -> None:
    manifest = _manifest(DOC_V1)
    selector = Selector(Population.CORPUS, heading_patterns=("RELATED",))
    kinds = {manifest.get(i).kind for i in selected_anchors(manifest, selector)}  # type: ignore[union-attr]
    assert AnchorKind.TABLE in kinds and AnchorKind.CELL in kinds and AnchorKind.SECTION in kinds


def test_no_pattern_selects_every_anchor_of_the_kinds_and_nothing_means_all() -> None:
    manifest = _manifest(DOC_V1)
    tables = Selector(Population.CORPUS, elements=(AnchorKind.TABLE,))
    assert len(selected_anchors(manifest, tables)) == 1
    everything = selected_anchors(manifest, Selector(Population.CORPUS))
    assert everything == tuple(a.id for a in manifest.anchors)


def test_anchor_ids_differ_across_converter_versions_but_selection_holds() -> None:
    first, second = _manifest(DOC_V1), _manifest(DOC_V2)
    selector = Selector(
        Population.CORPUS, elements=(AnchorKind.PARAGRAPH,), heading_patterns=("experiments",)
    )
    ids_1, ids_2 = selected_anchors(first, selector), selected_anchors(second, selector)
    assert _texts(first, ids_1) == _texts(second, ids_2)
    assert ids_1 != ids_2  # the converters number the same sections differently


def test_selection_is_pure_and_carries_ids_only() -> None:
    manifest = _manifest(DOC_V1)
    selector = Selector(Population.CORPUS, heading_patterns=("experiments",))
    out = selected_anchors(manifest, selector)
    assert out == selected_anchors(manifest, selector)
    assert all(isinstance(i, str) and " " not in i for i in out)


@pytest.mark.parametrize(
    "which", [Population.INCLUDED_FINAL, Population.INCLUDED_FT, Population.CORPUS]
)
def test_population_names(project: Project, world: list[str], which: Population) -> None:
    got = list(population(project, Selector(which)))
    works = [w for w, _ in got]
    assert works == sorted(works)
    for work, conversion in got:
        ref = default_conversion(project, work)
        assert ref is not None and ref.conversion_id == conversion
    if which is not Population.CORPUS:
        assert set(works) <= set(world) and works


def test_population_ta_corpus_and_references_are_not_empty(
    project: Project, agent: Actor, world: list[str]
) -> None:
    ta = set(population_works(project, Population.INCLUDED_TA))
    assert ta and set(world) <= ta  # a work included at full text was included at title/abstract
    corpus = set(population_works(project, Population.CORPUS))
    assert corpus and ta <= corpus
    assert list(population(project, Selector(Population.WITH_REFERENCES))) == []
    with_references(project, agent, world[0])
    cited = list(population(project, Selector(Population.WITH_REFERENCES)))
    assert [w for w, _ in cited] == [world[0]]
    assert cited[0][1] == default_conversion(project, world[0]).conversion_id  # type: ignore[union-attr]


def test_corpus_excludes_a_probe_only_work(
    project: Project, agent: Actor, world: list[str], mock_sources: Any
) -> None:
    item = openalex_item(
        title="Seed only paper",
        author="Ada Zhou",
        published="2021-01-01",
        openalex_id="W9",
        doi="10.1000/seedonly",
    )
    seed = SeedSpec(kind=SeedKind.POSITIVE, cite="Zhou 2021", doi="10.1000/seedonly")
    add_seeds(
        project,
        agent,
        [seed],
        sources=mock_sources(openalex=[item]),
        decision_ids=bind_ids(project, agent, DecisionLevel.SEEDS),
    )
    hidden = {w.id for w in list_works(project, include_probe=True)} - {
        w.id for w in list_works(project)
    }
    assert hidden
    corpus = set(population_works(project, Population.CORPUS))
    assert corpus and not hidden & corpus


def test_population_streams(project: Project, world: list[str]) -> None:
    selector = Selector(Population.INCLUDED_FT)
    stream = population(project, selector)
    assert inspect.isgenerator(stream)
    limited = list(population(project, replace(selector, max_units=1)))
    assert len(limited) == 1
    assert limited[0][0] == sorted(w for w, _ in population(project, selector))[0]


# --- IDEA-99: fallback when the headings serve too little ---

from factory.mining.select import SELECTION_FALLBACK_BELOW, select_with_fallback  # noqa: E402

DOC_SUMMARY = (
    """# Summary

"""
    + " ".join(["word"] * 100)
    + """

# Reporting checklist

Tiny note here.

# References

1. Someone, A paper, 2020.
2. Another, B paper, 2021.
"""
)


def test_fallback_constant_is_ten_percent() -> None:
    assert SELECTION_FALLBACK_BELOW == 0.10


def test_fallback_when_share_below_threshold() -> None:
    manifest = _manifest(DOC_SUMMARY)
    selector = Selector(
        Population.CORPUS, elements=(AnchorKind.PARAGRAPH,), heading_patterns=("checklist",)
    )
    result = select_with_fallback(manifest, selector)
    assert result.fallback is True
    assert result.matched_share < SELECTION_FALLBACK_BELOW
    texts = _texts(manifest, result.anchors)
    assert any(t.startswith("word word") for t in texts)  # the Summary paragraph is served now
    assert "Tiny note here." in texts


def test_no_fallback_when_share_above_threshold() -> None:
    manifest = _manifest(DOC_SUMMARY)
    selector = Selector(
        Population.CORPUS, elements=(AnchorKind.PARAGRAPH,), heading_patterns=("summary",)
    )
    result = select_with_fallback(manifest, selector)
    assert result.fallback is False
    assert result.anchors == selected_anchors(manifest, selector)
    assert result.matched_share > 0.9


def test_no_fallback_without_heading_patterns() -> None:
    manifest = _manifest(DOC_SUMMARY)
    selector = Selector(Population.CORPUS, elements=(AnchorKind.TABLE,))
    result = select_with_fallback(manifest, selector)
    assert result.fallback is False and result.matched_share == 0.0


def test_no_fallback_without_paragraph_words() -> None:
    manifest = _manifest("# Summary\n")
    selector = Selector(Population.CORPUS, heading_patterns=("nothing",))
    result = select_with_fallback(manifest, selector)
    assert result.fallback is False and result.anchors == ()


def test_fallback_never_selects_bibliography_entries() -> None:
    manifest = _manifest(DOC_SUMMARY)
    kinds = {a.kind for a in manifest.anchors}
    selector = Selector(Population.CORPUS, heading_patterns=("checklist",))
    result = select_with_fallback(manifest, selector)
    assert result.fallback is True
    got = {manifest.get(i).kind for i in result.anchors}  # type: ignore[union-attr]
    assert AnchorKind.BIBLIOGRAPHY_ENTRY not in got
    if AnchorKind.BIBLIOGRAPHY_ENTRY in kinds:
        assert AnchorKind.PARAGRAPH in got
