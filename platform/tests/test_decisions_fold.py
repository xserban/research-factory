"""Fold of decision.suggested and decision.selected (slice 8, plan A2)."""

from typing import Any

from sqlalchemy import text

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.model.decisions import (
    DecisionItem,
    DecisionLevel,
    DecisionSelected,
    DecisionSuggested,
)
from factory.model.screening import Channel
from factory.services.context import Project
from factory.services.project import init_project
from tests.helpers import S2, SESSION

DEC = "dec_01JZ9Q3K5M7N8P0R2S4T6V8W0X"
DEC2 = "dec_01JZ9Q3K5M7N8P0R2S4T6V8W0Y"
CRED = "crd_01JZ9Q3K5M7N8P0R2S4T6V8W0X"

Rows = list[tuple[Any, ...]]


def suggest_payload(decision_id: str = DEC, supersedes: str | None = None) -> DecisionSuggested:
    return DecisionSuggested(
        decision_id=decision_id,
        level=DecisionLevel.PROTOCOL,
        subject="criteria-exclusion",
        explanation="The exclusion criteria set what leaves the corpus.",
        items=(
            DecisionItem(item_id="I01", text="Exclude preprints", grounds=("prb_1",)),
            DecisionItem(item_id="I02", text="Keep preprints"),
            DecisionItem(item_id="I03", text="Exclude non-English"),
        ),
        supersedes=supersedes,
    )


def write(project: Project, actor: Actor, type_: str, payload: Any) -> None:
    blob = project.blobs.put_json({}) if actor.kind == "agent" else None
    project.record([project.events.make(type_, payload, actor, input_blob=blob)])


def tables(project: Project) -> tuple[Rows, Rows]:
    with project.index.connect() as conn:
        decisions = conn.execute(
            text(
                "SELECT decision_id, level, subject, supersedes, superseded_by, actor "
                "FROM decision_sets ORDER BY decision_id"
            )
        ).all()
        items = conn.execute(
            text(
                "SELECT decision_id, item_id, text, grounds, recommended, origin, status "
                "FROM decision_items ORDER BY decision_id, item_id"
            )
        ).all()
    return [tuple(r) for r in decisions], [tuple(r) for r in items]


def statuses(project: Project, decision_id: str = DEC) -> dict[str, str]:
    return {str(r[1]): str(r[6]) for r in tables(project)[1] if r[0] == decision_id}


def select(project: Project, human: Actor, **over: Any) -> None:
    body: dict[str, Any] = {"decision_id": DEC, "selected": ("I01",)}
    body.update(over)
    write(project, human, "decision.selected", DecisionSelected(**body))


def test_suggestion_folds_items_as_proposed(project: Project, agent: Actor) -> None:
    write(project, agent, "decision.suggested", suggest_payload())
    decisions, items = tables(project)
    assert decisions == [(DEC, "protocol", "criteria-exclusion", None, None, "screener-a")]
    assert [(r[1], r[3], r[4], r[5], r[6]) for r in items] == [
        ("I01", '["prb_1"]', 0, "suggested", "proposed"),
        ("I02", "[]", 0, "suggested", "proposed"),
        ("I03", "[]", 0, "suggested", "proposed"),
    ]


def test_suggestion_by_a_human_changes_nothing(project: Project, human: Actor) -> None:
    write(project, human, "decision.suggested", suggest_payload())
    assert tables(project) == ([], [])


def test_duplicate_decision_id_changes_nothing(project: Project, agent: Actor) -> None:
    write(project, agent, "decision.suggested", suggest_payload())
    before = tables(project)
    other = DecisionSuggested(
        decision_id=DEC,
        level=DecisionLevel.GOAL,
        subject="other",
        explanation="A second suggestion under the same id.",
        items=(DecisionItem(item_id="I01", text="Different"),),
    )
    write(project, agent, "decision.suggested", other)
    assert tables(project) == before


def test_supersedes_unknown_decision_changes_nothing(project: Project, agent: Actor) -> None:
    write(project, agent, "decision.suggested", suggest_payload(DEC2, supersedes=DEC))
    assert tables(project) == ([], [])


def test_supersession_marks_the_old_one_and_keeps_its_rows(
    project: Project, agent: Actor, human: Actor
) -> None:
    write(project, agent, "decision.suggested", suggest_payload())
    select(project, human)
    write(project, agent, "decision.suggested", suggest_payload(DEC2, supersedes=DEC))
    decisions, items = tables(project)
    assert [(r[0], r[3], r[4]) for r in decisions] == [(DEC, None, DEC2), (DEC2, DEC, None)]
    assert statuses(project, DEC) == {"I01": "validated", "I02": "rejected", "I03": "rejected"}
    assert len([r for r in items if r[0] == DEC2]) == 3


