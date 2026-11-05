"""The failed-directions registry (slice 6, plan XP-B task 6; acceptance 21; R-52, R-124). No test
sets or patches a hook list."""

# ruff: noqa: F401, F811

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.model.directions import Conditions, DirectionReason
from factory.model.hypotheses import DiscardReason, LeadInput, Trigger, TriggerKind
from factory.services.context import Project
from factory.services.directions import close_direction, direction_exists, registry_query
from factory.services.experiments import experiment_view
from factory.services.hypotheses import abandon_hypothesis, draft_hypothesis
from factory.services.leads import decide_lead, lead_view, record_lead
from tests.card_helpers import cw
from tests.evaluation_helpers import REFUTED, SUPPORTED, report_runs, unlocked
from tests.experiment_helpers import (
    COMMIT,
    XW,
    frozen_design,
    inject,
    raw_event,
    register_with_review,
    xw,
)
from tests.finder_helpers import MatchWorld, mw
from tests.hypothesis_helpers import (
    DRAFTER,
    HW,
    LEAD_AUTHOR,
    LEAD_TEXT,
    card_trigger,
    gw,
    hw,
    lead_input,
    make_spec,
)
from tests.lineage_helpers import ctr_a, ctr_b, lin, screened, world
from tests.test_reproduction import _repro


def _fields(err: pytest.ExceptionInfo[FactoryValidationError]) -> list[tuple[str, str]]:
    return [(i.field, i.reason) for i in err.value.issues]


def _by_id(project: Project, **kw: Any) -> dict[str, Any]:
    return {r.direction_id: r for r in registry_query(project, **kw).rows}


def test_empty_registry_on_a_fresh_project(project: Project) -> None:
    page = registry_query(project)
    assert (page.rows, page.total, page.next) == ([], 0, None)


def test_refuted_hypothesis_row_with_conditions(
    project: Project, human: Any, xw: XW, hw: HW, tmp_path: Path
) -> None:
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, REFUTED)
    rows = _by_id(project)
    row = rows[xw.hid]
    view = experiment_view(project, exp)
    assert view is not None
    assert (row.source_kind, row.reason) == ("hypothesis", "below-baseline")
    assert row.conditions == Conditions(
        e_version=view.e_version,
        datasets=("imagenet-dev", "imagenet-test"),
        gpu_hours_used="9",
        models=("model-critic", "model-drafter"),
        code_commit=COMMIT,
    )
    assert {xw.hid, hw.lead, exp, "ds:imagenet-test", hw.works[0]} <= set(row.keys)
    assert xw.hid in row.summary and "design " + view.e_version in row.summary
    assert row.text is None


def test_inconclusive_row_and_a_success_adds_none(
    project: Project, human: Any, xw: XW, tmp_path: Path
) -> None:
    from tests.test_multiverse import INCONCLUSIVE

    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, INCONCLUSIVE)
    assert _by_id(project)[xw.hid].reason == "inconclusive"


def test_rows_never_removed_after_later_success(
    project: Project, human: Any, xw: XW, hw: HW, tmp_path: Path
) -> None:
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, REFUTED)
    hid2, _ = draft_hypothesis(project, DRAFTER, make_spec(lead=hw.lead, rationale="again"))
    register_with_review(project, human, hid2)
    fresh = [
        {"name": "imagenet-dev", "version": "1", "sha256": "a" * 64, "role": "dev"},
        {"name": "imagenet-test2", "version": "1", "sha256": "c" * 64, "role": "confirmatory"},
    ]
    second = unlocked(project, human, XW(hid2, xw.rows), datasets=fresh)
    report_runs(project, human, tmp_path, second, SUPPORTED)  # a similar direction succeeds
    rows = _by_id(project)
    assert xw.hid in rows and hid2 not in rows  # the old row stays; success adds none
    project.index.rebuild()
    assert xw.hid in _by_id(project)


def test_abandoned_and_not_reproduced_rows(
    project: Project, human: Any, xw: XW, tmp_path: Path
) -> None:
    exp = frozen_design(project, human, xw)
    _repro(project, human, tmp_path, exp, xw.rows[0], {1: "50.0", 2: "50.0", 3: "50.0"})
    abandon_hypothesis(project, human, xw.hid, "budget-exhausted", "out of GPU time")  # type: ignore[arg-type]
    rows = _by_id(project)
    assert rows[xw.hid].reason == "compute-budget-exhausted"
    baseline = rows[f"{exp}:{xw.rows[0]}"]
    assert (baseline.source_kind, baseline.reason) == ("baseline", "baseline-not-reproduced")
    assert {xw.rows[0], exp, xw.hid} <= set(baseline.keys)
    assert baseline.conditions.e_version is not None and baseline.conditions.gpu_hours_used == "4.5"
    assert xw.rows[0] in baseline.summary


