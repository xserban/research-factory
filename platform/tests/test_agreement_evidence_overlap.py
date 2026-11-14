"""Evidence-overlap agreement for free-quote fields, off by default (IDEA-52).

Exact-string agreement and evidence-overlap agreement differ on a fixture of quote pairs: the same
evidence worded differently agrees only under the option; unrelated evidence agrees under neither;
enum and number fields are never compared by overlap."""

import pytest

from factory.extraction.verify import pack_row_key
from factory.mining.compile import compile_miner
from factory.mining.score import score
from factory.model.extraction import StoredField
from factory.model.miner_calibration import GoldRow
from factory.model.protocol import ExtractionSchema
from factory.model.screening import PassLabel
from factory.packs import Pack
from factory.services.extraction import ExtractionRow
from factory.services.extraction_agreement import (
    _compare,
    _Pair,
    _State,
    _tally,
    evidence_overlaps,
    same_field,
)
from tests.miner_helpers import vision_result

PACK = compile_miner(vision_result())
METRIC = PACK.field("metric")


def _f(value: str, anchor: str | None = None, **over: object) -> StoredField:
    base: dict[str, object] = {
        "value": value,
        "quote": value,
        "anchor": anchor,
        "copy_marker": False,
    }
    base.update(over)
    return StoredField.model_validate(base)


# pairs of (A quote, A anchor, B quote, B anchor, exact agrees, overlap agrees at 0.5)
CASES = [
    ("accuracy on the test set", "s1.p1", "accuracy on the test set", "s1.p1", True, True),
    # one quote contains the other: spans overlap
    (
        "accuracy on the held-out test set",
        "s1.p1",
        "accuracy on the held-out test set of 500",
        "s1.p2",
        False,
        True,
    ),
    # the same words in another order: token overlap 3/4
    ("top-1 accuracy of 91%", "s2.p1", "91% top-1 accuracy", "s2.p2", False, True),
    # different sentences of one paragraph: the same anchor
    ("trained for ten epochs", "s3.p4", "batch size was 32", "s3.p4", False, True),
    # unrelated evidence
    ("latency per image", "s4.p1", "training cost in gpu hours", "s5.p2", False, False),
    # a little shared wording only: 1/7 under the threshold
    ("mean accuracy over runs", "s6.p1", "mean latency under load", "s7.p1", False, False),
]


@pytest.mark.parametrize(("qa", "aa", "qb", "ab", "exact", "overlap"), CASES)
def test_exact_and_overlap_differ_as_intended(
    qa: str, aa: str, qb: str, ab: str, exact: bool, overlap: bool
) -> None:
    fa, fb = _f(qa, aa), _f(qb, ab)
    assert same_field(METRIC, fa, fb) is exact  # off by default
    assert same_field(METRIC, fa, fb, evidence_overlap=0.5) is overlap
    assert same_field(METRIC, fb, fa, evidence_overlap=0.5) is overlap  # symmetric


def test_the_threshold_decides_token_overlap() -> None:
    fa, fb = _f("top-1 accuracy of 91%", "s2.p1"), _f("91% top-1 accuracy", "s2.p2")
    assert evidence_overlaps(fa, fb, 0.8) and not evidence_overlaps(fa, fb, 0.81)


def test_other_fields_are_never_compared_by_overlap() -> None:
    value = PACK.field("value")
    direction = PACK.field("direction")
    a = _f("1", "s1.p1", canonical="1")
    b = _f("2", "s1.p1", canonical="2")  # same anchor, different number
    assert not same_field(value, a, b, evidence_overlap=0.1)
    assert not same_field(
        direction, _f("higher", "s1.p1"), _f("lower", "s1.p1"), evidence_overlap=0.1
    )


def test_reported_in_still_has_to_match() -> None:
    from factory.model.extraction import ReportedIn

    a = _f("accuracy on the test set", "s1.p1")
    b = _f("accuracy on the test set", "s1.p1", reported_in=ReportedIn.CITED)
    assert not same_field(METRIC, a, b, evidence_overlap=0.5)


# --- the score ---


def _row(key: str, metric: StoredField) -> GoldRow:
    return GoldRow(row_key=key, fields={"metric": metric, "value": _f("1", canonical="1")})


