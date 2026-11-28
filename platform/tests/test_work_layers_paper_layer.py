"""A derived miner flagged `paper_layers` supplies the paper layers without a layer scheme on its
dimension, whatever the recorded reference layer scheme is."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import JsonValue

from factory.events.envelope import Actor
from factory.mining.derive import derive_miner
from factory.mining.spec import MinerRegime, Selector, spec_to_json
from factory.mining.spec import Population as MinerPopulation
from factory.mining.taxonomy import Category, Dimension, TaxonomySpec, taxonomy_to_json
from factory.model.miners import MinerUse
from factory.model.protocol import TaxonomyUse
from factory.model.references import LayerDef, LayerSchemeRecorded
from factory.services import work_layers
from factory.services.context import Project
from factory.services.mining import register_miner
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.reference_layers import record_scheme
from factory.services.taxonomies import register_taxonomy
from factory.services.work_layers import layer_of, layers_of, move_layer
from tests.extraction_helpers import _both, ext_a, ext_b, screened, world  # noqa: F401

NAME = "m-layer"


def _scheme() -> LayerSchemeRecorded:
    def layer(i: str, ring: int) -> LayerDef:
        return LayerDef(id=i, ring=ring, snowball=ring == 0, name=i, criteria=f"criteria of {i}")

    return LayerSchemeRecorded(version=1, layers=(layer("core", 0), layer("near", 1)))


def _setup(project: Project, agent: Actor, human: Actor, *, flagged: bool) -> None:
    record_scheme(project, human, _scheme())
    taxonomy = TaxonomySpec(
        name="t-pl",
        version=1,
        dimensions=(
            Dimension(
                "layer",
                "Layer",
                "Which layer?",
                "single",
                (Category("general-vlm", "General", "d"), Category("benchmark", "Bench", "d")),
            ),
        ),
    )
    register_taxonomy(project, human, taxonomy_to_json(taxonomy))
    spec = derive_miner(
        taxonomy,
        ("layer",),
        name=NAME,
        version=1,
        selector=Selector(MinerPopulation.INCLUDED_FT),
        regime=MinerRegime(2, 3, 0.8, 0.9),
    )
    register_miner(project, agent, _json(spec))
    current = current_protocol(project)
    assert current is not None
    miner_use = MinerUse.model_validate(
        {"name": NAME, "version": 1, "paper_layers": flagged, "dual_extract_sample": 1.0}
    )
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(
            update={
                "miners": (*(current.spec.miners or ()), miner_use),
                "taxonomies": (TaxonomyUse(name="t-pl", version=1),),
            }
        ),
        reason="list the paper-layer miner",
        semantic=True,
        effects={},
    )


def _json(spec: Any) -> JsonValue:
    return spec_to_json(spec)


def _rows(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    rows = [
        SimpleNamespace(work_id=w, fields={"category": SimpleNamespace(value=v)})
        for w, v in values.items()
    ]
    monkeypatch.setattr(work_layers, "final_rows", lambda project, scope: rows)
    monkeypatch.setattr(
        work_layers,
        "final_rows_restricted",
        lambda project, works, scope: [r for r in rows if r.work_id in works],
    )


def test_a_flagged_derived_miner_supplies_layers(
    project: Project,
    agent: Actor,
    human: Actor,
    world: list[str],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup(project, agent, human, flagged=True)
    a, b, c = sorted(world)[:3]
    _rows(monkeypatch, {a: "layer/general-vlm", b: "layer/not-stated", c: "layer/other"})
    got = layers_of(project)
    assert got[a].layer == "general-vlm" and got[a].source == "miner"
    assert got[a].scheme_version is None
    assert got[b].layer is None and got[b].source == "pending"
    assert got[b].miner_layer == "not-stated"
    assert got[c].source == "pending" and got[c].miner_layer == "other"


def test_an_unflagged_miner_without_a_layer_scheme_gives_nothing(
    project: Project,
    agent: Actor,
    human: Actor,
    world: list[str],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup(project, agent, human, flagged=False)
    _rows(monkeypatch, {sorted(world)[0]: "layer/general-vlm"})
    assert layers_of(project) == {}


def test_a_move_to_a_flagged_category_is_effective(
    project: Project,
    agent: Actor,
    human: Actor,
    world: list[str],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup(project, agent, human, flagged=True)
    a, b = sorted(world)[:2]
    _rows(monkeypatch, {a: "layer/general-vlm", b: "layer/not-stated"})
    move_layer(project, human, a, "benchmark", "read it")
    move_layer(project, human, b, "core", "scheme layer still works")
    assert layer_of(project, a).layer == "benchmark"
    assert layer_of(project, a).source == "moved"
    assert layer_of(project, a).miner_layer == "general-vlm"
    assert layer_of(project, b).layer == "core"


def test_a_move_outside_scheme_and_categories_is_ignored_not_recorded(
    project: Project,
    agent: Actor,
    human: Actor,
    world: list[str],  # noqa: F811
) -> None:
    from factory.errors import FactoryValidationError

    _setup(project, agent, human, flagged=False)
    with pytest.raises(FactoryValidationError):
        move_layer(project, human, sorted(world)[0], "benchmark", "not a layer here")


def test_the_flag_is_omitted_from_serialisation_when_false() -> None:
    plain = MinerUse.model_validate({"name": "m-a", "version": 1})
    assert "paper_layers" not in plain.model_dump(mode="json")
    on = MinerUse.model_validate({"name": "m-a", "version": 1, "paper_layers": True})
    assert on.model_dump(mode="json")["paper_layers"] is True
