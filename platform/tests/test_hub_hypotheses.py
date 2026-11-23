"""Hub hypotheses payload (page "Hypotheses") and the researcher's acts (hypothesis engine v1)."""

# ruff: noqa: F811
from __future__ import annotations

import json
import re
from importlib import resources
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.hypotheses import DiscardReason, LeadInput, Trigger, TriggerKind
from factory.model.lead_engine import Candidate
from factory.services import hub_build as hb
from factory.services import hub_hypotheses as hh
from factory.services import hub_ui, site_server
from factory.services.context import Project
from factory.services.hypotheses import draft_hypothesis
from factory.services.hypothesis_review import record_review, review_next
from factory.services.lead_candidates import lead_candidates
from factory.services.leads import decide_lead, record_lead
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.hypothesis_helpers import CRITIC, DRAFTER, LEAD_AUTHOR, LEAD_TEXT, make_spec
from tests.lead_engine_helpers import engine_world
from tests.test_hypothesis_review import verdict


def payload(project: Project) -> dict[str, Any]:
    return hh.build(hb.HubContext(project))


def total(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


def lead_from(project: Project, *candidates: Candidate) -> str:
    triggers = tuple(
        Trigger(kind=TriggerKind(t.kind), ref=t.ref) for c in candidates for t in c.triggers
    )
    return record_lead(project, LEAD_AUTHOR, LeadInput(text=LEAD_TEXT, triggers=triggers))


@pytest.fixture
def populated(project: Project, agent: Actor, human: Actor, world: list[str]) -> dict[str, str]:
    """Miner rows, four leads in four states and one reviewed draft of the promoted lead."""
    engine_world(project, agent, human, world)
    found = lead_candidates(project, layer="all", technique_min_works=1)
    by_source: dict[str, Candidate] = {}
    for c in found.candidates:
        by_source.setdefault(c.source, c)
    promoted = lead_from(project, by_source["claims-limitation"])
    discarded = lead_from(project, by_source["technique-combination"])
    parked = lead_from(project, by_source["technique-gap"])
    open_ = lead_from(project, by_source["technique-challenge"])
    decide_lead(project, human, promoted, "promote")
    decide_lead(project, human, discarded, "discard", DiscardReason.DUPLICATE)
    decide_lead(project, human, parked, "park")
    hid, _version = draft_hypothesis(project, DRAFTER, make_spec(lead=promoted))
    return {
        "promoted": promoted,
        "discarded": discarded,
        "parked": parked,
        "open": open_,
        "hid": hid,
    }


# ---------------------------------------------------------------- the empty world


def test_the_empty_world_says_what_is_missing_and_what_makes_it(project: Project) -> None:
    p = payload(project)
    assert p["ready"] is True and p["empty"] is True
    stages = {s["id"]: s for s in p["stages"]}
    assert list(stages) == [
        "grounding",
        "leads",
        "critique",
        "prior",
        "ordering",
        "drafting",
        "review",
    ]
    for sid, s in stages.items():
        assert s["made_by"], sid
        if sid == "critique":
            assert s["state"] == "session" and s["count"] is None
        else:
            assert s["state"] == "empty" and s["count"] == 0 and s["missing"], sid
    assert p["grounding"]["missing"] and p["grounding"]["total"] == 0
    assert p["queue"]["items"] == [] and p["queue"]["total_candidates"] == 0
    assert p["leads"]["totals"] == {"open": 0, "promoted": 0, "parked": 0, "discarded": 0}
    assert p["hypotheses"]["items"] == [] and p["hypotheses"]["total"] == 0
    assert p["stats"]["recorded"] == 0 and p["stats"]["promotion_rate"] is None
    assert p["skill"] == "rf-hypothesis-engine"
    assert "exploratory" in p["notice"]
    assert set(p["methods"]) >= {"page", "stages", "grounding", "queue", "leads", "hypotheses"}
    json.loads(hb.dumps(p))


def test_the_builder_writes_nothing(project: Project) -> None:
    before = total(project)
    payload(project)
    assert total(project) == before


# ---------------------------------------------------------------- a populated world


def test_figures_equal_what_the_services_record(
    project: Project, populated: dict[str, str]
) -> None:
    p = payload(project)
    assert p["empty"] is False
    assert p["leads"]["totals"] == {"open": 1, "promoted": 1, "parked": 1, "discarded": 1}
    assert p["stats"]["recorded"] == 4 and p["stats"]["by_state"]["promoted"] == 1
    assert p["stats"]["hypotheses_drafted"] == 1
    ids = {s: [x["lead_id"] for x in p["leads"]["by_state"][s]] for s in p["leads"]["by_state"]}
    assert ids["open"] == [populated["open"]] and ids["discarded"] == [populated["discarded"]]
    discarded = p["leads"]["by_state"]["discarded"][0]
    assert discarded["decision"] == "discard" and discarded["reason"] == "duplicate"
    dumped = hb.dumps(p)
    assert "author_session" not in dumped and "drafter_session" not in dumped
    stages = {s["id"]: s for s in p["stages"]}
    assert stages["leads"]["count"] == 4 and stages["drafting"]["count"] == 1
    assert stages["grounding"]["count"] == p["grounding"]["total"] > 0
    assert stages["grounding"]["state"] == "done" and stages["grounding"]["missing"] is None
    assert p["grounding"]["miners"] and p["grounding"]["lineage"] == {"relations": 0, "ideas": 0}


def test_a_queue_entry_has_its_observation_reason_and_evidence(
    project: Project, populated: dict[str, str]
) -> None:
    q = payload(project)["queue"]
    assert q["items"] and q["shown"] == len(q["items"]) <= q["cap"]
    assert [e["rank"] for e in q["items"]] == list(range(1, len(q["items"]) + 1))
    assert q["order_by"] and q["order_rule"] and q["comparability"]
    for e in q["items"]:
        assert e["kind"] == "candidate" and e["observation"] and e["why"]
        assert len(e["quotes"]) <= hh.QUOTE_CAP and e["quotes_total"] >= len(e["quotes"])
        assert e["measures"]["basis"] in ("live", "stale", "superseded", "unknown")
    assert any(e["quotes"] for e in q["items"])
    # the open lead is listed once: on its own, or as the record of the candidate it cites
    own = {e["entry_id"] for e in q["leads_open"]}
    linked = {e["recorded_as"]["lead_id"] for e in q["items"] if e["recorded_as"]}
    assert populated["open"] in own | linked
    [open_lead] = payload(project)["leads"]["by_state"]["open"]
    assert open_lead["entry"] is None or open_lead["entry"]["why"]


def test_a_draft_shows_its_gates_and_a_review_changes_them(
    project: Project, populated: dict[str, str]
) -> None:
    [h] = payload(project)["hypotheses"]["items"]
    gates = {g["id"]: g["status"] for g in h["gates"]}
    assert h["state"] == "draft" and h["falsifier"] and h["lead"] == populated["promoted"]
    assert gates == {"review": "pending", "registration": "pending", "evaluation": "pending"}
    served = review_next(project, CRITIC)
    assert served is not None
    record_review(project, CRITIC, served.task_id, verdict("revise", falsifiable="fail"))
    [h] = payload(project)["hypotheses"]["items"]
    gates = {g["id"]: g for g in h["gates"]}
    assert h["state"] == "reviewed" and h["reviews"] == 1
    assert gates["review"]["status"] == "fail" and "falsifiable" in gates["review"]["detail"]
    assert h["last_review"]["recommend"] == "revise" and h["last_review"]["failed"] == [
        "falsifiable"
    ]
    assert payload(project)["stats"]["reviews"] == 1


def test_the_payload_is_deterministic_and_capped(
    project: Project, populated: dict[str, str]
) -> None:
    assert hb.dumps(payload(project)) == hb.dumps(payload(project))
    p = payload(project)
    assert len(p["queue"]["items"]) <= hh.QUEUE_CAP
    for state, rows in p["leads"]["by_state"].items():
        assert len(rows) <= hh.LEAD_CAP and len(rows) <= p["leads"]["totals"][state]
    assert len(p["hypotheses"]["items"]) <= hh.HYPOTHESIS_CAP


# ---------------------------------------------------------------- the acts


def test_a_bad_body_writes_nothing(
    project: Project, human: Actor, populated: dict[str, str]
) -> None:
    before = total(project)
    bad: list[tuple[Any, dict[str, Any]]] = [
        (hh.decide_lead_act, {}),
        (hh.decide_lead_act, {"lead_id": populated["open"], "decision": "maybe"}),
        (hh.decide_lead_act, {"lead_id": populated["open"], "decision": "promote", "x": 1}),
        (hh.decide_lead_act, {"lead_id": populated["open"], "decision": "discard"}),
        (
            hh.decide_lead_act,
            {"lead_id": populated["open"], "decision": "discard", "reason": "no-such"},
        ),
        (hh.decide_lead_act, {"lead_id": "led_NOPE", "decision": "promote"}),
        (hh.register_act, {}),
        (hh.register_act, {"hypothesis_id": "hyp_NOPE"}),
        (hh.abandon_act, {"hypothesis_id": populated["hid"]}),
        (hh.abandon_act, {"hypothesis_id": populated["hid"], "reason": "other", "note": " "}),
    ]
    for act, body in bad:
        with pytest.raises(FactoryValidationError):
            act(project, human, body)
    assert total(project) == before


def test_an_agent_cannot_decide_and_the_service_keeps_the_gate(
    project: Project, populated: dict[str, str]
) -> None:
    before = total(project)
    with pytest.raises(FactoryValidationError) as err:
        hh.decide_lead_act(project, DRAFTER, {"lead_id": populated["open"], "decision": "park"})
    assert err.value.issues[0].field == "actor"
    with pytest.raises(FactoryValidationError):
        hh.abandon_act(
            project, DRAFTER, {"hypothesis_id": populated["hid"], "reason": "other", "note": "x"}
        )
    assert total(project) == before


def test_the_researcher_decides_a_lead_and_the_payload_follows(
    project: Project, human: Actor, populated: dict[str, str]
) -> None:
    out = hh.decide_lead_act(
        project,
        human,
        {"lead_id": populated["open"], "decision": "discard", "reason": "out-of-scope"},
    )
    assert out["lead_id"] == populated["open"] and out["event_id"]
    p = payload(project)
    assert p["leads"]["totals"]["open"] == 0 and p["leads"]["totals"]["discarded"] == 2
    hh.abandon_act(
        project, human, {"hypothesis_id": populated["hid"], "reason": "infeasible", "note": "n"}
    )
    assert payload(project)["hypotheses"]["items"][0]["state"] == "abandoned"


def test_the_routes_authorise_each_decision_as_its_cli_command(project: Project) -> None:
    assert set(hh.ACTS) == {
        "/ui/act/lead-decide",
        "/ui/act/hypothesis-register",
        "/ui/act/hypothesis-abandon",
    }
    command_of = hh.ACTS["/ui/act/lead-decide"][0]
    assert command_of({"decision": "park"}) == "cli:leads park"
    assert command_of({"decision": "discard"}) == "cli:leads discard"
    assert command_of({"decision": "x"}) is None and command_of({}) is None
    before = total(project)
    route = site_server._ROUTES["/ui/act/lead-decide"]
    code, body = route(project, {"lead_id": "led_X", "decision": "x"})
    assert code == 400 and body
    code, _ = route(project, {"decision": "promote"})
    assert code == 400
    assert total(project) == before


# ---------------------------------------------------------------- registration and the script


def _js() -> str:
    rel = hub_ui.PAGES["hypotheses"].script.split("/")
    return resources.files("factory.hub_ui").joinpath(*rel).read_text(encoding="utf-8")


def test_the_page_is_registered_with_its_payload_and_inputs() -> None:
    spec = hub_ui.PAGES["hypotheses"]
    assert spec.payloads == ("shell", "hypotheses") and spec.script in hub_ui.ASSETS
    assert hb.BUILDERS["hypotheses"].__module__ == "factory.services.hub_hypotheses"
    inputs = hb.PAYLOAD_INPUTS["hypotheses"]
    assert hb.reads("hypotheses", "lead.decided") and hb.reads("hypotheses", "hypothesis.drafted")
    assert not hb.reads("hypotheses", "feed.item_seen") and not hb.reads("hypotheses", "runner.x")
    assert "lead." in inputs and "hypothesis." in inputs


def test_the_script_uses_only_the_allow_listed_routes_and_the_served_guard() -> None:
    src = _js()
    routes = set(re.findall(r"/ui/act/[a-z-]+", src))
    assert routes == set(hh.ACTS)
    assert "HUB.served" in src and "D.skill" in src
    assert "Proposal" in src and "never evidence" in src
    assert "outerHTML" not in src and "document.write" not in src
