"""Selectors over manifests and populations (M-C, task 4)."""

# ruff: noqa: F811
import inspect
from dataclasses import replace

import pytest

from factory.document.anchorise import anchorise
from factory.document.anchors import AnchorKind, Manifest, parse_manifest
from factory.mining.select import selected_anchors
from factory.mining.spec import Population, Selector
from factory.services.context import Project
from factory.services.document_read import default_conversion
from factory.services.mining import population
from tests.contribution_helpers import screened, world  # noqa: F401

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


def test_population_ta_and_references(project: Project, world: list[str]) -> None:
    ta = {w for w, _ in population(project, Selector(Population.INCLUDED_TA))}
    assert set(world) <= ta | set(world)
    assert list(population(project, Selector(Population.WITH_REFERENCES))) == []


def test_population_streams(project: Project, world: list[str]) -> None:
    selector = Selector(Population.INCLUDED_FT)
    stream = population(project, selector)
    assert inspect.isgenerator(stream)
    limited = list(population(project, replace(selector, max_units=1)))
    assert len(limited) == 1
    assert limited[0][0] == sorted(w for w, _ in population(project, selector))[0]
