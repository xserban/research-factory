# ruff: noqa: F401, F811
"""Hub intuition payload and review act (page "Intuition"): states, caps, determinism, empties."""

from __future__ import annotations

import json
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.model.intuition import ConceptInput, UseBasisInput
from factory.services import hub_build as hb
from factory.services import hub_intuition as hi
from factory.services import hub_ui, site_server
from factory.services.concepts import define_concept, propose_concept_link
from factory.services.context import Project
from factory.services.interpretations import supersede_interpretation
from tests.intuition_helpers import (
    IWorld,
    ctr_a,
    ctr_b,
    iw,
    lin,
    reviewer,
    rows,
    screened,
    world,
)
from tests.test_interpretations_review import _agent_int


def build(project: Project) -> dict[str, Any]:
    return hi.build(hb.HubContext(project))


def _concept(project: Project, iw: IWorld) -> str:
    entry = ConceptInput.model_validate(
        {
            "name": "softmax attention",
            "text": "Attention normalised by a softmax.",
            "source": {"kind": "textbook", "citation": "Textbook, chapter 3"},
        }
    )
    cid = define_concept(project, iw.human, entry, approve_source=True)
    quote = iw.quote("s1.p2", "Unlike softmax attention")
    propose_concept_link(
        project, iw.writer, iw.source, cid, UseBasisInput.model_validate({"quote": quote})
    )
    return cid


def test_registered_with_a_page_and_narrow_inputs() -> None:
    assert "intuition" in hb.BUILDERS and "intuition" in hub_ui.PAGES
    assert hb.PAYLOAD_INPUTS["intuition"][0] != "*"
    assert hb.reads("intuition", "interpretation.reviewed")
    assert not hb.reads("intuition", "screening.decision")
    assert "/ui/act/intuition-review" in site_server.UI_INTUITION_ROUTES


def test_the_empty_world_says_what_is_missing(project: Project) -> None:
    data = build(project)
    assert data["ready"] is True and data["empty"] is True
    assert set(hi.METHODS) <= set(data["methods"])
    assert "rf-intuition" in data["producer"]
    assert data["counts"]["unreviewed"] == 0 and data["counts"]["concepts"] == 0
    assert data["queue"] == {"items": [], "omitted": 0}
    assert data["reviewed"] == {"items": [], "omitted": 0}
    assert data["concepts"]["items"] == []


def test_every_state_is_listed_and_labelled(project: Project, iw: IWorld) -> None:
    waiting = _agent_int(project, iw, iw.idea1)
    right = _agent_int(project, iw, iw.idea2)
    wrong = _agent_int(project, iw, iw.source)
    gone = _agent_int(project, iw, iw.other)
    hi.act_review(project, iw.human, {"interpretation_id": right, "verdict": "reviewed"})
    hi.act_review(
        project,
        iw.human,
        {"interpretation_id": wrong, "verdict": "wrong", "note": "conflates two modules"},
    )
    supersede_interpretation(project, iw.human, gone, "A replacement.", [iw.quote()])
    data = build(project)
    counts = data["counts"]
    assert (counts["unreviewed"], counts["reviewed"], counts["wrong"], counts["superseded"]) == (
        2,  # the waiting one and the human's replacement
        1,
        1,
        1,
    )
    assert data["empty"] is False
    card = next(i for i in data["queue"]["items"] if i["id"] == waiting)
    assert len(data["queue"]["items"]) == 2
    assert card["id"] == waiting and card["class"] == "interpretation"
    assert card["label"] == "interpretation · unreviewed" and card["author"] == "agent"
    assert card["subject_kind"] == "idea" and card["subject_name"] == "linear attention"
    assert card["session"] == iw.writer.session and card["review"] is None
    [src] = card["sources"]
    assert src["anchor"] == "s1.p4" and src["quote"] == "very long sequences degrade"
    assert "very long sequences degrade" in src["paragraph"]
    done = {i["id"]: i for i in data["reviewed"]["items"]}
    assert set(done) == {right, wrong}
    assert done[wrong]["review"]["note"] == "conflates two modules"
    assert done[wrong]["state"] == "wrong" and done[right]["review"]["state"] == "reviewed"
    assert done[wrong]["subject_kind"] == "paper"


def test_caps_report_the_omitted_counts(
    project: Project, iw: IWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    _agent_int(project, iw, iw.idea1)
    _agent_int(project, iw, iw.idea2)
    _agent_int(project, iw, iw.source)
    monkeypatch.setattr(hi, "QUEUE_CAP", 2)
    data = build(project)
    assert len(data["queue"]["items"]) == 2 and data["queue"]["omitted"] == 1
    assert data["counts"]["unreviewed"] == 3


def test_concepts_list_the_ideas_that_use_them(project: Project, iw: IWorld) -> None:
    cid = _concept(project, iw)
    data = build(project)
    assert data["empty"] is False and data["counts"]["concepts"] == 1
    [concept] = data["concepts"]["items"]
    assert concept["id"] == cid and concept["name"] == "softmax attention"
    assert concept["source"] == "Textbook, chapter 3"
    assert [u["kind"] for u in concept["ideas"]] == ["paper"]


def test_the_payload_is_deterministic(project: Project, iw: IWorld) -> None:
    _agent_int(project, iw, iw.idea1)
    _agent_int(project, iw, iw.idea2)
    _concept(project, iw)
    assert json.dumps(build(project), sort_keys=True) == json.dumps(build(project), sort_keys=True)


def test_the_act_records_a_review_and_refuses_the_authors_session(
    project: Project, iw: IWorld
) -> None:
    iid = _agent_int(project, iw, iw.idea1)
    before = len(rows(project, "SELECT 1 FROM events WHERE type LIKE 'interpretation.%'"))
    relay = iw.human.model_copy(update={"session": iw.writer.session})
    with pytest.raises(FactoryValidationError) as e:
        hi.act_review(project, relay, {"interpretation_id": iid, "verdict": "reviewed"})
    assert e.value.issues[0].field == "actor"
    assert len(rows(project, "SELECT 1 FROM events WHERE type LIKE 'interpretation.%'")) == before
    out = hi.act_review(project, iw.human, {"interpretation_id": iid, "verdict": "reviewed"})
    assert out["verdict"] == "reviewed" and str(out["event_id"])
    assert build(project)["counts"]["reviewed"] == 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"interpretation_id": "int_X", "verdict": "accepted"},
        {"interpretation_id": "", "verdict": "reviewed"},
        {"interpretation_id": "int_X", "verdict": "wrong", "note": 3},
    ],
)
def test_the_act_validates_its_input_and_writes_nothing(
    project: Project, iw: IWorld, body: dict[str, Any]
) -> None:
    before = len(rows(project, "SELECT 1 FROM events"))
    with pytest.raises(FactoryValidationError):
        hi.act_review(project, iw.human, body)
    assert len(rows(project, "SELECT 1 FROM events")) == before


def test_a_wrong_verdict_needs_a_note(project: Project, iw: IWorld) -> None:
    iid = _agent_int(project, iw, iw.idea1)
    with pytest.raises(FactoryValidationError) as e:
        hi.act_review(project, iw.human, {"interpretation_id": iid, "verdict": "wrong"})
    assert e.value.issues[0].field == "note"
