"""The technique landscape over a real small project: eight-miner shape reduced to two stages,
rows read through the index, held-out and report rules."""

# ruff: noqa: F811
from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.mining.derive import derive_miner
from factory.mining.spec import (
    EnumKind,
    MinerField,
    MinerRegime,
    Population,
    Selector,
    spec_to_json,
)
from factory.mining.taxonomy import Category, Dimension, TaxonomySpec, taxonomy_to_json
from factory.model.extraction import ExtractedRowInput, FieldInput
from factory.model.protocol import TaxonomyUse
from factory.model.references import LayerDef, LayerSchemeRecorded
from factory.model.screening import PassLabel
from factory.services import technique_graph as tg
from factory.services.context import Project
from factory.services.evidence_report import evidence_report
from factory.services.mining import register_miner
from factory.services.prisma import prisma_flow
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.reference_layers import record_scheme
from factory.services.taxonomies import register_taxonomy
from factory.services.work_layers import move_layer
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.miner_helpers import SESSION_M1, declare_exploratory, mine_pass, miner_actor, use

QUOTE = "Lorem ipsum dolor sit amet."
STATUS = MinerField("status", "use", EnumKind(("core", "secondary", "reused-cited", "standard")))
EVIDENCE = MinerField(
    "evidence",
    "use",
    EnumKind(
        ("independent-test", "own-ablation", "own-comparison", "asserted-only", "reported-failure")
    ),
)


def _taxonomy(stage: str, ids: tuple[str, ...]) -> TaxonomySpec:
    cats = tuple(Category(i, i.upper(), f"Definition of {i}.") for i in ids)
    return TaxonomySpec(
        name=f"t-tech-{stage}",
        version=1,
        dimensions=(Dimension("technique", "Technique", "Which technique?", "multi", cats),),
    )


def _field(value: str) -> FieldInput:
    return FieldInput(value=value, anchor="s3.p1", quote=QUOTE)


def _row(
    cat: str, status: str | None = "core", evidence: str | None = "own-ablation"
) -> ExtractedRowInput:
    fields = {"category": _field(f"technique/{cat}"), "quote": _field(QUOTE)}
    if status:
        fields["status"] = _field(status)
    if evidence:
        fields["evidence"] = _field(evidence)
    return ExtractedRowInput(fields=fields)


def _setup(project: Project, agent: Actor, human: Actor, works: list[str]) -> list[str]:
    record_scheme(
        project,
        human,
        LayerSchemeRecorded(
            version=1,
            layers=(
                LayerDef(id="core", ring=0, snowball=True, name="core", criteria="c"),
                LayerDef(id="applied", ring=1, snowball=False, name="applied", criteria="a"),
            ),
        ),
    )
    ordered = sorted(works)
    for i, work in enumerate(ordered):
        move_layer(project, human, work, "core" if i != len(ordered) - 1 else "applied", "test")
    uses = []
    for stage, ids in (("ideation", ("ide-01", "ide-02")), ("experiment", ("exp-01",))):
        taxonomy = _taxonomy(stage, ids)
        register_taxonomy(project, human, taxonomy_to_json(taxonomy))
        miner = derive_miner(
            taxonomy,
            ("technique",),
            name=f"m-tech-{stage}",
            version=1,
            selector=Selector(Population.INCLUDED_FT),
            regime=MinerRegime(2, 3, 0.8, 0.9),
            attributes=(STATUS, EVIDENCE),
        )
        register_miner(project, agent, spec_to_json(miner))
        uses.append((taxonomy.name, use(miner)))
    current = current_protocol(project)
    assert current is not None
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(
            update={
                "miners": (*(current.spec.miners or ()), *(u for _, u in uses)),
                "taxonomies": tuple(TaxonomyUse(name=n, version=1) for n, _ in uses),
            }
        ),
        reason="list the technique miners",
        semantic=True,
        effects={},
    )
    for _, u in uses:
        declare_exploratory(project, u.name, u.version)
    return ordered


def _mine(project: Project, ordered: list[str]) -> None:
    actor = miner_actor(SESSION_M1, "claude-opus-5-5")
    plan = {
        ordered[0]: ("ide-01", "exp-01"),
        ordered[1]: ("ide-01", "ide-02"),
        ordered[2]: ("ide-02", "exp-01"),
    }

    def rows(stage: str):  # type: ignore[no-untyped-def]
        def for_work(work: str) -> list[ExtractedRowInput]:
            out = [_row(c) for c in plan.get(work, ()) if c.startswith(stage[:3])]
            return out or [
                ExtractedRowInput(
                    fields={"category": _field("technique/not-stated"), "quote": _field(QUOTE)}
                )
            ]

        return for_work

    for stage in ("ideation", "experiment"):
        mine_pass(project, actor, PassLabel.A, rows(stage), name=f"m-tech-{stage}")


