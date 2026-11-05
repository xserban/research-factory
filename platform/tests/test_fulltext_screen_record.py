"""screen_record at full text: anchor-verified quotes, stage-keyed supersession (plan 2C)."""

import json
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from factory.events.envelope import Actor
from factory.model.protocol import Criterion, ScreeningPlan, ScreeningStage
from factory.model.screening import PassLabel, ScreeningItem, Verdict
from factory.model.task import Task, TaskStatus
from factory.services import screening
from factory.services.calibration import draw_calibration
from factory.services.context import Project
from factory.services.conversions import conversion_manifest
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.screening import (
    ScreenBatch,
    ScreenBatchContent,
    live_decisions,
    screen_next,
    screen_record,
)
from factory.services.tasks import get_task
from factory.sources.registry import SourceFactory
from tests.document_helpers import (
    ARTICLE,
    StubConverter,
    fetched_document,
    make_registry,
    promoted_works,
    run_convert,
)
from tests.fulltext_helpers import _include_all
from tests.helpers import _of_type, _setup
from tests.screening_helpers import _batch as ta_batch
from tests.screening_helpers import _decide, _draw

FT = ScreeningStage.FULL_TEXT
TA = ScreeningStage.TITLE_ABSTRACT
SourcesFor = Callable[..., Mapping[str, SourceFactory]]

EXTRA = ("s1.p3", "Dolor footnote text.")  # s1.p3 exists only after the inserted paragraph
INSERTED = "Zebra unique paragraph."
WITH_EXTRA = ARTICLE.replace(
    b'</div>\n</section>\n<section class="ltx_section" id="S2">',
    b'</div>\n<div class="ltx_para"><p class="ltx_p">' + INSERTED.encode() + b"</p></div>\n"
    b'</section>\n<section class="ltx_section" id="S2">',
    1,
)
assert WITH_EXTRA != ARTICLE
PARAGRAPH = ("s3.p1", "Lorem ipsum dolor sit amet.")
OTHER = ("s1.p1", "Ut enim ad minim veniam")


def _criterion(cid: str, stage: ScreeningStage, priority: int) -> Criterion:
    return Criterion(
        id=cid,
        parent="NG03",
        statement=f"statement {cid}",
        rule="exclude it",
        applies_at=stage,
        priority=priority,
    )


