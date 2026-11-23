# ruff: noqa: F401, F811
"""Hub ideas payload (page "Ideas") and the researcher's decision acts."""

from __future__ import annotations

import json
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.lineage import LineageDecision, RelationProposal
from factory.services import hub_build as hb
from factory.services import hub_ideas as hi
from factory.services import hub_ui, site_server
from factory.services.context import Project
from factory.services.ideas import propose_idea
from factory.services.relations import decide_relation, propose_relation
from tests.lineage_helpers import Lineage, ctr_a, ctr_b, lin, screened, world


def prop(lin: Lineage, target: str, basis: str | None, edge: str = "builds-on") -> RelationProposal:
    return RelationProposal(
        source_work=lin.source,
        target=target,
        edge_type=edge,  # type: ignore[arg-type]
        basis_item=basis,
    )


def payload(project: Project) -> dict[str, Any]:
    return hi.build(hb.HubContext(project))


@pytest.fixture
def decider(other_session_human: Actor) -> Actor:
    return other_session_human


@pytest.fixture
def rich(
    project: Project, agent: Actor, decider: Actor, lin: Lineage, world: list[str]
) -> dict[str, str]:
    """Relations in every status and one proposed idea, over the lineage world."""
    other = next(w for w in world if w != lin.source)
    stated = propose_relation(project, agent, prop(lin, lin.target5, lin.base)).relation_id
    stated2 = propose_relation(
        project, agent, prop(lin, lin.target3, lin.addition, "improves-on")
    ).relation_id
    to_confirm = propose_relation(project, agent, prop(lin, lin.target3, lin.base)).relation_id
    waiting = propose_relation(project, agent, prop(lin, other, lin.base)).relation_id
    to_reject = propose_relation(
        project, agent, prop(lin, lin.target5, lin.addition, "improves-on")
    ).relation_id
    decide_relation(project, decider, to_confirm, LineageDecision.CONFIRM, "the quote says so")
    decide_relation(project, decider, to_reject, LineageDecision.REJECT, "not that work")
    idea = propose_idea(project, agent, "linear attention", lin.source, lin.base, [lin.source])
    return {
        "stated": stated,
        "stated2": stated2,
        "confirmed": to_confirm,
        "waiting": waiting,
        "rejected": to_reject,
        "idea": idea,
    }


# ---------------------------------------------------------------- the empty world


def test_an_empty_world_says_what_is_missing_and_what_produces_it(project: Project) -> None:
    data = payload(project)
    assert data["ready"] is True and data["empty"] is True
    assert data["nodes"] == [] and data["edges"] == [] and data["needs"] == []
    assert data["paths"] == {}
    steps = " ".join(f"{m['what']} {m['step']}" for m in data["missing"])
    assert "rf-contributions" in steps and "rf-lineage" in steps
    assert steps.index("rf-contributions") < steps.index("rf-lineage")
    assert data["counts"]["works_read"] == 0 and data["counts"]["items"] == 0
    assert data["counts"]["relations"] == {
        "stated": 0,
        "confirmed": 0,
        "inferred": 0,
        "stale": 0,
        "rejected": 0,
    }
    assert set(hi.METHODS) <= set(data["methods"])


# ---------------------------------------------------------------- items only


def test_items_without_relations_ask_for_the_lineage_step(project: Project, lin: Lineage) -> None:
    data = payload(project)
    assert data["empty"] is False
    assert [m["id"] for m in data["missing"]] == ["lineage"]
    assert data["counts"]["works_read"] == 1 and data["counts"]["items"] == 4
    node = next(n for n in data["nodes"] if n["id"] == lin.source)
    assert node["kind"] == "paper" and node["read"] is True
    kinds = sorted(i["kind"] for i in node["items"])
    assert kinds == ["addition", "base-idea", "base-idea", "limitation"]
    cited = next(i for i in node["items"] if i["id"] == lin.base)
    assert cited["quote"] and cited["anchor"] and cited["cited_entry"] == 5


# ---------------------------------------------------------------- every status


def test_relations_in_every_status_with_their_evidence(
    project: Project, lin: Lineage, rich: dict[str, str]
) -> None:
    data = payload(project)
    by_id = {e["id"]: e for e in data["edges"]}
    status = {name: by_id[rid]["status"] for name, rid in rich.items() if name != "idea"}
    assert status == {
        "stated": "stated",
        "stated2": "stated",
        "confirmed": "confirmed",
        "waiting": "inferred",
        "rejected": "rejected",
    }
    assert data["counts"]["relations"] == {
        "stated": 2,
        "confirmed": 1,
        "inferred": 1,
        "stale": 0,
        "rejected": 1,
    }
    waiting = by_id[rich["waiting"]]
    assert waiting["proposal"] is True and waiting["flags"] == ["uncited-base"]
    assert waiting["proposer"]["kind"] == "agent" and waiting["proposer"]["model"]
    assert waiting["basis"] == lin.base
    assert waiting["basis_item"]["quote"] and waiting["basis_item"]["anchor"]
    assert by_id[rich["confirmed"]]["proposal"] is False
    assert by_id[rich["confirmed"]]["decision"] == "confirm"
    assert by_id[rich["rejected"]]["decision"] == "reject"
    assert by_id[rich["stated"]]["kind"] == "builds-on"
    assert by_id[rich["stated2"]]["kind"] == "improves-on"