def test_the_landscape_reads_the_miners_rows_through_the_index(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    ordered = _setup(project, agent, human, world)
    assert tg.technique_landscape(project).approaches == ()
    _mine(project, ordered)
    result = tg.technique_landscape(project, min_co_works=1)
    counts = {a.id: a.works for a in result.approaches}
    assert counts == {"ide-01": 2, "ide-02": 2, "exp-01": 2}
    assert result.lens.layer == "core" and result.exploratory
    assert {s.stage for s in result.stages} == {"ideation", "experiment"}
    assert all(s.residual_rows >= 0 for s in result.stages)
    view = tg.technique_view(project, "ide-01")
    assert [u.work_id for u in view.uses] == ordered[:2]
    assert all(u.quote == QUOTE and u.anchor == "s3.p1" for u in view.uses)
    again = tg.technique_landscape(project, min_co_works=1)
    assert result.model_dump_json(by_alias=True) == again.model_dump_json(by_alias=True)
    with pytest.raises(FactoryValidationError):
        tg.technique_view(project, "nope")
    neighbours = tg.technique_neighbors(project, "ide-01")
    assert [(c.approach.id, c.weight) for c in neighbours.co_used] == [("exp-01", 1), ("ide-02", 1)]


def test_held_out_works_are_corpus_works_and_nothing_is_masked(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    ordered = _setup(project, agent, human, world)
    _mine(project, ordered)
    text = tg.technique_view(project, "ide-02").model_dump_json(by_alias=True)
    assert ordered[1] in text and "[withheld]" not in text


def _use_every_technique_read(project: Project) -> None:
    from factory.services.check import check

    tg.technique_landscape(project, min_co_works=1)
    tg.technique_view(project, "ide-01")
    tg.technique_neighbors(project, "ide-01")
    tg.technique_gaps(project, from_stage="ideation", to_stage="experiment", min_works=1)
    tg.technique_combinations(project, min_works=1)
    tg.technique_challenges(project)
    check(project)  # `factory check`


def test_report_output_is_identical_with_and_without_technique_rows(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    ordered = _setup(project, agent, human, world)
    before = (
        evidence_report(project).model_dump_json(),
        prisma_flow(project).model_dump_json(),
    )
    _mine(project, ordered)
    _use_every_technique_read(project)
    after = (
        evidence_report(project).model_dump_json(),
        prisma_flow(project).model_dump_json(),
    )
    assert before == after


def test_no_index_lock_is_held_across_the_scan(
    project: Project, agent: Actor, human: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    ordered = _setup(project, agent, human, world)
    _mine(project, ordered)
    tg._CACHE.clear()
    tg._AGREEMENT.clear()
    seen: list[bool] = []
    original = tg._read_cites

    def probe(proj: Project, sources: object) -> object:
        done = threading.Event()

        def write_side() -> None:
            with proj.index.exclusive():  # what any writer takes: waits while a snapshot is held
                done.set()

        thread = threading.Thread(target=write_side)
        thread.start()
        seen.append(done.wait(timeout=10))
        thread.join(timeout=10)
        return original(proj, sources)  # type: ignore[arg-type]

    monkeypatch.setattr(tg, "_read_cites", probe)
    tg.technique_landscape(project, min_co_works=1)
    assert seen == [True]


def test_concurrent_misses_share_one_scan_and_the_memo_survives_threads(
    project: Project, agent: Actor, human: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading
    import time

    ordered = _setup(project, agent, human, world)
    _mine(project, ordered)
    tg._CACHE.clear()
    scans: list[int] = []
    original = tg._read

    def slow(proj: Project) -> tg.Inputs:
        scans.append(1)
        time.sleep(0.3)
        return original(proj)

    monkeypatch.setattr(tg, "_read", slow)
    errors: list[BaseException] = []

    def call() -> None:
        try:
            tg.read_inputs(project)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors and len(scans) == 1
    # eviction under contention: many keys at once never raises
    inputs = tg.read_inputs(project)

    def store(i: int) -> None:
        try:
            for j in range(50):
                with tg._GUARD:
                    tg._store(tg._CACHE, f"k{i}-{j}", None, inputs)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=store, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors and len(tg._CACHE) <= tg._CACHE_MAX


def test_check_reports_a_technique_taxonomy_no_miner_projects(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    from factory.services.check import check

    register_taxonomy(project, human, taxonomy_to_json(_taxonomy("ideation", ("ide-01",))))
    codes = [f.code for f in check(project).findings]
    assert "technique-no-miner" in codes
    miner = derive_miner(
        _taxonomy("ideation", ("ide-01",)),
        ("technique",),
        name="m-tech-ideation",
        version=1,
        selector=Selector(Population.INCLUDED_FT),
        regime=MinerRegime(2, 3, 0.8, 0.9),
    )
    register_miner(project, agent, spec_to_json(miner))
    assert "technique-no-miner" not in [f.code for f in check(project).findings]
