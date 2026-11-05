"""The lead and hypothesis MCP tools (slice 6, plan H-C task 7).

Every tool is refused to a pass session and, before a pass opens, answers with the same neutral
message as the finders. The decision tools refuse under a `human` policy."""

# ruff: noqa: F401, F811

from __future__ import annotations

import pytest
from mcp import Client

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.mcp import server as mcp_server
from factory.mcp.server import build_server
from factory.services import coverage as coverage_service
from factory.services.context import Project
from factory.services.hypotheses import draft_hypothesis, hypothesis_view
from factory.services.leads import decide_lead, lead_view
from tests.extraction_helpers import SESSION_A
from tests.helpers import install_skill, open_session
from tests.hypothesis_helpers import (
    DRAFTER,
    HW,
    LEAD_TEXT,
    STATEMENT,
    exploratory_card,
    hw,
    make_spec,
    promoted_lead,
)
from tests.test_finder_gaps import gw
from tests.test_mcp_cards import SESSION_E, _session

TOOLS = (
    "lead_record",
    "lead_decide",
    "hypothesis_draft",
    "hypothesis_view",
    "hypothesis_review_next",
    "hypothesis_review",
    "hypothesis_register",
)
SESSION_F = "01JZ9Q3K5M7N8P0R2S4T6V8W1F"
IDEATE = {"role": "ideator", "model": "claude-opus-5-5", "skill": "rf-ideate"}
CRITIC = {"role": "critic", "model": "claude-sonnet-5-5", "skill": "rf-critic"}
CHECKLIST_ALL_PASS = {
    "items": {
        k: "pass"
        for k in (
            "falsifiable",
            "measurable",
            "single-factor",
            "baselines-named",
            "rule-complete",
            "prior-addressed",
            "conditions-in-evidence",
        )
    },
    "recommend": "register",
}


def _of(project: Project, *kinds: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in kinds]


def _spec(lead: str) -> dict[str, object]:
    return make_spec(lead=lead).model_dump(mode="json")