def test_superseded_before_evidence_is_not_failure(
    project: Project, human: Any, xw: XW, hw: HW
) -> None:
    hid2, _ = draft_hypothesis(
        project, DRAFTER, make_spec(lead=hw.lead, rationale="revised"), supersedes=hw.hid
    )
    assert registry_query(project).total == 0 and hid2


def test_each_source_appears_with_conditions_closed_and_lead(
    project: Project, human: Any, mw: MatchWorld
) -> None:
    lead = record_lead(project, LEAD_AUTHOR, lead_input(LEAD_TEXT, card_trigger(mw.ok)))
    decide_lead(project, human, lead, "discard", DiscardReason.PRIOR_FAILURE, "tried and failed")
    closed = close_direction(
        project,
        human,
        "Dense variants never fit the memory bound.",
        DirectionReason.INFEASIBLE,
        Conditions(models=("model-x",), gpu_hours_used="12"),
        [mw.ok, "pr:tasks"],
    )
    rows = _by_id(project, agent=True)
    assert (rows[lead].source_kind, rows[lead].reason) == ("lead", "discarded-lead")
    assert (rows[closed].source_kind, rows[closed].reason) == ("closed", "infeasible")
    assert rows[closed].conditions.models == ("model-x",)
    assert rows[closed].text is None  # an agent's answer carries no free text
    researcher = registry_query(project).rows
    assert [r.text for r in researcher if r.direction_id == closed] == [
        "Dense variants never fit the memory bound."
    ]


def test_query_by_card_idea_property_work(project: Project, human: Any, mw: MatchWorld) -> None:
    by_card = record_lead(project, LEAD_AUTHOR, lead_input(LEAD_TEXT, card_trigger(mw.ok)))
    decide_lead(project, human, by_card, "discard", DiscardReason.DUPLICATE, "same as before")
    idea = Trigger(kind=TriggerKind.IDEA, ref=mw.cw.idea)
    by_idea = record_lead(project, LEAD_AUTHOR, lead_input(LEAD_TEXT, idea))
    decide_lead(project, human, by_idea, "discard", DiscardReason.NOT_FALSIFIABLE, "vague")
    assert set(_by_id(project, keys=[mw.ok])) == {by_card}  # by card
    assert by_idea in _by_id(project, keys=[mw.cw.idea])  # by idea
    assert by_card in _by_id(project, keys=["pr:memory-scaling"])  # by property of the card
    with project.index.connect() as conn:
        subject = str(
            conn.execute(
                text("SELECT subject FROM cards WHERE card_id = :c"), {"c": mw.ok}
            ).scalar_one()
        )
    assert by_card in _by_id(project, keys=[subject])  # by the work the card is about
    assert registry_query(project, keys=["pr:unknown-key"]).rows == []
    both = registry_query(project, reasons=["discarded-lead"])
    assert {r.direction_id for r in both.rows} == {by_card, by_idea} and both.total == 2
    assert registry_query(project, reasons=["infeasible"]).rows == []


def test_paging(project: Project, human: Any, mw: MatchWorld) -> None:
    ids = []
    for i in range(3):
        ids.append(
            close_direction(
                project,
                human,
                f"Closed direction {i}.",
                DirectionReason.OTHER,
                Conditions(),
                [mw.ok],
            )
        )
    first = registry_query(project, limit=2)
    assert [r.direction_id for r in first.rows] == sorted(ids)[:2]
    assert first.total == 3 and first.next == sorted(ids)[1]
    rest = registry_query(project, limit=2, after=first.next)
    assert [r.direction_id for r in rest.rows] == sorted(ids)[2:] and rest.next is None
    with pytest.raises(FactoryValidationError) as err:
        registry_query(project, limit=0)
    assert _fields(err) == [("limit", "between 1 and 200")]
    with pytest.raises(FactoryValidationError) as err:
        registry_query(project, reasons=["nonsense"])
    assert _fields(err) == [("reasons", "unknown")]


