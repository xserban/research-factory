"""Attribute fields on a derived miner (decision 127 item 2): appended after the derived fields,
refused when they clash or are of another kind, and re-derived by `register`."""

# ruff: noqa: F811
import json
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.mining.derive import derive_miner
from factory.mining.spec import (
    EnumKind,
    IntegerKind,
    MinerField,
    MinerRegime,
    MinerSpec,
    NumberKind,
    Population,
    QuoteKind,
    Selector,
    Unverified,
    kind_to_json,
    spec_from_json,
    spec_to_json,
)
from factory.mining.taxonomy import Category, Dimension, TaxonomySpec, taxonomy_to_json
from factory.mining.validate import validate_miner
from factory.packs.model import UnitFamily
from factory.services.context import Project
from factory.services.mining import register_miner
from factory.services.taxonomies import register_taxonomy
from tests.cli_helpers import _env
from tests.extraction_helpers import screened, world  # noqa: F401

TAXONOMY = TaxonomySpec(
    name="t-attr",
    version=1,
    dimensions=(
        Dimension(
            "stage",
            "Stage",
            "Which stage?",
            "single",
            tuple(Category(i, i.upper(), f"Definition of {i}.") for i in ("plan", "run")),
        ),
    ),
)
SELECTOR = Selector(Population.INCLUDED_FT)
RUNNER = CliRunner()

SCALE = MinerField("scale", "attributes", EnumKind(("small", "large")), description="Scale.")
YEAR = MinerField("year", "attributes", IntegerKind(), compared=False)
SCORE = MinerField("score", "attributes", NumberKind(UnitFamily.SCORE), compared=False)
NOTE = MinerField("note", "attributes", QuoteKind(), compared=False)


def _derive(**over: object) -> MinerSpec:
    return derive_miner(
        TAXONOMY,
        ("stage",),
        name="m-attr",
        version=1,
        selector=SELECTOR,
        regime=MinerRegime(),
        **over,  # type: ignore[arg-type]
    )


def test_no_attributes_is_the_spec_without_the_argument() -> None:
    assert _derive(attributes=()) == _derive()
    assert spec_to_json(_derive(attributes=())) == spec_to_json(_derive())
    assert [f.name for f in _derive().fields] == ["category", "quote", "described_as"]


def test_attributes_are_appended_in_the_given_order() -> None:
    spec = _derive(attributes=(YEAR, SCALE, SCORE, NOTE))
    assert [f.name for f in spec.fields] == [
        "category", "quote", "described_as", "year", "scale", "score", "note",
    ]  # fmt: skip
    assert spec.fields[3:] == (YEAR, SCALE, SCORE, NOTE)
    assert spec.row_key_fields == ()
    assert spec.row_anchor_fields == ()
    assert validate_miner(spec) == []


@pytest.mark.parametrize(
    "attributes",
    [
        (replace(SCALE, name="category"),),
        (replace(SCALE, name="quote"),),
        (replace(SCALE, name="described_as"),),
        (SCALE, SCALE),
        (replace(SCALE, kind=Unverified()),),
        (replace(SCALE, required=True),),
    ],
)
def test_invalid_attributes_are_refused(attributes: tuple[MinerField, ...]) -> None:
    with pytest.raises(ValueError):
        _derive(attributes=attributes)


def _register(project: Project, agent: Actor, human: Actor, spec: MinerSpec) -> str:
    register_taxonomy(project, human, taxonomy_to_json(TAXONOMY))
    return register_miner(project, agent, spec_to_json(spec)).name


def test_a_derived_spec_with_attributes_registers(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    assert _register(project, agent, human, _derive(attributes=(SCALE, YEAR))) == "m-attr"


def test_a_tampered_attribute_list_is_still_validated(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    register_taxonomy(project, human, taxonomy_to_json(TAXONOMY))
    bad = _derive(attributes=(SCALE,))
    bad = replace(bad, fields=(*bad.fields, replace(SCALE, name="quote")))
    with pytest.raises(FactoryValidationError):
        register_miner(project, agent, spec_to_json(bad))
    required = replace(_derive(attributes=(SCALE,)))
    required = replace(required, fields=(*required.fields[:3], replace(SCALE, required=True)))
    with pytest.raises(FactoryValidationError) as raised:
        register_miner(project, agent, spec_to_json(required))
    assert raised.value.issues[0].field == "spec.taxonomy"


def _field_json(field: MinerField) -> dict[str, object]:
    return {
        "name": field.name,
        "group": field.group,
        "kind": kind_to_json(field.kind),
        "required": field.required,
        "description": field.description,
        "compared": field.compared,
    }


def test_cli_attributes_round_trip(
    settings: Settings, project: Project, human: Actor, world: list[str], tmp_path: Path
) -> None:
    register_taxonomy(project, human, taxonomy_to_json(TAXONOMY))
    path = tmp_path / "attributes.json"
    path.write_text(json.dumps([_field_json(SCALE), _field_json(YEAR)]))
    args = ["taxonomy", "derive", "t-attr", "1", "--miner-name", "m-attr", "--miner-version", "1"]
    args += ["--dimension", "stage"]
    result = RUNNER.invoke(app, [*args, "--attributes", str(path)], env=_env(settings.root))
    assert result.exit_code == 0, result.stderr
    assert spec_from_json(json.loads(result.stdout)) == _derive(attributes=(SCALE, YEAR))
    plain = RUNNER.invoke(app, args, env=_env(settings.root))
    assert spec_from_json(json.loads(plain.stdout)) == _derive()


def test_cli_refuses_invalid_attributes(
    settings: Settings, project: Project, human: Actor, world: list[str], tmp_path: Path
) -> None:
    register_taxonomy(project, human, taxonomy_to_json(TAXONOMY))
    args = ["taxonomy", "derive", "t-attr", "1", "--miner-name", "m-attr", "--miner-version", "1"]
    args += ["--dimension", "stage"]
    for body in ('{"not": "a list"}', "not json", json.dumps([{"name": "x"}])):
        path = tmp_path / "bad.json"
        path.write_text(body)
        result = RUNNER.invoke(app, [*args, "--attributes", str(path)], env=_env(settings.root))
        assert result.exit_code != 0