def test_an_idea_is_a_distinct_labelled_proposal(
    project: Project, lin: Lineage, rich: dict[str, str]
) -> None:
    data = payload(project)
    idea = next(n for n in data["nodes"] if n["kind"] == "idea")
    assert idea["id"] == rich["idea"] and idea["label"] == "linear attention"
    assert idea["state"] == "proposed" and idea["proposal"] is True
    assert idea["members"] == [lin.source] and idea["origin"] == lin.source
    assert idea["name_item"]["quote"] and idea["proposer"]["kind"] == "agent"
    assert data["counts"]["ideas"] == {"proposed": 1, "confirmed": 0, "rejected": 0}


def test_needs_decision_lists_proposals_newest_first(
    project: Project, rich: dict[str, str]
) -> None:
    needs = payload(project)["needs"]
    assert {(n["type"], n["id"]) for n in needs} == {
        ("relation", rich["waiting"]),
        ("idea", rich["idea"]),
    }
    assert [n["at"] for n in needs] == sorted((n["at"] for n in needs), reverse=True)
    assert all(n["at"] for n in needs)


def test_paths_reach_back_and_name_the_start(
    project: Project, lin: Lineage, rich: dict[str, str]
) -> None:
    data = payload(project)
    path = data["paths"][lin.source]
    assert {lin.target5, lin.target3} <= set(path["nodes"])
    assert rich["stated"] in path["edges"]
    assert set(path["roots"]) <= set(path["nodes"]) and path["truncated"] is False


def test_output_is_deterministic(project: Project, rich: dict[str, str]) -> None:
    first = json.dumps(payload(project), sort_keys=False)
    second = json.dumps(payload(project), sort_keys=False)
    assert first == second


def test_the_caps_cut_and_count(
    project: Project, rich: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hi, "NODE_CAP", 2)
    data = payload(project)
    assert len(data["nodes"]) <= 3  # the idea is always kept
    assert data["omitted"]["nodes"] >= 1
    ids = {n["id"] for n in data["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in data["edges"])


# ---------------------------------------------------------------- registration


def test_the_payload_is_registered_with_narrow_inputs() -> None:
    assert hb.BUILDERS["ideas"] is hi.build
    spec = hub_ui.PAGES["ideas"]
    assert spec.payloads == ("shell", "ideas") and spec.script in hub_ui.ASSETS
    assert hb.reads("ideas", "relation.decided") and hb.reads("ideas", "idea.proposed")
    assert hb.reads("ideas", "extraction.recorded")
    for quiet in ("runner.started", "task.opened", "feed.run", "watch.run", "xrun.recorded"):
        assert not hb.reads("ideas", quiet)


def test_the_acts_are_routed_as_the_cli_commands() -> None:
    routes = site_server.UI_IDEA_ROUTES
    assert {c for c, _ in routes.values()} == {
        "cli:relations confirm",
        "cli:relations reject",
        "cli:ideas confirm",
        "cli:ideas reject",
    }
    assert all(path in site_server._ROUTES for path in routes)


# ---------------------------------------------------------------- the acts


def test_the_proposing_session_cannot_decide_through_the_act(
    project: Project, agent: Actor, human: Actor, rich: dict[str, str]
) -> None:
    assert human.session == agent.session
    with pytest.raises(FactoryValidationError) as err:
        hi.confirm_relation_act(
            project, human, {"relation_id": rich["waiting"], "rationale": "looks right"}
        )
    assert err.value.issues[0].field == "actor"
    assert payload(project)["counts"]["relations"]["inferred"] == 1  # nothing was written


def test_a_decision_from_another_session_is_recorded(
    project: Project, decider: Actor, rich: dict[str, str]
) -> None:
    out = hi.confirm_relation_act(
        project, decider, {"relation_id": rich["waiting"], "rationale": "the quote supports it"}
    )
    assert out["decision"] == "confirm" and out["relation_id"] == rich["waiting"]
    counts = payload(project)["counts"]["relations"]
    assert counts["inferred"] == 0 and counts["confirmed"] == 2
    out = hi.reject_idea_act(project, decider, {"idea_id": rich["idea"], "rationale": "too vague"})
    assert out["decision"] == "reject"
    assert payload(project)["counts"]["ideas"]["rejected"] == 1


def test_the_act_needs_a_reason_and_refuses_a_stated_confirmation(
    project: Project, decider: Actor, rich: dict[str, str]
) -> None:
    with pytest.raises(FactoryValidationError) as err:
        hi.confirm_relation_act(project, decider, {"relation_id": rich["waiting"]})
    assert err.value.issues[0].field == "rationale"
    with pytest.raises(FactoryValidationError) as err:
        hi.confirm_relation_act(
            project, decider, {"relation_id": rich["stated"], "rationale": "checked"}
        )
    assert err.value.issues[0].reason == "only an inferred relation is confirmed"
    with pytest.raises(FactoryValidationError) as err:
        hi.reject_relation_act(project, decider, {"rationale": "no"})
    assert err.value.issues[0].field == "relation_id"


# ---------------------------------------------------------------- the page script


def test_the_page_writes_only_through_acts_and_only_when_served() -> None:
    from importlib import resources

    src = resources.files("factory.hub_ui").joinpath("pages/ideas.js").read_text(encoding="utf-8")
    assert "HUB.served" in src and "HUB.post(" in src
    for route in site_server.UI_IDEA_ROUTES:
        assert route in src
    assert "proposal" in src.lower()
