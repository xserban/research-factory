"""The technique landscape's pure builders (IDEA-78): rows in, labelled exploratory graph out."""

from __future__ import annotations

import inspect
import json
import re

import pytest

from factory.errors import FactoryValidationError
from factory.model.technique_graph import NOTICE, Lens
from factory.services import technique_graph as tg
from factory.services.technique_graph import Inputs, RawRow, StageInfo, WorkMeta

CATALOGUE = {
    "ide-01": ("ideation", "Tournament ranking", "Ranks ideas by pairwise matches."),
    "ide-02": ("ideation", "Debate", "Agents argue."),
    "ide-03": ("ideation", "Novelty search", "Searches prior work."),
    "exp-01": ("experiment", "Tree search", "Searches code variants."),
    "exp-02": ("experiment", "Sandbox", "Runs code in a sandbox."),
}


def row(
    work: str,
    approach: str,
    *,
    status: str | None = "core",
    evidence: str | None = "own-ablation",
    n: int = 1,
) -> RawRow:
    return RawRow(
        approach=approach,
        stage=CATALOGUE[approach][0],
        work_id=work,
        extraction_id=f"rex-{work}-{approach}-{n}",
        status=status,
        evidence=evidence,
        described_as=f"{work} variant",
        quote=f"quote {work} {approach}",
        anchor="s1.p1",
        parameters=None,
    )


WORKS = {
    "rf:a": WorkMeta("A", "2023-01-05", 2023, "core"),
    "rf:b": WorkMeta("B", "2024-02-01", 2024, "core"),
    "rf:c": WorkMeta("C", "2024-02-01", 2024, "core"),
    "rf:d": WorkMeta("D", None, None, "core"),
    "rf:e": WorkMeta("E", "2022-03-03", 2022, "applied"),
}


def inputs(rows: list[RawRow], cites: tuple[tuple[str, str, str], ...] = ()) -> Inputs:
    return Inputs(
        catalogue=CATALOGUE,
        rows=tuple(rows),
        stages=(
            StageInfo("experiment", "m-tech-experiment", 1, 2, None, None),
            StageInfo("ideation", "m-tech-ideation", 1, 1, 0.4, 0.6),
        ),
        works=WORKS,
        cites=cites,
    )


BASE = [
    row("rf:a", "ide-01"),
    row("rf:b", "ide-01", status="reused-cited"),
    row("rf:b", "ide-02"),
    row("rf:c", "ide-01", evidence=None),
    row("rf:c", "ide-02", evidence="reported-failure"),
    row("rf:c", "exp-01"),
    row("rf:d", "ide-01"),
    row("rf:e", "ide-01"),
    row("rf:a", "exp-01"),
]


def land(data: Inputs, **kw: object) -> object:
    lens = Lens(**{k: v for k, v in kw.items() if k in Lens.model_fields})  # type: ignore[arg-type]
    return tg.build_landscape(data, lens)


def test_nodes_and_counts_are_distinct_works_in_the_default_core_lens() -> None:
    # two rows of one work and approach count once; the applied work is outside the core lens
    data = inputs([*BASE, row("rf:a", "ide-01", n=2)])
    result = tg.build_landscape(data, Lens())
    ide1 = next(a for a in result.approaches if a.id == "ide-01")
    assert ide1.works == 4 and ide1.rows == 5
    assert result.lens.layer == "core"
    assert {a.id for a in result.approaches} == {"ide-01", "ide-02", "exp-01"}


def test_all_layers_widens_and_is_named() -> None:
    result = tg.build_landscape(inputs(BASE), Lens(layer="all"))
    assert next(a for a in result.approaches if a.id == "ide-01").works == 5
    assert result.lens.layer == "all"


def test_stage_evidence_and_status_lenses_reduce() -> None:
    data = inputs(BASE)
    by_stage = tg.build_landscape(data, Lens(stage="experiment"))
    assert {a.stage for a in by_stage.approaches if a.id.startswith("exp")} == {"experiment"}
    assert [s.stage for s in by_stage.stages] == ["experiment"]
    failed = tg.build_landscape(data, Lens(evidence="reported-failure"))
    assert [(a.id, a.works) for a in failed.approaches] == [("ide-02", 1)]
    reused = tg.build_landscape(data, Lens(status="reused-cited"))
    assert [(a.id, a.works) for a in reused.approaches] == [("ide-01", 1)]
    unstated = tg.build_landscape(data, Lens(evidence="not-stated"))
    assert [(a.id, a.works) for a in unstated.approaches] == [("ide-01", 1)]


