"""A small world with miner rows for the lead engine tests: three technique miners rows (two
stages) and an `m-claims` miner, all pass A, all quoting the fixture document.

Works are the sorted `world` list (W0..W2 carry rows): W2 is in layer `applied`, the rest in
`core`.
Technique rows (work: approach evidence): W0 ide-01 own-ablation, exp-01 own-comparison;
W1 ide-01 reported-failure, ide-02 own-ablation, ide-03 own-ablation; W2 ide-02 independent-test,
exp-02 own-ablation. Claims rows: W0 limitation + finding, W1 limitation + no-limitation-stated,
W2 no-limitation-stated only.
"""

from __future__ import annotations

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
from factory.services.context import Project
from factory.services.mining import mine_next, mine_record, register_miner
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.reference_layers import record_scheme
from factory.services.taxonomies import register_taxonomy
from factory.services.work_layers import move_layer
from tests.claims_helpers import QUOTES, claim_row, claims_spec
from tests.miner_helpers import (
    SESSION_M1,
    declare_exploratory,
    list_miner,
    mine_pass,
    miner_actor,
    use,
)

QUOTE = "Lorem ipsum dolor sit amet."
STATUS = MinerField("status", "use", EnumKind(("core", "secondary", "reused-cited", "standard")))
EVIDENCE = MinerField(
    "evidence",
    "use",
    EnumKind(
        ("independent-test", "own-ablation", "own-comparison", "asserted-only", "reported-failure")
    ),
)
STAGES = (("ideation", ("ide-01", "ide-02", "ide-03")), ("experiment", ("exp-01", "exp-02")))
TECH_ROWS: dict[int, tuple[tuple[str, str], ...]] = {
    0: (("ide-01", "own-ablation"), ("exp-01", "own-comparison")),
    1: (
        ("ide-01", "reported-failure"),
        ("ide-02", "own-ablation"),
        ("ide-03", "own-ablation"),
    ),
    2: (("ide-02", "independent-test"), ("exp-02", "own-ablation")),
}
CLAIM_ROWS: dict[int, tuple[tuple[str, str], ...]] = {
    0: (("limitation", QUOTES[0]), ("finding", QUOTES[1])),
    1: (("limitation", QUOTES[1]), ("no-limitation-stated", QUOTES[2])),
    2: (("no-limitation-stated", QUOTES[2]),),
}


def _field(value: str) -> FieldInput:
    return FieldInput(value=value, anchor="s3.p1", quote=QUOTE)


def tech_row(cat: str, evidence: str) -> ExtractedRowInput:
    return ExtractedRowInput(
        fields={
            "category": _field(f"technique/{cat}"),
            "quote": _field(QUOTE),
            "status": _field("core"),
            "evidence": _field(evidence),
        }
    )


def _taxonomy(stage: str, ids: tuple[str, ...]) -> TaxonomySpec:
    cats = tuple(Category(i, i.upper(), f"Definition of {i}.") for i in ids)
    return TaxonomySpec(
        name=f"t-tech-{stage}",
        version=1,
        dimensions=(Dimension("technique", "Technique", "Which technique?", "multi", cats),),
    )


def register_technique_miners(
    project: Project, agent: Actor, human: Actor, works: list[str]
) -> list[str]:
    """Layers, the two stage taxonomies and their derived miners, listed and declared
    exploratory; returns the sorted works."""
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
        move_layer(project, human, work, "applied" if i == 2 else "core", "test")
    uses = []
    for stage, ids in STAGES:
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


def mine_technique(project: Project, ordered: list[str]) -> None:
    actor = miner_actor(SESSION_M1, "claude-opus-5-5")
    for stage, ids in STAGES:

        def rows(work: str, ids: tuple[str, ...] = ids) -> list[ExtractedRowInput]:
            out = [tech_row(c, e) for c, e in TECH_ROWS.get(ordered.index(work), ()) if c in ids]
            return out or [
                ExtractedRowInput(
                    fields={"category": _field("technique/not-stated"), "quote": _field(QUOTE)}
                )
            ]

        mine_pass(project, actor, PassLabel.A, rows, name=f"m-tech-{stage}")


def mine_claims(project: Project, agent: Actor, ordered: list[str]) -> None:
    list_miner(project, agent, claims_spec())
    actor = miner_actor(SESSION_M1, "claude-opus-5-5")
    mine_pass(
        project,
        actor,
        PassLabel.A,
        lambda w: [claim_row(t, q) for t, q in CLAIM_ROWS.get(ordered.index(w), ())],
        name="m-claims",
    )


def engine_world(
    project: Project, agent: Actor, human: Actor, works: list[str], *, claims: bool = True
) -> list[str]:
    """Technique and claims rows mined; returns the sorted works."""
    ordered = register_technique_miners(project, agent, human, works)
    mine_technique(project, ordered)
    if claims:
        mine_claims(project, agent, ordered)
    return ordered


def mine_claims_superseding(project: Project, agent: Actor, ordered: list[str]) -> tuple[str, str]:
    """`mine_claims` where the first work's first row (a limitation) is superseded by a corrected
    row in the same unit; returns the superseded and the superseding extraction ids."""
    list_miner(project, agent, claims_spec())
    actor = miner_actor(SESSION_M1, "claude-opus-5-5")
    declare_exploratory(project, "m-claims", 1)
    old = new = ""
    for _ in range(100):
        batch = mine_next(project, actor, "m-claims", 1, PassLabel.A).batch
        if batch is None:
            return old, new
        index = ordered.index(batch.records[0]["work_id"])
        rows = [claim_row(t, q) for t, q in CLAIM_ROWS.get(index, ())]
        if index != 0:
            mine_record(project, actor, batch.task_id, rows, finish=True)
            continue
        old = mine_record(project, actor, batch.task_id, rows, finish=False).rows.written[0]
        fixed = [claim_row("limitation", QUOTES[2])]
        done = mine_record(project, actor, batch.task_id, fixed, finish=True, supersedes={0: old})
        new = done.rows.written[0]
    raise AssertionError("too many tasks")
