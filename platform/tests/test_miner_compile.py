"""Compilation of miners to packs, the built-in round trip and the digest (M-C, task 2)."""

from dataclasses import replace

import pytest

from factory.mining.compile import (
    BUILT_IN_MINERS,
    compile_miner,
    miner_digest,
    miner_of_pack,
    unverified_fields,
)
from factory.mining.spec import (
    CitationKind,
    EnumKind,
    MinerField,
    MinerRegime,
    NumberKind,
    Population,
    QuoteKind,
    Selector,
    spec_from_json,
    spec_to_json,
)
from factory.mining.validate import validate_miner
from factory.packs import CONTRIBUTION_V1, ML_BENCHMARK_V1
from factory.packs.model import Check, FieldDef, FieldKind, Pack, UnitFamily
from tests.miner_helpers import vision_result

_SELECTOR = Selector(Population.INCLUDED_FT)
_REGIME = MinerRegime(2, 10, 0.8, 0.9)


@pytest.mark.parametrize("pack", [ML_BENCHMARK_V1, CONTRIBUTION_V1])
def test_built_in_round_trip(pack: Pack) -> None:
    spec = miner_of_pack(pack, _SELECTOR, _REGIME)
    rebuilt = compile_miner(spec)
    assert rebuilt == pack
    assert [f.name for f in rebuilt.fields] == [f.name for f in pack.fields]
    assert rebuilt.conditionals == pack.conditionals
    assert rebuilt.row_key_fields == pack.row_key_fields
    assert rebuilt.compared_fields == pack.compared_fields
    assert rebuilt.report is pack.report  # carried by reference; outside equality
    assert validate_miner(spec, built_in=True) == []
    assert spec_from_json(spec_to_json(spec)) == spec


def test_built_in_table_holds_both_packs() -> None:
    assert set(BUILT_IN_MINERS) == {"ml-benchmark@1", "contribution@1"}
    assert compile_miner(BUILT_IN_MINERS["ml-benchmark@1"]) == ML_BENCHMARK_V1
    assert compile_miner(BUILT_IN_MINERS["contribution@1"]) == CONTRIBUTION_V1


def test_a_pack_shape_without_a_kind_is_refused() -> None:
    odd = Pack(
        "odd",
        1,
        (FieldDef("x", "g", FieldKind.NUMBER, UnitFamily.SCORE, Check.TEXT_IN_QUOTE),),
        (),
        (),
        (),
    )
    with pytest.raises(ValueError, match="no miner kind"):
        miner_of_pack(odd, _SELECTOR, _REGIME)


def test_registered_miner_compiles_to_a_pack() -> None:
    pack = compile_miner(vision_result())
    assert pack.name == "m-vision-result" and pack.version == 1
    assert pack.required == ("metric", "value")
    assert pack.field("direction") == FieldDef(
        "direction",
        "result",
        FieldKind.TEXT,
        UnitFamily.NONE,
        Check.NONE,
        allowed=("higher", "lower"),
    )
    assert pack.field("value") is not None and pack.field("value").check is Check.NUMBER  # type: ignore[union-attr]
    # the quote field of group "evidence" is evidence only: dual extraction does not compare it
    assert pack.compared_fields == ("metric", "value", "direction")
    assert pack.row_key_fields == ("metric",)


def test_citation_patterns_are_the_union() -> None:
    spec = replace(
        vision_result(),
        citation_patterns=(r"\[\d+\]",),
        fields=(
            *vision_result().fields,
            MinerField("cite", "c", CitationKind((r"\[\d+\]", r"\(\d{4}\)"))),
        ),
    )
    assert compile_miner(spec).citation_patterns == (r"\[\d+\]", r"\(\d{4}\)")


def test_digest_ignores_prose_and_order_of_json_keys() -> None:
    spec = vision_result()
    prose = replace(
        spec,
        rationale="completely different words",
        fields=tuple(replace(f, description="described") for f in spec.fields),
    )
    assert miner_digest(prose) == miner_digest(spec)
    assert len(miner_digest(spec)) == 16
    body = spec_to_json(spec)
    reordered = spec_from_json(dict(reversed(list(body.items()))))
    assert miner_digest(reordered) == miner_digest(spec)


@pytest.mark.parametrize(
    "change",
    [
        lambda s: replace(
            s,
            fields=(
                replace(s.fields[1], kind=NumberKind(UnitFamily.COUNT)),
                *s.fields[:1],
                *s.fields[2:],
            ),
        ),
        lambda s: replace(
            s,
            fields=(
                *s.fields[:2],
                replace(s.fields[2], kind=EnumKind(("higher", "lower", "equal"))),
                s.fields[3],
            ),
        ),
        lambda s: replace(
            s, fields=(replace(s.fields[0], kind=CitationKind(("x",))), *s.fields[1:])
        ),
        lambda s: replace(s, fields=(replace(s.fields[0], required=False), *s.fields[1:])),
        lambda s: replace(s, version=2),
        lambda s: replace(s, selector=replace(s.selector, max_units=21)),
        lambda s: replace(s, procedure="rf-other"),
        lambda s: replace(s, regime=replace(s.regime, recall_min=0.7)),
    ],
)
def test_digest_changes_with_any_field_kind(change: object) -> None:
    spec = vision_result()
    assert miner_digest(change(spec)) != miner_digest(spec)  # type: ignore[operator]


def test_quote_kinds_alone_do_not_change_pack_equality_of_kinds() -> None:
    assert compile_miner(
        replace(vision_result(), fields=(MinerField("a", "g", QuoteKind(), True),))
    ).required == ("a",)


def test_unverified_fields_listed_for_ml_benchmark() -> None:
    free = unverified_fields(BUILT_IN_MINERS["ml-benchmark@1"])
    assert "variant" in free and "hardware" in free and "is_proposed" in free
    assert "value" not in free and "method_name" not in free
    assert unverified_fields(vision_result()) == []
