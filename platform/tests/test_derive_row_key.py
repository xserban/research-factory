"""A derived miner for one single dimension keys its row on the work (IDEA-69 (1)), and the layer
pass case reads 0.85 under both the stricter rate (IDEA-69 (2)) and the work key.

The layer pass of 2026-11-13 (`m-layer` v1): 40 dual works, the passes agreed on the layer of 34
and chose different layers on 6. Keyed on the category, the 6 works gave 12 unmatched rows and the
aligned rate read 1.000; the true agreement is 34/40 = 0.85."""

from dataclasses import replace

import pytest

from factory.extraction.verify import pack_row_key
from factory.mining.compile import compile_miner
from factory.mining.derive import derive_miner
from factory.mining.score import score
from factory.mining.spec import MinerRegime, MinerSpec, Population, Selector
from factory.mining.taxonomy import Category, Dimension, TaxonomySpec
from factory.mining.validate import validate_miner
from factory.model.extraction import StoredField
from factory.model.miner_calibration import GoldRow
from factory.model.protocol import ExtractionSchema
from factory.model.screening import PassLabel
from factory.packs import Pack
from factory.services.extraction import ExtractionRow
from factory.services.extraction_agreement import _compare, _Pair, _State, _tally

LAYERS = ("l1", "l2", "l3")
SELECTOR = Selector(Population.INCLUDED_FT)
REGIME = MinerRegime()


def _cats(*ids: str) -> tuple[Category, ...]:
    return tuple(Category(i, i.upper(), f"Definition of {i}.") for i in ids)


TAXONOMY = TaxonomySpec(
    name="t-test",
    version=1,
    dimensions=(
        Dimension("layer", "Layer", "Which layer?", "single", (), layer_scheme=1),
        Dimension("stage", "Stage", "Which stage?", "single", _cats("plan", "run")),
        Dimension("tech", "Technique", "Which techniques?", "multi", _cats("rl", "llm")),
    ),
)


def _derive(*dimensions: str) -> MinerSpec:
    return derive_miner(
        TAXONOMY,
        dimensions,
        name="m-test",
        version=1,
        selector=SELECTOR,
        regime=REGIME,
        layer_ids=LAYERS,
    )


def test_single_dimension_of_single_cardinality_keys_on_the_work() -> None:
    for dimension in ("layer", "stage"):
        spec = _derive(dimension)
        assert spec.row_key_fields == ()
        assert validate_miner(spec) == []
        pack = compile_miner(spec)
        assert pack.row_per_work
        one = pack_row_key(pack, "c1", {"category": _f("x")})
        assert one == pack_row_key(pack, "c1", {"category": _f("y")})
        assert one != pack_row_key(pack, "c2", {"category": _f("x")})


def test_multi_dimension_and_multi_cardinality_keep_the_category_key() -> None:
    for dimensions in (("tech",), ("layer", "stage")):
        spec = _derive(*dimensions)
        assert spec.row_key_fields == ("category",)
        assert not compile_miner(spec).row_per_work


def test_a_hand_written_miner_still_declares_its_key() -> None:
    spec = replace(_derive("stage"), taxonomy=None)
    assert any(i.field == "row_key_fields" for i in validate_miner(spec))
    assert not compile_miner(spec).row_per_work


# --- The layer pass case ---


def _f(value: str) -> StoredField:
    return StoredField(value=value, quote="q", copy_marker=False)


def _choices() -> dict[str, tuple[str, str]]:
    """40 works: the passes agree on 34 and choose different layers on 6."""
    out = {f"w{i:02d}": ("layer:l1", "layer:l1") for i in range(34)}
    out.update({f"w{i:02d}": ("layer:l1", "layer:l2") for i in range(34, 40)})
    return out


def _row(pack: Pack, work: str, label: PassLabel, category: str) -> ExtractionRow:
    fields = {"category": _f(category), "quote": _f("q")}
    return ExtractionRow(
        extraction_id=f"x-{work}-{label.value}",
        work_id=work,
        pass_label=label,
        task_id="t",
        protocol_id="p",
        conversion_id=f"c-{work}",
        document_id="d",
        row_key=pack_row_key(pack, f"c-{work}", fields),
        fields=fields,
        event_id="e",
    )


def _state(pack: Pack) -> _State:
    """The agreement state of the layer case under `pack`'s row key."""
    pairs: dict[tuple[str, str], _Pair] = {}
    for work, (a, b) in _choices().items():
        for label, category in ((PassLabel.A, a), (PassLabel.B, b)):
            row = _row(pack, work, label, category)
            pair = pairs.setdefault(
                (work, row.row_key), _Pair(work, row.row_key, [], [], dual=True)
            )
            (pair.a if label is PassLabel.A else pair.b).append(row)
    schema = ExtractionSchema(pack="m-test", pack_version=1, fields=("category", "quote"))
    for pair in pairs.values():
        if pair.aligned:
            pair.compared = _compare(pack, ["category"], pair.a[0], pair.b[0])
    return _State(
        scope=None,  # type: ignore[arg-type]  # unused by the tally
        schema=schema,
        pack=pack,
        configs={},
        known=True,
        dual=frozenset(_choices()),
        single=frozenset(),
        blocking=False,
        pairs=list(pairs.values()),
    )


def test_layer_case_category_key_now_reads_0_85_over_all_rows() -> None:
    legacy = compile_miner(replace(_derive("layer"), row_key_fields=("category",)))
    tally = _tally(_state(legacy))
    assert (tally.rows_aligned, tally.rows_unmatched, tally.unmatched_slots) == (34, 12, 6)
    assert tally.overall == 1.0  # what the layer pass reported
    assert tally.overall_all_rows == pytest.approx(0.85)


def test_layer_case_work_key_aligns_every_work_and_reads_0_85() -> None:
    tally = _tally(_state(compile_miner(_derive("layer"))))
    assert (tally.rows_aligned, tally.rows_unmatched, tally.unmatched_slots) == (40, 0, 0)
    assert tally.overall == pytest.approx(0.85)
    assert tally.overall_all_rows == pytest.approx(0.85)


def _gold(pack: Pack, side: int) -> dict[str, tuple[GoldRow, ...]]:
    out: dict[str, tuple[GoldRow, ...]] = {}
    for work, choice in _choices().items():
        fields = {"category": _f(choice[side]), "quote": _f("q")}
        out[work] = (GoldRow(row_key=pack_row_key(pack, f"c-{work}", fields), fields=fields),)
    return out


def test_layer_case_in_the_calibration_score() -> None:
    legacy = compile_miner(replace(_derive("layer"), row_key_fields=("category",)))
    old = score(_gold(legacy, 0), _gold(legacy, 1), legacy)
    assert (old.matched, old.unmatched, old.field_agreement) == (34, 6, 1.0)
    assert old.field_agreement_all == pytest.approx(0.85)
    work = compile_miner(_derive("layer"))
    new = score(_gold(work, 0), _gold(work, 1), work)
    assert (new.matched, new.unmatched) == (40, 0)
    assert new.field_agreement == pytest.approx(0.85) == new.field_agreement_all
