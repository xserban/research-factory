"""Re-resolution restricted to layers (IDEA-89 T4). Every entry is invented."""

from __future__ import annotations

import pytest

from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.references import (
    LayerAssigned,
    LayerDef,
    LayerLabelled,
    LayerSchemeRecorded,
    LinkState,
)
from factory.services.context import Project
from factory.services.reference_items import cited_items
from factory.services.reference_layers import (
    entries_in_layers,
    record_scheme,
    snowball_layer_ids,
)
from factory.services.references import extract_references, re_resolve
from tests.document_helpers import events_of_type
from tests.references_service_helpers import Lookups, converted_work, oa_item
from tests.test_cli_references import _cli, _use

ENTRIES = [
    "R. Thornbury. Sparse kernels for tidal data. Imaginary Methods, 2019. doi:10.5555/jim.4.",
    "E. Marlowe. Weather of small fluids. Journal of Tests, 2018. doi:10.5555/jt.5.",
    "I. Vance. Granular flows in the lab. Journal of Tests, 2017. doi:10.5555/jt.6.",
]
BODY = ["See {cite:1}, {cite:2} and {cite:3}."]
RECORDS = [
    oa_item("Sparse kernels for tidal data", "Rae Thornbury", 2019, "W1", "10.5555/jim.4"),
    oa_item("Weather of small fluids", "Eli Marlowe", 2018, "W2", "10.5555/jt.5"),
    oa_item("Granular flows in the lab", "Ida Vance", 2017, "W3", "10.5555/jt.6"),
]


def _scheme() -> LayerSchemeRecorded:
    def layer(i: str, ring: int, snowball: bool) -> LayerDef:
        return LayerDef(id=i, ring=ring, snowball=snowball, name=i, criteria=f"criteria of {i}")

    return LayerSchemeRecorded(
        version=1, layers=(layer("core", 0, True), layer("applied", 1, False))
    )


def _key(project: Project, title: str) -> str:
    return next(i.key for i in cited_items(project).items if i.title == title)


def _assign(project: Project, agent: Actor, title: str, layer: str, stage: str = "title") -> None:
    blob = project.blobs.put_json({"item_keys": []})
    key = _key(project, title)
    event = project.events.make(
        "reference.layer_assigned",
        LayerAssigned(
            item_key=key,
            scheme_version=1,
            stage=stage,
            layer=layer,
            rationale="test",
        ),
        agent,
        refs=(key,),
        input_blob=blob,
    )
    project.record([event])


@pytest.fixture
def failed_links(project: Project, corpus: None, agent: Actor, human: Actor) -> None:
    """Three DOI entries recorded as source-error; a scheme; two items layered."""
    converted_work(project, ENTRIES, BODY)
    extract_references(project, agent, None, sources={})
    record_scheme(project, human, _scheme())
    _assign(project, agent, "Sparse kernels for tidal data", "core")
    _assign(project, agent, "Weather of small fluids", "applied")


def test_only_entries_of_the_requested_layers_are_retried(
    project: Project, agent: Actor, failed_links: None
) -> None:
    lookups = Lookups(openalex=RECORDS)
    summary = re_resolve(project, agent, sources=lookups.sources(), layers=["core"])
    assert lookups.asked == ["crossref doi:10.5555/jim.4"]
    assert summary.selected == 1 and summary.skipped_layer == 2
    assert summary.re_resolved[0].ordinals == [1]
    assert summary.re_resolved[0].states[LinkState.RESOLVED] == 1


def test_without_layers_everything_retryable_is_retried(
    project: Project, agent: Actor, failed_links: None
) -> None:
    lookups = Lookups(openalex=RECORDS)
    summary = re_resolve(project, agent, sources=lookups.sources())
    assert summary.selected == 3 and summary.skipped_layer == 0
    assert len(lookups.asked) == 1 and lookups.asked[0].count("|") == 2


def test_a_human_label_wins_over_the_agent_layer(
    project: Project, agent: Actor, human: Actor, failed_links: None
) -> None:
    key = _key(project, "Weather of small fluids")
    # the item is not in the calibration sample, so the label is written as the event it is
    project.record(
        [
            project.events.make(
                "reference.layer_labelled",
                LayerLabelled(item_key=key, scheme_version=1, layer="core"),
                human,
                refs=(key,),
            )
        ]
    )
    selected = entries_in_layers(project, ["core"])
    assert {o for _, o in selected} == {1, 2}  # tidal (agent: core) and weather (label: core)
    assert {o for _, o in entries_in_layers(project, ["applied"])} == set()


def test_the_abstract_stage_layer_wins_over_the_title_stage(
    project: Project, agent: Actor, failed_links: None
) -> None:
    _assign(project, agent, "Weather of small fluids", "core", stage="abstract")
    assert {o for _, o in entries_in_layers(project, ["core"])} == {1, 2}


def test_unknown_layer_is_refused_and_writes_nothing(
    project: Project, agent: Actor, failed_links: None
) -> None:
    lookups = Lookups(openalex=RECORDS)
    before = len(events_of_type(project, "reference.re_resolved"))
    with pytest.raises(FactoryValidationError) as bad:
        re_resolve(project, agent, sources=lookups.sources(), layers=["core", "nope"])
    assert [i.field for i in bad.value.issues] == ["layers"]
    assert lookups.asked == []
    assert len(events_of_type(project, "reference.re_resolved")) == before == 0


def test_layers_need_a_recorded_scheme(project: Project, corpus: None, agent: Actor) -> None:
    converted_work(project, ENTRIES, BODY)
    extract_references(project, agent, None, sources={})
    with pytest.raises(FactoryValidationError):
        re_resolve(project, agent, sources=Lookups().sources(), layers=["core"])


def test_snowball_layer_ids_are_the_schemes(project: Project, failed_links: None) -> None:
    assert snowball_layer_ids(project) == ["core"]


def test_cli_rejects_an_unknown_source_and_layer(
    project: Project,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    failed_links: None,
) -> None:
    _use(monkeypatch, Lookups(openalex=RECORDS))
    code, _, err = _cli(settings.root, "references", "re-resolve", "--source", "s2")
    assert code != 0 and "source" in err
    code, _, err = _cli(settings.root, "references", "re-resolve", "--layer", "nope")
    assert code != 0 and "layers" in err
    assert events_of_type(project, "reference.re_resolved") == []


def test_cli_snowball_layers_and_summary_counts(
    project: Project,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    failed_links: None,
) -> None:
    lookups = Lookups(openalex=RECORDS)
    _use(monkeypatch, lookups)
    code, out, _ = _cli(settings.root, "references", "re-resolve", "--snowball-layers")
    assert code == 0, out
    assert "1 entries selected, 2 skipped by layer, 0 skipped by flagged title" in out
    assert lookups.asked == ["crossref doi:10.5555/jim.4"]
