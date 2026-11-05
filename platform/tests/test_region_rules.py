"""Region rule models and canonical hashing (slice 3d, plan Regions-A, task 1)."""

from __future__ import annotations

import gzip
import inspect

import pytest
from pydantic import TypeAdapter, ValidationError

from factory.lineage.paths import MAX_DEPTH
from factory.model.protocol import ScreeningStage
from factory.regions import version as version_module
from factory.regions.rules import (
    CitesRule,
    CorpusRule,
    LineageRule,
    MemberType,
    RegionRule,
    Rule,
    RuleSet,
    RunRule,
    TextRule,
)
from factory.regions.version import (
    canonical_rules,
    compress,
    members_hash,
    members_text,
    region_version,
    rules_hash,
)

R1 = "R@" + "a" * 8


def _lineage(depth: int = 2) -> LineageRule:
    return LineageRule(node="rf:a-1", direction="ancestors", depth=depth)


def test_rule_discriminator_round_trip() -> None:
    adapter: TypeAdapter[Rule] = TypeAdapter(Rule)
    for rule in (
        CorpusRule(outcome="included"),
        RunRule(run_id="run_x"),
        _lineage(),
        CitesRule(base=R1, direction="citing", min_k=2),
        RegionRule(version=R1),
        TextRule(blocks=(("Attention", "attn"),)),
    ):
        assert adapter.validate_python(rule.model_dump(mode="json")) == rule


def test_lineage_depth_bounds() -> None:
    _lineage(1)
    _lineage(MAX_DEPTH)
    for bad in (0, MAX_DEPTH + 1):
        with pytest.raises(ValidationError):
            _lineage(bad)


def test_run_rule_exactly_one() -> None:
    with pytest.raises(ValidationError):
        RunRule()
    with pytest.raises(ValidationError):
        RunRule(run_id="a", query_id="b")


def test_text_rule_bounds() -> None:
    with pytest.raises(ValidationError):
        TextRule(blocks=())
    with pytest.raises(ValidationError):
        TextRule(blocks=((),))
    with pytest.raises(ValidationError):
        TextRule(blocks=tuple((f"t{i}",) for i in range(9)))
    with pytest.raises(ValidationError):
        TextRule(blocks=(tuple(f"t{i}" for i in range(21)),))
    assert TextRule(blocks=(("  Foo   BAR ",),)).blocks == (("foo bar",),)


def test_canonical_order_independent() -> None:
    a, b = CorpusRule(outcome="included"), _lineage()
    one = RuleSet(include=(a, b), exclude=(RunRule(run_id="r1"), RunRule(run_id="r2")))
    two = RuleSet(include=(b, a, a), exclude=(RunRule(run_id="r2"), RunRule(run_id="r1")))
    assert canonical_rules(one) == canonical_rules(two)
    assert rules_hash(one) == rules_hash(two)
    flipped = LineageRule(
        node="rf:a-1", direction="ancestors", depth=2, edge_types=("improves-on", "builds-on")
    )
    assert rules_hash(RuleSet(include=(flipped,))) == rules_hash(RuleSet(include=(b,)))
    assert rules_hash(RuleSet(include=(a,))) != rules_hash(RuleSet(include=(b,)))


def test_defaults_dropped_from_canonical() -> None:
    canon = canonical_rules(RuleSet(include=(CorpusRule(outcome="all"),)))
    assert canon == {
        "include": [{"kind": "corpus", "outcome": "all"}],
        "exclude": [],
        "within": None,
    }
    full = CorpusRule(outcome="all", stage=ScreeningStage.FULL_TEXT)
    assert canonical_rules(RuleSet(include=(full,)))["include"] == [  # type: ignore[call-overload]
        {"kind": "corpus", "outcome": "all", "stage": "full-text"}
    ]


def test_compress_deterministic() -> None:
    text = members_text([(MemberType.WORK, "rf:b"), (MemberType.WORK, "rf:a")])
    assert text == b"work\trf:a\nwork\trf:b\n"
    assert compress(text) == compress(text)
    assert gzip.decompress(compress(text)) == text
    again = members_text([(MemberType.WORK, "rf:a"), (MemberType.WORK, "rf:b")])
    assert members_hash(text) == members_hash(again)


def test_version_ignores_definition() -> None:
    params = set(inspect.signature(region_version).parameters)
    assert params == {"region_id", "kind", "facet", "rules_hash", "decisions", "members_hash"}
    assert not {"name", "definition", "author", "text"} & params
    v = region_version("reg_x", "region", None, "0" * 64, ["ev_b", "ev_a"], "1" * 64)
    assert v == region_version("reg_x", "region", None, "0" * 64, ["ev_a", "ev_b"], "1" * 64)
    assert v.startswith("R@") and len(v) == 10
    assert v != region_version("reg_x", "region", None, "0" * 64, [], "1" * 64)
    assert hasattr(version_module, "canonical_rule")
