"""The researcher's balance of a sheet and the lead guard (spar night N4, ruling 7 and 8)."""

# ruff: noqa: F811
import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.hypotheses import LeadInput, Trigger, TriggerKind
from factory.model.sheets import SheetBalanceRecorded
from factory.services import sheets as sh
from factory.services.chat_candidates import CandidateInput as C
from factory.services.context import Project
from factory.services.leads import list_leads, record_lead
from factory.services.selection import SelectionSpec
from tests.extraction_helpers import (
    screened,  # noqa: F401
    world,  # noqa: F401
)

ANCHOR, QUOTE = "s3.p1", "Lorem ipsum"


def _arg(work: str, stance: str) -> sh.ArgumentInput:
    return sh.ArgumentInput(stance, work, ANCHOR, QUOTE, "it fails", "moderate")


def _open(project: Project, agent: Actor, world: list[str], mode: str = "prepare") -> str:
    works = sorted(world)
    proposals = [
        C(works[0], "claims", "against", ANCHOR, QUOTE),
        C(works[1], "keyword", "for", ANCHOR, QUOTE),
    ]
    payload = sh.open_sheet(
        project,
        agent,
        "Reflection helps",
        SelectionSpec(),
        proposals,
        mode=mode,  # type: ignore[arg-type]
    )
    return payload.sheet_id


def _close_both(project: Project, agent: Actor, other: Actor, world: list[str], sheet: str) -> None:
    work = sorted(world)[0]
    sh.record_arguments(project, agent, sheet, [_arg(work, "against")])
    sh.close_section(project, agent, sheet, "against")
    sh.record_arguments(project, other, sheet, [_arg(work, "for")])
    sh.close_section(project, other, sheet, "for")


def _count(project: Project, table: str) -> int:
    project.index.sync()
    with project.index.connect() as conn:
        return int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())


def _lead(sheet: str) -> LeadInput:
    return LeadInput(text="an idea", triggers=(Trigger(kind=TriggerKind.SHEET, ref=sheet),))


def test_balance_is_human_only_in_the_service(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, world: list[str]
) -> None:
    sheet = _open(project, agent, world)
    _close_both(project, agent, agent_other, world, sheet)
    with pytest.raises(FactoryValidationError) as err:
        sh.record_balance(project, agent, sheet, "mostly for")
    assert err.value.issues[0].field == "actor"
    assert _count(project, "sheet_balances") == 0
    sh.record_balance(project, human, sheet, "mostly for", lean="for", note="need replication")
    assert _count(project, "sheet_balances") == 1