def test_score_records_the_threshold_and_differs() -> None:
    gold = {f"w{i}": (_row(f"rk_{i:012d}", _f(c[0], c[1])),) for i, c in enumerate(CASES)}
    agent = {f"w{i}": (_row(f"rk_{i:012d}", _f(c[2], c[3])),) for i, c in enumerate(CASES)}
    exact = score(gold, agent, PACK)
    overlap = score(gold, agent, PACK, evidence_overlap=0.5)
    assert exact.evidence_overlap is None and overlap.evidence_overlap == 0.5
    # each row has a metric and a value field; the value always agrees
    assert exact.field_agreement == pytest.approx((1 + 6) / 12)
    assert overlap.field_agreement == pytest.approx((4 + 6) / 12)


# --- the pass agreement ---


def _er(work: str, label: PassLabel, metric: StoredField, key: str) -> ExtractionRow:
    fields = {"metric": metric, "value": _f("1", canonical="1")}
    return ExtractionRow(
        extraction_id=f"x-{work}-{label.value}",
        work_id=work,
        pass_label=label,
        task_id="t",
        protocol_id="p",
        conversion_id=f"c-{work}",
        document_id="d",
        row_key=key,
        fields=fields,
        event_id="e",
    )


def _state(pack: Pack) -> _State:
    schema = ExtractionSchema(pack="m-vision-result", pack_version=1, fields=("metric", "value"))
    pairs: list[_Pair] = []
    for i, c in enumerate(CASES):
        key = pack_row_key(pack, f"c{i}", {"metric": _f(c[0])})
        pair = _Pair(
            f"w{i}",
            key,
            [_er(f"w{i}", PassLabel.A, _f(c[0], c[1]), key)],
            [_er(f"w{i}", PassLabel.B, _f(c[2], c[3]), key)],
            dual=True,
        )
        pair.compared = _compare(pack, ["metric", "value"], pair.a[0], pair.b[0])
        pairs.append(pair)
    return _State(
        scope=None,  # type: ignore[arg-type]
        schema=schema,
        pack=pack,
        configs={},
        known=True,
        dual=frozenset(p.work_id for p in pairs),
        single=frozenset(),
        blocking=False,
        pairs=pairs,
    )


def test_the_pass_agreement_differs_and_the_default_is_exact() -> None:
    state = _state(PACK)
    exact = _tally(state)
    overlap = _tally(state, 0.5)
    assert exact.overall == pytest.approx((1 + 6) / 12)  # off: as before
    assert overlap.overall == pytest.approx((4 + 6) / 12)
    assert (overlap.rows_aligned, overlap.rows_unmatched) == (6, 0)
    assert [g.compared for g in overlap.rates] == [g.compared for g in exact.rates]


def test_containment_is_on_token_boundaries() -> None:
    assert not evidence_overlaps(_f("ion", "s1.p1"), _f("ionization energy", "s2.p1"), 0.5)
    assert not evidence_overlaps(_f("3", "s1.p1"), _f("13 samples", "s2.p1"), 0.5)
    # a contained phrase still overlaps, at any threshold and in either order
    short, long = _f("mean accuracy", "s1.p1"), _f("the mean accuracy over many runs", "s2.p1")
    assert evidence_overlaps(short, long, 1.0) and evidence_overlaps(long, short, 1.0)
    # the shorter's tokens must be contiguous in the longer
    assert not evidence_overlaps(_f("mean runs", "s1.p1"), long, 1.0)


def test_punctuation_and_hyphens_are_ignored() -> None:
    assert evidence_overlaps(
        _f("ionization energy.", "s1.p1"), _f("the ionization energy", "s2.p1"), 1.0
    )
    assert evidence_overlaps(_f("state-of-the-art", "s1.p1"), _f("state of the art", "s2.p1"), 1.0)
    assert evidence_overlaps(_f("(mean accuracy),", "s1.p1"), _f("the mean accuracy", "s2.p1"), 1.0)
    assert not evidence_overlaps(_f("ion.", "s1.p1"), _f("ionization energy", "s2.p1"), 0.5)
    assert not evidence_overlaps(_f("3.", "s1.p1"), _f("13 samples", "s2.p1"), 0.5)
    assert not evidence_overlaps(_f("...", "s1.p1"), _f("ionization", "s2.p1"), 0.5)


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.5])
def test_the_threshold_is_bounded(bad: float) -> None:
    from factory.errors import FactoryValidationError

    with pytest.raises(FactoryValidationError):
        score({}, {}, PACK, evidence_overlap=bad)
    with pytest.raises(FactoryValidationError):
        _tally(_state(PACK), bad)
    assert score({}, {}, PACK, evidence_overlap=1.0).evidence_overlap == 1.0