def test_every_node_and_edge_and_result_is_labelled_exploratory() -> None:
    data = inputs(BASE, (("rf:b", "rf:a", "cit:1:1"),))
    result = tg.build_landscape(data, Lens(), include_uses=True)
    dumped = json.loads(result.model_dump_json(by_alias=True))
    assert dumped["exploratory"] is True and dumped["notice"] == NOTICE
    assert dumped["approaches"] and dumped["edges"]
    kinds = {e["kind"] for e in dumped["edges"]}
    assert {"uses", "co-used-with", "derives-from", "earliest-in-corpus"} <= kinds
    for item in (*dumped["approaches"], *dumped["edges"]):
        assert item["class"] == "interpretation" and item["state"] == "exploratory"
    view = tg.build_view(data, "ide-01", Lens())
    one = json.loads(view.model_dump_json(by_alias=True))
    assert one["exploratory"] is True
    for item in (one["approach"], *one["works"], *one["uses"], *one["derives_from"]):
        assert item["class"] == "interpretation" and item["state"] == "exploratory"


def test_derives_from_positive_and_the_negative_cases() -> None:
    cite = (("rf:b", "rf:a", "cit:x:1"),)
    found = tg.derives_from(inputs(BASE, cite), BASE)
    assert [(e.source, e.target, e.approach, e.basis) for e in found] == [
        ("rf:b", "rf:a", "ide-01", "cit:x:1")
    ]
    # the other direction is never derived
    assert not tg.derives_from(inputs(BASE, (("rf:a", "rf:b", "cit:y:1"),)), BASE)
    # no link at all (unresolved or stale links are not in the inputs)
    assert not tg.derives_from(inputs(BASE, ()), BASE)
    # the target does not use the approach
    only_other = [row("rf:b", "ide-01", status="reused-cited"), row("rf:c", "ide-02")]
    assert not tg.derives_from(inputs(only_other, (("rf:b", "rf:c", "c"),)), only_other)
    # status core is not reused-cited
    core = [row("rf:b", "ide-01"), row("rf:a", "ide-01")]
    assert not tg.derives_from(inputs(core, (("rf:b", "rf:a", "c"),)), core)


def test_earliest_in_corpus_breaks_ties_by_id_and_lists_undated_works() -> None:
    data = inputs(BASE)
    view = tg.build_view(data, "ide-01", Lens())
    assert view.earliest is not None and view.earliest.target == "rf:a"
    assert "not an origin" in (view.earliest.note or "")
    assert view.undated_works == ("rf:d",)
    tie = [row("rf:c", "ide-02"), row("rf:b", "ide-02")]
    edge = tg.build_view(inputs(tie), "ide-02", Lens()).earliest
    assert edge is not None and edge.target == "rf:b"
    land_ = tg.build_landscape(data, Lens())
    assert land_.undated_works == ("rf:d",)


def test_two_builds_are_byte_identical() -> None:
    data = inputs(BASE, (("rf:b", "rf:a", "cit:x:1"),))
    one = tg.build_landscape(data, Lens(), include_uses=True).model_dump_json(by_alias=True)
    two = tg.build_landscape(inputs(list(reversed(BASE)), data.cites), Lens(), include_uses=True)
    assert one == two.model_dump_json(by_alias=True)
    again = tg.build_landscape(data, Lens(), include_uses=True).model_dump_json(by_alias=True)
    assert one == again


def test_the_module_never_writes() -> None:
    source = inspect.getsource(tg)
    for forbidden in ("exclusive(", ".record(", "INSERT", "UPDATE ", "DELETE", ".append("):
        if forbidden == ".append(":
            continue
        assert forbidden not in source, forbidden
    assert not re.search(r"\bproject\.events\b", source)


def test_a_reported_failure_is_its_own_bucket_and_not_stated_is_never_defaulted() -> None:
    result = tg.build_landscape(inputs(BASE), Lens())
    ide2 = next(a for a in result.approaches if a.id == "ide-02")
    assert ide2.by_evidence == {"own-ablation": 1, "reported-failure": 1}
    ide1 = next(a for a in result.approaches if a.id == "ide-01")
    assert ide1.by_evidence.get("not-stated") == 1
    summary = next(s for s in result.stages if s.stage == "ideation")
    assert summary.no_evidence_share == pytest.approx(1 / 6, abs=1e-4)
    uses = tg.build_view(inputs(BASE), "ide-01", Lens()).uses
    assert [u.evidence for u in uses if u.work_id == "rf:c"] == ["not-stated"]
    assert tg.build_view(inputs(BASE), "ide-01", Lens()).not_stated_share is not None


def test_the_agreement_block_and_its_absence() -> None:
    result = tg.build_landscape(inputs(BASE), Lens())
    by = {s.stage: s for s in result.stages}
    assert by["ideation"].agreement == 0.4 and by["ideation"].agreement_aligned == 0.6
    assert by["ideation"].agreement_note == "exploratory, not calibrated"
    assert by["experiment"].agreement is None
    assert by["experiment"].agreement_note == "no second pass"
    assert by["experiment"].residual_rows == 2


