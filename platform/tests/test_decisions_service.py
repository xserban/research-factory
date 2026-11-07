"""The decisions service: suggest, select, list and view (slice 8, plan A3)."""

from __future__ import annotations

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.decisions import DecisionItem, DecisionLevel
from factory.model.screening import Channel
from factory.services import decisions as svc
from factory.services.context import Project
from factory.services.seeds import SeedRole, all_seeds
from tests.helpers import S2, SourcesFor, _setup

CRED = "crd_01JZ9Q3K5M7N8P0R2S4T6V8W0X"

ITEMS = (
    DecisionItem(item_id="I01", text="Exclude preprints", grounds=("prb_1",)),
    DecisionItem(item_id="I02", text="Keep preprints"),
    DecisionItem(item_id="I03", text="Exclude non-English"),
)


def _suggest(project: Project, agent: Actor, **over: object) -> str:
    args: dict[str, object] = {
        "level": DecisionLevel.PROTOCOL,
        "subject": "exclusions",
        "explanation": "The exclusions set what leaves the corpus.",
        "items": ITEMS,
    }
    args.update(over)
    return svc.suggest(project, agent, **args)  # type: ignore[arg-type]


def _fields(err: pytest.ExceptionInfo[FactoryValidationError]) -> list[tuple[str, str]]:
    return [(i.field, i.reason) for i in err.value.issues]


def _types(project: Project) -> list[str]:
    return [e.type for e in read_all(project.paths.events_dir, project.catalog)]


def test_suggest_records_and_lists_as_open(project: Project, agent: Actor) -> None:
    decision_id = _suggest(project, agent)
    assert decision_id.startswith("dec_")
    [row] = svc.list_decisions(project)
    assert (row.decision_id, row.state, row.items, row.selected) == (decision_id, "open", 3, 0)
    view = svc.view_decision(project, decision_id)
    assert [(i.item_id, i.status, i.origin) for i in view.items] == [
        ("I01", "proposed", "suggested"),
        ("I02", "proposed", "suggested"),
        ("I03", "proposed", "suggested"),
    ]
    assert view.items[0].grounds == ("prb_1",)
    assert view.selection is None


def test_suggest_refuses_a_human(project: Project, human: Actor) -> None:
    with pytest.raises(FactoryValidationError) as err:
        _suggest(project, human)
    assert _fields(err) == [("actor", "only an agent suggests a decision")]
    assert "decision.suggested" not in _types(project)


def test_suggest_refuses_duplicate_item_ids(project: Project, agent: Actor) -> None:
    items = (ITEMS[0], DecisionItem(item_id="I01", text="Again"))
    with pytest.raises(FactoryValidationError):
        _suggest(project, agent, items=items)
    assert svc.list_decisions(project) == []


def test_suggest_refuses_recommended_on_a_research_subject(project: Project, agent: Actor) -> None:
    items = (DecisionItem(item_id="I01", text="Use X", recommended=True),)
    with pytest.raises(FactoryValidationError):
        _suggest(project, agent, items=items)
    assert svc.list_decisions(project) == []
    _suggest(project, agent, subject="tooling", items=items)  # a technical subject may
    assert len(svc.list_decisions(project)) == 1


def test_suggest_refuses_unknown_and_superseded_supersedes(project: Project, agent: Actor) -> None:
    with pytest.raises(FactoryValidationError) as err:
        _suggest(project, agent, supersedes="dec_01JZ9Q3K5M7N8P0R2S4T6V8W0X")
    assert _fields(err) == [("supersedes", "unknown decision")]
    first = _suggest(project, agent)
    second = _suggest(project, agent, supersedes=first)
    with pytest.raises(FactoryValidationError) as again:
        _suggest(project, agent, supersedes=first)
    assert _fields(again) == [("supersedes", "already superseded")]
    states = {r.decision_id: r.state for r in svc.list_decisions(project)}
    assert states == {first: "superseded", second: "open"}
    assert svc.list_decisions(project, open_only=True)[0].decision_id == second


def test_suggest_refuses_text_naming_a_held_out_seed(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, random_works=0)
    [held, *_] = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    assert held.doi is not None
    before = _types(project)
    with pytest.raises(FactoryValidationError) as in_text:
        _suggest(project, agent, items=(DecisionItem(item_id="I01", text=f"Seed {held.doi}"),))
    assert _fields(in_text) == [("items.0.text", "names a held-out seed (R-20)")]
    with pytest.raises(FactoryValidationError) as in_grounds:
        _suggest(
            project,
            agent,
            items=(DecisionItem(item_id="I01", text="Fine", grounds=(held.seed_id,)),),
        )
    assert _fields(in_grounds) == [("items.0.grounds.0", "names a held-out seed (R-20)")]
    with pytest.raises(FactoryValidationError) as in_explanation:
        _suggest(project, agent, explanation=f"Because of {held.doi.upper()}")
    assert _fields(in_explanation) == [("explanation", "names a held-out seed (R-20)")]
    assert _types(project) == before