@pytest.fixture
def batch(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> ScreenBatch:
    """A claimed full-text calibration batch of pass A: every record pins a converted ARTICLE.

    The protocol declares a full-text plan, EX04 (full text only) and EX05 (either) beside the
    title/abstract-only EX01-EX03."""
    _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    current = current_protocol(project)
    assert current is not None
    plan = ScreeningPlan(
        passes=2,
        dual_sample=1.0,
        kappa_floor=0.7,
        calibration_size=3,
        reviewers=current.spec.screening.reviewers,
    )
    spec = current.spec.model_copy(
        update={
            "full_text_screening": plan,
            "criteria": (
                *current.spec.criteria,
                _criterion("EX04", FT, 4),
                _criterion("EX05", ScreeningStage.EITHER, 5),
            ),
        }
    )
    amend_protocol(project, agent, spec, reason="declare full text", semantic=True, effects={})
    amended = current_protocol(project)
    assert amended is not None
    _draw(project)
    from factory.services.screening import open_pass

    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    _include_all(project, agent, human, amended.protocol_id)
    # Every second promoted work (sorted) has an extra paragraph, anchor s1.p3, in its conversion.
    for position, work in enumerate(sorted(promoted_works(project))):
        fetched_document(project, work, WITH_EXTRA if position % 2 else ARTICLE)
    run_convert(project, make_registry(StubConverter()))
    draw_calibration(project, project.system_actor(), random_seed=3, stage=FT)
    served = screen_next(project, agent, PassLabel.A, stage=FT).batch
    assert served is not None and served.stage is FT and len(served.records) >= 3
    return served


def _item(
    record: Mapping[str, Any],
    anchor: str | None = PARAGRAPH[0],
    quote: str = PARAGRAPH[1],
    verdict: Verdict = Verdict.INCLUDE,
    criterion: str | None = None,
    rationale: str = "it fits",
) -> ScreeningItem:
    return ScreeningItem(
        work_id=str(record["work_id"]),
        verdict=verdict,
        criterion=criterion,
        quote=quote,
        rationale=rationale,
        anchor=anchor,
    )


def _fields(project: Project, agent: Actor, batch: ScreenBatch, items: list[ScreeningItem]) -> Any:
    return screen_record(project, agent, batch.task_id, items)


def _ft_live(project: Project) -> list[Any]:
    return live_decisions(project, PassLabel.A, stage=FT)


def test_valid_item_written_with_anchor_and_conversion(
    project: Project, agent: Actor, batch: ScreenBatch
) -> None:
    record = batch.records[0]
    result = screen_record(project, agent, batch.task_id, [_item(record)])
    assert result.rejected == [] and len(result.written) == 1
    [decision] = _ft_live(project)
    assert decision.stage is FT
    assert decision.anchor == PARAGRAPH[0]
    assert decision.conversion_id == record["conversion_id"]
    assert decision.work_id == record["work_id"]
    assert live_decisions(project, PassLabel.A, stage=TA) != _ft_live(project)


def test_quote_at_wrong_anchor_rejected(project: Project, agent: Actor, batch: ScreenBatch) -> None:
    record = batch.records[0]
    result = screen_record(
        project, agent, batch.task_id, [_item(record, anchor=OTHER[0], quote=PARAGRAPH[1])]
    )
    assert result.written == []
    [error] = result.rejected
    assert [(i.field, i.reason) for i in error.issues] == [
        ("items.0.quote", "is not in the cited anchor")
    ]
    assert _ft_live(project) == []


def test_quote_spanning_cells_rejected(project: Project, agent: Actor, batch: ScreenBatch) -> None:
    record = batch.records[0]
    result = screen_record(
        project, agent, batch.task_id, [_item(record, anchor="t1", quote="Lorem 1 2")]
    )
    assert result.written == []
    assert [i.field for i in result.rejected[0].issues] == ["items.0.quote"]
    ok = screen_record(project, agent, batch.task_id, [_item(record, anchor="t1", quote="Lorem")])
    assert len(ok.written) == 1


def test_anchor_missing_from_conversion_rejected(
    project: Project, agent: Actor, batch: ScreenBatch
) -> None:
    result = screen_record(project, agent, batch.task_id, [_item(batch.records[0], anchor="s9.p9")])
    assert result.written == []
    assert [i.field for i in result.rejected[0].issues] == ["items.0.anchor"]


def test_item_without_anchor_rejected_at_full_text(
    project: Project, agent: Actor, batch: ScreenBatch
) -> None:
    result = screen_record(project, agent, batch.task_id, [_item(batch.records[0], anchor=None)])
    assert result.written == []
    [issue] = result.rejected[0].issues
    assert issue.field == "items.0.anchor" and "required" in issue.reason


def test_anchor_rejected_at_title_abstract(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ta = ta_batch(project, agent, human, mock_sources)
    record = ta.records[0]
    item = ScreeningItem(
        work_id=str(record["work_id"]),
        verdict=Verdict.INCLUDE,
        quote=str(record["title"]),
        rationale="it fits",
        anchor="s1",
    )
    result = screen_record(project, agent, ta.task_id, [item])
    assert result.written == []
    [issue] = result.rejected[0].issues
    assert (issue.field, issue.reason) == ("items.0.anchor", "is only for full-text screening")


def test_title_abstract_only_criterion_rejected_at_full_text(
    project: Project, agent: Actor, batch: ScreenBatch
) -> None:
    assert {c["id"] for c in batch.criteria} == {"EX04", "EX05"}
    record = batch.records[0]
    bad = _item(record, verdict=Verdict.EXCLUDE, criterion="EX01")
    result = screen_record(project, agent, batch.task_id, [bad])
    assert result.written == []
    assert [i.field for i in result.rejected[0].issues] == ["items.0.criterion"]
    for cid in ("EX04", "EX05"):
        good = _item(record, verdict=Verdict.EXCLUDE, criterion=cid)
        assert len(screen_record(project, agent, batch.task_id, [good]).written) == 1


def test_valid_items_survive_invalid_neighbours(
    project: Project, agent: Actor, batch: ScreenBatch
) -> None:
    r0, r1, r2 = batch.records[:3]
    items = [_item(r0), _item(r1, anchor="s9.p9"), _item(r2, anchor=OTHER[0], quote=OTHER[1])]
    result = screen_record(project, agent, batch.task_id, items)
    assert [e.index for e in result.rejected] == [1]
    assert len(result.written) == 2
    assert {d.work_id for d in _ft_live(project)} == {r0["work_id"], r2["work_id"]}


def test_exclude_still_names_ex_criterion_and_rationale(
    project: Project, agent: Actor, batch: ScreenBatch
) -> None:
    record = batch.records[0]
    with pytest.raises(ValidationError):
        _item(record, verdict=Verdict.EXCLUDE, criterion=None)
    with pytest.raises(ValidationError):
        _item(record, verdict=Verdict.EXCLUDE, criterion="EX04", rationale="")
    with pytest.raises(ValidationError):
        _item(record, verdict=Verdict.CANNOT_ASSESS, criterion=None)
    # Built without validation, the service still refuses the item.
    bare = ScreeningItem.model_construct(
        work_id=str(record["work_id"]),
        verdict=Verdict.EXCLUDE,
        criterion=None,
        quote=PARAGRAPH[1],
        rationale="why",
        anchor=PARAGRAPH[0],
    )
    result = screen_record(project, agent, batch.task_id, [bare])
    assert result.written == [] and result.rejected


def test_decision_supersedes_prior_in_same_pass_and_stage(
    project: Project, agent: Actor, batch: ScreenBatch
) -> None:
    record = batch.records[0]
    work = str(record["work_id"])
    protocol_id = batch.protocol_id
    ta_id = _decide(project, agent, work, "A", "screening", "include", None, protocol_id)
    first = screen_record(project, agent, batch.task_id, [_item(record)])
    second = screen_record(
        project,
        agent,
        batch.task_id,
        [_item(record, verdict=Verdict.EXCLUDE, criterion="EX04")],
    )
    [live] = _ft_live(project)
    assert live.decision_id == second.written[0] and live.supersedes == first.written[0]
    # The title/abstract decision of the same work stays live and is not superseded.
    [ta] = [d for d in live_decisions(project, PassLabel.A, stage=TA) if d.work_id == work]
    assert ta.decision_id == ta_id and ta.supersedes is None


def test_task_completes_when_all_records_decided_at_full_text(
    project: Project, agent: Actor, batch: ScreenBatch
) -> None:
    *head, last = batch.records
    screen_record(project, agent, batch.task_id, [_item(r) for r in head])
    task = get_task(project, batch.task_id)
    assert task is not None and task.status is not TaskStatus.COMPLETED
    screen_record(project, agent, batch.task_id, [_item(last)])
    task = get_task(project, batch.task_id)
    assert task is not None and task.status is TaskStatus.COMPLETED
    assert len(_of_type(project, "task.completed")) >= 1


def test_decision_event_has_no_document_text_beyond_quote(
    project: Project, agent: Actor, batch: ScreenBatch
) -> None:
    screen_record(project, agent, batch.task_id, [_item(batch.records[0])])
    [event] = [
        e
        for e in _of_type(project, "screening.decision_recorded")
        if e.payload["stage"] == FT.value
    ]
    assert set(event.payload) == {
        "decision_id", "work_id", "pass_label", "phase", "stage", "verdict", "criterion",
        "quote", "rationale", "protocol_id", "task_id", "supersedes", "anchor", "conversion_id",
    }  # fmt: skip
    assert event.payload["quote"] == PARAGRAPH[1]
    dumped = json.dumps(event.payload)
    assert "Consectetur" not in dumped and "Synthetic Author" not in dumped


def _has_extra(project: Project, record: Mapping[str, Any]) -> bool:
    manifest = conversion_manifest(project, str(record["conversion_id"]))
    return manifest.get(EXTRA[0]) is not None


def test_damaged_conversion_is_per_item_error(
    project: Project, agent: Actor, batch: ScreenBatch
) -> None:
    # Works with identical documents share one manifest blob; pick one of each kind.
    r0 = next(r for r in batch.records if _has_extra(project, r))
    r1 = next(r for r in batch.records if not _has_extra(project, r))
    with project.index.connect() as conn:
        manifest_hash = conn.execute(
            text("SELECT manifest_hash FROM document_conversions WHERE conversion_id = :c"),
            {"c": r0["conversion_id"]},
        ).scalar_one()
    project.library.path(str(manifest_hash)).unlink()
    result = screen_record(project, agent, batch.task_id, [_item(r0), _item(r1)])
    assert [e.index for e in result.rejected] == [0]
    [issue] = result.rejected[0].issues
    assert issue.field == "items.0.anchor"
    assert issue.reason.startswith("pinned conversion unreadable: ")
    assert "Lorem" not in issue.reason
    assert len(result.written) == 1
    assert [d.work_id for d in _ft_live(project)] == [r1["work_id"]]


def test_foreign_conversion_anchor_rejected(
    project: Project, agent: Actor, batch: ScreenBatch
) -> None:
    with_extra = [r for r in batch.records if _has_extra(project, r)]
    without = [r for r in batch.records if not _has_extra(project, r)]
    assert with_extra and without, "the batch must mix both kinds of conversion"
    foreign = _item(without[0], anchor=EXTRA[0], quote=EXTRA[1])
    own = _item(with_extra[0], anchor=EXTRA[0], quote=EXTRA[1])
    result = screen_record(project, agent, batch.task_id, [foreign, own])
    assert [(e.index, [i.field for i in e.issues]) for e in result.rejected] == [
        (0, ["items.0.anchor"])
    ]
    assert len(result.written) == 1


def test_record_without_pinned_conversion_rejected(
    project: Project, agent: Actor, batch: ScreenBatch, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = screening._batch_of

    def stripped(proj: Project, task: Task) -> ScreenBatchContent:
        content = real(proj, task)
        records = [{**r, "conversion_id": None} for r in content.records]
        return content.model_copy(update={"records": records})

    monkeypatch.setattr(screening, "_batch_of", stripped)
    result = screen_record(project, agent, batch.task_id, [_item(batch.records[0])])
    assert result.written == []
    assert [i.field for i in result.rejected[0].issues] == ["items.0.work_id"]


def test_task_whose_content_stage_differs_from_its_kind_is_refused(
    project: Project, agent: Actor, batch: ScreenBatch
) -> None:
    from factory.errors import FactoryValidationError
    from factory.services.stages import task_kind
    from factory.services.tasks import TaskSpec, create_tasks, task_content

    task = get_task(project, batch.task_id)
    assert task is not None
    content = task_content(project, task)
    assert isinstance(content, dict)
    forged = create_tasks(
        project,
        agent,
        [TaskSpec(kind=task_kind(FT, PassLabel.A), content={**content, "stage": TA.value})],
    ).written[0]
    forged_task = get_task(project, forged)
    assert forged_task is not None

    with pytest.raises(FactoryValidationError) as caught:
        screening._batch_of(project, forged_task)
    assert [i.field for i in caught.value.issues] == ["task_id"]


def test_calibration_only_full_text_decisions_leave_the_stage_not_run(
    project: Project, agent: Actor, batch: ScreenBatch
) -> None:
    from factory.model.screening import ScreeningPhase
    from factory.services.prisma import prisma_flow

    assert batch.phase is ScreeningPhase.CALIBRATION
    result = screen_record(project, agent, batch.task_id, [_item(batch.records[0])])
    assert len(result.written) == 1 and _ft_live(project)

    assert prisma_flow(project).full_text.stage_run is False


def test_full_text_batch_examples_are_marked_style_only(batch: ScreenBatch) -> None:
    assert batch.worked_examples
    for example in batch.worked_examples:
        assert example["basis"] == "title_abstract"
        assert example["use"] == "style only; verdicts were decided on title and abstract"
        assert {"title", "abstract", "expected"} <= set(example)


def test_title_abstract_batch_examples_unchanged(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    served = ta_batch(project, agent, human, mock_sources)
    assert served.worked_examples
    for example in served.worked_examples:
        assert set(example) == {"title", "abstract", "expected"}
