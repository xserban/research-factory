"""Definitions, snapshots and drift (slice 3d, plan Regions-A, task 3)."""

# ruff: noqa: F811

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.protocol import ScreeningStage
from factory.model.regions import RegionKind
from factory.regions.rules import (
    CitesRule,
    CorpusRule,
    ImportRule,
    MemberType,
    RegionRule,
    RuleSet,
    RunRule,
)
from factory.services.regions import (
    decide_member,
    define_region,
    region_members,
    region_state,
    snapshot_region,
)
from tests.region_helpers import (  # noqa: F401
    RWorld,
    definition_event_of,
    region_project,
    screened,
    snapshot_event,
)

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
    decide_member(w.project, human, region, W, w.extra, "add")
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
    decide_member(w.project, human, region, W, w.extra, "add")
    decide_member(w.project, human, region, W, w.included[0], "remove")
    drift = region_state(w.project, region)
    assert (drift.drift_added, drift.drift_removed) == (1, 1)
    assert drift.latest_version == version  # drift is reported, never applied


def test_projection_keeps_latest_only(region_project: RWorld, human: Actor) -> None:
    w = region_project
    region = define(w, human)
    snapshot_region(w.project, human, region)
    decide_member(w.project, human, region, W, w.extra, "add")
    second = snapshot_region(w.project, human, region)
    with w.project.index.connect() as conn:
        versions = {
            str(r[0])
            for r in conn.execute(text("SELECT DISTINCT version FROM region_members")).all()
        }
        snapshots = int(conn.execute(text("SELECT COUNT(*) FROM region_snapshots")).scalar_one())
        basis = conn.execute(
            text("SELECT basis FROM region_members WHERE member = :m"), {"m": w.extra}
        ).scalar_one()
    assert versions == {second} and snapshots == 2
    assert '"decision":"ev_' in str(basis)


def test_old_version_members_from_blob(region_project: RWorld, human: Actor) -> None:
    w = region_project
    region = define(w, human)
    first = snapshot_region(w.project, human, region)
    decide_member(w.project, human, region, W, w.extra, "add")
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
    decide_member(w.project, human, region, W, w.extra, "add")
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


@pytest.mark.parametrize(
    ("kind", "member", "reason"),
    [
        (MemberType.WORK, "rf:no-such-work", "member-unknown"),
        (MemberType.WORK, "rf:a\nb", "member-invalid"),
        (MemberType.WORK, "rf:a\tb", "member-invalid"),
        (MemberType.WORK, "rf:a\u2028b", "member-invalid"),
        (MemberType.WORK, "", "member-invalid"),
        (MemberType.WORK, "ida_01JZ9Q3K5M7N8P0R2S4T6V8W1I", "member-type-mismatch"),
        (MemberType.IDEA, "rf:some-work", "member-type-mismatch"),
        (MemberType.CONCEPT, "cpt_01JZ9Q3K5M7N8P0R2S4T6V8WZZ", "member-unknown"),
    ],
)
def test_decide_member_validates_at_the_boundary(
    region_project: RWorld, human: Actor, kind: MemberType, member: str, reason: str
) -> None:
    w = region_project
    region = define(w, human)
    before = event_count(w)
    with pytest.raises(FactoryValidationError) as caught:
        decide_member(w.project, human, region, kind, member, "add")
    assert [(i.field, i.reason) for i in caught.value.issues] == [("member", reason)]
    assert event_count(w) == before
    decide_member(w.project, human, region, MemberType.IDEA, w.idea, "add")
    decide_member(w.project, human, region, MemberType.CONCEPT, w.concept, "add")


def _held_out_region(w: RWorld, human: Actor, version: str, nested: str | None = None) -> str:
    rule = (
        ImportRule(import_id="imp_x", part="all") if nested is None else RegionRule(version=nested)
    )
    region = define(w, human, RuleSet(include=(rule,)))
    snapshot_event(w.project, version, region, definition_event_of(w.project, region), [])
    return region