def test_select_validates_and_updates_statuses(
    project: Project, agent: Actor, human: Actor
) -> None:
    decision_id = _suggest(project, agent)
    event_id = svc.select(
        project, human, decision_id, ["I01"], ["Exclude theses"], " why ", Channel.CLI
    )
    assert event_id
    view = svc.view_decision(project, decision_id)
    assert view.state == "selected"
    assert {i.item_id: i.status for i in view.items} == {
        "A01": "added",
        "I01": "validated",
        "I02": "rejected",
        "I03": "rejected",
    }
    assert view.selection is not None
    assert (view.selection.note, view.selection.added, view.selection.channel) == (
        "why",
        ("Exclude theses",),
        "cli",
    )
    [row] = svc.list_decisions(project)
    assert (row.state, row.selected) == ("selected", 1)
    assert svc.list_decisions(project, open_only=True) == []


def test_select_refuses_an_agent_and_unknown_things(
    project: Project, agent: Actor, human: Actor
) -> None:
    decision_id = _suggest(project, agent)
    with pytest.raises(FactoryValidationError) as by_agent:
        svc.select(project, agent, decision_id, ["I01"], [], "", Channel.CLI)
    assert _fields(by_agent)[0][0] == "actor"
    with pytest.raises(FactoryValidationError) as unknown:
        svc.select(project, human, "dec_01JZ9Q3K5M7N8P0R2S4T6V8W0X", ["I01"], [], "", Channel.CLI)
    assert _fields(unknown) == [("decision_id", "unknown")]
    with pytest.raises(FactoryValidationError) as bad_item:
        svc.select(project, human, decision_id, ["I01", "I09"], [], "", Channel.CLI)
    assert _fields(bad_item) == [("selected.1", "not an item of this decision")]
    assert "decision.selected" not in _types(project)


def test_empty_selection_needs_a_note(project: Project, agent: Actor, human: Actor) -> None:
    decision_id = _suggest(project, agent)
    with pytest.raises(FactoryValidationError):
        svc.select(project, human, decision_id, [], [], "  ", Channel.CLI)
    assert "decision.selected" not in _types(project)
    svc.select(project, human, decision_id, [], [], "none of these fit", Channel.CLI)
    view = svc.view_decision(project, decision_id)
    assert {i.status for i in view.items} == {"rejected"}
    assert view.selection is not None and view.selection.note == "none of these fit"


def test_select_refuses_a_superseded_decision(project: Project, agent: Actor, human: Actor) -> None:
    first = _suggest(project, agent)
    svc.select(project, human, first, ["I01"], [], "", Channel.CLI)
    second = _suggest(project, agent, supersedes=first)
    with pytest.raises(FactoryValidationError) as err:
        svc.select(project, human, first, ["I02"], [], "", Channel.CLI)
    assert _fields(err) == [("decision_id", f"superseded by {second}")]
    old = svc.view_decision(project, first)
    assert old.state == "superseded" and old.superseded_by == second
    assert old.selection is not None and old.selection.selected == ("I01",)
    assert svc.view_decision(project, second).supersedes == first


def test_elicit_channel_needs_a_credential(project: Project, agent: Actor, human: Actor) -> None:
    decision_id = _suggest(project, agent)
    with pytest.raises(FactoryValidationError) as err:
        svc.select(project, human, decision_id, ["I01"], [], "", Channel.ELICIT)
    assert _fields(err)[0][0] == "channel"
    credentialed = human.model_copy(update={"credential": CRED, "session": S2})
    svc.select(project, credentialed, decision_id, ["I01"], [], "", Channel.ELICIT)
    view = svc.view_decision(project, decision_id)
    assert view.selection is not None and view.selection.channel == "elicit"


def test_reconstructed_flag_is_recorded(project: Project, agent: Actor, human: Actor) -> None:
    decision_id = _suggest(project, agent)
    svc.select(project, human, decision_id, ["I02"], [], "", Channel.CLI, reconstructed=True)
    view = svc.view_decision(project, decision_id)
    assert view.selection is not None and view.selection.reconstructed is True


def test_view_of_unknown_decision_is_refused(project: Project) -> None:
    with pytest.raises(FactoryValidationError) as err:
        svc.view_decision(project, "dec_01JZ9Q3K5M7N8P0R2S4T6V8W0X")
    assert _fields(err) == [("decision_id", "unknown")]


def test_list_filters_by_level(project: Project, agent: Actor) -> None:
    _suggest(project, agent)
    _suggest(project, agent, level=DecisionLevel.GOAL, subject="objective")
    assert [r.level for r in svc.list_decisions(project, DecisionLevel.GOAL)] == ["goal"]
    assert len(svc.list_decisions(project)) == 2
