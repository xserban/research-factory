"""Definitions, snapshots and drift (slice 3d, plan Regions-A, task 3)."""

# ruff: noqa: F811

from __future__ import annotations

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.protocol import ScreeningStage
from factory.model.regions import RegionKind
from factory.regions.rules import CorpusRule, ImportRule, MemberType, RuleSet
from factory.services.regions import (
    decide_member,
    define_region,
    region_members,
    region_state,
    snapshot_region,
)
from tests.region_helpers import RWorld, region_project, screened  # noqa: F401

W = MemberType.WORK
FT_INCLUDED = CorpusRule(outcome="included", stage=ScreeningStage.FULL_TEXT)
TA_ALL = CorpusRule(outcome="all")


def define(w: RWorld, human: Actor, rules: RuleSet | None = None, **kw: object) -> str:
    return define_region(
        w.project,
        human,
        kind=RegionKind.REGION,
        name="attention works",
        definition="Works on attention.",
        rules=rules or RuleSet(include=(FT_INCLUDED,)),
        **kw,  # type: ignore[arg-type]
    )


def event_count(w: RWorld) -> int:
    with w.project.index.connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM events")).scalar_one())


def test_version_hash_sensitivity(region_project: RWorld, human: Actor) -> None:
    w = region_project
    rules = RuleSet(include=(FT_INCLUDED, TA_ALL))
    region = define(w, human, rules)
    first = snapshot_region(w.project, human, region)
    # reordering the rules leaves R@ unchanged
    define_region(
        w.project,
        human,
        kind=RegionKind.REGION,
        name="attention works",
        definition="Works on attention.",
        rules=RuleSet(include=(TA_ALL, FT_INCLUDED)),
        region_id=region,
    )
    assert snapshot_region(w.project, human, region) == first
    # editing the definition text and the name leaves R@ unchanged
    define_region(
        w.project,
        human,
        kind=RegionKind.REGION,
        name="renamed",
        definition="A different sentence about the same selection.",
        rules=rules,
        region_id=region,
    )
    assert snapshot_region(w.project, human, region) == first
    # adding one included work changes it
    decide_member(w.project, human, region, W, "rf:added-00000001", "add")
    assert snapshot_region(w.project, human, region) != first


def test_snapshot_idempotent(region_project: RWorld, human: Actor) -> None:
    w = region_project
    region = define(w, human)
    version = snapshot_region(w.project, human, region)
    before = event_count(w)
    assert snapshot_region(w.project, human, region) == version
    assert event_count(w) == before


def test_drift_after_new_inclusion(region_project: RWorld, human: Actor) -> None:
    w = region_project
    region = define(w, human)
    assert region_state(w.project, region).latest_version is None
    version = snapshot_region(w.project, human, region)
    state = region_state(w.project, region)
    assert (state.latest_version, state.drift_added, state.drift_removed) == (version, 0, 0)
    assert state.live_counts == {"work": len(w.included)}
    decide_member(w.project, human, region, W, "rf:added-00000001", "add")
    decide_member(w.project, human, region, W, w.included[0], "remove")
    drift = region_state(w.project, region)
    assert (drift.drift_added, drift.drift_removed) == (1, 1)
    assert drift.latest_version == version  # drift is reported, never applied


def test_projection_keeps_latest_only(region_project: RWorld, human: Actor) -> None:
    w = region_project
    region = define(w, human)
    snapshot_region(w.project, human, region)
    decide_member(w.project, human, region, W, "rf:added-00000001", "add")
    second = snapshot_region(w.project, human, region)
    with w.project.index.connect() as conn:
        versions = {
            str(r[0])
            for r in conn.execute(text("SELECT DISTINCT version FROM region_members")).all()
        }
        snapshots = int(conn.execute(text("SELECT COUNT(*) FROM region_snapshots")).scalar_one())
        basis = conn.execute(
            text("SELECT basis FROM region_members WHERE member = 'rf:added-00000001'")
        ).scalar_one()
    assert versions == {second} and snapshots == 2
    assert '"decision":"ev_' in str(basis)