def test_agent_guard_follows_pinned_versions(
    region_project: RWorld, human: Actor, agent: Actor
) -> None:
    w = region_project
    inner, outer = "R@" + "a" * 8, "R@" + "b" * 8
    _held_out_region(w, human, inner)
    _held_out_region(w, human, outer, nested=inner)
    for rule in (
        RegionRule(version=inner),
        RegionRule(version=outer),  # through a nested region
        CitesRule(base=outer, direction="citing"),
    ):
        before = event_count(w)
        with pytest.raises(FactoryValidationError) as caught:
            define(w, agent, RuleSet(include=(FT_INCLUDED, rule)))
        assert caught.value.issues[0].field == "rules.include[1]"
        assert event_count(w) == before
    # a human may name them, and an agent may name a version without the held-out part
    define(w, human, RuleSet(include=(RegionRule(version=outer),)))
    clean = define(w, human)
    ok = "R@" + "c" * 8
    snapshot_event(w.project, ok, clean, definition_event_of(w.project, clean), [])
    define(w, agent, RuleSet(include=(RegionRule(version=ok),)))


def test_agent_may_not_select_by_import_seed_or_probe_runs(
    region_project: RWorld, agent: Actor, human: Actor
) -> None:
    from sqlalchemy import text

    w = region_project
    purposes = {"qry_imp": "import", "qry_seed": "seed", "qry_probe": "probe", "qry_ok": "search"}
    with w.project.index.connect() as conn:
        for query, purpose in purposes.items():
            conn.execute(
                text(
                    "INSERT INTO queries (query_id, source, kind, text, purpose, filters, "
                    "interface, registered_at, actor_id) VALUES (:q, 's', 'k', 't', :p, '{}', "
                    "'i', 'now', 'a')"
                ),
                {"q": query, "p": purpose},
            )
            conn.execute(
                text(
                    "INSERT INTO runs (run_id, query_id, source, status, started_at, pages) "
                    "VALUES (:r, :q, 's', 'finished', 'now', 0)"
                ),
                {"r": f"run_{query}", "q": query},
            )
        conn.commit()
    for query in ("qry_imp", "qry_seed", "qry_probe"):
        for rule in (RunRule(query_id=query), RunRule(run_id=f"run_{query}")):
            with pytest.raises(FactoryValidationError) as caught:
                define(w, agent, RuleSet(include=(rule,)))
            assert caught.value.issues[0].field == "rules.include[0]"
        define(w, human, RuleSet(include=(RunRule(query_id=query),)))
    define(w, agent, RuleSet(include=(RunRule(query_id="qry_ok"),)))


@pytest.mark.slow
def test_snapshot_replays_from_the_event_prefix(
    region_project: RWorld, human: Actor, tmp_path: Path
) -> None:
    """Acceptance 3: the log up to `as_of` gives the same member hash."""
    import json
    import shutil

    from factory.config import Settings
    from factory.services.context import open_project
    from tests.helpers import SESSION

    w = region_project
    region = define(w, human)
    version = snapshot_region(w.project, human, region)
    with w.project.index.connect() as conn:
        as_of, members_hash = conn.execute(
            text("SELECT as_of, members_hash FROM region_snapshots")
        ).one()
    copy_root = tmp_path / "replay"
    shutil.copytree(w.project.settings.root, copy_root, ignore=shutil.ignore_patterns(".index"))
    for path in (copy_root / "projects").rglob("*.jsonl"):
        kept = [ln for ln in path.read_text().splitlines() if json.loads(ln)["id"] <= as_of]
        path.write_text("".join(f"{ln}\n" for ln in kept))
    replayed = open_project(
        Settings(root=copy_root, user="obd"),
        w.project.paths.slug,
        session=SESSION,
        clock=w.project.clock,
    )
    replayed.index.sync()
    assert replayed.index.last_event_id() == as_of
    again = snapshot_region(replayed, human, region)
    with replayed.index.connect() as conn:
        assert conn.execute(text("SELECT members_hash FROM region_snapshots")).scalar_one() == (
            members_hash
        )
    assert again == version