def test_already_superseded_decision_cannot_be_superseded_again(
    project: Project, agent: Actor
) -> None:
    write(project, agent, "decision.suggested", suggest_payload())
    write(project, agent, "decision.suggested", suggest_payload(DEC2, supersedes=DEC))
    before = tables(project)
    third = "dec_01JZ9Q3K5M7N8P0R2S4T6V8W0Z"
    write(project, agent, "decision.suggested", suggest_payload(third, supersedes=DEC))
    assert tables(project) == before


def test_selection_validates_rejects_and_adds(project: Project, agent: Actor, human: Actor) -> None:
    write(project, agent, "decision.suggested", suggest_payload())
    select(project, human, selected=("I02",), added=("Exclude theses", "Exclude posters"))
    assert statuses(project) == {
        "A01": "added",
        "A02": "added",
        "I01": "rejected",
        "I02": "validated",
        "I03": "rejected",
    }
    origins = {str(r[1]): str(r[5]) for r in tables(project)[1]}
    assert origins["A01"] == "added" and origins["I01"] == "suggested"


def test_selection_by_an_agent_changes_nothing(project: Project, agent: Actor) -> None:
    write(project, agent, "decision.suggested", suggest_payload())
    before = tables(project)
    write(project, agent, "decision.selected", DecisionSelected(decision_id=DEC, selected=("I01",)))
    assert tables(project) == before


def test_forged_elicit_changes_nothing(project: Project, agent: Actor, human: Actor) -> None:
    """Channel `elicit` needs a human with a credential; a human without one is forged."""
    write(project, agent, "decision.suggested", suggest_payload())
    before = tables(project)
    select(project, human, channel=Channel.ELICIT)
    assert tables(project) == before
    credentialed = human.model_copy(update={"credential": CRED})
    select(project, credentialed, channel=Channel.ELICIT)
    assert statuses(project)["I01"] == "validated"


def test_relay_barred_in_systematic_changes_nothing(
    settings: Settings, clock: FixedClock, agent: Actor
) -> None:
    project = init_project(settings, "sys", "systematic", session=SESSION, clock=clock)
    write(project, agent, "decision.suggested", suggest_payload())
    before = tables(project)
    relay = Actor(kind="human", id="obd", user="obd", session=S2, credential=CRED)
    select(project, relay, channel=Channel.MCP)
    assert tables(project) == before
    select(project, relay, channel=Channel.ELICIT)
    assert statuses(project)["I01"] == "validated"


def test_unknown_item_changes_nothing(project: Project, agent: Actor, human: Actor) -> None:
    write(project, agent, "decision.suggested", suggest_payload())
    before = tables(project)
    select(project, human, selected=("I01", "I09"))
    assert tables(project) == before


def test_unknown_decision_changes_nothing(project: Project, human: Actor) -> None:
    select(project, human)
    assert tables(project) == ([], [])


def test_superseded_decision_cannot_be_selected(
    project: Project, agent: Actor, human: Actor
) -> None:
    write(project, agent, "decision.suggested", suggest_payload())
    write(project, agent, "decision.suggested", suggest_payload(DEC2, supersedes=DEC))
    before = tables(project)
    select(project, human)
    assert tables(project) == before
    select(project, human, decision_id=DEC2, selected=("I03",))
    assert statuses(project, DEC2)["I03"] == "validated"


def test_later_selection_rederives_statuses(project: Project, agent: Actor, human: Actor) -> None:
    write(project, agent, "decision.suggested", suggest_payload())
    select(project, human, selected=("I01",), added=("First extra",))
    select(project, human, selected=("I02", "I03"), added=("Second extra",))
    decisions, items = tables(project)
    assert statuses(project) == {
        "A01": "added",
        "I01": "rejected",
        "I02": "validated",
        "I03": "validated",
    }
    assert [r[2] for r in items if r[1] == "A01"] == ["Second extra"]
    assert len(decisions) == 1


def test_empty_selection_with_a_note_rejects_everything(
    project: Project, agent: Actor, human: Actor
) -> None:
    write(project, agent, "decision.suggested", suggest_payload())
    select(project, human, selected=(), note="none fits")
    assert set(statuses(project).values()) == {"rejected"}


def test_rebuild_is_deterministic(project: Project, agent: Actor, human: Actor) -> None:
    write(project, agent, "decision.suggested", suggest_payload())
    select(project, human, selected=("I02",), added=("Extra",))
    select(project, human, selected=("I09",))  # refused
    write(project, agent, "decision.suggested", suggest_payload(DEC2, supersedes=DEC))
    select(project, human, decision_id=DEC2, selected=("I01",))
    write(
        project, agent, "decision.selected", DecisionSelected(decision_id=DEC2, selected=("I02",))
    )
    before, digest = tables(project), project.index.state_hash()
    project.index.rebuild()
    assert tables(project) == before
    assert project.index.state_hash() == digest