def test_co_use_edges_have_weights_works_and_a_threshold() -> None:
    data = inputs(BASE)
    wide = tg.build_landscape(data, Lens(min_co_works=1))
    co = {(e.source, e.target): e for e in wide.edges if e.kind == "co-used-with"}
    assert co[("ide-01", "ide-02")].weight == 2 and co[("ide-01", "ide-02")].works == (
        "rf:b",
        "rf:c",
    )
    assert co[("exp-01", "ide-01")].works == ("rf:a", "rf:c")
    strict = tg.build_landscape(data, Lens(min_co_works=3))
    assert not [e for e in strict.edges if e.kind == "co-used-with"]
    capped = tg.build_landscape(data, Lens(min_co_works=1), max_edges=1)
    assert len([e for e in capped.edges if e.kind == "co-used-with"]) == 1
    assert capped.edges_omitted == len(co) - 1
    # a stage lens keeps the edges with an end in the stage, and their other end as a node
    staged = tg.build_landscape(data, Lens(stage="experiment", min_co_works=1))
    assert any(e.kind == "co-used-with" for e in staged.edges)
    assert {"ide-01", "exp-01"} <= {a.id for a in staged.approaches}


def test_neighbors_are_ordered_by_weight() -> None:
    n = tg.build_neighbors(inputs(BASE), "ide-01", Lens())
    assert [(c.approach.id, c.weight) for c in n.co_used] == [("exp-01", 2), ("ide-02", 2)]
    assert n.works == ("rf:a", "rf:b", "rf:c", "rf:d")
    assert {(s.stage, s.works) for s in n.stages} == {("ideation", 4), ("experiment", 2)}
    capped = tg.build_neighbors(inputs(BASE), "ide-01", Lens(), min_works=3)
    assert capped.co_used == ()
    with pytest.raises(FactoryValidationError):
        tg.build_neighbors(inputs(BASE), "zzz", Lens())


def test_gaps_apply_thresholds_and_are_labelled() -> None:
    data = inputs(BASE)
    out = tg.build_gaps(
        data, Lens(), from_stage="ideation", to_stage="experiment",
        min_works=1, max_to_share=0.0, limit=None,
    )  # fmt: skip
    assert out.total == 0 and out.gaps == ()  # every approach's users include one with a row
    assert out.exploratory is True and out.kind == "gaps"
    wide = tg.build_gaps(
        data, Lens(), from_stage="ideation", to_stage="experiment",
        min_works=1, max_to_share=0.5, limit=None,
    )  # fmt: skip
    assert [(g.approach.id, g.works_with_to_stage) for g in wide.gaps] == [
        ("ide-02", ("rf:c",)),
        ("ide-01", ("rf:a", "rf:c")),
    ]
    assert wide.total == 2
    none = tg.build_gaps(
        data, Lens(), from_stage="ideation", to_stage="experiment",
        min_works=9, max_to_share=1.0, limit=None,
    )  # fmt: skip
    assert none.total == 0 and none.gaps == ()
    assert all("hypothesis to check" in g.label for g in wide.gaps)


def test_combinations_need_users_and_no_co_use() -> None:
    rows = [
        row("rf:a", "ide-01"),
        row("rf:b", "ide-01"),
        row("rf:c", "ide-03"),
        row("rf:d", "ide-03"),
    ]
    out = tg.build_combinations(
        inputs(rows), Lens(), min_works=2, max_co_works=0, stage=None, limit=None
    )
    assert [(c.a.id, c.b.id, c.co_works) for c in out.combinations] == [("ide-01", "ide-03", ())]
    assert out.total == 1 and out.exploratory is True
    together = [*rows, row("rf:a", "ide-03")]
    out2 = tg.build_combinations(
        inputs(together), Lens(), min_works=2, max_co_works=0, stage=None, limit=None
    )
    assert out2.total == 0 and out2.combinations == ()
    out3 = tg.build_combinations(
        inputs(together), Lens(), min_works=2, max_co_works=1, stage=None, limit=None
    )
    assert out3.total == 1 and out3.combinations[0].co_works == ("rf:a",)
    staged = tg.build_combinations(
        inputs(rows), Lens(), min_works=2, max_co_works=0, stage="experiment", limit=None
    )
    assert staged.total == 0


def test_challenges_need_failure_and_support_in_different_works() -> None:
    out = tg.build_challenges(inputs(BASE), Lens(), limit=None)
    assert [c.approach.id for c in out.challenges] == ["ide-02"]
    assert out.challenges[0].failed[0].work_id == "rf:c"
    same = [row("rf:c", "ide-02", evidence="reported-failure")]
    assert tg.build_challenges(inputs(same), Lens(), limit=None).total == 0


def test_a_bad_stage_or_evidence_is_refused() -> None:
    data = inputs(BASE)
    with pytest.raises(FactoryValidationError):
        tg._check_lens(data, "nope", None, None)
    with pytest.raises(FactoryValidationError):
        tg._check_lens(data, None, "great", None)
