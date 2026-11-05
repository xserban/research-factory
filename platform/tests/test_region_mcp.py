"""The region MCP tools (slice 3d, plan Regions-B, task 3).

No tool reviews a version, decides a member, links or adopts. A region that reaches an import's
`all` part or a run of a barred purpose is refused to an agent as a whole, directly or through a
pinned version.
"""

# ruff: noqa: F401, F811

from __future__ import annotations

from typing import Any

import pytest
from mcp import Client

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.protocol import ScreeningStage
from factory.model.regions import RegionKind
from factory.regions.rules import CorpusRule, MemberType, RegionRule, RuleSet, RunRule
from factory.services.context import Project
from factory.services.regions import (
    decide_member,
    define_region,
    propose_member,
    snapshot_region,
)
from tests.contribution_helpers import ctr_a, ctr_b, world
from tests.helpers import install_skill, open_session
from tests.intuition_helpers import live_conversion
from tests.lineage_helpers import Lineage, lin
from tests.region_helpers import RWorld, add_queries, region_project, screened
from tests.test_mcp_intuition import SESSION_I, _session

AGENT = {"role": "regioner", "model": "claude-opus-5-5", "skill": "rf-regions"}
FT_INCLUDED = {"kind": "corpus", "outcome": "included", "stage": "full-text"}
RULES = {"include": [FT_INCLUDED]}
W = MemberType.WORK
TOOLS = (
    "region_propose",
    "region_propose_member",
    "region_snapshot",
    "region_status",
    "region_query",
)


def region_events(project: Project) -> list[Event]:
    return [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type.startswith("region.")
    ]


def human_region(w: RWorld, human: Actor, rules: RuleSet, name: str = "held") -> str:
    return define_region(
        w.project,
        human,
        kind=RegionKind.REGION,
        name=name,
        definition=name,
        rules=rules,
    )


@pytest.mark.anyio
async def test_no_decision_tool_exists(settings: Settings, clock: FixedClock) -> None:
    async with Client(build_server_for(settings, clock)) as client:
        names = [t.name for t in (await client.list_tools()).tools]
    mine = [n for n in names if n.startswith("region")]
    assert sorted(mine) == sorted(TOOLS)
    banned = ("review", "decide", "link", "adopt", "add", "remove", "reject", "approve", "merge")
    assert not [n for n in names if n.startswith("region") and any(b in n for b in banned)]


def build_server_for(settings: Settings, clock: FixedClock) -> Any:
    from factory.mcp.server import build_server

    return build_server(settings, clock=clock)