@pytest.mark.anyio
async def test_tool_list_pins_the_hypothesis_tools(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    async with Client(build_server(settings, clock=clock)) as client:
        names = [t.name for t in (await client.list_tools()).tools]
    assert all(tool in names for tool in TOOLS)
    related = [n for n in names if n.startswith(("lead_", "hypothesis_"))]
    assert sorted(related) == sorted(TOOLS)  # nothing concludes, abandons or declares a cut-off


@pytest.mark.anyio
async def test_lead_draft_review_flow_and_human_gates(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    human: Actor,
    gw: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-ideate")
    install_skill(settings, "rf-critic")
    _session(monkeypatch, SESSION_E)
    async with open_session(settings, clock) as client:
        recorded = await client.call(
            "lead_record",
            project="demo",
            text=LEAD_TEXT,
            triggers=[{"kind": "work", "ref": gw[0]}],
            framework="scamper",
            **IDEATE,
        )
        no_trigger = await client.call(
            "lead_record", project="demo", text=LEAD_TEXT, triggers=[], **IDEATE
        )
        refused_decide = await client.call(
            "lead_decide",
            project="demo",
            lead_id=recorded["data"]["lead_id"],
            decision="promote",
            **IDEATE,
        )
    assert recorded["ok"] is True and recorded["data"]["prior"] == []
    assert no_trigger["ok"] is False
    assert refused_decide["ok"] is False and refused_decide["errors"][0]["field"] == "gate"
    lead = recorded["data"]["lead_id"]
    [lead_event] = _of(project, "lead.recorded")
    assert lead_event.actor.kind == "agent" and lead_event.input_blob is not None
    assert lead_view(project, lead).state == "open"  # type: ignore[union-attr]
    decide_lead(project, human, lead, "promote")

    async with open_session(settings, clock) as client:
        drafted = await client.call("hypothesis_draft", project="demo", spec=_spec(lead), **IDEATE)
        refused_register = await client.call(
            "hypothesis_register", project="demo", hypothesis_id="hyp_x", **IDEATE
        )
        own_review = await client.call("hypothesis_review_next", project="demo", **CRITIC)
    assert drafted["ok"] is True, drafted
    hid = drafted["data"]["hypothesis_id"]
    assert drafted["data"]["h_version"].startswith("H@")
    assert drafted["data"]["falsifier"].startswith("Refuted if the 95% CI upper bound")
    assert refused_register["ok"] is False and refused_register["errors"][0]["field"] == "gate"
    # the drafting session cannot review its own draft, and is turned away before any artefact
    assert own_review["ok"] is False and own_review["errors"][0]["reason"] == "drafter-session"

    _session(monkeypatch, SESSION_F)
    async with open_session(settings, clock) as client:
        served = await client.call("hypothesis_review_next", project="demo", **CRITIC)
        task = served["data"]["task"]
        assert task["hypothesis_id"] == hid and task["statement"] == STATEMENT
        assert LEAD_TEXT not in str(served) and "rationale" not in task["spec_without_prose"]
        bad = await client.call(
            "hypothesis_review",
            project="demo",
            task_id=served["data"]["task_id"],
            review={"items": {"falsifiable": "pass"}, "recommend": "register"},
            **CRITIC,
        )
        reviewed = await client.call(
            "hypothesis_review",
            project="demo",
            task_id=served["data"]["task_id"],
            review=CHECKLIST_ALL_PASS,
            **CRITIC,
        )
        view = await client.call("hypothesis_view", project="demo", hypothesis_id=hid)
        unknown = await client.call("hypothesis_view", project="demo", hypothesis_id="hyp_nope")
    assert bad["ok"] is False and bad["errors"][0]["field"].startswith("review")
    assert reviewed["ok"] is True
    assert view["data"]["state"] == "reviewed" and view["data"]["falsifier"]
    assert unknown["ok"] is False
    [review_event] = _of(project, "hypothesis.reviewed")
    assert review_event.actor.skill is not None and review_event.actor.skill.startswith(
        "rf-critic@"
    )
    assert hypothesis_view(project, hid).state == "reviewed"  # type: ignore[union-attr]


@pytest.mark.anyio
async def test_agent_gates_open_under_the_exploratory_preset(
    settings: Settings,
    explore_project: Project,
    clock: FixedClock,
    human: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = explore_project
    install_skill(settings, "rf-ideate")
    monkeypatch.setattr(coverage_service, "held_out_visible", lambda _p: True)
    card = exploratory_card(project, human)
    _session(monkeypatch, SESSION_E)
    async with open_session(settings, clock) as client:
        lead = await client.call(
            "lead_record",
            project="demo",
            text=LEAD_TEXT,
            triggers=[{"kind": "card", "ref": card}],
            **IDEATE,
        )
        drafted = await client.call(
            "hypothesis_draft", project="demo", spec=_spec_no_lead(), **IDEATE
        )
    assert lead["ok"] is True and drafted["ok"] is True
    _session(monkeypatch, SESSION_F)
    async with open_session(settings, clock) as client:
        decided = await client.call(
            "lead_decide",
            project="demo",
            lead_id=lead["data"]["lead_id"],
            decision="discard",
            reason="out-of-scope",
            **IDEATE,
        )
        registered = await client.call(
            "hypothesis_register",
            project="demo",
            hypothesis_id=drafted["data"]["hypothesis_id"],
            **IDEATE,
        )
    assert decided["ok"] is True and registered["ok"] is True
    view = hypothesis_view(project, drafted["data"]["hypothesis_id"])
    assert view is not None and view.state == "registered" and view.autonomy == "agent"
    assert lead_view(project, lead["data"]["lead_id"]).state == "discarded"  # type: ignore[union-attr]


def _spec_no_lead() -> dict[str, object]:
    return make_spec().model_dump(mode="json")


@pytest.mark.anyio
async def test_pass_session_is_refused(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    hw: HW,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-ideate")
    install_skill(settings, "rf-critic")
    _session(monkeypatch, SESSION_A)  # an extraction-pass session of the evidence world
    async with open_session(settings, clock) as client:
        outs = [
            await client.call(
                "lead_record",
                project="demo",
                text=LEAD_TEXT,
                triggers=[{"kind": "work", "ref": hw.works[0]}],
                **IDEATE,
            ),
            await client.call(
                "lead_decide", project="demo", lead_id=hw.lead, decision="park", **IDEATE
            ),
            await client.call("hypothesis_draft", project="demo", spec=_spec(hw.lead), **IDEATE),
            await client.call("hypothesis_view", project="demo", hypothesis_id=hw.hid),
            await client.call("hypothesis_review_next", project="demo", **CRITIC),
            await client.call(
                "hypothesis_review",
                project="demo",
                task_id="tsk_01JZ9Q3K5M7N8P0R2S4T6V8W1A",
                review=CHECKLIST_ALL_PASS,
                **CRITIC,
            ),
            await client.call(
                "hypothesis_register", project="demo", hypothesis_id=hw.hid, **IDEATE
            ),
        ]
    for out in outs:
        assert out["ok"] is False and out["errors"][0]["field"] == "session", out
    assert len(_of(project, "lead.recorded")) == 1  # only the fixture's


@pytest.mark.anyio
async def test_tools_are_role_blind_before_a_pass_opens(
    settings: Settings, project: Project, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_skill(settings, "rf-ideate")
    install_skill(settings, "rf-critic")
    _session(monkeypatch, SESSION_E)
    async with open_session(settings, clock) as client:
        outs = [
            await client.call(
                "lead_record",
                project="demo",
                text="t",
                triggers=[{"kind": "work", "ref": "rf:a-b-1-00000000"}],
                **IDEATE,
            ),
            await client.call(
                "lead_decide",
                project="demo",
                lead_id="led_01JZ9Q3K5M7N8P0R2S4T6V8W1A",
                decision="park",
                **IDEATE,
            ),
            await client.call("hypothesis_draft", project="demo", spec={}, **IDEATE),
            await client.call("hypothesis_view", project="demo", hypothesis_id="hyp_x"),
            await client.call("hypothesis_review_next", project="demo", **CRITIC),
            await client.call(
                "hypothesis_register", project="demo", hypothesis_id="hyp_x", **IDEATE
            ),
        ]
    assert {(o["ok"], o["errors"][0]["reason"]) for o in outs} == {(False, "not available yet")}