def test_balance_refused_before_both_sections_closed(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    sheet = _open(project, agent, world)
    with pytest.raises(FactoryValidationError) as err:
        sh.record_balance(project, human, sheet, "too early")
    assert err.value.issues[0].field == "sheet_id" and "close" in err.value.issues[0].reason
    sh.record_arguments(project, agent, sheet, [_arg(sorted(world)[0], "against")])
    sh.close_section(project, agent, sheet, "against")
    with pytest.raises(FactoryValidationError):  # for still open
        sh.record_balance(project, human, sheet, "still early")
    assert _count(project, "sheet_balances") == 0


def test_balance_input_is_validated(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, world: list[str]
) -> None:
    sheet = _open(project, agent, world)
    _close_both(project, agent, agent_other, world, sheet)
    for bad, field in (
        (dict(body=" "), "text"),
        (dict(body="x" * 4001), "text"),
        (dict(body="ok", lean="yes"), "lean"),
        (dict(body="ok", note="x" * 1001), "note"),
    ):
        with pytest.raises(FactoryValidationError) as err:
            sh.record_balance(project, human, sheet, **bad)  # type: ignore[arg-type]
        assert err.value.issues[0].field == field
    with pytest.raises(FactoryValidationError) as err:
        sh.record_balance(project, human, "sht_NOPE", "x")
    assert err.value.issues[0].field == "sheet_id"
    assert _count(project, "sheet_balances") == 0


def test_latest_balance_stands_and_history_is_kept(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, world: list[str]
) -> None:
    sheet = _open(project, agent, world)
    _close_both(project, agent, agent_other, world, sheet)
    assert sh.view_sheet(project, sheet).balance is None
    sh.record_balance(project, human, sheet, "first", lean="mixed")
    sh.record_balance(project, human, sheet, "second", lean="for")
    view = sh.view_sheet(project, sheet)
    assert view.balance is not None
    assert (view.balance.text, view.balance.lean, view.balance_history) == ("second", "for", 2)
    assert _count(project, "sheet_balances") == 2


def test_projection_ignores_a_hand_written_agent_balance(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, world: list[str]
) -> None:
    sheet = _open(project, agent, world)
    _close_both(project, agent, agent_other, world, sheet)
    forged = SheetBalanceRecorded(sheet_id=sheet, text="an agent's verdict")
    blob = project.blobs.put_json({"forged": True})
    with project.index.exclusive():
        project.record(
            [project.events.make("sheet.balance_recorded", forged, agent, input_blob=blob)]
        )
    assert _count(project, "sheet_balances") == 0
    assert sh.view_sheet(project, sheet).balance is None


def test_projection_ignores_a_balance_before_the_sections_close(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    sheet = _open(project, agent, world)
    forged = SheetBalanceRecorded(sheet_id=sheet, text="early")
    with project.index.exclusive():
        project.record([project.events.make("sheet.balance_recorded", forged, human)])
    assert _count(project, "sheet_balances") == 0


def test_rebuild_keeps_the_balances(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, world: list[str]
) -> None:
    sheet = _open(project, agent, world)
    _close_both(project, agent, agent_other, world, sheet)
    sh.record_balance(project, human, sheet, "one")
    sh.record_balance(project, human, sheet, "two", lean="against")
    before = sh.view_sheet(project, sheet)
    project.index.rebuild()
    assert sh.view_sheet(project, sheet) == before


def test_lead_guard_refuses_explore_open_and_unbalanced_sheets(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, world: list[str]
) -> None:
    explore = _open(project, agent, world, mode="explore")
    _close_both(project, agent, agent_other, world, explore)
    sh.record_balance(project, human, explore, "balanced")
    with pytest.raises(FactoryValidationError) as err:
        record_lead(project, agent, _lead(explore))
    assert err.value.issues[0].field == "triggers.0" and "prepare" in err.value.issues[0].reason

    opened = _open(project, agent, world)
    with pytest.raises(FactoryValidationError) as err:
        record_lead(project, agent, _lead(opened))
    assert "closed" in err.value.issues[0].reason

    nobalance = _open(project, agent, world)
    _close_both(project, agent, agent_other, world, nobalance)
    with pytest.raises(FactoryValidationError) as err:
        record_lead(project, agent, _lead(nobalance))
    assert "balance" in err.value.issues[0].reason

    with pytest.raises(FactoryValidationError):
        record_lead(project, agent, _lead("sht_01JZ9Q3K5M7N8P0R2S4T6V8W0X"))
    assert list_leads(project) == []


def test_lead_guard_accepts_a_balanced_prepare_sheet(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, world: list[str]
) -> None:
    sheet = _open(project, agent, world)
    _close_both(project, agent, agent_other, world, sheet)
    sh.record_balance(project, human, sheet, "the case is mixed", lean="mixed")
    lead_id = record_lead(project, agent, _lead(sheet))
    assert [v.lead_id for v in list_leads(project)] == [lead_id]
    project.index.rebuild()
    assert [v.lead_id for v in list_leads(project)] == [lead_id]


def test_projection_ignores_a_lead_citing_a_sheet_that_breaks_the_guard(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, world: list[str]
) -> None:
    from factory.model.hypotheses import LeadRecorded

    sheet = _open(project, agent, world)
    _close_both(project, agent, agent_other, world, sheet)  # no balance
    forged = LeadRecorded(
        lead_id="led_" + "0" * 26, text="x", triggers=_lead(sheet).triggers, keys=(sheet,)
    )
    blob = project.blobs.put_json({"forged": True})
    with project.index.exclusive():
        project.record([project.events.make("lead.recorded", forged, agent, input_blob=blob)])
    assert list_leads(project) == []


def test_old_lead_events_without_a_sheet_trigger_stay_valid(project: Project) -> None:
    from factory.model.hypotheses import LeadRecorded

    payload = LeadRecorded.model_validate(
        {
            "lead_id": "led_" + "0" * 26,
            "text": "old",
            "triggers": [{"kind": "work", "ref": "rf:nobody2020-nothing-1-00000000"}],
        }
    )
    assert payload.triggers[0].kind is TriggerKind.WORK
