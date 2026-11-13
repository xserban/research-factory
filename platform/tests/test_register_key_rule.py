"""`register` derives with the row key rule the spec declares: a version registered under the old
category key stays valid, a new single dimension spec keys on the work, any other key is refused
(IDEA-69 (1), option B)."""

# ruff: noqa: F811
from dataclasses import replace

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.mining.derive import derive_miner
from factory.mining.spec import MinerRegime, MinerSpec, Population, Selector, spec_to_json
from factory.mining.taxonomy import Category, Dimension, TaxonomySpec, taxonomy_to_json
from factory.services.mining import register_miner
from factory.services.taxonomies import register_taxonomy
from tests.extraction_helpers import _both, ext_a, ext_b, screened, world  # noqa: F401

TAXONOMY = TaxonomySpec(
    name="t-key",
    version=1,
    dimensions=(
        Dimension(
            "stage",
            "Stage",
            "Which stage?",
            "single",
            tuple(Category(i, i.upper(), f"Definition of {i}.") for i in ("plan", "run")),
        ),
        Dimension(
            "tech",
            "Technique",
            "Which techniques?",
            "multi",
            tuple(Category(i, i.upper(), f"Definition of {i}.") for i in ("rl", "llm")),
        ),
    ),
)


def _spec(dimensions: tuple[str, ...], **over: object) -> MinerSpec:
    spec = derive_miner(
        TAXONOMY,
        dimensions,
        name="m-key",
        version=1,
        selector=Selector(Population.INCLUDED_FT),
        regime=MinerRegime(),
    )
    return replace(spec, **over) if over else spec  # type: ignore[arg-type]


def test_new_single_spec_keys_on_the_work(project, agent: Actor, human: Actor, world) -> None:  # type: ignore[no-untyped-def]
    register_taxonomy(project, human, taxonomy_to_json(TAXONOMY))
    registered = register_miner(project, agent, spec_to_json(_spec(("stage",))))
    assert registered.name == "m-key"


def test_a_version_under_the_old_category_key_stays_valid(
    project, agent: Actor, human: Actor, world
) -> None:  # type: ignore[no-untyped-def]
    register_taxonomy(project, human, taxonomy_to_json(TAXONOMY))
    old = _spec(("stage",), row_key_fields=("category",))
    first = register_miner(project, agent, spec_to_json(old))
    again = register_miner(project, human, spec_to_json(old))  # re-registration and imports
    assert again.digest == first.digest


def test_other_keys_are_refused(project, agent: Actor, human: Actor, world) -> None:  # type: ignore[no-untyped-def]
    register_taxonomy(project, human, taxonomy_to_json(TAXONOMY))
    for key in (("quote",), ("category", "quote")):
        with pytest.raises(FactoryValidationError) as raised:
            register_miner(project, agent, spec_to_json(_spec(("stage",), row_key_fields=key)))
        assert raised.value.issues[0].field == "row_key_fields"


def test_the_work_key_is_refused_for_a_multi_dimension(
    project, agent: Actor, human: Actor, world
) -> None:  # type: ignore[no-untyped-def]
    register_taxonomy(project, human, taxonomy_to_json(TAXONOMY))
    with pytest.raises(FactoryValidationError) as raised:
        register_miner(project, agent, spec_to_json(_spec(("tech",), row_key_fields=())))
    assert raised.value.issues[0].field == "spec.taxonomy"
    assert "work" in raised.value.issues[0].reason
