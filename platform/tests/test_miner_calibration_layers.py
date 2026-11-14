"""The calibration draw respects the protocol use's `layers` (IDEA-69 (4)): a layer-filtered miner
is calibrated on its own works, not on the whole base population."""

# ruff: noqa: F811
from dataclasses import replace

from pydantic import JsonValue

from factory.events.envelope import Actor
from factory.mining.derive import derive_miner
from factory.mining.spec import MinerRegime, MinerSpec, Population, Selector
from factory.mining.taxonomy import Dimension, TaxonomySpec, taxonomy_to_json
from factory.model.protocol import TaxonomyUse
from factory.model.references import LayerDef, LayerSchemeRecorded
from factory.services.context import Project
from factory.services.miners import draw_miner_calibration
from factory.services.mining import miner_population, population, register_miner
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.reference_layers import record_scheme
from factory.services.taxonomies import register_taxonomy
from factory.services.work_layers import move_layer, request_mining
from tests.extraction_helpers import _both, ext_a, ext_b, screened, world  # noqa: F401
from tests.miner_helpers import VISION_NAME, method_vision, use


def _scheme() -> LayerSchemeRecorded:
    def layer(i: str, ring: int, snowball: bool) -> LayerDef:
        return LayerDef(id=i, ring=ring, snowball=snowball, name=i, criteria=f"criteria of {i}")

    return LayerSchemeRecorded(
        version=1, layers=(layer("core", 0, True), layer("applied", 1, False))
    )


def _list_with_layers(
    project: Project,
    agent: Actor,
    human: Actor,
    world: list[str],
    layers: tuple[str, ...],
    on_demand: bool = False,
) -> list[str]:
    """Half the works (every second) are core, the rest applied; the miner lists `layers`."""
    record_scheme(project, human, _scheme())
    ordered = sorted(world)
    for i, work in enumerate(ordered):
        move_layer(project, human, work, "core" if i % 2 == 0 else "applied", "test")
    taxonomy = TaxonomySpec(
        name="t-lay",
        version=1,
        dimensions=(Dimension("layer", "Layer", "Which layer?", "single", (), layer_scheme=1),),
    )
    register_taxonomy(project, human, taxonomy_to_json(taxonomy))
    layer_miner = derive_miner(
        taxonomy,
        ("layer",),
        name="m-lay",
        version=1,
        selector=Selector(Population.INCLUDED_FT),
        regime=MinerRegime(2, 3, 0.8, 0.9),
        layer_ids=("core", "applied"),
    )
    register_miner(project, agent, _json(layer_miner))
    spec = replace(method_vision(), regime=MinerRegime(2, 3, 0.8, 0.9))
    register_miner(project, agent, _json(spec))
    current = current_protocol(project)
    assert current is not None
    miners = (
        *(current.spec.miners or ()),
        use(layer_miner),
        use(spec, layers=layers, on_demand=on_demand),
    )
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(
            update={"miners": miners, "taxonomies": (TaxonomyUse(name="t-lay", version=1),)}
        ),
        reason="list the miner",
        semantic=True,
        effects={},
    )
    return ordered


def _json(spec: MinerSpec) -> JsonValue:
    from factory.mining.spec import spec_to_json

    return spec_to_json(spec)


def test_the_draw_holds_only_works_of_the_listed_layers(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    ordered = _list_with_layers(project, agent, human, world, ("core",))
    core = {w for w in ordered[::2]}
    base = {w for w, _ in population(project, method_vision().selector)}
    assert base - core, "the base population must hold works outside the layer"
    allowed = set(miner_population(project, VISION_NAME))
    assert allowed and allowed <= core
    drawn = draw_miner_calibration(project, human, VISION_NAME, 1, random_seed=7)
    assert {u.work_id for u in drawn.units} <= core
    assert drawn.population == len(allowed)


def test_without_layers_the_draw_is_the_base_population(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    _list_with_layers(project, agent, human, world, ())
    base = {w for w, _ in population(project, method_vision().selector)}
    drawn = draw_miner_calibration(project, human, VISION_NAME, 1, random_seed=7)
    assert drawn.population == len(base)


def test_requested_works_are_never_calibration_candidates(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    ordered = _list_with_layers(project, agent, human, world, ("core",), on_demand=True)
    outside = ordered[1]  # an applied work, outside the use's layers
    request_mining(project, human, works=[outside], miners=[VISION_NAME])
    assert outside in miner_population(project, VISION_NAME)  # production still serves it
    drawn = draw_miner_calibration(project, human, VISION_NAME, 1, random_seed=3)
    assert outside not in {u.work_id for u in drawn.units}
    assert drawn.population == len(ordered[::2])