def test_old_version_members_from_blob(region_project: RWorld, human: Actor) -> None:
    w = region_project
    region = define(w, human)
    first = snapshot_region(w.project, human, region)
    decide_member(w.project, human, region, W, "rf:added-00000001", "add")
    second = snapshot_region(w.project, human, region)
    assert [m for _, m in region_members(w.project, first, limit=500)] == sorted(w.included)
    page = region_members(w.project, second, offset=1, limit=2)
    assert len(page) == 2
    assert len(region_members(w.project, second)) == len(w.included) + 1
    assert region_members(w.project, "R@" + "0" * 8) == []


def test_rebuild_identical(region_project: RWorld, human: Actor) -> None:
    w = region_project
    region = define(w, human)
    snapshot_region(w.project, human, region)
    decide_member(w.project, human, region, W, "rf:added-00000001", "add")
    snapshot_region(w.project, human, region)
    # the synthetic graph rows are not events: compare only the region tables
    tables = ("regions", "region_definitions", "region_snapshots", "region_members")
    sql = "SELECT * FROM {} ORDER BY 1, 2, 3"

    def dump() -> list[list[tuple[object, ...]]]:
        with w.project.index.connect() as conn:
            return [[tuple(r) for r in conn.execute(text(sql.format(t))).all()] for t in tables]

    before = dump()
    w.project.index.rebuild()
    assert dump() == before
    assert before[3]


def test_agent_definition_has_provenance(region_project: RWorld, agent: Actor) -> None:
    w = region_project
    region = define(w, agent)
    version = snapshot_region(w.project, agent, region)
    with w.project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT type, model, skill, input_blob FROM events "
                "WHERE type IN ('region.defined', 'region.snapshot_taken') ORDER BY id"
            )
        ).all()
    assert [r[0] for r in rows] == ["region.defined", "region.snapshot_taken"]
    for _, model, skill, blob in rows:
        assert model and skill and blob
    assert w.project.blobs.get_json(str(rows[1][3]))["region_id"] == region  # type: ignore[call-overload]
    assert version.startswith("R@")


def test_definition_too_long_refused(region_project: RWorld, human: Actor) -> None:
    w = region_project
    before = event_count(w)
    with pytest.raises(FactoryValidationError) as caught:
        define_region(
            w.project,
            human,
            kind=RegionKind.REGION,
            name="x",
            definition="d" * 601,
            rules=RuleSet(include=(FT_INCLUDED,)),
        )
    assert [i.field for i in caught.value.issues] == ["definition"]
    assert event_count(w) == before


def test_agent_may_not_name_the_held_out_part(region_project: RWorld, agent: Actor) -> None:
    rules = RuleSet(include=(ImportRule(import_id="imp_x", part="all"),))
    with pytest.raises(FactoryValidationError) as caught:
        define(region_project, agent, rules)
    assert caught.value.issues[0].field == "rules.include[0].part"


def test_redefinition_keeps_kind_and_supersedes(region_project: RWorld, human: Actor) -> None:
    w = region_project
    region = define(w, human)
    with pytest.raises(FactoryValidationError) as caught:
        define_region(
            w.project,
            human,
            kind=RegionKind.FOCUS,
            name="x",
            definition="y",
            rules=RuleSet(include=(FT_INCLUDED,)),
            region_id=region,
        )
    assert "kind" in [i.field for i in caught.value.issues]
    with pytest.raises(FactoryValidationError):
        snapshot_region(w.project, human, "reg_01JZ9Q3K5M7N8P0R2S4T6V8WZZ")
    with pytest.raises(FactoryValidationError):
        region_state(w.project, "reg_01JZ9Q3K5M7N8P0R2S4T6V8WZZ")


def test_agent_cannot_decide_a_member(region_project: RWorld, human: Actor, agent: Actor) -> None:
    w = region_project
    region = define(w, human)
    with pytest.raises(FactoryValidationError) as caught:
        decide_member(w.project, agent, region, W, "rf:x", "add")
    assert caught.value.issues[0].field == "actor"