def test_registry_feeds_prior(project: Project, human: Any, mw: MatchWorld) -> None:
    closed = close_direction(
        project,
        human,
        "Tried on every dense card.",
        DirectionReason.INFEASIBLE,
        Conditions(),
        [mw.ok],
    )
    later = record_lead(project, LEAD_AUTHOR, lead_input(LEAD_TEXT, card_trigger(mw.ok)))
    view = lead_view(project, later)
    assert view is not None and closed in view.prior  # no hook was patched


def test_dir_trigger_resolves_without_monkeypatch(
    project: Project, human: Any, mw: MatchWorld
) -> None:
    closed = close_direction(
        project, human, "Closed.", DirectionReason.OTHER, Conditions(), [mw.ok]
    )
    assert direction_exists(project, closed) is True
    good = Trigger(kind=TriggerKind.DIRECTION, ref=closed)
    lead = record_lead(project, LEAD_AUTHOR, lead_input(LEAD_TEXT, good))
    assert lead_view(project, lead) is not None
    with pytest.raises(FactoryValidationError) as err:
        record_lead(
            project,
            LEAD_AUTHOR,
            lead_input(
                LEAD_TEXT,
                Trigger(kind=TriggerKind.DIRECTION, ref="dir_01JZ9Q3K5M7N8P0R2S4T6V8WZZ"),
            ),
        )
    assert _fields(err) == [("triggers.0", "unknown")]
    # a hypothesis or lead id is not a closed direction
    assert direction_exists(project, "hyp_01JZ9Q3K5M7N8P0R2S4T6V8WZZ") is False


# --- Guards -------------------------------------------------------------------------------------


def test_close_direction_human_only(project: Project, human: Any, mw: MatchWorld) -> None:
    with pytest.raises(FactoryValidationError) as err:
        close_direction(project, DRAFTER, "Nope.", DirectionReason.OTHER, Conditions(), [mw.ok])
    assert _fields(err) == [("actor", "human-only")]
    assert registry_query(project).total == 0


def test_close_direction_validates(project: Project, human: Any, mw: MatchWorld) -> None:
    with pytest.raises(FactoryValidationError) as err:
        close_direction(project, human, " ", DirectionReason.OTHER, Conditions(), [])
    assert {f for f, _ in _fields(err)} >= {"text", "keys"}
    with pytest.raises(FactoryValidationError) as err:
        close_direction(
            project, human, "Fine.", DirectionReason.OTHER, Conditions(), [mw.ok, "pr:nonexistent"]
        )
    assert _fields(err) == [("keys.1", "unknown")]
    assert registry_query(project).total == 0


def test_a_forged_closure_changes_nothing(project: Project, human: Any, mw: MatchWorld) -> None:
    body = {
        "direction_id": "dir_01JZ9Q3K5M7N8P0R2S4T6V8WZZ",
        "text": "Forged.",
        "reason": "other",
        "conditions": {},
        "keys": [mw.ok],
    }
    agent_event = raw_event(project, "direction.closed", human, body).model_copy(
        update={"actor": DRAFTER, "input_blob": project.blobs.put_json({"x": 1})}
    )
    system_event = raw_event(project, "direction.closed", project.system_actor(), body)
    bad_event = raw_event(project, "direction.closed", human, {**body, "keys": []})
    for event in (agent_event, system_event, bad_event):
        inject(project, event)
    assert registry_query(project).total == 0
    project.index.rebuild()
    assert registry_query(project).total == 0
    inject(project, raw_event(project, "direction.closed", human, body))
    assert registry_query(project).total == 1  # the same body from a human is folded


def test_a_forged_evaluation_makes_no_row(
    project: Project, human: Any, xw: XW, tmp_path: Path
) -> None:
    exp = unlocked(project, human, xw)
    report_runs(project, human, tmp_path, exp, dict(list(SUPPORTED.items())[:5]))
    from factory.services.evaluation import recompute

    exact = recompute(project, xw.hid)
    assert exact is not None
    forged = {**exact.model_dump(mode="json"), "outcome": "refuted", "inputs_hash": "9" * 16}
    inject(project, raw_event(project, "hypothesis.evaluated", project.system_actor(), forged))
    assert registry_query(project).total == 0
    project.index.rebuild()
    assert registry_query(project).total == 0