@pytest.mark.anyio
async def test_region_tools_refuse_pass_sessions(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    region_project: RWorld,
    lin: Lineage,
    ctr_a: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-regions")
    _session(monkeypatch, ctr_a.session)
    async with open_session(settings, clock) as client:
        outs = [
            await client.call(
                "region_propose",
                project="demo",
                region_name="x",
                kind="region",
                definition="x",
                rules=RULES,
                **AGENT,
            ),
            await client.call(
                "region_propose_member",
                project="demo",
                region_id="reg_01HZX3K4M5N6P7Q8R9S0T1V2WZ",
                member_type="work",
                member=lin.source,
                basis={"kind": "edge", "edge_id": "e"},
                **AGENT,
            ),
            await client.call(
                "region_snapshot",
                project="demo",
                region_id="reg_01HZX3K4M5N6P7Q8R9S0T1V2WZ",
                **AGENT,
            ),
            await client.call("region_status", project="demo"),
            await client.call("region_query", project="demo", query="regions_of"),
        ]
    for out in outs:
        assert out["ok"] is False and out["errors"][0]["field"] == "session", out
    assert region_events(project) == []


@pytest.mark.anyio
async def test_agent_import_rule_all_refused(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    region_project: RWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-regions")
    _session(monkeypatch, SESSION_I)
    rules = {"include": [{"kind": "import", "import_id": "imp_x", "part": "all"}]}
    async with open_session(settings, clock) as client:
        out = await client.call(
            "region_propose",
            project="demo",
            region_name="x",
            kind="region",
            definition="x",
            rules=rules,
            **AGENT,
        )
    assert out["ok"] is False
    assert out["errors"][0]["field"] == "rules.include.0.part"
    assert region_events(project) == []


@pytest.mark.anyio
async def test_roundtrip_provenance_and_members_paginated(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    region_project: RWorld,
    lin: Lineage,
    human: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = region_project
    skill = install_skill(settings, "rf-regions")
    _session(monkeypatch, SESSION_I)
    cnv, _ = live_conversion(project, lin.source)
    async with open_session(settings, clock) as client:
        proposed = await client.call(
            "region_propose",
            project="demo",
            region_name="included",
            kind="region",
            definition="Included works.",
            rules=RULES,
            **AGENT,
        )
        assert proposed["ok"] is True, proposed
        region = proposed["data"]["region_id"]
        assert proposed["data"]["live_counts"] == {"work": len(w.included)}
        assert proposed["data"]["counts_withheld"] is False
        snap = await client.call("region_snapshot", project="demo", region_id=region, **AGENT)
        assert snap["ok"] is True, snap
        version = snap["data"]["version"]
        assert snap["data"]["review_state"] == "unreviewed"
        status = await client.call("region_status", project="demo")
        assert [r["region_id"] for r in status["data"]["regions"]] == [region]
        seen: list[str] = []
        offset = 0
        while True:
            page = await client.call(
                "region_query",
                project="demo",
                query="members",
                version=version,
                offset=offset,
                limit=2,
            )
            assert page["ok"] is True, page
            assert len(page["data"]["members"]) <= 2
            seen += [m["id"] for m in page["data"]["members"]]
            offset = page["data"]["next_offset"]
            if offset is None:
                break
        assert seen == sorted(w.included)
        of = await client.call(
            "region_query",
            project="demo",
            query="regions_of",
            member_type="work",
            member=w.included[0],
        )
        assert [r["region_id"] for r in of["data"]["regions"]] == [region]
        # a human removes one work; the agent proposes it back with a verified quote
        decide_member(project, human, region, W, lin.source, "remove")
        bad = await client.call(
            "region_propose_member",
            project="demo",
            region_id=region,
            member_type="work",
            member=lin.source,
            basis={
                "kind": "quote",
                "work_id": lin.source,
                "conversion_id": cnv,
                "anchor": "s1.p4",
                "quote": "very long sequences degrade badly",
            },
            **AGENT,
        )
        assert bad["ok"] is False and bad["errors"][0]["field"] == "basis.quote"
        good = await client.call(
            "region_propose_member",
            project="demo",
            region_id=region,
            member_type="work",
            member=lin.source,
            basis={
                "kind": "quote",
                "work_id": lin.source,
                "conversion_id": cnv,
                "anchor": "s1.p4",
                "quote": "very long sequences degrade",
            },
            **AGENT,
        )
        assert good["ok"] is True and good["data"]["proposal_id"].startswith("rmp_")
        shape = await client.call(
            "region_propose_member",
            project="demo",
            region_id=region,
            member_type="work",
            member=lin.source,
            basis={"kind": "guess"},
            **AGENT,
        )
        assert shape["ok"] is False
        second = await client.call("region_snapshot", project="demo", region_id=region, **AGENT)
        diff = await client.call(
            "region_query", project="demo", query="diff", a=version, b=second["data"]["version"]
        )
        overlap = await client.call(
            "region_query", project="demo", query="overlap", a=version, b=second["data"]["version"]
        )
    assert diff["data"]["removed"] == [{"type": "work", "id": lin.source}]
    assert diff["data"]["added"] == []
    assert overlap["data"]["shared"] == {"work": len(w.included) - 1}
    for e in region_events(project):
        if e.actor.kind == "agent":
            assert e.actor.skill == skill and e.input_blob is not None, e.type


@pytest.mark.anyio
async def test_withheld_region_returns_no_members_or_counts(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    region_project: RWorld,
    lin: Lineage,
    human: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = region_project
    add_queries(project, {"qry_imp": "import", "qry_probe": "probe", "qry_ok": "search"})
    barred = RuleSet(
        include=(
            CorpusRule(outcome="included", stage=ScreeningStage.FULL_TEXT),
            RunRule(query_id="qry_imp"),
        )
    )
    held = human_region(w, human, barred, "held")
    held_version = snapshot_region(project, human, held)
    pinned = human_region(
        w, human, RuleSet(include=(RegionRule(version=held_version),)), "through a pin"
    )
    pinned_version = snapshot_region(project, human, pinned)
    fine = human_region(
        w,
        human,
        RuleSet(include=(CorpusRule(outcome="included", stage=ScreeningStage.FULL_TEXT),)),
        "fine",
    )
    fine_version = snapshot_region(project, human, fine)
    install_skill(settings, "rf-regions")
    _session(monkeypatch, SESSION_I)
    async with open_session(settings, clock) as client:
        status = await client.call("region_status", project="demo")
        assert status["ok"] is True, status
        by_id = {r["region_id"]: r for r in status["data"]["regions"]}
        for region in (held, pinned):
            row = by_id[region]
            assert row["counts_withheld"] is True
            assert row["live_counts"] == {} and row["drift_added"] == 0
        assert by_id[fine]["counts_withheld"] is False and by_id[fine]["live_counts"]
        refused = []
        for version in (held_version, pinned_version):
            refused.append(
                await client.call("region_query", project="demo", query="members", version=version)
            )
            refused.append(
                await client.call(
                    "region_query", project="demo", query="overlap", a=version, b=fine_version
                )
            )
            refused.append(
                await client.call(
                    "region_query", project="demo", query="diff", a=fine_version, b=version
                )
            )
        for region in (held, pinned):
            refused.append(
                await client.call("region_snapshot", project="demo", region_id=region, **AGENT)
            )
            refused.append(
                await client.call(
                    "region_propose_member",
                    project="demo",
                    region_id=region,
                    member_type="work",
                    member=lin.source,
                    basis={"kind": "edge", "edge_id": "cit:rex_" + "1".zfill(26) + ":1"},
                    **AGENT,
                )
            )
            refused.append(
                await client.call(
                    "region_propose",
                    project="demo",
                    region_name="mine now",
                    kind="region",
                    definition="redefined",
                    rules=RULES,
                    region_id=region,
                    **AGENT,
                )
            )
        for out in refused:
            assert out["ok"] is False, out
            assert out["errors"] == [
                {"field": out["errors"][0]["field"], "reason": "region-unavailable"}
            ], out
            assert "included" not in str(out) and lin.source not in str(out)
        of = await client.call(
            "region_query",
            project="demo",
            query="regions_of",
            member_type="work",
            member=lin.source,
        )
    assert [r["region_id"] for r in of["data"]["regions"]] == [fine]
    # the held regions were neither snapshotted, proposed to nor redefined by the agent
    agent_events = [e for e in region_events(project) if e.actor.kind == "agent"]
    assert agent_events == []


def test_service_refuses_an_agent_on_a_withheld_region(
    region_project: RWorld, human: Actor, agent: Actor, lin: Lineage
) -> None:
    w = region_project
    add_queries(w.project, {"qry_seed": "seed"})
    held = human_region(w, human, RuleSet(include=(RunRule(query_id="qry_seed"),)))
    with pytest.raises(FactoryValidationError) as caught:
        snapshot_region(w.project, agent, held)
    assert caught.value.issues[0].reason == "region-unavailable"
    # a human may snapshot it
    assert snapshot_region(w.project, human, held).startswith("R@")
